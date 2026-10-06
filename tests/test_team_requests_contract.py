import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import sql
from .team_support import (
    NAMES,
    NOW,
    USERS,
    create_players,
    create_team,
    memberships,
    public_text,
    requests,
    resources,
)


def pending_request(play, kind):
    if kind == "apply":
        play("team_join", NAMES[0], user=USERS[1])
        return 0, NAMES[1], 1, NAMES[0]
    play("team_invite", NAMES[1], user=USERS[0])
    return 1, NAMES[0], 0, NAMES[1]


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_only_recipient_can_accept_or_reject_and_only_initiator_can_withdraw(game, play, kind):
    create_players(play, count=3)
    create_team(play)
    recipient, recipient_arg, sender, sender_arg = pending_request(play, kind)
    before = requests(game[1])
    before_resources = resources(game[1], USERS[:3])

    for action in ("team_accept", "team_reject"):
        for actor, target in ((sender, sender_arg), (2, recipient_arg), (2, sender_arg)):
            with pytest.raises(GameError):
                play(action, target, user=USERS[actor])
            assert requests(game[1]) == before
    for actor, target in ((recipient, recipient_arg), (2, sender_arg)):
        with pytest.raises(GameError):
            play("team_withdraw", target, user=USERS[actor])
        assert requests(game[1]) == before

    outsider = public_text(play("team_requests", user=USERS[2]))
    assert NAMES[0] not in outsider and NAMES[1] not in outsider
    for target in NAMES[:2]:
        try:
            reply = play("team_requests", target, user=USERS[2])
        except GameError:
            pass
        else:
            assert NAMES[0] not in public_text(reply) and NAMES[1] not in public_text(reply)
    assert resources(game[1], USERS[:3]) == before_resources

    play("team_withdraw", sender_arg, user=USERS[sender])
    assert not requests(game[1])
    assert len(memberships(game[1])) == 1
    with pytest.raises(GameError):
        play("team_accept", recipient_arg, user=USERS[recipient])


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_rejection_and_withdrawal_are_idempotent_but_new_events_do_not_repeat(game, play, kind):
    create_players(play, count=2)
    create_team(play)
    recipient, target, sender, sender_arg = pending_request(play, kind)
    before = resources(game[1], USERS[:2])
    rejected = play("team_reject", target, user=USERS[recipient], op="rejected-once")
    assert play("team_reject", target, user=USERS[recipient], op="rejected-once") == rejected
    assert not requests(game[1])
    with pytest.raises(GameError):
        play("team_reject", target, user=USERS[recipient])
    pending_request(play, kind)
    withdrawn = play("team_withdraw", sender_arg, user=USERS[sender], op="withdrawn-once")
    assert play("team_withdraw", sender_arg, user=USERS[sender], op="withdrawn-once") == withdrawn
    assert not requests(game[1])
    with pytest.raises(GameError):
        play("team_withdraw", sender_arg, user=USERS[sender])
    assert resources(game[1], USERS[:2]) == before


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_opposite_request_does_not_replace_or_implicitly_accept_pending_request(game, play, kind):
    create_players(play, count=2)
    create_team(play)
    pending_request(play, kind)
    before = requests(game[1])
    action, actor, target = ("team_invite", 0, NAMES[1]) if kind == "apply" else ("team_join", 1, NAMES[0])
    with pytest.raises(GameError):
        play(action, target, user=USERS[actor], now=NOW + 1)
    assert requests(game[1]) == before
    assert len(memberships(game[1])) == 1


