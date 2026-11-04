"""Share leaderboard rank rewards: tiers, claims, boundaries and read-only pages."""

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
from nonebot_plugin_spirit_pet.domain.share_rank_reward_content import ShareRankReward
from nonebot_plugin_spirit_pet.gameplay import share_rank_rewards
from nonebot_plugin_spirit_pet.gameplay.shares import READER_PREFIX

from .support import items, player, sql

NOW = 1_800_000_000


def account(game, play, user):
    play("adopt", "青鸾", user=user)


def add_readers(game, owner, count, start=0):
    for index in range(start, start + count):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (owner, f"{READER_PREFIX}{owner}{index}"),
        )


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def seed_ranking(game, play):
    for index in range(1, 12):
        account(game, play, f"u{index}")
        add_readers(game, f"u{index}", 12 - index)


def test_content_has_three_named_tiers(game):
    rewards = game[0].content.share_rank_rewards
    assert sorted(rewards) == [1, 3, 10]
    assert rewards[1].stones == 500
    assert rewards[3].stones == 260
    assert rewards[10].stones == 120
    assert rewards[1].items["forge_ore"] == 3
    assert rewards[10].items["spirit_food"] == 1


def test_reward_model_rejects_empty_bad_rank_and_bad_items():
    base = {"rank": 1, "name": "测试", "stones": 10, "items": {}}
    assert ShareRankReward.model_validate(base).rank == 1
    with pytest.raises(ValidationError):
        ShareRankReward.model_validate({**base, "stones": 0})
    with pytest.raises(ValidationError):
        ShareRankReward.model_validate({**base, "rank": 0})
    with pytest.raises(ValidationError):
        ShareRankReward.model_validate({**base, "items": {"x": 0}})


def test_catalog_rejects_missing_tier_and_unknown_item(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    source = (data / "share_rank_rewards.json").read_text()
    rewards = json.loads(source)
    (data / "share_rank_rewards.json").write_text(json.dumps(rewards[:2], ensure_ascii=False))
    with pytest.raises(ValueError, match="cover ranks 1, 3 and 10"):
        Catalog.load(data)
    (data / "share_rank_rewards.json").write_text(
        source.replace('"spirit_food": 1', '"no_such_item": 1', 1)
    )
    with pytest.raises(ValueError, match="unknown|reward items"):
        Catalog.load(data)


def test_unregistered_page_is_read_only(game, play):
    page = play("share_rank_rewards", user="ghost")
    assert page.title == "灵宠分享榜奖励"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_page_lists_tiers_and_unranked_state(game, play):
    account(game, play, "u1")
    page = play("share_rank_rewards")
    assert "当前分享榜名次：尚未上榜。" in page.text()
    for line in ("前 1 名 · 传书之首", "前 3 名 · 传书三甲", "前 10 名 · 传书十强"):
        assert line in page.text()
    assert "尚未上榜" in page.text()
    assert page.inline_commands == ()


def test_rank_one_can_claim_all_three_tiers(game, play):
    seed_ranking(game, play)
    page = play("share_rank_rewards", user="u1")
    assert "当前分享榜名次：第 1 名。" in page.text()
    assert page.text().count("可领取") == 3
    assert {
        link.command for link in page.inline_commands
    } == {"灵宠分享榜领奖 1", "灵宠分享榜领奖 3", "灵宠分享榜领奖 10"}
    before = player(game[1], "u1")["stones"]
    play("share_rank_claim", "1", user="u1", op="rank-1")
    play("share_rank_claim", "3", user="u1", op="rank-3")
    play("share_rank_claim", "10", user="u1", op="rank-10")
    assert player(game[1], "u1")["stones"] == before + 500 + 260 + 120
    assert items(game[1], "u1")["forge_ore"] == 4
    assert items(game[1], "u1")["spirit_food"] == 8
    record = sql(
        game[1],
        "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (share_rank_rewards.claim_id(10),),
    )
    assert record == [{"progress": 1, "claimed": 1}]


def test_rank_three_only_claims_three_and_ten(game, play):
    seed_ranking(game, play)
    page = play("share_rank_rewards", user="u3")
    assert "当前分享榜名次：第 3 名。" in page.text()
    commands = {link.command for link in page.inline_commands}
    assert commands == {"灵宠分享榜领奖 3", "灵宠分享榜领奖 10"}
    with pytest.raises(GameError, match="尚未进入前 1 名"):
        play("share_rank_claim", "1", user="u3", op="rank3-1")
    assert player(game[1], "u3")["stones"] == 100


def test_rank_ten_claims_only_ten_and_eleven_claims_nothing(game, play):
    seed_ranking(game, play)
    ten = play("share_rank_rewards", user="u10")
    assert "当前分享榜名次：第 10 名。" in ten.text()
    assert {link.command for link in ten.inline_commands} == {"灵宠分享榜领奖 10"}
    eleven = play("share_rank_rewards", user="u11")
    assert "当前分享榜名次：第 11 名。" in eleven.text()
    assert eleven.inline_commands == ()
    with pytest.raises(GameError, match="尚未进入前 10 名"):
        play("share_rank_claim", "10", user="u11", op="rank11-10")


def test_claim_is_idempotent_and_duplicate_is_rejected(game, play):
    seed_ranking(game, play)
    first = play("share_rank_claim", "3", user="u1", op="rank-dup")
    assert "已领取（第 1 名）" in first.text()
    assert play("share_rank_claim", "3", user="u1", op="rank-dup") == first
    with pytest.raises(GameError, match="已经领取"):
        play("share_rank_claim", "3", user="u1", op="rank-dup-2")


def test_insufficient_unknown_and_bad_arguments_write_nothing(game, play):
    account(game, play, "u1")
    before = state(game[1])
    with pytest.raises(GameError, match="尚未进入分享榜"):
        play("share_rank_claim", "1", op="rank-poor")
    for argument in ("", "0", "2", "11", "abc", "1 3"):
        with pytest.raises(GameError, match="格式"):
            play("share_rank_claim", argument, op=f"rank-bad-{argument}")
    assert state(game[1]) == before


def test_rank_and_reward_pages_are_read_only(game, play):
    seed_ranking(game, play)
    before = state(game[1])
    play("share_board")
    play("share_rank_rewards")
    assert state(game[1]) == before


def test_rank_of_matches_board_order(game, play):
    seed_ranking(game, play)
    assert share_rank_rewards.rank_of(_ctx(game, "u1"), "u1") == 1
    assert share_rank_rewards.rank_of(_ctx(game, "u1"), "u10") == 10
    assert share_rank_rewards.rank_of(_ctx(game, "u1"), "ghost") is None


def test_help_parser_and_native_payload(game, play):
    account(game, play, "u1")
    assert _parse("灵宠分享榜奖励") == ("share_rank_rewards", "")
    assert _parse("灵宠分享榜领奖 1") == ("share_rank_claim", "1")
    guide = play("help", "对战与赛季")
    assert "灵宠分享榜奖励" in guide.text()
    assert "灵宠分享榜领奖 名次" in guide.text()
    page = play("share_rank_rewards")
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


def _ctx(game, user):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    conn = game[1].connect()
    return Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "read")
