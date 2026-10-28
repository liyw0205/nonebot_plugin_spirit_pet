"""Defense lineup and weekly defense reward contracts."""

import json

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, pet, player_uid, sql

NOW = 1_800_000_000


def setup(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    sql(game[1], "UPDATE pets SET realm=1")


def add_pet(game, user, species, name, *, archived=0, realm=1):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp,"
        " affinity, energy, energy_updated, archived) VALUES (?, ?, ?, ?, 5, 0, 0, 0, 100, ?, ?)",
        (user, species, name, realm, NOW, archived),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def rows(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id GLOB 'defense_pet_*'"
        " ORDER BY quest_id",
        (user,),
    )


def uid(game, user):
    return f"UID {player_uid(game[1], user)}"


def seed_defense(game, count, *, winner: str = "u1", played_at=NOW, salt: str = ""):
    """Seed challenges against u1; winner="draw" stores a draw (NULL winner)."""
    stored: str | None = None if winner == "draw" else winner
    season = sql(game[1], "SELECT season_id FROM seasons ORDER BY starts_at DESC LIMIT 1")[0]["season_id"]
    target = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' ORDER BY pet_id LIMIT 1")[0]["pet_id"]
    challenger = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2' ORDER BY pet_id LIMIT 1")[0]["pet_id"]
    for index in range(count):
        sql(
            game[1],
            "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id,"
            " target_pet_id, winner_id, day, played_at, delta, operation_id, reply)"
            " VALUES (?, 'u2', 'u1', ?, ?, ?, '2027-01-15', ?, ?, ?, '{}')",
            (season, challenger, target, stored, played_at, 20 if stored else 0,
             f"defense-seed-{played_at}-{winner}-{salt}-{index}"),
        )


def test_unregistered_preview_is_read_only(game, play):
    page = play("defense", user="u9")
    assert page.title == "灵宠防守"
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert [link.command for link in page.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_page_shows_active_fallback_and_two_unreached_tiers(game, play):
    setup(game, play)
    page = play("defense")
    assert "防守阵容：未设置，沿用出战阵容（青鸾）" in page.text()
    assert "本周被挑战 0 场，守擂成功 0 场" in page.text()
    assert "守擂 2 胜 · 初守 · 灵石 100、灵粮 1 · 未达成（0/2）" in page.text()
    assert "守擂 5 胜 · 稳守 · 灵石 300、灵粮 2、锻灵矿 2 · 未达成（0/5）" in page.text()
    assert page.commands == ("灵宠防守", "灵宠论剑榜", "灵宠战报", "我的灵宠")
    assert page.inline_commands == ()


def test_set_stores_slots_and_page_show_the_mirror(game, play):
    setup(game, play)
    main = pet(game[1], "u1")["pet_id"]
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    reply = play("defense", f"设置 {extra} {main}")
    assert "防守阵容已保存" in reply.text()
    assert rows(game) == [
        {"quest_id": "defense_pet_1", "progress": extra},
        {"quest_id": "defense_pet_2", "progress": main},
    ]
    page = play("defense")
    assert f"防守阵容（镜像）：#{extra} 小玄、#{main} 青鸾。" in page.text()
    assert "未设置，沿用出战阵容" not in page.text()
    assert [link.label for link in page.inline_commands] == ["清除阵容"]


def test_set_rejects_a_cross_realm_lineup(game, play):
    setup(game, play)
    main = pet(game[1], "u1")["pet_id"]
    higher = add_pet(game, "u1", "xuanhu", "小玄", realm=2)
    with pytest.raises(GameError, match="同一大境界"):
        play("defense", f"设置 {main} {higher}")
    assert rows(game) == []


def test_ranked_pvp_uses_the_defense_lineup_not_the_active_roster(game, play):
    setup(game, play)
    main = pet(game[1], "u2")["pet_id"]
    extra = add_pet(game, "u2", "baize", "守山")
    play("defense", f"设置 {extra} {main}", user="u2")
    reply = play("pvp", uid(game, "u2"))
    assert reply.title == "论剑结算"
    assert "的1宠阵容 挑战" in reply.text()
    assert "的2宠阵容镜像" in reply.text()
    assert sql(game[1], "SELECT target_pet_id FROM pvp_results")[0]["target_pet_id"] == extra


def test_ranked_pvp_reaches_a_preset_only_defender(game, play):
    setup(game, play)
    main = pet(game[1], "u2")["pet_id"]
    extra = add_pet(game, "u2", "baize", "守山")
    play("defense", f"设置 {extra} {main}", user="u2")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    assert sql(game[1], "SELECT * FROM active_pet_slots WHERE user_id='u2'") != []

    reply = play("pvp", uid(game, "u2"))
    assert reply.title == "论剑结算"
    assert "的2宠阵容镜像" in reply.text()
    assert sql(game[1], "SELECT target_pet_id FROM pvp_results")[0]["target_pet_id"] == extra


def test_ranked_pvp_still_rejects_a_target_without_any_lineup(game, play):
    setup(game, play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    with pytest.raises(GameError, match="尚未选择出战灵宠"):
        play("pvp", uid(game, "u2"))


def test_spar_keeps_the_active_roster(game, play):
    setup(game, play)
    main = pet(game[1], "u2")["pet_id"]
    extra = add_pet(game, "u2", "baize", "守山")
    play("defense", f"设置 {extra}", user="u2")
    reply = play("spar", uid(game, "u2"))
    assert reply.title == "切磋结算"
    assert "1宠阵容" in reply.text()
    assert "玄狐" in reply.text()
    assert "守山" not in reply.text()
    assert main


def test_spar_refuses_a_preset_only_defender_without_crashing(game, play):
    setup(game, play)
    extra = add_pet(game, "u2", "baize", "守山")
    play("defense", f"设置 {extra}", user="u2")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    with pytest.raises(GameError, match="尚未选择出战灵宠"):
        play("spar", uid(game, "u2"))


def test_invalid_lineups_are_rejected_without_writing(game, play):
    setup(game, play)
    main = pet(game[1], "u1")["pet_id"]
    other = add_pet(game, "u1", "xuanhu", "小玄")
    archived = add_pet(game, "u1", "baize", "旧卷", archived=1)
    same_species = add_pet(game, "u1", "qingluan", "同类")
    foreign = add_pet(game, "u2", "baize", "外人")
    cases = [
        ("设置 9999", "灵宠不存在"),
        (f"设置 {foreign}", "只能使用自己的灵宠"),
        (f"设置 {archived}", "已封存"),
        (f"设置 {main} {main}", "不能重复同一只灵宠"),
        (f"设置 {main} {same_species}", "不能重复宠物种类"),
        ("设置 1 2 3 4", "最多三只"),
        ("设置", "格式"),
        ("设置 abc", "编号必须是数字"),
        ("领取 x", "格式"),
    ]
    for command, message in cases:
        with pytest.raises(GameError, match=message):
            play("defense", command)
        assert rows(game) == []
    assert other
    assert "本周被挑战 0 场" in play("defense").text()
    assert "当前没有设置防守阵容，未做改动。" in play("defense", "清除").text()


def test_archived_defense_pet_falls_back_to_active_without_blocking_attackers(game, play):
    setup(game, play)
    main = pet(game[1], "u1")["pet_id"]
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    play("defense", f"设置 {extra}")
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (extra,))
    page = play("defense")
    assert "防守阵容已失效，暂沿用出战阵容：青鸾" in page.text()
    play("pvp", uid(game, "u1"), user="u2")
    assert sql(game[1], "SELECT target_pet_id FROM pvp_results")[0]["target_pet_id"] == main


def test_realm_split_after_growth_falls_back_to_the_active_roster(game, play):
    setup(game, play)
    main = pet(game[1], "u1")["pet_id"]
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    play("defense", f"设置 {extra} {main}")
    sql(game[1], "UPDATE pets SET realm=2 WHERE pet_id=?", (extra,))
    page = play("defense")
    assert "防守阵容已失效，暂沿用出战阵容：青鸾" in page.text()
    play("pvp", uid(game, "u1"), user="u2")
    assert sql(game[1], "SELECT target_pet_id FROM pvp_results")[0]["target_pet_id"] == main


def test_weekly_tiers_claim_once_and_ignore_previous_weeks(game, play):
    setup(game, play)
    season = play("pvp", uid(game, "u2"))
    assert season.title == "论剑结算"
    start, _ = beijing_week(NOW)
    seed_defense(game, 3, played_at=start - 1)
    page = play("defense")
    assert "本周被挑战 0 场，守擂成功 0 场" in page.text()
    with pytest.raises(GameError, match="尚未达到 2 场"):
        play("defense", "领取 2")
    seed_defense(game, 2)
    pages = play("defense")
    assert "守擂成功 2 场" in pages.text()
    assert [link.command for link in pages.inline_commands if link.label == "领取"] == [
        "灵宠防守 领取 2",
    ]
    stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    before = items(game[1])
    first = play("defense", "领取 2")
    assert "初守" in first.text() and "灵石 +100" in first.text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones + 100
    after = items(game[1])
    assert after.get("spirit_food", 0) - before.get("spirit_food", 0) == 1
    again = play("defense", "领取 2")
    assert "已经领取" in again.text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones + 100
    seed_defense(game, 3, played_at=start - 1, salt="late")
    assert "守擂成功 2 场" in play("defense").text()
    claim = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE 'defense_reward_%'")
    assert len(claim) == 1


def test_five_wins_unlocks_both_tiers(game, play):
    setup(game, play)
    play("pvp", uid(game, "u2"))
    start, _ = beijing_week(NOW)
    seed_defense(game, 2, played_at=start - 1)
    assert "守擂成功 0 场" in play("defense").text()
    seed_defense(game, 5)
    page = play("defense")
    assert "守擂成功 5 场" in page.text()
    assert [link.command for link in page.inline_commands if link.label == "领取"] == [
        "灵宠防守 领取 2", "灵宠防守 领取 5",
    ]
    before = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    before_items = items(game[1])
    assert "稳守" in play("defense", "领取 5").text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before + 300
    after = items(game[1])
    assert after.get("spirit_food", 0) - before_items.get("spirit_food", 0) == 2
    assert after.get("forge_ore", 0) - before_items.get("forge_ore", 0) == 2


def test_claiming_the_higher_tier_first_keeps_the_lower_one(game, play):
    setup(game, play)
    play("pvp", uid(game, "u2"))
    seed_defense(game, 5)
    before = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    assert "稳守" in play("defense", "领取 5").text()
    assert "初守" in play("defense", "领取 2").text()
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before + 400
    assert "已经领取" in play("defense", "领取 5").text()
    assert "已经领取" in play("defense", "领取 2").text()
    start, _ = beijing_week(NOW)
    claims = sql(
        game[1],
        "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'defense_reward_%'"
        " ORDER BY quest_id",
    )
    assert [row["quest_id"] for row in claims] == [
        f"defense_reward_{start}_first",
        f"defense_reward_{start}_steady",
    ]


def test_draws_and_losses_never_count_as_defense_wins(game, play):
    setup(game, play)
    play("pvp", uid(game, "u2"))
    seed_defense(game, 2, winner="draw")
    seed_defense(game, 1, winner="u2")
    page = play("defense")
    assert "本周被挑战 3 场，守擂成功 0 场" in page.text()
    with pytest.raises(GameError, match="尚未达到 2 场"):
        play("defense", "领取 2")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'defense_reward_%'") == []


def test_claim_leaves_pet_progress_and_energy_alone(game, play):
    setup(game, play)
    play("pvp", uid(game, "u2"))
    seed_defense(game, 2)
    before = sql(game[1], "SELECT exp, energy, affinity FROM pets WHERE user_id='u1'")[0]
    play("defense", "领取 2")
    after = sql(game[1], "SELECT exp, energy, affinity FROM pets WHERE user_id='u1'")[0]
    assert after == before


def test_defense_state_and_claims_persist_across_restart(game, play):
    setup(game, play)
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    play("defense", f"设置 {extra}")
    play("pvp", uid(game, "u2"))
    seed_defense(game, 2)
    first = play("defense", "领取 2", op="defense-claim")
    assert "初守" in first.text()
    replay = play("defense", "领取 2", op="defense-claim")
    assert replay.lines == first.lines

    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "defense", "", "restart-defense", NOW)
    assert f"防守阵容（镜像）：#{extra} 小玄。" in page.text()
    assert "守擂 2 胜 · 初守 · 灵石 100、灵粮 1 · 已领取" in page.text()
    assert "守擂 5 胜 · 稳守 · 灵石 300、灵粮 2、锻灵矿 2 · 未达成（2/5）" in page.text()


def test_clear_restores_active_fallback_and_same_request_replays(game, play):
    setup(game, play)
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    first = play("defense", f"设置 {extra}", op="defense-set")
    again = play("defense", f"设置 {extra}", op="defense-set")
    assert again.title == first.title and again.lines == first.lines
    assert len(rows(game)) == 1
    assert "已清除" in play("defense", "清除").text()
    assert rows(game) == []
    assert "未设置，沿用出战阵容" in play("defense").text()


def test_native_payload_keeps_buttons_and_links_separate(game, play):
    setup(game, play)
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    play("defense", f"设置 {extra}")
    page = play("defense")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in page.inline_commands}
    assert buttons == set(page.commands)
    assert buttons & links == set()
    assert "灵宠防守 清除" in links


