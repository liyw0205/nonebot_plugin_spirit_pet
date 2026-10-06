from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql

NOW = 1_800_000_000


def register(play, user, name):
    play("adopt", user=user)
    play("dao_name", name, user=user)


def setup(play):
    register(play, "private-leader", "青云")
    register(play, "private-candidate", "赤霄")
    register(play, "private-outsider", "玄月")
    play("team_create", user="private-leader")


def requests(game):
    return sql(game[1], "SELECT * FROM team_requests ORDER BY team_id, candidate_id")


def members(game):
    return sql(game[1], "SELECT * FROM team_members ORDER BY team_id, user_id")


def snapshot(game):
    return requests(game), members(game), sql(game[1], "SELECT * FROM players ORDER BY user_id"), \
        sql(game[1], "SELECT * FROM pets ORDER BY pet_id")


def assert_private(reply):
    combined = reply.text() + " ".join(reply.commands)
    for user in ("private-leader", "private-candidate", "private-outsider"):
        assert user not in combined


def test_apply_requires_leader_approval_and_hides_raw_ids(game, play):
    setup(play)
    reply = play("team_join", "青云", user="private-candidate", op="apply-once")
    assert len(members(game)) == 1
    assert requests(game)[0]["kind"] == "apply"
    assert requests(game)[0]["initiator_id"] == "private-candidate"
    assert play("team_join", "青云", user="private-candidate", op="apply-once") == reply
    before = snapshot(game)
    for user, name in (("private-candidate", "青云"), ("private-outsider", "赤霄")):
        with pytest.raises(GameError):
            play("team_accept", name, user=user)
        assert snapshot(game) == before
    accepted = play("team_accept", "赤霄", user="private-leader", op="approve-once")
    assert play("team_accept", "赤霄", user="private-leader", op="approve-once") == accepted
    assert len(members(game)) == 2
    assert not requests(game)
    assert_private(reply)
    assert_private(accepted)


def test_invitation_requires_target_consent_not_inviter_approval(game, play):
    setup(play)
    reply = play("team_invite", "赤霄", user="private-leader")
    assert requests(game)[0]["kind"] == "invite"
    assert len(members(game)) == 1
    for user, name in (("private-leader", "赤霄"), ("private-outsider", "青云")):
        with pytest.raises(GameError):
            play("team_accept", name, user=user)
    accepted = play("team_accept", "青云", user="private-candidate")
    assert len(members(game)) == 2
    assert not requests(game)
    assert_private(reply)
    assert_private(accepted)


@pytest.mark.parametrize("initial", ["apply", "invite"])
def test_same_pair_cross_requests_never_reverse_approval_or_refresh_expiry(game, play, initial):
    setup(play)
    first = ("team_join", "青云", "private-candidate") if initial == "apply" else (
        "team_invite", "赤霄", "private-leader",
    )
    play(first[0], first[1], user=first[2])
    before = requests(game)
    for action, name, user in (
        ("team_join", "青云", "private-candidate"), ("team_invite", "赤霄", "private-leader"),
    ):
        with pytest.raises(GameError, match="已有"):
            play(action, name, user=user, now=NOW + 1)
    assert requests(game) == before
    assert len(members(game)) == 1


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_only_receiver_can_reject_and_only_initiator_can_withdraw(game, play, kind):
    setup(play)
    if kind == "apply":
        action, argument = "team_join", "青云"
        sender, receiver, sender_target, receiver_target = "private-candidate", "private-leader", "青云", "赤霄"
    else:
        action, argument = "team_invite", "赤霄"
        sender, receiver, sender_target, receiver_target = "private-leader", "private-candidate", "赤霄", "青云"
    play(action, argument, user=sender)
    before = snapshot(game)
    with pytest.raises(GameError):
        play("team_reject", sender_target, user=sender)
    with pytest.raises(GameError):
        play("team_withdraw", receiver_target, user=receiver)
    assert snapshot(game) == before
    play("team_reject", receiver_target, user=receiver, op="reject")
    assert not requests(game)
    play(action, argument, user=sender)
    play("team_withdraw", sender_target, user=sender)
    assert not requests(game)
    assert len(members(game)) == 1


def test_empty_unknown_numeric_ids_and_nonleader_invites_are_rejected(game, play):
    setup(play)
    team_id = str(sql(game[1], "SELECT team_id FROM teams")[0]["team_id"])
    for name in ("", "不存在", "private-leader", team_id):
        with pytest.raises(GameError):
            play("team_join", name, user="private-candidate")
    with pytest.raises(GameError):
        play("team_join", "玄月", user="private-candidate")
    with pytest.raises(GameError):
        play("team_invite", "赤霄", user="private-outsider")
    with pytest.raises(GameError):
        play("team_invite", "青云", user="private-leader")
    assert not requests(game)


