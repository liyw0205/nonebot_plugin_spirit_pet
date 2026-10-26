"""Team arena must fight the lineup 灵宠准备 previewed.

The shared team-battle rule (`loadout.team_pets`) is: the captain fields up to
three pets, each teammate fields one, at most five per side. Team dungeons and
team stages already use it, and `灵宠准备` stores exactly those pets. Team arena
used to build each side from every member's full roster instead, so a two-player
team where both players keep a three-pet lineup previewed 4 pets and then failed
with "每侧最多出战五只灵宠" without ever fighting.
"""

import json

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql
from .team_support import USERS, create_players, create_team

SPECIES = ("qingluan", "xuanhu", "baize")


def three_pet_lineups(play, game, users):
    """Give each user a three-pet lineup, the maximum a single player may field."""
    for user in users:
        play("adopt", "青鸾", user=user)
        sql(game[1], "UPDATE players SET stones=10000 WHERE user_id=?", (user,))
        play("summon", "2", user=user)
        pets = sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user,))
        for row, species_id in zip(pets, SPECIES):
            sql(
                game[1],
                "UPDATE pets SET species_id=?, energy=100 WHERE pet_id=?",
                (species_id, row["pet_id"]),
            )
        play("lineup", " ".join(str(row["pet_id"]) for row in pets), user=user)


def roster(game, user):
    return [
        row["pet_id"] for row in sql(
            game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id=? ORDER BY slot", (user,),
        )
    ]


def energies(game, pet_ids):
    placeholders = ", ".join("?" for _ in pet_ids)
    rows = sql(
        game[1], f"SELECT pet_id, energy FROM pets WHERE pet_id IN ({placeholders}) ORDER BY pet_id",
        tuple(pet_ids),
    )
    return {row["pet_id"]: row["energy"] for row in rows}


def ready_team(play, users):
    for user in users:
        play("team_ready", user=user)


def test_two_player_teams_fight_the_previewed_four_pets(game, play):
    users = USERS[:4]
    three_pet_lineups(play, game, users)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    ready_team(play, users)
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")

    reply = play("team_arena_battle", "10002", user=users[0], op="lineup-battle")

    # Captain three pets + teammate one pet on each side: the previewed lineup.
    assert "本队 4 宠 对 对方 4 宠" in reply.lines[0]
    snapshot = sql(game[1], "SELECT snapshot FROM battle_records WHERE operation_id='lineup-battle'")[0]
    teams = json.loads(snapshot["snapshot"])["teams"]
    assert [len(team["members"]) for team in teams] == [4, 4]


def test_only_fighting_pets_pay_energy_and_earn_mastery(game, play):
    users = USERS[:4]
    three_pet_lineups(play, game, users)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    ready_team(play, users)
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")

    captain_pets = roster(game, users[0])
    teammate_pets = roster(game, users[1])
    defender_pets = roster(game, users[2]) + roster(game, users[3])
    before = energies(game, captain_pets + teammate_pets + defender_pets)

    play("team_arena_battle", "10002", user=users[0], op="lineup-energy")

    after = energies(game, captain_pets + teammate_pets + defender_pets)
    # Captain fights with all three; the teammate fights with the first one only.
    for pet_id in captain_pets:
        assert after[pet_id] == before[pet_id] - 20
    assert after[teammate_pets[0]] == before[teammate_pets[0]] - 20
    # The teammate's bench and the whole defending team keep their energy.
    for pet_id in teammate_pets[1:] + defender_pets:
        assert after[pet_id] == before[pet_id]


def test_lineup_change_after_ready_blocks_the_battle(game, play):
    users = USERS[:4]
    three_pet_lineups(play, game, users)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    ready_team(play, users)
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")

    # Changing the lineup drops the ready row, so the team must re-prepare and
    # no battle may be recorded against the old preview.
    play("lineup", str(roster(game, users[1])[0]), user=users[1])
    with pytest.raises(GameError, match="全员准备"):
        play("team_arena_battle", "10002", user=users[0], op="lineup-stale")
    assert sql(game[1], "SELECT COUNT(*) AS count FROM battle_records")[0]["count"] == 0


def test_ready_row_mismatch_is_refused_instead_of_silently_refighting(game, play):
    """Defensive guard: a ready row that does not match the side must not fight."""
    users = USERS[:4]
    three_pet_lineups(play, game, users)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    ready_team(play, users)
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")

    # Simulate a stale row written by another version: non-empty, but listing
    # pets the shared rule would not field.
    sql(
        game[1],
        "UPDATE team_members SET ready_pet_ids=? WHERE user_id=?",
        (json.dumps(roster(game, users[1])), users[1]),
    )
    with pytest.raises(GameError, match="尚未准备当前出战灵宠"):
        play("team_arena_battle", "10002", user=users[0], op="lineup-mismatch")
    assert sql(game[1], "SELECT COUNT(*) AS count FROM battle_records")[0]["count"] == 0


def test_single_pet_teams_keep_fighting_one_pet_each(game, play):
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    ready_team(play, USERS[:4])
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")

    reply = play("team_arena_battle", "10002", user=USERS[0], op="lineup-single")
    assert "本队 2 宠 对 对方 2 宠" in reply.lines[0]


def test_full_three_player_team_stops_at_the_five_pet_cap(game, play):
    users = USERS[:6]
    three_pet_lineups(play, game, users)
    create_team(play, leader=0, members=(1, 2))
    create_team(play, leader=3, members=(4,))
    ready_team(play, users[:3])
    ready_team(play, users[3:5])
    sql(game[1], "UPDATE pets SET bloodline=4, layer=10")

    reply = play("team_arena_battle", "10003", user=users[0], op="lineup-cap")
    assert "本队 5 宠 对 对方 4 宠" in reply.lines[0]
