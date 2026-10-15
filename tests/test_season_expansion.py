import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import season_bounds

from .support import player, sql

NOW = 1_800_000_000
SEASON_LABEL, SEASON_START, SEASON_END = season_bounds(NOW)
NEXT_SEASON = SEASON_END + 3600
HARD = {
    "season_matches_deep": "season_matches",
    "season_wins_deep": "season_wins",
    "season_pve_deep": "season_pve",
    "season_discoveries_deep": "season_discoveries",
    "season_claims_deep": "season_claims",
}


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def stones(game):
    return player(game[1])["stones"]


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


def page_with(game, play, name):
    for page in ("1", "2"):
        reply = play("season_missions", page)
        if name in reply.text():
            return reply
    raise AssertionError(name)


def test_pool_doubles_with_a_harder_variant_per_metric(game):
    content = game[0].content
    assert len(content.season_missions) == 10
    by_metric = {}
    for mission in content.season_missions.values():
        by_metric.setdefault(mission.metric, []).append(mission)
    assert len(by_metric) == 5
    for metric, entries in by_metric.items():
        assert len(entries) == 2
        assert len({entry.target for entry in entries}) == 2
    assert set(HARD) <= set(content.season_missions)


def test_harder_variants_pay_more_than_their_light_counterpart(game):
    content = game[0].content
    by_metric = {}
    for mission in content.season_missions.values():
        by_metric.setdefault(mission.metric, []).append(mission)
    for metric, entries in by_metric.items():
        lighter, heavier = sorted(entries, key=lambda entry: entry.target)
        assert heavier.reward.stones.minimum > lighter.reward.stones.minimum
        assert all(item in content.items for item in heavier.reward.items)


def test_hard_mission_claims_once_and_resets_next_season(game, play):
    account(game, play)
    mission = game[0].content.season_missions["season_pve_deep"]
    listing = page_with(game, play, mission.name)
    assert f"{mission.name} · 灵石 {mission.reward.stones.minimum}" in listing.text()

    with pytest.raises(GameError, match="本赛季尚未完成"):
        play("season_mission_claim", mission.name)

    for index in range(mission.target):
        seed_pve_win(game, NOW + index, f"season-hard-{index}")

    listing = page_with(game, play, mission.name)
    assert "可领取" in next(text for text in listing.lines if text.startswith(mission.name + " ·"))
    assert [link.command for link in listing.inline_commands] == [f"灵宠赛季任务领奖 {mission.name}"]

    before = stones(game)
    claim = play("season_mission_claim", mission.name, op="season-hard")
    assert claim.title == "赛季任务奖励"
    assert stones(game) == before + mission.reward.stones.minimum
    assert play("season_mission_claim", mission.name, op="season-hard").lines == claim.lines
    with pytest.raises(GameError, match="本赛季奖励已领取，下赛季再来"):
        play("season_mission_claim", mission.name)

    marker = sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id=?",
                 (f"season_{mission.id}",))
    assert marker and marker[0]["progress"] == SEASON_START

    # Next season the marker is stale; the same mission is claimable again once its window has progress.
    for index in range(mission.target):
        seed_pve_win(game, NEXT_SEASON + index, f"season-hard-next-{index}")
    assert play("season_mission_claim", mission.name, now=NEXT_SEASON).title == "赛季任务奖励"


def test_hub_counts_follow_the_pool(game, play):
    content = game[0].content
    account(game, play)
    line = next(text for text in play("objectives").lines if text.startswith("赛季任务："))
    assert line == "赛季任务：暂无可领 · 已领取 0/10 项"
    assert f"/{len(content.season_missions)} 项" in line
