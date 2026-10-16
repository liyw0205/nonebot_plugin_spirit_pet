import json
from dataclasses import replace
from datetime import datetime

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import BEIJING

from .support import sql


def stamp(month, day=1):
    return int(datetime(2028, month, day, tzinfo=BEIJING).timestamp())


JAN = stamp(1)
FEB = stamp(2)


def reward_snapshot(tier_name="天阙", rating=1150):
    return json.dumps({
        "tier_id": tier_name.lower(), "tier_name": tier_name, "rating": rating,
        "stones": 1000, "items": {"forge_ore": 10, "bloodline_essence": 4},
    }, ensure_ascii=False)


def seed_claim(game, user="u1", season_id="2028-01", starts_at=JAN, rating=1150):
    sql(game[1], "INSERT OR IGNORE INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot) "
        "VALUES (?, ?, ?, ?, ?)", (season_id, starts_at, stamp(int(season_id[-2:]) + 1), starts_at, "{}"))
    sql(game[1], "INSERT OR IGNORE INTO season_entries(season_id,user_id,rating) VALUES (?,?,?)",
        (season_id, user, rating))
    sql(game[1], "INSERT INTO season_claims(season_id,user_id,reward_snapshot,claimed_at) VALUES (?,?,?,?)",
        (season_id, user, reward_snapshot(rating=rating), starts_at + 10))


def test_history_is_read_only_for_unregistered_players(game, play):
    listing = play("arena_reward_history", now=JAN)
    assert listing.title == "赛季奖励回顾 1/1"
    assert listing.lines == ("尚无已领取的赛季奖励。",)
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="没有属于你的该赛季奖励回顾"):
        play("arena_reward_history", "2028-01", now=JAN)
    assert not sql(game[1], "SELECT * FROM players")


def test_history_lists_claims_and_links_each_season_detail(game, play):
    play("adopt", "青鸾", now=JAN)
    for month in range(1, 6):
        seed_claim(game, season_id=f"2028-{month:02d}", starts_at=stamp(month), rating=1000 + month)
    first = play("arena_reward_history", now=stamp(6))
    assert first.title == "赛季奖励回顾 1/2"
    assert len(first.lines) == len(first.inline_commands) == 4
    assert first.lines[0].startswith("2028-05 · 最终积分 1005")
    assert all(link.command in first.commands for link in first.inline_commands)
    assert first.inline_commands[0].command == "灵宠赛季奖励回顾 2028-05"
    second = play("arena_reward_history", "2", now=stamp(6))
    assert second.title == "赛季奖励回顾 2/2"
    assert second.lines[0].startswith("2028-01 · 最终积分 1001")
    with pytest.raises(GameError, match="共 2 页"):
        play("arena_reward_history", "3", now=stamp(6))


def test_history_detail_reads_persistent_snapshot_after_content_change(game, play):
    play("adopt", "青鸾", now=JAN)
    seed_claim(game, rating=1150)
    detail = play("arena_reward_history", "2028-01", now=FEB)
    assert detail.title == "赛季奖励回顾 · 2028-01"
    assert "最终积分：1150。" in detail.lines
    assert "结算档位：天阙。" in detail.lines
    assert "实际发放：灵石 +1000、锻灵矿 +10、血脉精华 +4。" in detail.lines
    assert any(line.startswith("领取凭证：已永久保存") for line in detail.lines)
    original = game[0].content
    changed = original.arena.model_copy(update={
        "tiers": [tier.model_copy(update={"stones": tier.stones + 9999}) for tier in original.arena.tiers],
    })
    game[0].content = replace(original, arena=changed)
    assert "灵石 +1000" in play("arena_reward_history", "2028-01", now=FEB).text()
    game[0].content = original


def test_history_rejects_foreign_unknown_and_pending_records(game, play):
    play("adopt", "青鸾", now=JAN)
    seed_claim(game)
    play("adopt", "玄狐", user="u2", now=JAN)
    with pytest.raises(GameError, match="没有属于你的该赛季奖励回顾"):
        play("arena_reward_history", "2028-01", user="u2", now=FEB)
    with pytest.raises(GameError, match="没有属于你的该赛季奖励回顾"):
        play("arena_reward_history", "2028-09", now=FEB)
    sql(game[1], "DELETE FROM season_claims WHERE season_id='2028-01' AND user_id='u1'")
    with pytest.raises(GameError, match="没有属于你的该赛季奖励回顾"):
        play("arena_reward_history", "2028-01", now=FEB)


def test_history_reports_corrupt_snapshot_and_keeps_listing_safe(game, play):
    play("adopt", "青鸾", now=JAN)
    seed_claim(game)
    sql(game[1], "UPDATE season_claims SET reward_snapshot='not-json' WHERE season_id='2028-01'")
    listing = play("arena_reward_history", now=FEB)
    assert listing.lines == ("2028-01 · 奖励快照异常",)
    with pytest.raises(GameError, match="奖励快照暂不可回顾"):
        play("arena_reward_history", "2028-01", now=FEB)


def test_help_and_native_links_expose_history_without_button_duplicates(game, play):
    assert "灵宠赛季奖励回顾" in play("help", "对战与赛季").text()
    play("adopt", "青鸾", now=JAN)
    seed_claim(game)
    listing = play("arena_reward_history", now=FEB)
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    linked = {link.command for link in listing.inline_commands}
    assert linked == {"灵宠赛季奖励回顾 2028-01"}
    assert not buttons & linked


def test_history_replay_returns_the_same_read_only_reply(game, play):
    play("adopt", "青鸾", now=JAN)
    seed_claim(game)
    first = play("arena_reward_history", "2028-01", now=FEB, op="history-detail")
    again = play("arena_reward_history", "ignored", now=FEB, op="history-detail")
    assert again == first