def test_expiry_boundary_blocks_acceptance_and_new_request_can_replace_expired_pair(game, play):
    setup(play)
    play("team_invite", "赤霄", user="private-leader")
    expires = requests(game)[0]["expires_at"]
    assert expires == NOW + game[0].config.spirit_pet_team_request_ttl
    assert "青云" in play("team_requests", user="private-candidate", now=expires - 1).text()
    with pytest.raises(GameError):
        play("team_accept", "青云", user="private-candidate", now=expires)
    assert not any("灵宠队务 青云" == command for command in play(
        "team_requests", user="private-candidate", now=expires,
    ).commands)
    play("team_join", "青云", user="private-candidate", now=expires)
    assert len(requests(game)) == 1
    assert requests(game)[0]["kind"] == "apply"
    assert requests(game)[0]["created_at"] == expires


def test_pending_request_survives_process_reconstruction(game, play):
    setup(play)
    play("team_join", "青云", user="private-candidate")
    restarted = Game(game[1], game[0].config, game[0].rng)
    reply = restarted.execute("private-leader", "team_accept", "赤霄", "restart-accept", NOW + 1)
    assert len(members(game)) == 2
    assert not requests(game)
    assert_private(reply)


def test_acceptance_clears_all_candidate_requests_and_all_team_readiness(game, play):
    setup(play)
    play("team_create", user="private-outsider")
    play("team_ready", user="private-leader")
    play("team_join", "青云", user="private-candidate")
    play("team_invite", "赤霄", user="private-outsider")
    assert len(requests(game)) == 2
    before = pet(game[1], "private-candidate"), player(game[1], "private-candidate")
    play("team_accept", "赤霄", user="private-leader")
    assert not requests(game)
    assert all(row["ready_pet_id"] is None for row in members(game))
    assert (pet(game[1], "private-candidate"), player(game[1], "private-candidate")) == before


def test_full_team_is_checked_at_send_and_again_at_acceptance(game, play):
    setup(play)
    game[0].config.spirit_pet_team_request_limit = 10
    play("team_join", "青云", user="private-candidate")
    play("team_join", "青云", user="private-outsider")
    register(play, "fourth-private", "白露")
    play("team_invite", "白露", user="private-leader")
    play("team_accept", "赤霄", user="private-leader")
    play("team_accept", "玄月", user="private-leader")
    before = snapshot(game)
    with pytest.raises(GameError, match="已满"):
        play("team_accept", "青云", user="fourth-private")
    assert snapshot(game) == before
    register(play, "fifth-private", "流光")
    with pytest.raises(GameError, match="已满"):
        play("team_join", "青云", user="fifth-private")
    with pytest.raises(GameError, match="已满"):
        play("team_invite", "流光", user="private-leader")


def test_parallel_approvals_cannot_overfill_last_slot(game, play):
    setup(play)
    play("team_join", "青云", user="private-candidate")
    play("team_accept", "赤霄", user="private-leader")
    register(play, "fourth-private", "白露")
    for name, user in (("玄月", "private-outsider"), ("白露", "fourth-private")):
        play("team_join", "青云", user=user)

    def approve(name):
        try:
            game[0].execute("private-leader", "team_accept", name, f"approve-{name}", NOW)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(approve, ("玄月", "白露"))) == 1
    assert len(members(game)) == 3


def test_parallel_acceptance_of_different_teams_joins_only_one(game, play):
    setup(play)
    play("team_create", user="private-outsider")
    play("team_invite", "赤霄", user="private-leader")
    play("team_invite", "赤霄", user="private-outsider")

    def accept(name):
        try:
            game[0].execute("private-candidate", "team_accept", name, f"accept-{name}", NOW)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(accept, ("青云", "玄月"))) == 1
    assert len([member for member in members(game) if member["user_id"] == "private-candidate"]) == 1
    assert not requests(game)


def test_both_pending_limits_count_only_unexpired_requests(game, play):
    setup(play)
    game[0].config.spirit_pet_team_request_limit = 1
    play("team_join", "青云", user="private-candidate")
    with pytest.raises(GameError, match="上限"):
        play("team_join", "青云", user="private-outsider")
    play("team_create", user="private-outsider")
    with pytest.raises(GameError, match="上限"):
        play("team_invite", "赤霄", user="private-outsider")
    deadline = requests(game)[0]["expires_at"]
    play("team_invite", "赤霄", user="private-outsider", now=deadline)
    active = [row for row in requests(game) if row["expires_at"] > deadline]
    assert len(active) == 1


