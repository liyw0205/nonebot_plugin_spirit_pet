import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_day, beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
WEEK_START, WEEK_END = beijing_week(NOW)
LAST_WEEK = WEEK_START - 86400
NEXT_WEEK = WEEK_END + 3600


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def pet_id(game, user="u1"):
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,))[0]["pet_id"]


def seed_pve_win(game, user, played_at, op):
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title,"
            " winner_side, rounds, played_at, reply, snapshot, battle_log)"
            " VALUES (?, ?, 'pve', 'forest', '秘境', 0, 3, ?, '{}', '{}', '[]')",
            (op, user, played_at),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, 0, 'participant')",
            (cursor.lastrowid, user),
        )


def seed_expedition(game, user, played_at, op):
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
            " started_at, finishes_at, state, reward_snapshot, settled_at)"
            " VALUES (?, ?, 'job', '任务', ?, ?, ?, 'claimed', '{}', ?)",
            (user, pet_id(game, user), op, played_at - 3600, played_at, played_at),
        )


def seed_discovery(game, user, encounter_id, played_at):
    sql(
        game[1],
        "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
        (user, encounter_id, played_at),
    )


def seed_stage_clear(game, user, stage_id, played_at, op):
    sql(
        game[1],
        "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id)"
        " VALUES (?, ?, ?, ?)",
        (user, stage_id, played_at, op),
    )


def seed_achievement_claim(game, user, achievement_id, played_at, op):
    sql(
        game[1],
        "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at,"
        " reward_snapshot, reply) VALUES (?, ?, ?, ?, '{}', '{}')",
        (user, achievement_id, op, played_at),
    )


def seed_pvp_win(game, user, played_at, op, season_id="2027-01"):
    with game[1].connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot)"
            " VALUES (?, ?, ?, ?, '{}')",
            (season_id, WEEK_START - 86400 * 30, WEEK_END + 86400 * 30, WEEK_START - 86400 * 30),
        )
        conn.execute(
            "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id,"
            " target_pet_id, winner_id, day, played_at, delta, operation_id, reply)"
            " VALUES (?, ?, 'u2', ?, ?, ?, ?, ?, 10, ?, '{}')",
            (season_id, user, pet_id(game, user), pet_id(game, "u2"), user, beijing_day(played_at),
             played_at, op),
        )


def test_content_defines_six_weekly_goals(game):
    quests = list(game[0].content.weekly_quests.values())
    assert len(quests) == 6
    assert {quest.metric for quest in quests} == {
        "weekly_pve_wins", "weekly_pvp_wins", "weekly_expedition_claims",
        "weekly_adventures", "weekly_stage_clears", "weekly_achievement_claims",
    }
    for quest in quests:
        assert quest.target > 0 and quest.description
        assert all(item in game[0].content.items for item in quest.reward.items)


def test_catalog_previews_without_an_account(game, play):
    listing = play("weekly_quests")
    assert "尚未结契" in listing.text()
    assert beijing_day(WEEK_START) in listing.lines[0]
    assert links(listing) == [(1, "开始领养", "灵宠领养 ")]
    assert not sql(game[1], "SELECT * FROM players")


def test_catalog_shows_the_week_and_zero_progress(game, play):
    account(game, play)
    listing = play("weekly_quests")
    assert listing.title == "灵宠周常 1/2"
    assert listing.lines[0] == f"本周周期：{beijing_day(WEEK_START)} ~ {beijing_day(WEEK_END - 1)}（北京时间，周一 00:00 重置）"
    assert "秘境历练：0/5（未达成） · 灵石 800-800，锻灵矿 3-3" in listing.text()
    assert "论剑周赛：0/3（未达成） · 灵石 600-600，破境丹 1-1" in listing.text()
    assert links(listing) == []
    assert listing.commands == ("灵宠周常 2", "灵宠任务")
    assert play("weekly_quests", "2").title == "灵宠周常 2/2"


