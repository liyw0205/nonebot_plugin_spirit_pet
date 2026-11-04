"""Share reader milestones: distinct readers, claims and boundaries."""

import json
import shutil
from contextlib import closing

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.share_reward_content import ShareReward
from nonebot_plugin_spirit_pet.gameplay import share_rewards, shares

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400


def account(game, play, user):
    play("adopt", "青鸾", user=user)


def seed_report(game, owner="u1", title="试炼"):
    snapshot = json.dumps({
        "version": 2,
        "teams": [
            {"side": 0, "members": [{"pet_name": "青鸾"}]},
            {"side": 1, "members": [{"pet_name": "木灵"}]},
        ],
    })
    log = json.dumps(["第一回合：青鸾出手", "第二回合：木灵倒下"])
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, title, winner_side, rounds,"
            " played_at, reply, snapshot, battle_log) VALUES (?, ?, 'pve', ?, 0, 3, ?, '{}', ?, ?)",
            (f"share-reward-{owner}-{title}", owner, title, NOW, snapshot, log),
        )
        battle_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, 0, 'participant')",
            (battle_id, owner),
        )
        conn.commit()
    return battle_id


def code_of(reply):
    import re
    match = re.search(rf"[{shares.ALPHABET}]{{{shares.CODE_LENGTH}}}", reply.text())
    assert match is not None
    return match.group(0)


def share(play, battle_id, user="u1"):
    return play("shares", str(battle_id), user=user)


def reader_row(game, viewer, owner="u1"):
    return sql(
        game[1],
        "SELECT progress, claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (owner, f"{shares.READER_PREFIX}{viewer}"),
    )


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def seed_readers(game, count, owner="u1", start=0):
    for index in range(start, start + count):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (owner, f"{shares.READER_PREFIX}r{index}"),
        )


def reader_count(game, owner="u1"):
    return sql(
        game[1],
        "SELECT COUNT(*) AS total FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{shares.READER_PREFIX}%"),
    )[0]["total"]


def test_content_has_three_ordered_milestones(game):
    rewards = game[0].content.share_rewards
    assert sorted(rewards) == [3, 10, 30]
    assert rewards[3].stones == 120
    assert rewards[10].stones == 300
    assert rewards[30].stones == 800
    assert rewards[30].items["bloodline_essence"] == 1


def test_reward_model_rejects_empty_and_bad_values():
    base = {"readers": 3, "name": "测试", "stones": 10, "items": {}}
    assert ShareReward.model_validate(base).readers == 3
    with pytest.raises(ValidationError):
        ShareReward.model_validate({**base, "stones": 0})
    with pytest.raises(ValidationError):
        ShareReward.model_validate({**base, "readers": 0})
    with pytest.raises(ValidationError):
        ShareReward.model_validate({**base, "items": {"x": 0}})


