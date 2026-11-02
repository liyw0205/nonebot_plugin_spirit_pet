"""Daily bounties: three rotating goals, independent claims, today-scoped progress."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import bounty, counters
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
DAY = 86400


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def ready(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='u1'")


def today_names(game, now=NOW):
    return [entry.name for entry in bounty.todays(ctx_of(game, now))]


def day_with(game, bounty_id, *, start=NOW):
    """The first day offset whose window contains the given bounty."""
    total = len(game[0].content.bounties)
    for offset in range(total + 1):
        now = start + offset * DAY
        if any(entry.id == bounty_id for entry in bounty.todays(ctx_of(game, now))):
            return now
    raise AssertionError(f"{bounty_id} never offered")


def offered(game, now=NOW):
    return bounty.todays(ctx_of(game, now))


def test_content_declares_a_pool_over_the_new_metrics(game):
    rows = sorted(game[0].content.bounties.values(), key=lambda entry: entry.id)
    assert len(rows) == 5
    assert {row.metric for row in rows} <= {"hybrid_brews", "alchemy_brews", "contracts_met", "hard_clears"}
    assert {row.metric for row in rows} == {"hybrid_brews", "alchemy_brews", "contracts_met", "hard_clears"}
    for row in rows:
        assert row.target >= 1
        assert row.reward.stones.minimum or row.reward.items


def test_page_without_a_pet_is_read_only(game, play):
    page = play("bounty", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_three_bounties_are_offered_and_stable_within_a_day(game, play):
    ready(game, play)
    page = play("bounty")
    names = today_names(game)
    assert len(names) == 3
    for name in names:
        assert name in page.text()
    assert today_names(game, NOW + 60) == names


def test_the_window_rotates_the_next_day(game, play):
    ready(game, play)
    today = today_names(game)
    tomorrow = today_names(game, NOW + DAY)
    assert today != tomorrow
    assert len(set(today) & set(tomorrow)) == 2


def test_progress_reads_only_todays_counter(game, play):
    ready(game, play)
    ctx = ctx_of(game)
    target = offered(game)[0]
    counters.bump(ctx, target.metric, 5)
    assert bounty.progress(ctx, target) == 5
    # the same work seen tomorrow does not count toward tomorrow's progress
    later = ctx_of(game, NOW + DAY)
    assert bounty.progress(later, target) == 0
    assert counters.value(ctx, target.metric) == 5


def test_claiming_before_the_target_is_refused(game, play):
    ready(game, play)
    target = offered(game)[0]
    with pytest.raises(GameError, match="尚未达成"):
        play("bounty", f"领取 {target.name}")
    assert not bounty.claimed(ctx_of(game), target)
    assert player(game[1])["stones"] == 5000


def test_claiming_pays_once_and_marks_the_day(game, play):
    ready(game, play)
    target = offered(game)[0]
    counters.bump(ctx_of(game), target.metric, target.target)
    stones = player(game[1])["stones"]
    reply = play("bounty", f"领取 {target.name}", op="claim")
    assert reply.title == "赏金已领"
    assert player(game[1])["stones"] == stones + target.reward.stones.minimum
    assert bounty.claimed(ctx_of(game), target)
    row = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id=?", (bounty.claim_key(target, NOW),))
    assert row and row[0]["progress"] == 1


def test_a_second_claim_is_refused(game, play):
    ready(game, play)
    target = offered(game)[0]
    counters.bump(ctx_of(game), target.metric, target.target)
    play("bounty", f"领取 {target.name}", op="first")
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="今日已领取"):
        play("bounty", f"领取 {target.name}", op="second")
    assert player(game[1])["stones"] == stones


def test_bounties_can_be_claimed_independently(game, play):
    ready(game, play)
    first, second = offered(game)[:2]
    counters.bump(ctx_of(game), first.metric, first.target)
    counters.bump(ctx_of(game), second.metric, second.target)
    play("bounty", f"领取 {first.name}", op="one")
    reply = play("bounty", f"领取 {second.name}", op="two")
    assert reply.title == "赏金已领"


def test_a_bounty_outside_todays_window_is_refused(game, play):
    ready(game, play)
    offered_ids = {entry.id for entry in offered(game)}
    outsider = next(entry for entry in game[0].content.bounties.values() if entry.id not in offered_ids)
    with pytest.raises(GameError, match="今日赏金没有"):
        play("bounty", f"领取 {outsider.name}")


def test_unknown_and_malformed_requests_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("bounty", "领取 不存在的赏金")
    with pytest.raises(GameError, match="格式"):
        play("bounty", "领取")
    with pytest.raises(GameError, match="格式"):
        play("bounty", "莫名其妙")


def test_replaying_a_claim_is_identical(game, play):
    ready(game, play)
    target = offered(game)[0]
    counters.bump(ctx_of(game), target.metric, target.target)
    first = play("bounty", f"领取 {target.name}", op="replay")
    stones = player(game[1])["stones"]
    again = play("bounty", f"领取 {target.name}", op="replay")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones


def test_real_work_moves_a_bounty(game, play):
    """A real alchemy brew raises today's counter and unlocks its bounty."""
    now = day_with(game, "bounty_alchemy")
    play("adopt", "青鸾", now=now)
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='u1'")
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1'")
    for item_id, amount in {"spirit_food": 4, "seed_blood_herb": 4}.items():
        sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, ?)", (item_id, amount))
    target = next(entry for entry in bounty.todays(ctx_of(game, now)) if entry.id == "bounty_alchemy")
    play("alchemy", "回元丹", op="brew", now=now)
    assert bounty.progress(ctx_of(game, now), target) >= 1
    reply = play("bounty", f"领取 {target.name}", op="claim", now=now)
    assert reply.title == "赏金已领"


def test_objective_help_and_parse(game, play):
    ready(game, play)
    target = offered(game)[0]
    assert "赏金：" in play("objectives").text()
    counters.bump(ctx_of(game), target.metric, target.target)
    assert "赏金：1 份可领取" in play("objectives").text()
    assert "灵宠赏金" in play("help", "秘境与关卡").text()
    assert handlers._parse("灵宠赏金") == ("bounty", "")
    assert handlers._parse("灵宠赏金 领取 丹火悬赏") == ("bounty", "领取 丹火悬赏")


def test_the_daily_counter_survives_a_restart(game, play):
    ready(game, play)
    target = offered(game)[0]
    counters.bump(ctx_of(game), target.metric, 1)
    rows = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ?",
               (f"stat_{target.metric}_day_%",))
    assert rows and rows[0]["progress"] == 1
    assert bounty.progress(ctx_of(game), target) == 1


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    target = offered(game)[0]
    counters.bump(ctx_of(game), target.metric, target.target)
    page = play("bounty")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4