def test_weekly_metrics_count_only_the_current_week(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    seed_pve_win(game, "u1", NOW, "wk-pve-in")
    seed_pve_win(game, "u1", LAST_WEEK, "wk-pve-old")
    seed_pvp_win(game, "u1", NOW, "wk-pvp-in")
    seed_pvp_win(game, "u1", NEXT_WEEK, "wk-pvp-new")
    seed_expedition(game, "u1", NOW, "wk-exp-in")
    seed_expedition(game, "u1", LAST_WEEK, "wk-exp-old")
    encounters = list(game[0].content.encounters)
    seed_discovery(game, "u1", encounters[0], NOW)
    seed_discovery(game, "u1", encounters[1], LAST_WEEK)
    seed_stage_clear(game, "u1", "stage_01", NOW, "wk-stage-in")
    seed_stage_clear(game, "u1", "tower_01", NOW, "wk-tower-in")
    seed_stage_clear(game, "u1", "stage_02", LAST_WEEK, "wk-stage-old")
    seed_achievement_claim(game, "u1", "first_bond", NOW, "wk-ach-in")
    seed_achievement_claim(game, "u1", "first_bond_old", LAST_WEEK, "wk-ach-old")

    text = play("weekly_quests").text()
    assert "秘境历练：1/5" in text
    assert "论剑周赛：1/3" in text
    assert "山海往来：1/3" in text
    assert "奇闻寻访：1/5" in text
    assert "关卡推进：1/2" in text
    # The sixth goal sits on the second page.
    assert "成就累积：1/2" in play("weekly_quests", "2").text()


def test_claim_grants_once_and_marks_the_week(game, play):
    account(game, play)
    seed_pve_win(game, "u1", NOW, "wk-claim-1")
    listing = play("weekly_quests")
    assert "秘境历练：1/5（未达成）" in listing.text()
    with pytest.raises(GameError, match="本周尚未达成"):
        play("weekly_quest_claim", "秘境历练", op="wk-claim-early")

    for index in range(2, 6):
        seed_pve_win(game, "u1", NOW, f"wk-claim-{index}")
    listing = play("weekly_quests")
    assert "秘境历练：5/5（可领取）" in listing.text()
    assert (1, "领取奖励", "灵宠周常领奖 秘境历练") in links(listing)

    before = (player(game[1])["stones"], items(game[1]).get("forge_ore", 0))
    claimed = play("weekly_quest_claim", "秘境历练", op="wk-claim")
    assert claimed.title == "周常奖励已领取"
    assert "秘境历练已完成。" in claimed.text()
    assert "灵石 +800" in claimed.text() and "锻灵矿 +3" in claimed.text()
    assert player(game[1])["stones"] == before[0] + 800
    assert items(game[1])["forge_ore"] == before[1] + 3
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id='weekly_pve'",
    ) == [{"progress": WEEK_START, "claimed": 1}]
    assert "秘境历练：5/5（已领取）" in play("weekly_quests").text()

    after = (player(game[1])["stones"], items(game[1]))
    with pytest.raises(GameError, match="本周这项奖励已领取"):
        play("weekly_quest_claim", "秘境历练", op="wk-claim-again")
    assert (player(game[1])["stones"], items(game[1])) == after


def test_week_rollover_resets_progress_and_claim(game, play):
    account(game, play)
    for index in range(5):
        seed_pve_win(game, "u1", NOW, f"wk-roll-{index}")
    play("weekly_quest_claim", "秘境历练", op="wk-roll-claim", now=NOW)
    assert "秘境历练：5/5（已领取）" in play("weekly_quests", now=NOW).text()

    later = play("weekly_quests", now=WEEK_END + 3600)
    assert "秘境历练：0/5（未达成）" in later.text()
    assert beijing_day(WEEK_END) in later.lines[0]


def test_replay_does_not_grant_twice(game, play):
    account(game, play)
    for index in range(5):
        seed_pve_win(game, "u1", NOW, f"wk-replay-{index}")
    first = play("weekly_quest_claim", "秘境历练", op="wk-replay")
    state = (player(game[1])["stones"], items(game[1]))
    assert play("weekly_quest_claim", "秘境历练", op="wk-replay") == first
    assert (player(game[1])["stones"], items(game[1])) == state


def test_claim_rejects_an_unknown_goal(game, play):
    account(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("weekly_quest_claim", "不存在的周常")


def test_help_lists_the_weekly_entries(game, play):
    guide = play("help", "秘境与关卡")
    assert "灵宠周常" in guide.text()
    assert "灵宠周常领奖 名称" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    account(game, play)
    for index in range(5):
        seed_pve_win(game, "u1", NOW, f"wk-native-{index}")
    listing = play("weekly_quests")
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