def test_catalog_rejects_missing_tier_and_unknown_item(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    source = (data / "share_rewards.json").read_text()
    rewards = json.loads(source)
    (data / "share_rewards.json").write_text(json.dumps(rewards[:2], ensure_ascii=False))
    with pytest.raises(ValueError, match="cover 3, 10 and 30"):
        Catalog.load(data)
    (data / "share_rewards.json").write_text(
        source.replace('"spirit_food": 1', '"no_such_item": 1', 1)
    )
    with pytest.raises(ValueError, match="unknown|reward items"):
        Catalog.load(data)


def test_unregistered_page_is_read_only(game, play):
    page = play("share_rewards", user="ghost")
    assert page.title == "灵宠分享奖励"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_page_lists_milestones_and_zero_readers(game, play):
    account(game, play, "u1")
    page = play("share_rewards")
    assert "分享的去重读者：0 位。" in page.text()
    assert "3 位读者 · 初传佳话" in page.text()
    assert "还差 3 位读者" in page.text()
    assert page.commands == ("灵宠分享", "灵宠战报", "灵宠目标")
    assert page.inline_commands == ()


def test_distinct_readers_across_codes_and_repeat_reads(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    account(game, play, "u3")
    first = share(play, seed_report(game, title="一"))
    second = share(play, seed_report(game, title="二"))
    code_one, code_two = code_of(first), code_of(second)
    play("shares", f"查看 {code_one}", user="u2")
    play("shares", f"查看 {code_one}", user="u2")
    play("shares", f"查看 {code_two}", user="u2")
    assert reader_count(game) == 1
    assert reader_row(game, "u2") == [{"progress": 1, "claimed": 1}]
    play("shares", f"查看 {code_one}", user="u3")
    assert reader_count(game) == 2
    play("shares", f"查看 {code_one}", user="u1")  # owner does not count
    assert reader_count(game) == 2


def test_three_readers_make_the_first_milestone_claimable(game, play):
    account(game, play, "u1")
    for user in ("u2", "u3", "u4"):
        account(game, play, user)
    code = code_of(share(play, seed_report(game)))
    for user in ("u2", "u3", "u4"):
        play("shares", f"查看 {code}", user=user)
    page = play("share_rewards")
    assert "分享的去重读者：3 位。" in page.text()
    assert "可领取" in page.text()
    assert "灵宠分享领奖 3" in [link.command for link in page.inline_commands]
    assert "灵宠分享领奖 10" not in [link.command for link in page.inline_commands]


def test_claim_pays_once_and_snapshots_the_reader_count(game, play):
    account(game, play, "u1")
    seed_readers(game, 3)
    before = player(game[1])["stones"]
    reply = play("share_read_claim", "3", op="share-3")
    assert "3 位读者" in reply.text()
    assert player(game[1])["stones"] == before + 120
    assert items(game[1])["spirit_food"] == 4
    record = sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (share_rewards.claim_id(3),),
    )
    assert record == [{"progress": 3, "claimed": 1}]
    assert play("share_read_claim", "3", op="share-3") == reply
    with pytest.raises(GameError, match="已经领取"):
        play("share_read_claim", "3", op="share-3b")


def test_larger_milestones_and_idempotency(game, play):
    account(game, play, "u1")
    seed_readers(game, 10)
    play("share_read_claim", "10", op="share-10")
    assert player(game[1])["stones"] == 100 + 300
    assert items(game[1])["forge_ore"] == 1
    assert items(game[1])["spirit_food"] == 5
    seed_readers(game, 20, start=10)
    play("share_read_claim", "30", op="share-30")
    assert player(game[1])["stones"] == 100 + 300 + 800
    assert items(game[1])["bloodline_essence"] == 1


def test_insufficient_unknown_and_bad_arguments_write_nothing(game, play):
    account(game, play, "u1")
    seed_readers(game, 2)
    before = state(game[1])
    with pytest.raises(GameError, match="读者不足"):
        play("share_read_claim", "3", op="share-poor")
    for argument in ("", "0", "5", "31", "abc", "3 10"):
        with pytest.raises(GameError, match="格式"):
            play("share_read_claim", argument, op=f"share-bad-{argument}")
    assert state(game[1]) == before


def test_views_and_reward_pages_are_read_only(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    play("shares", f"查看 {code}", user="u2")
    before = state(game[1])
    play("share_rewards")
    play("shares", "我的")
    assert state(game[1]) == before


def test_owner_viewing_own_code_does_not_add_a_reader(game, play):
    account(game, play, "u1")
    code = code_of(share(play, seed_report(game)))
    play("shares", f"查看 {code}", user="u1")
    assert reader_row(game, "u1") == []
    assert reader_count(game) == 0


def test_expired_code_does_not_add_a_reader(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    with pytest.raises(GameError, match="分享码无效或已失效"):
        play("shares", f"查看 {code}", user="u2", now=NOW + 8 * DAY)
    assert reader_row(game, "u2") == []


def test_reader_and_claim_markers_survive_restart(game, play):
    account(game, play, "u1")
    seed_readers(game, 3)
    play("share_read_claim", "3", op="share-persist")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "share_rewards", "", "share-restart", NOW)
    assert "已领取" in page.text()
    assert "3 位" in page.text()


def test_help_parser_and_native_payload(game, play):
    account(game, play, "u1")
    assert _parse("灵宠分享奖励") == ("share_rewards", "")
    assert _parse("灵宠分享领奖 3") == ("share_read_claim", "3")
    guide = play("help", "对战与赛季")
    assert "灵宠分享奖励" in guide.text()
    assert "灵宠分享领奖 读者数" in guide.text()
    page = play("share_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons <= set(page.commands)
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}
