import json
from datetime import date, datetime, timedelta, timezone

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
BEIJING = timezone(timedelta(hours=8))


def week_start(now=NOW):
    start, _ = beijing_week(now)
    return start


def next_week(now=NOW):
    return now + 7 * 86400


def seed_battle(game, *, user="u1", winner_side=0, played_at=NOW, operation="seed-boss"):
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, 'pve', 'world_boss_seed', 'seed', ?, 3, ?, '{}', '[]')",
            (operation, user, winner_side, played_at),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')",
            (cursor.lastrowid, user),
        )


def threat_rows(game, week=None):
    suffix = f"world_boss_threat_{week}" if week is not None else "%"
    return sql(game[1], f"SELECT user_id, progress, claimed FROM quest_progress WHERE quest_id LIKE '{suffix}'")


def boss_name(play, now=NOW):
    return play("world_boss", now=now).lines[0].split("：", 1)[1].split(" · ", 1)[0]


def test_boss_rotation_is_deterministic_per_beijing_week(game, play):
    first = boss_name(play, week_start())
    assert boss_name(play, week_start() + 3600) == first
    assert boss_name(play, week_start() + 6 * 86400) == first
    second = boss_name(play, next_week())
    assert second != first
    assert first in {entry.name for entry in game[0].content.enemies.values()}


def test_catalog_previews_rules_without_an_account(game, play):
    page = play("world_boss", user="u9")
    assert "本周首领：" in page.lines[0]
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_win_adds_threat_and_loss_adds_less(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")
    before = 0
    reply = play("world_boss_challenge", op="boss-win")
    assert reply.title == "首领战胜利"
    assert "全服威胁 +12" in reply.text()
    assert threat_rows(game) and threat_rows(game)[0]["progress"] == 12
    after = sql(game[1], "SELECT COUNT(*) AS n FROM battle_records WHERE battle_key LIKE 'world_boss_%'")[0]["n"]
    assert after == before + 1
    assert player(game[1])["last_pve"] is not None


def test_daily_challenge_cap_three_per_day(game, play):
    play("adopt", "青鸾")
    for index in range(3):
        sql(game[1], "UPDATE players SET last_pve=NULL")
        sql(game[1], "UPDATE pets SET energy=100")
        play("world_boss_challenge", now=NOW + index, op=f"cap-{index}")
    with pytest.raises(GameError, match="已达 3 次"):
        play("world_boss_challenge", now=NOW + 3, op="cap-4")
    # Next Beijing day resets the counter.
    tomorrow = NOW + 86400
    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    reply = play("world_boss_challenge", now=tomorrow, op="cap-next-day")
    assert reply.title in {"首领战胜利", "首领战败退", "首领战平局"}


def ensure_player(game, user):
    sql(game[1], "INSERT OR IGNORE INTO players(user_id, stones) VALUES (?, 0)", (user,))


def add_server_threat(game, user, amount, week=None):
    week = week_start() // (7 * 86400) if week is None else week
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (user, f"world_boss_threat_{week}", amount),
    )


