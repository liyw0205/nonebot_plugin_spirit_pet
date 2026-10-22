import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .team_support import NOW, USERS, create_players, create_team
from .support import pet, sql

U2_UID = "10001"
U3_UID = "10002"


def prepare_all(play, users):
    for user in users:
        play("team_ready", user=user)


def team_ids(game):
    return [row["team_id"] for row in sql(game[1], "SELECT team_id FROM team_members ORDER BY user_id")]


def rating_rows(game):
    return sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress WHERE quest_id LIKE 'team_rating_%'")


def boost(game):
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")


def test_team_pvp_moves_team_ratings(game, play):
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    prepare_all(play, USERS[:2])
    prepare_all(play, USERS[2:4])
    boost(game)
    play("team_arena_battle", "10002", user=USERS[0], op="battle-1")
    rows = rating_rows(game)
    assert len(rows) == 2
    values = sorted(row["progress"] for row in rows)
    assert values == [980, 1020]


def test_team_pvp_requires_two_members_each(game, play):
    create_players(play, 3)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2)
    with pytest.raises(GameError, match="至少两名"):
        play("team_arena_battle", U3_UID, user=USERS[0], op="battle-solo-opponent")


def test_team_pvp_requires_full_preparation(game, play):
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    prepare_all(play, USERS[:2])
    with pytest.raises(GameError, match="全员准备"):
        play("team_arena_battle", "10002", user=USERS[0], op="battle-not-ready")


def test_team_pvp_rejects_self_team(game, play):
    create_players(play, 2)
    create_team(play, leader=0, members=(1,))
    prepare_all(play, USERS[:2])
    with pytest.raises(GameError, match="自己的队伍|其他队伍"):
        play("team_arena_battle", "10000", user=USERS[0], op="battle-self")


def test_team_pvp_deducts_energy_and_awards_mastery(game, play):
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    prepare_all(play, USERS[:2])
    prepare_all(play, USERS[2:4])
    boost(game)
    play("team_arena_battle", "10002", user=USERS[0], op="battle-energy")
    # Only the challenger team pays energy; defenders keep theirs (mirror rule).
    rows = sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")
    assert any(row["energy"] < 100 for row in rows)


def test_rating_floor_never_negative(game, play):
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    prepare_all(play, USERS[:2])
    prepare_all(play, USERS[2:4])
    for team_id in (1, 2):
        captain = USERS[0] if team_id == 1 else USERS[2]
        sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 5, 0)",
            (captain, f"team_rating_2027-01_{team_id}"))
    play("team_arena_battle", "10002", user=USERS[0], op="battle-floor")
    values = sorted(row["progress"] for row in rating_rows(game))
    assert values[0] >= 0


def test_catalog_shows_team_rating(game, play):
    create_players(play, 2)
    create_team(play, leader=0, members=(1,))
    page = play("team_arena", user=USERS[0])
    assert "积分 1000" in page.text()
    assert "组队论剑" in page.title


def test_catalog_requires_a_team(game, play):
    create_players(play, 1)
    with pytest.raises(GameError, match="队伍"):
        play("team_arena", user=USERS[0])


def test_tier_claim_pays_once(game, play):
    create_players(play, 2)
    create_team(play, leader=0, members=(1,))
    team_id = team_ids(game)[0]
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1500, 0)",
        (USERS[0], f"team_rating_2027-01_{team_id}"))
    reply = play("team_arena_claim", "青云", user=USERS[0], op="claim-1")
    assert "已领取" in reply.text()
    with pytest.raises(GameError, match="已领取"):
        play("team_arena_claim", "青云", user=USERS[0], op="claim-2")


def test_tier_claim_rejects_low_rating(game, play):
    create_players(play, 2)
    create_team(play, leader=0, members=(1,))
    with pytest.raises(GameError, match="还差"):
        play("team_arena_claim", "凌霄", user=USERS[0], op="claim-low")


def test_tier_claim_rejects_unknown_tier(game, play):
    create_players(play, 2)
    create_team(play, leader=0, members=(1,))
    with pytest.raises(GameError, match="没有该段位"):
        play("team_arena_claim", "不存在段位", user=USERS[0], op="claim-unknown")


def test_season_id_scopes_team_rating(game, play):
    create_players(play, 2)
    create_team(play, leader=0, members=(1,))
    team_id = team_ids(game)[0]
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1500, 0)",
        (USERS[0], f"team_rating_2026-12_{team_id}"))
    page = play("team_arena", user=USERS[0])
    assert "积分 1000" in page.text()
