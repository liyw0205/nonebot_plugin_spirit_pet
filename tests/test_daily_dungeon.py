import re
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, player, sql

NOW = 1_800_000_000


def solo_dungeons(game):
    return [dungeon for dungeon in game[0].content.dungeons.values() if not dungeon.team]


def now_for(game, index, base=NOW):
    """A timestamp whose Beijing day selects solo dungeon `index`."""
    start = date.fromisoformat(beijing_day(base)).toordinal()
    count = len(solo_dungeons(game))
    for offset in range(40):
        if (start + offset) % count == index:
            return base + offset * 86400
    raise AssertionError("no matching day")


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def featured_name(play, now):
    return play("daily_dungeon", now=now).lines[0].split("：", 1)[1].split(" · ", 1)[0]


def test_rotation_is_a_pure_function_of_the_beijing_day(game, play):
    dungeons = solo_dungeons(game)
    assert len(dungeons) == 9
    day = now_for(game, 0)
    assert featured_name(play, day) == dungeons[0].name
    assert featured_name(play, day + 3600) == dungeons[0].name
    assert featured_name(play, day + 86400) == dungeons[1].name
    seen = {featured_name(play, day + offset * 86400) for offset in range(9)}
    assert seen == {dungeon.name for dungeon in dungeons}


def test_catalog_previews_without_an_account(game, play):
    day = now_for(game, 0)
    listing = play("daily_dungeon", now=day)
    assert "尚未结契" in listing.text()
    assert links(listing) == [(0, "开始领养", "灵宠领养 ")]
    assert not sql(game[1], "SELECT * FROM players")


def test_catalog_shows_today_and_the_win_state(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    listing = play("daily_dungeon", now=day)
    assert listing.title == "今日秘境"
    assert listing.lines[0] == "今日秘境：青岚林 · 启灵起 · 精力 20"
    assert listing.lines[1] == "首胜奖励：灵石 200-200，锻灵矿 1-1"
    assert listing.lines[2] == "三胜奖励：灵石 500-500，血脉精华 1-1"
    assert "今日已胜 0 场 · 首胜奖励 未领取 · 三胜奖励 未领取" in listing.text()
    assert links(listing) == [(0, "前往挑战", "灵宠挑战 青岚林")]
    assert listing.commands == ("灵宠秘境", "灵宠任务")
    assert not {command for _, _, command in links(listing)} & set(listing.commands)


def test_first_second_and_third_wins(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    first = play("challenge", "青岚林", now=day, op="daily-1")
    assert first.title == "秘境获胜"
    assert "今日首胜：修为 +0，灵石 +200，锻灵矿 +1" in first.text()
    assert "今日已胜 1 场 · 首胜奖励 已领取 · 三胜奖励 未领取" in play(
        "daily_dungeon", now=day,
    ).text()

    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    second = play("challenge", "青岚林", now=day + 10, op="daily-2")
    assert second.title == "秘境获胜"
    assert not any(line.startswith("今日首胜") or line.startswith("今日三胜") for line in second.lines)

    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    third = play("challenge", "青岚林", now=day + 20, op="daily-3")
    assert "今日三胜：修为 +0，灵石 +500，血脉精华 +1" in third.text()
    assert "今日已胜 3 场 · 首胜奖励 已领取 · 三胜奖励 已领取" in play(
        "daily_dungeon", now=day,
    ).text()


def test_non_featured_dungeon_grants_no_bonus(game, play):
    day = now_for(game, 1)
    assert featured_name(play, day) == "月影谷"
    play("adopt", "青鸾", now=day)
    result = play("challenge", "青岚林", now=day, op="non-featured")
    assert result.title == "秘境获胜"
    assert not any(line.startswith("今日首胜") or line.startswith("今日三胜") for line in result.lines)
    assert "今日已胜 0 场" in play("daily_dungeon", now=day).text()


def test_day_change_resets_the_daily_state(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    play("challenge", "青岚林", now=day, op="daily-day")
    assert "今日已胜 1 场" in play("daily_dungeon", now=day).text()
    later = play("daily_dungeon", now=day + 86400)
    assert "今日已胜 0 场 · 首胜奖励 未领取 · 三胜奖励 未领取" in later.text()


def test_replay_does_not_grant_the_bonus_twice(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    first = play("challenge", "青岚林", now=day, op="daily-replay")
    state = (player(game[1])["stones"], items(game[1]))
    assert play("challenge", "青岚林", now=day, op="daily-replay") == first
    assert (player(game[1])["stones"], items(game[1])) == state


def test_help_lists_the_daily_entry(game, play):
    guide = play("help", "秘境与关卡")
    assert "灵宠今日秘境" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    listing = play("daily_dungeon", now=day)
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in listing.inline_commands}
    assert not linked & buttons