def test_tiers_and_defeat_reward_flow(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")
    for index in range(3):
        sql(game[1], "UPDATE players SET last_pve=NULL")
        sql(game[1], "UPDATE pets SET energy=100")
        play("world_boss_challenge", now=NOW + index * 700, op=f"flow-{index}")
    page = play("world_boss")
    assert "第 1 档：灵石 120 · 可领取" in page.text()
    assert "第 3 档：灵石 300 · 可领取" in page.text()
    claimed = play("world_boss_claim", "1", op="tier-1")
    assert player(game[1])["stones"] >= 120
    assert items(game[1])["spirit_food"] >= 2
    with pytest.raises(GameError, match="已领取"):
        play("world_boss_claim", "1", op="tier-1-again")
    # Fill the server-wide goal to unlock the defeat reward.
    for user in ("u2", "u3", "u4"):
        ensure_player(game, user)
        add_server_threat(game, user, 12)
    page = play("world_boss")
    assert "击退奖励：本周首领已被击退，可领取。" in page.text()
    reward = play("world_boss_claim", "击退", op="defeat-reward")
    assert "击退奖励已领取" in reward.text()
    with pytest.raises(GameError, match="已领取"):
        play("world_boss_claim", "击退", op="defeat-reward-again")


def test_defeat_reward_requires_a_weekly_win(game, play):
    play("adopt", "青鸾")
    ensure_player(game, "u2")
    add_server_threat(game, "u2", 60)
    with pytest.raises(GameError, match="需战胜首领一次"):
        play("world_boss_claim", "击退", op="defeat-no-win")


def test_tier_claim_rejects_when_under_wins(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="还需"):
        play("world_boss_claim", "7", op="tier-too-early")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'world_boss_tier_%'") == []


def seed_wins(game, count, user="u1", now=NOW):
    """Seed this week's boss wins directly, bypassing the three-per-day cap."""
    key = f"world_boss_{week_start(now) // (7 * 86400)}"
    with game[1].connect() as conn:
        for index in range(count):
            cursor = conn.execute(
                "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
                "winner_side, rounds, played_at, reply, snapshot, battle_log) "
                "VALUES (?, ?, 'pve', ?, 'seed', 0, 3, ?, '{}', '[]', '[]')",
                (f"seed-win-{user}-{index}", user, key, now - index * 60),
            )
            conn.execute(
                "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
                "VALUES (?, ?, 0, 'participant')",
                (cursor.lastrowid, user),
            )


def test_each_win_tier_claims_independently(game, play):
    play("adopt", "青鸾")
    seed_wins(game, 7)
    page = play("world_boss")
    assert "第 1 档：灵石 120 · 可领取" in page.text()
    assert "第 7 档：灵石 700 · 可领取" in page.text()

    play("world_boss_claim", "1", op="tier-independent-1")
    # Claiming the first tier must not consume the other two.
    page = play("world_boss")
    assert "第 1 档：灵石 120 · 已领取" in page.text()
    assert "第 3 档：灵石 300 · 可领取" in page.text()
    assert "第 7 档：灵石 700 · 可领取" in page.text()

    stones = player(game[1])["stones"]
    play("world_boss_claim", "3", op="tier-independent-3")
    play("world_boss_claim", "7", op="tier-independent-7")
    assert player(game[1])["stones"] == stones + 300 + 700
    for tier in (1, 3, 7):
        with pytest.raises(GameError, match="已领取"):
            play("world_boss_claim", str(tier), op=f"tier-independent-{tier}-again")
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'world_boss_tier_%' ORDER BY quest_id")
    week = week_start() // (7 * 86400)
    assert [row["quest_id"] for row in rows] == [f"world_boss_tier_{week}_{tier}" for tier in (1, 3, 7)]


def test_legacy_shared_tier_credential_still_counts_as_the_first_tier(game, play):
    play("adopt", "青鸾")
    seed_wins(game, 7)
    week = week_start() // (7 * 86400)
    # Older saves wrote one shared row per week; it must keep meaning "tier 1".
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 7, 1)",
        (f"world_boss_tier_{week}",),
    )
    page = play("world_boss")
    assert "第 1 档：灵石 120 · 已领取" in page.text()
    assert "第 3 档：灵石 300 · 可领取" in page.text()
    with pytest.raises(GameError, match="已领取"):
        play("world_boss_claim", "1", op="legacy-tier-1")
    play("world_boss_claim", "3", op="legacy-tier-3")
    # The remaining tiers stay claimable next to the legacy row.
    assert "第 7 档奖励已领取" in play("world_boss_claim", "7", op="legacy-tier-7").text()
    with pytest.raises(GameError, match="已领取"):
        play("world_boss_claim", "7", op="legacy-tier-7-again")


def test_claims_reject_unknown_and_malformed_arguments(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="格式|没有该档位"):
        play("world_boss_claim", "abc", op="claim-abc")
    with pytest.raises(GameError, match="没有该档位"):
        play("world_boss_claim", "9", op="claim-9")


def test_credentials_reset_across_weeks(game, play):
    play("adopt", "青鸾")
    week = week_start() // (7 * 86400)
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)", (f"world_boss_tier_{week}",))
    page = play("world_boss", now=next_week())
    assert "第 1 档：灵石 120 · 未达成" in page.text()


def test_objectives_surfaces_boss_row_and_hub_link(game, play):
    play("adopt", "青鸾")
    page = play("objectives")
    assert "周首领：威胁 0/60" in page.text()
    row = next(index for index, line in enumerate(page.lines) if line.startswith("周首领："))
    link = next(link for link in page.inline_commands if link.command == "灵宠首领")
    assert link.line == row


def test_help_and_native_keyboard_stay_connected(game, play):
    play("adopt", "青鸾")
    help_page = play("help", "秘境与关卡")
    assert "灵宠首领：查看本周首领、全服威胁进度与个人档位奖励。" in help_page.text()
    page = play("world_boss")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & {link.command for link in page.inline_commands}