def test_request_details_only_visible_to_candidate_or_current_leader(game, play):
    setup(play)
    play("team_join", "青云", user="private-candidate")
    for user, target in (("private-leader", "赤霄"), ("private-candidate", "青云")):
        reply = play("team_requests", target, user=user)
        assert target in reply.text()
        assert_private(reply)
    outsider = play("team_requests", user="private-outsider")
    assert "赤霄" not in outsider.text()
    assert "青云" not in outsider.text()
    for target in ("青云", "赤霄"):
        with pytest.raises(GameError):
            play("team_requests", target, user="private-outsider")


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_detail_buttons_respect_approval_direction(game, play, kind):
    setup(play)
    if kind == "apply":
        play("team_join", "青云", user="private-candidate")
        sender, receiver, sender_target, receiver_target = "private-candidate", "private-leader", "青云", "赤霄"
    else:
        play("team_invite", "赤霄", user="private-leader")
        sender, receiver, sender_target, receiver_target = "private-leader", "private-candidate", "赤霄", "青云"
    own = play("team_requests", sender_target, user=sender)
    incoming = play("team_requests", receiver_target, user=receiver)
    assert f"灵宠队伍撤回 {sender_target}" in own.commands
    assert not any(command.startswith("灵宠队伍同意") for command in own.commands)
    assert f"灵宠队伍同意 {receiver_target}" in incoming.commands
    assert f"灵宠队伍拒绝 {receiver_target}" in incoming.commands
    assert not any(command.startswith("灵宠队伍撤回") for command in incoming.commands)


def test_inbox_pagination_and_name_changes_do_not_expose_internal_identifiers(game, play):
    setup(play)
    for index in range(9):
        user, name = f"secret-{index}", f"访客{index}"
        register(play, user, name)
        play("team_join", "青云", user=user)
    first = play("team_requests", user="private-leader")
    second = play("team_requests", "2", user="private-leader")
    assert len(first.commands) <= 8 and len(second.commands) <= 8
    assert "灵宠队务 分页 2" in first.commands
    assert "灵宠队务 分页 1" in second.commands
    assert first.text() != second.text()
    assert "secret-" not in first.text() + " ".join(first.commands)
    play("dao_name", "新道号", user="secret-0")
    renamed = play("team_requests", "新道号", user="private-leader")
    assert "新道号" in renamed.text()
    with pytest.raises(GameError):
        play("team_accept", "访客0", user="private-leader")
    play("team_accept", "新道号", user="private-leader")
    assert any(member["user_id"] == "secret-0" for member in members(game))


@pytest.mark.parametrize("dao_name", ["123", "12", "分页", "第2页"])
def test_legal_dao_name_is_detail_not_page_or_raw_id(game, play, dao_name):
    setup(play)
    play("dao_name", dao_name, user="private-candidate")
    play("team_invite", dao_name, user="private-leader")
    detail = play("team_requests", dao_name, user="private-leader")
    assert dao_name in detail.text()
    assert f"灵宠队伍撤回 {dao_name}" in detail.commands


def test_explicit_page_is_always_reachable_despite_numeric_dao_name(game, play):
    setup(play)
    game[0].config.spirit_pet_team_request_limit = 50
    play("dao_name", "12", user="private-candidate")
    play("team_join", "青云", user="private-candidate")
    for index in range(47):
        user = f"page-test-{index}"
        register(play, user, f"道友{index}")
        play("team_join", "青云", user=user)
    assert play("team_requests", "12", user="private-leader").title == "队务详情"
    page = play("team_requests", "分页 12", user="private-leader")
    assert page.title == "待处理队务 12/12"
    assert len(page.lines) == 4
    assert "灵宠队务 分页 11" in page.commands
    assert "灵宠队务 分页 12" in play("team_requests", "分页 11", user="private-leader").commands


@pytest.mark.parametrize("argument", ["0", "999", "-1", "1 extra", "分页 0", "分页 999"])
def test_invalid_pages_or_detail_names_fail_without_mutation(game, play, argument):
    setup(play)
    before = snapshot(game)
    with pytest.raises(GameError):
        play("team_requests", argument, user="private-leader")
    assert snapshot(game) == before


def test_nonleader_teammate_cannot_view_or_process_team_applications(game, play):
    setup(play)
    play("team_join", "青云", user="private-outsider")
    play("team_accept", "玄月", user="private-leader")
    play("team_join", "青云", user="private-candidate")
    assert "赤霄" not in play("team_requests", user="private-outsider").text()
    for action in ("team_requests", "team_accept", "team_reject", "team_withdraw"):
        with pytest.raises(GameError):
            play(action, "赤霄", user="private-outsider")


def test_stale_inviter_after_leader_change_cannot_authorize_entry(game, play):
    setup(play)
    team = sql(game[1], "SELECT team_id FROM teams")[0]["team_id"]
    play("team_invite", "赤霄", user="private-leader")
    sql(game[1], "INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", ("private-outsider", team))
    sql(game[1], "UPDATE teams SET leader_id=? WHERE team_id=?", ("private-outsider", team))
    before = snapshot(game)
    with pytest.raises(GameError):
        play("team_accept", "玄月", user="private-candidate")
    assert snapshot(game) == before
