import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import player, sql

NOW = 1_800_000_000
WEEK_START, WEEK_END = beijing_week(NOW)
NEXT_WEEK = WEEK_END + 3600
HARD = {
    "weekly_pve_deep": "weekly_pve_wins",
    "weekly_pvp_deep": "weekly_pvp_wins",
    "weekly_expedition_deep": "weekly_expedition_claims",
    "weekly_adventure_deep": "weekly_adventures",
    "weekly_stage_deep": "weekly_stage_clears",
    "weekly_achievement_deep": "weekly_achievement_claims",
}


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def pet_id(game, user="u1"):
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,))[0]["pet_id"]


def seed_pve_win(game, played_at, op, user="u1"):
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


def stones(game):
    return player(game[1])["stones"]


def test_pool_doubles_with_a_harder_variant_per_metric(game):
    content = game[0].content
    assert len(content.weekly_quests) == 12
    by_metric = {}
    for quest in content.weekly_quests.values():
        by_metric.setdefault(quest.metric, []).append(quest)
    assert len(by_metric) == 6
    for metric, entries in by_metric.items():
        assert len(entries) == 2
        assert len({entry.target for entry in entries}) == 2
    assert set(HARD) <= set(content.weekly_quests)


def test_harder_variants_pay_more_than_their_light_counterpart(game):
    content = game[0].content
    by_metric = {}
    for quest in content.weekly_quests.values():
        by_metric.setdefault(quest.metric, []).append(quest)
    for metric, entries in by_metric.items():
        ordered = sorted(entries, key=lambda entry: entry.target)
        lighter, heavier = ordered
        assert heavier.reward.stones.minimum > lighter.reward.stones.minimum
        assert all(item in content.items for item in heavier.reward.items)


def test_hard_variant_claims_once_and_resets_next_week(game, play):
    account(game, play)
    quest = game[0].content.weekly_quests["weekly_pve_deep"]
    page = next(
        page for page in ("1", "2", "3")
        if f"{quest.name}：" in play("weekly_quests", page).text()
    )
    listing = play("weekly_quests", page)
    assert f"{quest.name}：0/{quest.target}（未达成）" in listing.text()

    for index in range(quest.target):
        seed_pve_win(game, NOW + index, f"weekly-hard-{index}")

    listing = play("weekly_quests", page)
    assert f"{quest.name}：{quest.target}/{quest.target}（可领取）" in listing.text()
    assert (2, "领取奖励", f"灵宠周常领奖 {quest.name}") in links(listing)

    before = stones(game)
    claim = play("weekly_quest_claim", quest.name, op="weekly-hard")
    assert claim.title == "周常奖励已领取"
    assert stones(game) == before + quest.reward.stones.minimum
    assert play("weekly_quest_claim", quest.name, op="weekly-hard").lines == claim.lines
    with pytest.raises(GameError, match="已领取"):
        play("weekly_quest_claim", quest.name)

    # The marker stores the week start, so next week the same quest is claimable again.
    marker = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id=?",
                 (quest.id,))
    assert marker and marker[0]["progress"] == WEEK_START

    # Next week the marker is stale, so the same quest is claimable again once its new-week progress is met.
    for index in range(quest.target):
        seed_pve_win(game, NEXT_WEEK + index, f"weekly-hard-next-{index}")
    assert play("weekly_quest_claim", quest.name, now=NEXT_WEEK).title == "周常奖励已领取"


def test_hub_counts_follow_the_pool(game, play):
    content = game[0].content
    account(game, play)
    line = next(text for text in play("objectives").lines if text.startswith("本周周常："))
    assert f"共 {len(content.weekly_quests)} 项" in line
    assert "12 项" in line
