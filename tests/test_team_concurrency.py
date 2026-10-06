import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql
from .team_support import (
    NAMES,
    NOW,
    USERS,
    command,
    create_players,
    create_team,
    memberships,
    race,
    requests,
    resources,
)


def test_concurrent_approval_of_last_slot_admits_exactly_one(game, play):
    create_players(play)
    create_team(play, members=(1,))
    for candidate in (2, 3):
        play("team_join", NAMES[0], user=USERS[candidate])
    before = resources(game[1], USERS[:4])

    results = race(game[0], [
        command(0, "team_accept", NAMES[index], f"last-slot-{index}")
        for index in (2, 3)
    ])

    assert sum(not isinstance(result, GameError) for result in results) == 1
    rows = memberships(game[1])
    assert len(rows) == game[0].content.rules.max_team_size == 3
    assert sum(row["user_id"] in USERS[2:4] for row in rows) == 1
    assert resources(game[1], USERS[:4]) == before
    admitted = {row["user_id"] for row in rows}
    assert all(row["candidate_id"] not in admitted for row in requests(game[1]))


def test_two_teams_cannot_approve_the_same_candidate(game, play):
    create_players(play, count=3)
    create_team(play, leader=0)
    create_team(play, leader=1)
    for leader in (0, 1):
        play("team_join", NAMES[leader], user=USERS[2])
    before = resources(game[1], USERS[:3])

    results = race(game[0], [
        command(leader, "team_accept", NAMES[2], f"competing-team-{leader}")
        for leader in (0, 1)
    ])

    assert sum(not isinstance(result, GameError) for result in results) == 1
    candidate = [row for row in memberships(game[1]) if row["user_id"] == USERS[2]]
    assert len(candidate) == 1
    winner = next(index for index, result in enumerate(results) if not isinstance(result, GameError))
    assert candidate[0]["team_id"] == sql(
        game[1], "SELECT team_id FROM teams WHERE leader_id=?", (USERS[winner],),
    )[0]["team_id"]
    assert not requests(game[1])
    assert resources(game[1], USERS[:3]) == before


@pytest.mark.parametrize("request_action", ["team_join", "team_invite"])
def test_request_redelivery_and_approval_redelivery_do_not_mutate_twice(game, play, request_action):
    create_players(play, count=2)
    create_team(play)
    sender, argument, recipient = (1, NAMES[0], 0) if request_action == "team_join" else (0, NAMES[1], 1)
    request_event = command(sender, request_action, argument, "same-request")
    created = race(game[0], [request_event] * 4)
    assert all(result == created[0] for result in created)
    assert not isinstance(created[0], GameError)
    assert len(requests(game[1])) == 1
    with pytest.raises(GameError):
        play(request_action, argument, user=USERS[sender])

    accept_arg = NAMES[1] if request_action == "team_join" else NAMES[0]
    accept_event = command(recipient, "team_accept", accept_arg, "same-approval")
    accepted = race(game[0], [accept_event] * 4)
    assert all(result == accepted[0] for result in accepted)
    assert not isinstance(accepted[0], GameError)
    assert len(memberships(game[1])) == 2
    assert not requests(game[1])
    assert game[0].execute(*request_event) == created[0]
    assert not requests(game[1])
    with pytest.raises(GameError):
        play("team_accept", accept_arg, user=USERS[recipient])

    play("team_leave", user=USERS[1])
    after_leave = memberships(game[1])
    assert game[0].execute(*accept_event) == accepted[0]
    assert memberships(game[1]) == after_leave
    assert not requests(game[1])


@pytest.mark.parametrize("request_action", ["team_join", "team_invite"])
def test_different_events_cannot_consume_a_request_twice(game, play, request_action):
    create_players(play, count=2)
    create_team(play)
    if request_action == "team_join":
        play(request_action, NAMES[0], user=USERS[1])
        recipient, target = 0, NAMES[1]
    else:
        play(request_action, NAMES[1], user=USERS[0])
        recipient, target = 1, NAMES[0]

    results = race(game[0], [
        command(recipient, "team_accept", target, f"distinct-approval-{index}")
        for index in range(4)
    ])
    assert sum(not isinstance(result, GameError) for result in results) == 1
    assert len(memberships(game[1])) == 2
    assert not requests(game[1])


@pytest.mark.parametrize("change", ["team_leave", "team_kick", "team_disband"])
@pytest.mark.parametrize("battle_first", [False, True])
def test_membership_change_and_expedition_settle_atomically(game, play, change, battle_first):
    create_players(play, count=3)
    create_team(play, members=(1, 2))
    sql(game[1], "UPDATE pets SET layer=5")
    for user in USERS[:3]:
        play("team_ready", user=user)
    before = resources(game[1], USERS[:3])
    mutation = command(1 if change == "team_leave" else 0, change, NAMES[1] if change == "team_kick" else "", "roster-change")
    battle = command(0, "team_challenge", "上古灵殿", "racing-expedition")
    commands = [battle, mutation] if battle_first else [mutation, battle]

    results = race(game[0], commands)

    battle_result = results[0 if battle_first else 1]
    change_result = results[1 if battle_first else 0]
    assert not isinstance(change_result, GameError)
    if isinstance(battle_result, GameError):
        assert resources(game[1], USERS[:3]) == before
    else:
        assert battle_result.title == "秘境获胜"
        for user in USERS[:3]:
            assert pet(game[1], user)["energy"] == 70
            assert player(game[1], user)["last_pve"] == NOW
            assert items(game[1], user)["bloodline_essence"] == 1
        settled = resources(game[1], USERS[:3])
        assert game[0].execute(*battle) == battle_result
        assert resources(game[1], USERS[:3]) == settled
    rows = memberships(game[1])
    assert not any(row["ready_pet_id"] for row in rows)
    if change == "team_disband":
        assert not rows
        assert not sql(game[1], "SELECT * FROM teams")
    else:
        assert {row["user_id"] for row in rows} == {USERS[0], USERS[2]}


@pytest.mark.parametrize("change", ["team_leave", "team_kick", "team_disband"])
def test_failed_expedition_racing_roster_change_preserves_every_resource(game, play, change):
    create_players(play, count=3)
    create_team(play, members=(1, 2))
    sql(game[1], "UPDATE pets SET layer=5")
    sql(game[1], "UPDATE pets SET energy=0 WHERE user_id=?", (USERS[2],))
    for user in USERS[:3]:
        play("team_ready", user=user)
    before = resources(game[1], USERS[:3])

    results = race(game[0], [
        command(0, "team_challenge", "上古灵殿", "failed-expedition"),
        command(1 if change == "team_leave" else 0, change, NAMES[1] if change == "team_kick" else "", "concurrent-change"),
    ])

    assert isinstance(results[0], GameError)
    assert not isinstance(results[1], GameError)
    assert resources(game[1], USERS[:3]) == before
    assert not any(row["ready_pet_id"] for row in memberships(game[1]))