def test_help_and_parse_contract(game, play):
    assert "灵宠防守" in play("help", "对战与赛季").text()
    assert handlers._parse("灵宠防守 设置 1 2") == ("defense", "设置 1 2")
    assert handlers._parse("灵宠防守") == ("defense", "")


def test_objectives_hub_exposes_the_defense_row_and_link(game, play):
    setup(game, play)
    play("pvp", uid(game, "u2"))
    seed_defense(game, 2)
    hub = play("objectives")
    assert "灵宠防守：可领 1 档（初守）· 本周守擂 2 胜" in hub.text()
    link = next(link for link in hub.inline_commands if link.command == "灵宠防守")
    assert hub.lines[link.line].startswith("灵宠防守：")


def test_old_season_snapshot_without_defense_tiers_still_renders(game, play):
    setup(game, play)
    page = play("season")
    assert "论剑赛季" in page.title
    season = sql(game[1], "SELECT season_id, rules_snapshot FROM seasons")[0]
    data = json.loads(season["rules_snapshot"])
    data.pop("defense_tiers")
    sql(
        game[1],
        "UPDATE seasons SET rules_snapshot=? WHERE season_id=?",
        (json.dumps(data), season["season_id"]),
    )
    status = play("season", season["season_id"])
    assert season["season_id"] in status.title
    rules = play("season_rewards", f"规则 {season['season_id']}")
    assert rules.title.startswith("赛季档位")
    assert season["season_id"] in rules.title
