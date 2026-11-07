"""Weekly non-combat activity summary."""

import json
from contextlib import closing
from datetime import datetime

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day, beijing_week

from .support import pet, sql

NOW = 1_800_000_000
WEEK_START, WEEK_END = beijing_week(NOW)
DAY = 86_400


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW)


def seed_battle(game, kind, *, user="u1", played=WEEK_START + 1, winner_side=0, operation=None):
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, ?, '', 'seed', ?, 3, ?, '{}', ?, '[]')",
            (operation or f"week-{kind}-{user}-{played}", user, kind, winner_side, played,
             json.dumps({"teams": []})),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')", (cursor.lastrowid, user),
        )
        conn.commit()


def seed_signin(game, day, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (user, f"signin_day_{day}"),
    )


def seed_expedition(game, *, user="u1", started=WEEK_START + 1):
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, "
        "started_at, finishes_at, state, reward_snapshot, settled_at, slot) "
        "VALUES (?, ?, 'task', '任务', ?, ?, ?, 'running', '{}', NULL, 0)",
        (user, pet(game[1], user)["pet_id"], f"week-{started}", started, started + 100),
    )


def seed_mail(game, *, sender="u2", recipient="u1", created=WEEK_START + 1, state="active"):
    closed = claimed = created + 1 if state == "claimed" else None
    sql(
        game[1],
        "INSERT INTO mail_messages(sender_id, recipient_id, kind, stones, item_id, quantity, "
        "body, created_at, expires_at, state, closed_at, claimed_at) "
        "VALUES (?, ?, 'stones', 10, NULL, 0, '周报', ?, ?, ?, ?, ?)",
        (sender, recipient, created, created + DAY, state, closed, claimed),
    )


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
        "expeditions": sql(store, "SELECT * FROM expeditions ORDER BY 1"),
        "mail_messages": sql(store, "SELECT * FROM mail_messages ORDER BY 1"),
    }


def test_week_summarizes_signins_battles_expeditions_and_mail(game, play):
    account(game, play)
    account(game, play, "u2")
    seed_signin(game, datetime.fromtimestamp(WEEK_START, BEIJING).strftime("%Y-%m-%d"))
    seed_signin(game, datetime.fromtimestamp(WEEK_START + DAY, BEIJING).strftime("%Y-%m-%d"))
    seed_battle(game, "spar", winner_side=0, played=WEEK_START + 1, operation="w-spar")
    seed_battle(game, "pvp", winner_side=1, played=WEEK_START + 2, operation="w-pvp")
    seed_expedition(game, started=WEEK_START + 3)
    seed_mail(game, created=WEEK_START + 4)
    page = play("weekly_report", now=NOW)
    assert page.title == "灵宠周报"
    assert "统计区间：" in page.text()
    assert "签到：2 天。" in page.text()
    assert "战斗：2 场 · 1 胜。" in page.text()
    assert "切磋 1 场" in page.text() and "论剑 1 场" in page.text()
    assert "委托：本周出发 1 次。" in page.text()
    assert "信箱：收到 1 封 · 已领取 0 封。" in page.text()


def test_previous_week_is_excluded(game, play):
    account(game, play)
    account(game, play, "u2")
    seed_battle(game, "spar", played=WEEK_START - 1, operation="old-spar")
    seed_signin(game, datetime.fromtimestamp(WEEK_START - DAY, BEIJING).strftime("%Y-%m-%d"))
    seed_expedition(game, started=WEEK_START - 1)
    seed_mail(game, created=WEEK_START - 1)
    page = play("weekly_report", now=NOW)
    assert "签到：0 天。" in page.text()
    assert "战斗：0 场 · 0 胜。" in page.text()
    assert "委托：本周出发 0 次。" in page.text()
    assert "信箱：收到 0 封 · 已领取 0 封。" in page.text()


def test_claimed_mail_and_empty_week(game, play):
    account(game, play)
    account(game, play, "u2")
    seed_mail(game, created=WEEK_START + 1, state="claimed")
    page = play("weekly_report", now=NOW)
    assert "信箱：收到 1 封 · 已领取 1 封。" in page.text()


def test_unregistered_is_read_only(game, play):
    page = play("weekly_report", user="ghost", now=NOW)
    assert "尚未结契" in page.text()
    assert page.inline_commands == ()
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_weekly_report_is_read_only(game, play):
    account(game, play)
    account(game, play, "u2")
    seed_battle(game, "spar", operation="ro-week")
    seed_mail(game)
    before = state(game[1])
    play("weekly_report", now=NOW)
    assert state(game[1]) == before


def test_argument_and_help_parser_native(game, play):
    account(game, play)
    with pytest.raises(GameError, match="不接受参数"):
        play("weekly_report", "1", now=NOW)
    assert _parse("灵宠周报") == ("weekly_report", "")
    assert "灵宠周报" in play("help", "结契", now=NOW).text()
    page = play("weekly_report", now=NOW)
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


def seed_arc_choice(game, day, amount=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (user, f"stat_arc_choices_day_{day}", amount),
    )


def test_arc_choices_are_summed_for_the_week(game, play):
    account(game, play)
    seed_arc_choice(game, beijing_day(WEEK_START + DAY), 3)
    seed_arc_choice(game, beijing_day(WEEK_START + 2 * DAY), 2)
    seed_arc_choice(game, beijing_day(WEEK_START - 1), 9)   # previous week: excluded
    page = play("weekly_report", now=NOW)
    assert "奇缘：本周做出 5 次抉择。" in page.text()


def test_arc_choices_are_zero_without_any_history(game, play):
    account(game, play)
    page = play("weekly_report", now=NOW)
    assert "奇缘：本周做出 0 次抉择。" in page.text()
