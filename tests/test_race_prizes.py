"""Weekly race settlement: last week's top three, claims and the archive."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.race_prize_content import RacePrize
from nonebot_plugin_spirit_pet.gameplay import race_prizes
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86_400
CURRENT = beijing_week(NOW)[0]
LAST = CURRENT - WEEK


def label(start):
    return beijing_day(start)


def seed_week(store, user, start, tenths):
    sql(
        store,
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) "
        "VALUES (?, ?, ?, 1)",
        (user, f"race_best_{start}", tenths),
    )


def adopt(game, play, count=4):
    for index in range(1, count + 1):
        play("adopt", "青鸾", user=f"u{index}")


def seed_last_week(game, play, count=3):
    adopt(game, play, count)
    for index, tenths in enumerate((100 + index * 100 for index in range(count)), 1):
        seed_week(game[1], f"u{index}", LAST, tenths)


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def test_prize_content_is_three_ordered_ranks():
    content = Catalog.load()
    assert sorted(content.race_prizes) == [1, 2, 3]
    assert content.race_prizes[1].stones == 600
    assert content.race_prizes[2].stones == 320
    assert content.race_prizes[3].stones == 160
    for rank, prize in content.race_prizes.items():
        assert prize.rank == rank
        assert prize.stones or prize.items


def test_prize_model_rejects_empty_and_out_of_range():
    with pytest.raises(ValidationError):
        RacePrize.model_validate({"rank": 1, "stones": 0, "items": {}})
    with pytest.raises(ValidationError):
        RacePrize.model_validate({"rank": 4, "stones": 10, "items": {}})
    with pytest.raises(ValidationError):
        RacePrize.model_validate({"rank": 1, "stones": -1, "items": {}})


def test_prize_catalog_rejects_missing_rank(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src/plugins/nonebot_plugin_spirit_pet/data"
    for entry in source.glob("*.json"):
        (tmp_path / entry.name).write_text(entry.read_text())
    prizes = json.loads((tmp_path / "race_prizes.json").read_text())
    (tmp_path / "race_prizes.json").write_text(json.dumps(prizes[:2], ensure_ascii=False))
    with pytest.raises(ValueError, match="cover ranks 1, 2 and 3"):
        Catalog.load(tmp_path)


def test_prize_catalog_rejects_non_monotonic_reward(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src/plugins/nonebot_plugin_spirit_pet/data"
    for entry in source.glob("*.json"):
        (tmp_path / entry.name).write_text(entry.read_text())
    prizes = json.loads((tmp_path / "race_prizes.json").read_text())
    prizes[1]["stones"] = 999
    (tmp_path / "race_prizes.json").write_text(json.dumps(prizes, ensure_ascii=False))
    with pytest.raises(ValueError, match="must not fall"):
        Catalog.load(tmp_path)


def test_tied_times_break_by_identity_order(game, play):
    adopt(game, play, 3)
    for user in ("u1", "u2", "u3"):
        seed_week(game[1], user, LAST, 100)
    page = play("race_prizes")
    assert page.text().index("1. UID 10000") < page.text().index("2. UID 10001")
    assert page.text().index("2. UID 10001") < page.text().index("3. UID 10002")
    assert "你的上周成绩：第 1 名" in page.text()


def test_claim_accepts_the_last_week_label_and_上周(game, play):
    seed_last_week(game, play)
    play("race_prize_claim", "上周", user="u2", op="prize-alias")
    assert player(game[1], "u2")["stones"] == 100 + 320
    play("race_prize_claim", label(LAST), user="u3", op="prize-label")
    assert player(game[1], "u3")["stones"] == 100 + 160


def test_corrupt_claim_record_is_stable(game, play):
    seed_last_week(game, play)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 0)",
        (f"race_prize_{LAST}",),
    )
    before = state(game[1])
    with pytest.raises(GameError, match="记录异常"):
        play("race_prize_claim", "", op="corrupt-prize")
    assert state(game[1]) == before


def test_unregistered_claim_does_not_create_a_player(game, play):
    with pytest.raises(GameError, match="领养|结契"):
        play("race_prize_claim", "", user="ghost", op="ghost-prize")
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_unregistered_page_is_read_only(game, play):
    play("adopt", "青鸾", user="someone")
    seed_week(game[1], "someone", LAST, 100)
    page = play("race_prizes", user="ghost")
    assert page.title == "灵宠竞速奖励"
    assert "上周" in page.text()
    assert "UID 10000" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_settlement_lists_last_week_and_links_the_claim(game, play):
    seed_last_week(game, play)
    page = play("race_prizes")
    assert f"上周（{label(LAST)} 起）前三名" in page.text()
    assert page.text().index("1. UID") < page.text().index("2. UID") < page.text().index("3. UID")
    assert "你的上周成绩：第 1 名" in page.text()
    assert "可领取" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠竞速领奖", "灵宠竞速奖励 往期",
    ]
    assert page.commands == ("灵宠竞速", "灵宠竞速榜", "灵宠帮助")
    assert handlers._parse(page.inline_commands[0].command) == ("race_prize_claim", "")


def test_claim_pays_the_first_prize_once_and_records_rank(game, play):
    seed_last_week(game, play)
    before = player(game[1])
    reply = play("race_prize_claim", "", op="prize-1")
    assert "第 1 名" in reply.text()
    assert player(game[1])["stones"] == before["stones"] + 600
    assert items(game[1])["forge_ore"] == 3
    assert items(game[1])["spirit_food"] == 5
    record = sql(
        game[1],
        "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (f"race_prize_{LAST}",),
    )
    assert record == [{"progress": 1, "claimed": 1}]
    assert play("race_prize_claim", "", op="prize-1") == reply
    with pytest.raises(GameError, match="已经领取"):
        play("race_prize_claim", "", op="prize-2")


def test_second_and_third_prizes_pay_their_own_rewards(game, play):
    seed_last_week(game, play)
    play("race_prize_claim", label(LAST), user="u2", op="prize-u2")
    assert player(game[1], "u2")["stones"] == 100 + 320
    assert items(game[1], "u2")["forge_ore"] == 1
    assert items(game[1], "u2")["spirit_food"] == 5
    play("race_prize_claim", "", user="u3", op="prize-u3")
    assert player(game[1], "u3")["stones"] == 100 + 160
    assert items(game[1], "u3")["spirit_food"] == 4


def test_fourth_place_and_non_participants_are_refused_without_writes(game, play):
    seed_last_week(game, play, count=4)
    play("adopt", "青鸾", user="u5")
    before = state(game[1])
    with pytest.raises(GameError, match="第 4 名"):
        play("race_prize_claim", "", user="u4", op="prize-u4")
    with pytest.raises(GameError, match="没有参赛"):
        play("race_prize_claim", "", user="u5", op="prize-u5")
    assert state(game[1]) == before


def test_older_weeks_are_archived_and_not_claimable(game, play):
    adopt(game, play, 1)
    seed_week(game[1], "u1", LAST - WEEK, 90)
    seed_week(game[1], "u1", LAST, 100)
    old = label(LAST - WEEK)
    page = play("race_prizes", old)
    assert "已归档" in page.text()
    assert all(link.command != "灵宠竞速领奖" for link in page.inline_commands)
    before = state(game[1])
    with pytest.raises(GameError, match="只能领取上一自然周"):
        play("race_prize_claim", old, op="old-claim")
    assert state(game[1]) == before


def test_claim_arguments_and_unknown_weeks_are_strict(game, play):
    seed_last_week(game, play)
    for argument in ("2026-10-27", "not-a-date", "2026-13-01", "上周 1"):
        with pytest.raises(GameError, match="格式|周一"):
            play("race_prize_claim", argument, op=f"bad-{argument}")
    with pytest.raises(GameError, match="尚未结算"):
        play("race_prizes", label(CURRENT))
    with pytest.raises(GameError, match="只能领取|尚未结算"):
        play("race_prize_claim", label(CURRENT), op="current-claim")
    with pytest.raises(GameError, match="页码"):
        play("race_prizes", "往期 0")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'race_prize_%'") == []


def test_archive_pages_weeks_and_links_to_details(game, play):
    adopt(game, play, 1)
    for index in range(7):
        seed_week(game[1], "u1", LAST - index * WEEK, 100 + index)
    page = play("race_prizes", "往期")
    assert "第 1/2 页" in page.text()
    assert page.text().count("起 ·") == 6
    assert [link.command for link in page.inline_commands[:6]] == [
        f"灵宠竞速奖励 {label(LAST - index * WEEK)}" for index in range(6)
    ]
    assert page.inline_commands[-1].command == "灵宠竞速奖励 往期 2"
    second = play("race_prizes", "往期 2")
    assert "第 2/2 页" in second.text()
    assert second.text().count("起 ·") == 1
    assert "往期 2" in page.text().split("翻页：")[-1]
    assert "往期 1" in second.text().split("翻页：")[-1]
    assert second.inline_commands[-1].command == "灵宠竞速奖励 往期 1"
    with pytest.raises(GameError, match="只有 2 页"):
        play("race_prizes", "往期 3")
    with pytest.raises(GameError, match="格式"):
        play("race_prizes", "往期 1 2")
    for link in page.inline_commands:
        assert handlers._parse(link.command) == ("race_prizes", link.command.split(" ", 1)[1])


def test_archive_empty_state_is_explicit(game, play):
    adopt(game, play, 1)
    page = play("race_prizes", "往期")
    assert "还没有已结算的周" in page.text()
    assert page.inline_commands == ()
    with pytest.raises(GameError, match="只有 1 页"):
        play("race_prizes", "往期 2")


def test_detail_orders_rows_and_shows_own_result(game, play):
    seed_last_week(game, play)
    page = play("race_prizes", label(LAST))
    assert f"竞速周榜 · {label(LAST)} 起" in page.text()
    assert "你的成绩：第 1 名" in page.text()
    assert "可领取" in page.text()
    assert "灵宠竞速领奖" in [link.command for link in page.inline_commands]


def test_pages_are_read_only(game, play):
    seed_last_week(game, play)
    before = state(game[1])
    play("race_prizes")
    play("race_prizes", "往期")
    play("race_prizes", label(LAST))
    assert state(game[1]) == before


def test_claim_does_not_touch_race_rows_energy_or_battle_records(game, play):
    seed_last_week(game, play)
    before = state(game[1])
    play("race_prize_claim", "", op="clean-claim")
    after = state(game[1])
    added = [row for row in after["quest_progress"] if row not in before["quest_progress"]]
    assert added == [
        {"user_id": "u1", "quest_id": f"race_prize_{LAST}", "progress": 1, "claimed": 1},
    ]
    assert all(row in after["quest_progress"] for row in before["quest_progress"])
    assert after["pets"] == before["pets"]
    assert after["battle_records"] == before["battle_records"]
    best = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (f"race_best_{LAST}",),
    )
    assert best == [{"progress": 100}]


def test_objective_help_and_parse_are_connected(game, play):
    seed_last_week(game, play)
    objective = play("objectives")
    line = next(line for line in objective.lines if line.startswith("竞速："))
    assert line == "竞速：上周第 1 名，奖励可领"
    link = objective.inline_commands[objective.lines.index(line)]
    assert link.command == "灵宠竞速奖励"
    play("race_prize_claim", "", op="objective-claim")
    assert "竞速：" in play("objectives").text()
    help_page = play("help", "对战与赛季")
    assert "灵宠竞速奖励：查看上周竞速前三名" in help_page.text()
    assert "灵宠竞速领奖：领取上周进入前三名的竞速奖励" in help_page.text()
    assert handlers._parse("灵宠竞速奖励") == ("race_prizes", "")
    assert handlers._parse("灵宠竞速奖励 往期") == ("race_prizes", "往期")
    assert handlers._parse("灵宠竞速领奖") == ("race_prize_claim", "")


def test_native_buttons_and_inline_links_do_not_overlap(game, play):
    seed_last_week(game, play)
    page = play("race_prizes")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & {link.command for link in page.inline_commands}


def test_claim_rejects_missing_reward_item_without_writing(game, play):
    seed_last_week(game, play)
    content = game[0].content
    content.race_prizes[1] = content.race_prizes[1].model_copy(update={"items": {"missing": 1}})
    before = state(game[1])
    with pytest.raises(GameError, match="物品定义缺失"):
        play("race_prize_claim", "", op="missing-prize")
    assert state(game[1]) == before
