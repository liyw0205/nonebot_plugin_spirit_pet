import re
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
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


def win(game, play, now, op):
    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    return play("challenge", "青岚林", now=now, op=op)


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


def test_catalog_shows_rewards_and_progress(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    listing = play("daily_dungeon", now=day)
    assert listing.title == "今日秘境"
    assert listing.lines[0] == "今日秘境：青岚林 · 启灵起 · 精力 20"
    assert listing.lines[1] == "首胜奖励（当日第 1 胜）：灵石 200-200，锻灵矿 1-1 · 未达成（今日已胜 0/1 场）"
    assert listing.lines[2] == "三胜奖励（当日第 3 胜）：灵石 500-500，血脉精华 1-1 · 未达成（今日已胜 0/3 场）"
    assert links(listing) == [(0, "前往挑战", "灵宠挑战 青岚林")]
    assert listing.commands == ("灵宠秘境", "灵宠任务")
    assert not {command for _, _, command in links(listing)} & set(listing.commands)


def test_first_win_unlocks_the_first_claim_and_claiming_pays_once(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    win(game, play, day, "daily-win-1")
    listing = play("daily_dungeon", now=day)
    assert "首胜奖励（当日第 1 胜）：灵石 200-200，锻灵矿 1-1 · 可领取" in listing.text()
    assert "三胜奖励（当日第 3 胜）：灵石 500-500，血脉精华 1-1 · 未达成（今日已胜 1/3 场）" in listing.text()
    assert (1, "领取首胜奖励", "灵宠今日秘境领奖 首胜") in links(listing)

    before = (player(game[1])["stones"], items(game[1]).get("forge_ore", 0))
    claimed = play("daily_dungeon_claim", "首胜", now=day, op="daily-claim-1")
    assert claimed.title == "今日秘境奖励"
    assert "首胜奖励已领取。" in claimed.text()
    assert "灵石 +200" in claimed.text()
    assert player(game[1])["stones"] == before[0] + 200
    assert items(game[1])["forge_ore"] == before[1] + 1
    # The claim row is stamped with the Beijing day it belongs to.
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id='featured_first'",
    ) == [{"progress": date.fromisoformat(beijing_day(day)).toordinal(), "claimed": 1}]

    after = (player(game[1])["stones"], items(game[1]))
    assert "首胜奖励（当日第 1 胜）：灵石 200-200，锻灵矿 1-1 · 已领取" in play(
        "daily_dungeon", now=day,
    ).text()
    with pytest.raises(GameError, match="今日这份奖励已领取"):
        play("daily_dungeon_claim", "首胜", now=day, op="daily-claim-again")
    assert (player(game[1])["stones"], items(game[1])) == after


def test_third_win_unlocks_the_third_claim_only(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    win(game, play, day, "daily-3-1")
    with pytest.raises(GameError, match="还需 2 场"):
        play("daily_dungeon_claim", "三胜", now=day, op="daily-3-early")
    win(game, play, day + 10, "daily-3-2")
    assert "未达成（今日已胜 2/3 场）" in play("daily_dungeon", now=day).text()
    win(game, play, day + 20, "daily-3-3")
    listing = play("daily_dungeon", now=day)
    assert "三胜奖励（当日第 3 胜）：灵石 500-500，血脉精华 1-1 · 可领取" in listing.text()
    assert (2, "领取三胜奖励", "灵宠今日秘境领奖 三胜") in links(listing)
    assert "血脉精华 +1" in play("daily_dungeon_claim", "三胜", now=day, op="daily-3-claim").text()


def test_non_featured_dungeon_never_unlocks_a_claim(game, play):
    day = now_for(game, 1)
    assert featured_name(play, day) == "月影谷"
    play("adopt", "青鸾", now=day)
    result = play("challenge", "青岚林", now=day, op="non-featured")
    assert result.title == "秘境获胜"
    assert "未达成（今日已胜 0/1 场）" in play("daily_dungeon", now=day).text()
    with pytest.raises(GameError, match="已胜 0 场"):
        play("daily_dungeon_claim", "首胜", now=day, op="non-featured-claim")


def test_day_change_resets_the_daily_claim(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    win(game, play, day, "daily-day-1")
    play("daily_dungeon_claim", "首胜", now=day, op="daily-day-claim")
    assert "首胜奖励（当日第 1 胜）：灵石 200-200，锻灵矿 1-1 · 已领取" in play(
        "daily_dungeon", now=day,
    ).text()
    later = play("daily_dungeon", now=day + 86400)
    assert "未达成（今日已胜 0/1 场）" in later.text()
    assert featured_name(play, day + 86400) == "月影谷"


def test_replay_does_not_claim_twice(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    win(game, play, day, "daily-replay-win")
    first = play("daily_dungeon_claim", "首胜", now=day, op="daily-replay-claim")
    state = (player(game[1])["stones"], items(game[1]))
    assert play("daily_dungeon_claim", "首胜", now=day, op="daily-replay-claim") == first
    assert (player(game[1])["stones"], items(game[1])) == state


def test_claim_rejects_an_unknown_kind(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    with pytest.raises(GameError, match="格式"):
        play("daily_dungeon_claim", "首胜奖励", now=day)


def test_help_lists_the_daily_entries(game, play):
    guide = play("help", "秘境与关卡")
    assert "灵宠今日秘境" in guide.text()
    assert "灵宠今日秘境领奖 首胜" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    day = now_for(game, 0)
    play("adopt", "青鸾", now=day)
    win(game, play, day, "daily-native-win")
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