@pytest.mark.parametrize("kind", ["apply", "invite"])
@pytest.mark.parametrize("offset", [599, 600, 601])
def test_request_expiry_is_exclusive_at_exact_boundary(game, play, kind, offset):
    create_players(play, count=2)
    create_team(play)
    recipient, target, _, _ = pending_request(play, kind)
    row = requests(game[1])[0]
    assert row["created_at"] == NOW
    assert row["expires_at"] == NOW + game[0].config.spirit_pet_team_request_ttl == NOW + 600
    if offset < 600:
        play("team_accept", target, user=USERS[recipient], now=NOW + offset)
        assert len(memberships(game[1])) == 2
    else:
        with pytest.raises(GameError):
            play("team_accept", target, user=USERS[recipient], now=NOW + offset)
        assert len(memberships(game[1])) == 1
        listing = public_text(play("team_requests", user=USERS[recipient], now=NOW + offset))
        assert target not in listing


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_pending_request_survives_store_and_game_restart(game, play, kind):
    create_players(play, count=2)
    create_team(play)
    recipient, target, _, _ = pending_request(play, kind)
    before = requests(game[1])
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng)
    assert requests(reopened) == before
    restarted.execute(USERS[recipient], "team_accept", target, "accept-after-restart", NOW + 1)
    assert len(memberships(reopened)) == 2
    assert not requests(reopened)


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_pending_request_tracks_ids_while_display_and_actions_use_current_names(game, play, kind):
    create_players(play, count=2)
    create_team(play)
    recipient, _, _, _ = pending_request(play, kind)
    before = requests(game[1])
    renamed = ("云海", "长庚")
    for index, name in enumerate(renamed):
        play("dao_name", name, user=USERS[index])
    assert requests(game[1]) == before

    for actor in (0, 1):
        listing = public_text(play("team_requests", user=USERS[actor]))
        assert renamed[1 - actor] in listing
        assert all(name not in listing for name in NAMES[:2])
        assert all(user not in listing for user in USERS)
    target = renamed[1] if kind == "apply" else renamed[0]
    with pytest.raises(GameError):
        play("team_accept", NAMES[1] if kind == "apply" else NAMES[0], user=USERS[recipient])
    reply = play("team_accept", target, user=USERS[recipient])
    assert all(user not in public_text(reply) for user in USERS)
    status = public_text(play("team_status", user=USERS[0]))
    assert all(name in status for name in renamed)
    assert all(name not in status for name in NAMES[:2])
    assert all(user not in status for user in USERS)


def test_transfer_invalidates_old_leader_requests_authority_and_all_readiness(game, play):
    create_players(play)
    create_team(play, members=(1,))
    play("team_join", NAMES[0], user=USERS[2])
    play("team_invite", NAMES[3], user=USERS[0])
    for user in USERS[:2]:
        play("team_ready", user=user)
    before = resources(game[1], USERS[:4])

    reply = play("team_transfer", NAMES[1], user=USERS[0])

    assert NAMES[1] in public_text(reply)
    assert sql(game[1], "SELECT leader_id FROM teams")[0]["leader_id"] == USERS[1]
    assert not requests(game[1])
    assert not any(row["ready_pet_id"] for row in memberships(game[1]))
    for actor, action, target in (
        (0, "team_accept", NAMES[2]),
        (1, "team_accept", NAMES[2]),
        (3, "team_accept", NAMES[0]),
        (3, "team_accept", NAMES[1]),
        (0, "team_invite", NAMES[2]),
        (0, "team_transfer", NAMES[1]),
        (0, "team_kick", NAMES[1]),
        (0, "team_disband", ""),
    ):
        with pytest.raises(GameError):
            play(action, target, user=USERS[actor])
    assert resources(game[1], USERS[:4]) == before
    play("team_leave", user=USERS[0])
    assert [row["user_id"] for row in memberships(game[1])] == [USERS[1]]


def test_leader_must_explicitly_disband_and_disband_cascades_pending_requests(game, play):
    create_players(play)
    create_team(play, members=(1,))
    play("team_join", NAMES[0], user=USERS[2])
    play("team_invite", NAMES[3], user=USERS[0])
    before_members, before_requests = memberships(game[1]), requests(game[1])
    with pytest.raises(GameError):
        play("team_leave", user=USERS[0])
    assert memberships(game[1]) == before_members
    assert requests(game[1]) == before_requests
    with pytest.raises(GameError):
        play("team_disband", user=USERS[1])
    play("team_disband", user=USERS[0])
    assert not memberships(game[1])
    assert not requests(game[1])
    assert not sql(game[1], "SELECT * FROM teams")


def test_approved_new_member_clears_everyones_preparation_but_request_does_not(game, play):
    create_players(play, count=3)
    create_team(play, members=(1,))
    for user in USERS[:2]:
        play("team_ready", user=user)
    prepared = memberships(game[1])
    assert all(row["ready_pet_id"] for row in prepared)
    play("team_join", NAMES[0], user=USERS[2])
    assert memberships(game[1]) == prepared
    play("team_accept", NAMES[2], user=USERS[0])
    assert len(memberships(game[1])) == 3
    assert not any(row["ready_pet_id"] for row in memberships(game[1]))
