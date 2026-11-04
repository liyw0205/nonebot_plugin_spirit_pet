"""灵宠今日: the read-only digest of what can be claimed and what is still open."""

import re
from contextlib import closing
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import drill, mailbox, merchant, today
from nonebot_plugin_spirit_pet.storage.repository import Repository

from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import player, sql

NOW = 1_800_000_000
DAY = 86400


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "today")


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones, active_pet_id FROM players ORDER BY user_id"),
        sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
                     " ORDER BY user_id, quest_id"),
        sql(game[1], "SELECT message_id, state FROM mail_messages ORDER BY message_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
    )


def grant(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def labels(entries):
    return [entry["label"] for entry in entries]


def claim_commands(entries):
    return [entry["command"] for entry in entries if entry["kind"] == today.CLAIM]


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("today", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []


def test_opening_the_digest_changes_no_rows(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    sql(
        game[1],
        "INSERT INTO mail_messages(sender_id, recipient_id, kind, stones, item_id, quantity,"
        " body, created_at, expires_at, state)"
        " VALUES ('u2', 'u1', 'item', 0, 'forge_ore', 1, '寄来', ?, ?, 'active')",
        (NOW, NOW + DAY),
    )
    before = snapshot(game)
    play("today")
    play("today", "1")
    assert snapshot(game) == before


def test_the_digest_never_claims_or_collects(game, play):
    play("adopt", "青鸾")
    before = player(game[1])["stones"]
    play("today")
    assert player(game[1])["stones"] == before
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'sign%'") == []


# ---------------------------------------------------------------- contents

def test_a_fresh_player_is_told_what_is_left(game, play):
    play("adopt", "青鸾")
    claimable, pending = today.collect(context(game))
    assert "每周免费十连可领" in " ".join(labels(claimable))
    pending_text = " ".join(labels(pending))
    assert "演武还剩" in pending_text
    assert "每周图鉴试炼" in pending_text


def test_the_drill_entry_follows_the_quota(game, play):
    play("adopt", "青鸾")
    left = drill.remaining(context(game))
    assert left > 0
    pending = labels(today.collect(context(game))[1])
    assert any(f"演武还剩 {left} 次" == label for label in pending)


def test_mail_letters_are_counted_and_link_to_the_mailbox(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    for index in range(2):
        sql(
            game[1],
            "INSERT INTO mail_messages(sender_id, recipient_id, kind, stones, item_id, quantity,"
            " body, created_at, expires_at, state)"
            " VALUES ('u2', 'u1', 'item', 0, 'forge_ore', 1, ?, ?, ?, 'active')",
            (f"信{index}", NOW, NOW + DAY),
        )
    claimable = today.collect(context(game))[0]
    assert "信箱 2 封待领取" in labels(claimable)
    assert "灵宠信箱" in claim_commands(claimable)
    # count agrees with the mailbox page itself
    with closing(context(game).repo.conn):
        assert len(mailbox.inbox(context(game))) == 2


def test_a_finished_expedition_shows_up_as_claimable(game, play):
    play("adopt", "青鸾")
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', ?, 'task', '任务', 'today-op', ?, ?, 'running', '{}', 0)",
        (pet_id, NOW - 600, NOW - 1),
    )
    claimable = today.collect(context(game))[0]
    assert "派遣 1 项已完成" in labels(claimable)


def test_a_running_expedition_is_not_claimable(game, play):
    play("adopt", "青鸾")
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', ?, 'task', '任务', 'today-op2', ?, ?, 'running', '{}', 0)",
        (pet_id, NOW, NOW + 600),
    )
    assert not any("派遣" in label for label in labels(today.collect(context(game))[0]))


def test_a_deliverable_commission_appears_once_the_materials_are_there(game, play):
    play("adopt", "青鸾")
    with closing(context(game).repo.conn):
        orders = merchant.todays(context(game))
        assert orders, "the first reputation tier must ship orders"
        first = orders[0]
    assert not any("商会" in label for label in labels(today.collect(context(game))[0]))
    grant(game, dict(first.items))
    claimable = today.collect(context(game))[0]
    assert any("商会 1 单可交付" == label for label in labels(claimable))


def test_the_weekly_trial_entry_counts_cleared_slots(game, play):
    play("adopt", "青鸾")
    pending = labels(today.collect(context(game))[1])
    assert "每周图鉴试炼 0/3" in pending


def test_the_free_summon_entry_disappears_after_claiming(game, play):
    play("adopt", "青鸾")
    assert "每周免费十连可领" in labels(today.collect(context(game))[0])
    play("free_summon_claim")
    assert "每周免费十连可领" not in labels(today.collect(context(game))[0])


# ---------------------------------------------------------------- page

def test_the_page_badges_each_entry(game, play):
    play("adopt", "青鸾")
    text = play("today").text()
    assert "[可领] 每周免费十连可领" in text
    assert "[待做] 演武还剩" in text


def test_an_over_range_page_is_refused_without_writing(game, play):
    play("adopt", "青鸾")
    claimable, pending = today.collect(context(game))
    assert len(claimable) + len(pending) <= today.PAGE_SIZE, "this fixture fits one page"
    before = snapshot(game)
    with pytest.raises(GameError, match="今日待办共 1 页"):
        play("today", "2")
    assert snapshot(game) == before


def test_every_entry_command_is_a_real_command(game, play):
    play("adopt", "青鸾")
    play("today", "1")
    for entry in today.collect(context(game))[0] + today.collect(context(game))[1]:
        assert _parse(entry["command"]) is not None, entry["command"]


def test_every_rendered_link_reparses(game, play):
    play("adopt", "青鸾")
    page = play("today")
    for link in page.inline_commands:
        assert link.line < len(page.lines)
        assert _parse(link.command) is not None


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("today")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_the_onebot_text_page_spells_the_command(game, play):
    play("adopt", "青鸾")
    rendered = _qq_segments(play("today"), Config(spirit_pet_qq_mode="text"))[0]
    assert "【灵宠今日】" in rendered


def test_help_and_parser_cover_the_command(game, play):
    play("adopt", "青鸾")
    assert _parse("灵宠今日") == ("today", "")
    assert _parse("灵宠今日 2") == ("today", "2")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["身份与收集"]}
    assert "灵宠今日" in rows


def test_the_objectives_page_does_not_grow_a_line(game, play):
    play("adopt", "青鸾")
    assert all(not line.startswith("今日：") for line in play("objectives").lines)
    assert today.objective_line(None, "u1") == ""


# ---------------------------------------------------------------- check-in and assignments

def signed_days(game, count, user="u1"):
    """Mark the last `count` Beijing days (ending yesterday) as signed in."""
    today = date.fromisoformat(beijing_day(NOW))
    for offset in range(1, count + 1):
        day = today - timedelta(days=offset)
        sql(
            game[1],
            "INSERT OR IGNORE INTO quest_progress(user_id, quest_id, progress, claimed)"
            " VALUES (?, ?, 1, 1)",
            (user, f"signin_day_{day.isoformat()}"),
        )


def test_a_fresh_player_is_reminded_to_sign_in(game, play):
    play("adopt", "青鸾")
    pending = labels(today.collect(context(game))[1])
    assert "今日还没签到" in pending


def test_signing_in_clears_the_reminder(game, play):
    play("adopt", "青鸾")
    play("sign")
    pending = labels(today.collect(context(game))[1])
    assert "今日还没签到" not in pending


def test_a_reached_streak_milestone_becomes_claimable(game, play):
    play("adopt", "青鸾")
    signed_days(game, 3)
    claimable = today.collect(context(game))[0]
    assert "签到里程碑 1 项可领" in labels(claimable)
    assert "灵宠签到奖励" in claim_commands(claimable)


def test_claiming_the_streak_reward_clears_the_entry(game, play):
    play("adopt", "青鸾")
    signed_days(game, 3)
    assert "签到里程碑 1 项可领" in labels(today.collect(context(game))[0])
    play("checkin_reward_claim", "3")
    assert "签到里程碑 1 项可领" not in labels(today.collect(context(game))[0])


def test_assignments_count_as_claimable_only_at_their_target(game, play, monkeypatch):
    play("adopt", "青鸾")
    from nonebot_plugin_spirit_pet.gameplay import daily_assignment

    assert daily_assignment.claimable(context(game), "u1") == []
    monkeypatch.setattr(daily_assignment, "_value", lambda *args, **kwargs: 10_000)
    claimable = daily_assignment.claimable(context(game), "u1")
    assert len(claimable) == len(daily_assignment.todays(context(game)))
    assert "今日课题" in " ".join(labels(today.collect(context(game))[0]))


def test_only_one_assignment_is_claimable_per_day(game, play, monkeypatch):
    play("adopt", "青鸾")
    from nonebot_plugin_spirit_pet.gameplay import daily_assignment

    monkeypatch.setattr(daily_assignment, "_value", lambda *args, **kwargs: 10_000)
    monkeypatch.setattr(daily_assignment, "_chosen", lambda *args, **kwargs: object())
    assert daily_assignment.claimable(context(game), "u1") == []


def test_the_extra_sources_still_write_nothing(game, play):
    play("adopt", "青鸾")
    signed_days(game, 3)
    before = snapshot(game)
    play("today")
    assert snapshot(game) == before
