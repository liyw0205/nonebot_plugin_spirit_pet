from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql

USERS = {"leader-private": "领队青云", "member-private": "听雨道友", "third-private": "止水道友", "outsider-private": "乘风道友"}


def prepare(game, play, size=2):
    for user, name in USERS.items():
        play("adopt", "青鸾", user=user)
        play("dao_name", name, user=user)
    play("team_create", user="leader-private")
    team_id = sql(game[1], "SELECT team_id FROM teams WHERE leader_id='leader-private'")[0]["team_id"]
    for user in list(USERS)[1:size]:
        sql(game[1], "INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", (user, team_id))
    return team_id


def ready_all(game, team_id):
    sql(game[1], "UPDATE team_members SET ready_pet_id=(SELECT active_pet_id FROM players "
        "WHERE players.user_id=team_members.user_id) WHERE team_id=?", (team_id,))


def members(game, team_id):
    return sql(game[1], "SELECT * FROM team_members WHERE team_id=? ORDER BY user_id", (team_id,))


def resources(game):
    return [(player(game[1], user), pet(game[1], user), items(game[1], user)) for user in USERS]


def request(game, team_id, candidate, kind="apply"):
    initiator = candidate if kind == "apply" else sql(
        game[1], "SELECT leader_id FROM teams WHERE team_id=?", (team_id,),
    )[0]["leader_id"]
    sql(game[1], "INSERT INTO team_requests(team_id, candidate_id, kind, initiator_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, 1800000000, 1800000300)", (team_id, candidate, kind, initiator))


def test_create_and_status_show_names_capacity_and_only_authorized_actions(game, play):
    team_id = prepare(game, play)
    leader = play("team_status", user="leader-private")
    member = play("team_status", user="member-private")
    for reply in (leader, member):
        assert "领队青云" in reply.text() and "听雨道友" in reply.text()
        assert "2/3" in reply.text()
        assert "队长" in reply.text() and "队员" in reply.text()
        assert "未准备" in reply.text()
        assert not any(user in reply.text() for user in USERS)
        assert str(team_id) not in reply.title and "队伍编号" not in reply.text()
        assert "灵宠队务" in reply.commands
        assert len(reply.commands) <= 8
    assert "灵宠解散" in leader.commands
    assert "灵宠队伍 听雨道友" in leader.commands
    detail = play("team_status", "听雨道友", user="leader-private")
    assert "灵宠踢人 听雨道友" in detail.commands
    assert "灵宠转让 听雨道友" in detail.commands
    assert "灵宠退队" in member.commands
    assert not any(command.startswith(("灵宠踢人", "灵宠转让", "灵宠解散", "灵宠组队挑战"))
                   for command in member.commands)
    with pytest.raises(GameError):
        play("team_status", user="outsider-private")


def test_capacity_five_keeps_every_member_detail_reachable_without_privilege_leak(game, play):
    team_id = prepare(game, play, size=3)
    game[0].content = replace(game[0].content, rules=game[0].content.rules.model_copy(update={"max_team_size": 5}))
    play("adopt", "青鸾", user="fifth-private")
    play("dao_name", "观海道友", user="fifth-private")
    for user in ("outsider-private", "fifth-private"):
        sql(game[1], "INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", (user, team_id))
    reply = play("team_status", user="leader-private")
    assert "5/5" in reply.text()
    assert len(reply.commands) == 8
    for name in ("听雨道友", "止水道友", "乘风道友", "观海道友"):
        assert f"灵宠队伍 {name}" in reply.commands
        detail = play("team_status", name, user="leader-private")
        assert f"灵宠踢人 {name}" in detail.commands
        assert f"灵宠转让 {name}" in detail.commands
        assert len(detail.commands) <= 8
    member = play("team_status", user="member-private")
    assert len(member.commands) == 8
    for name in ("领队青云", "止水道友", "乘风道友", "观海道友"):
        assert f"灵宠队伍 {name}" in member.commands
        detail = play("team_status", name, user="member-private")
        assert not any(command.startswith(("灵宠踢人", "灵宠转让", "灵宠解散")) for command in detail.commands)
    with pytest.raises(GameError, match="本队|你的队伍"):
        play("team_status", "不存在", user="leader-private")


def test_member_detail_does_not_expose_other_teams(game, play):
    team_id = prepare(game, play)
    play("team_create", user="outsider-private")
    before = members(game, team_id), resources(game)
    for actor in ("leader-private", "member-private"):
        with pytest.raises(GameError, match="本队|你的队伍"):
            play("team_status", "乘风道友", user=actor)
    assert (members(game, team_id), resources(game)) == before


def test_create_clears_all_own_pending_requests_but_not_other_candidates(game, play):
    team_id = prepare(game, play, size=1)
    play("team_create", user="outsider-private")
    other_team = sql(game[1], "SELECT team_id FROM teams WHERE leader_id='outsider-private'")[0]["team_id"]
    request(game, team_id, "third-private")
    request(game, other_team, "third-private", "invite")
    request(game, team_id, "member-private")
    before = resources(game)
    result = play("team_create", user="third-private", op="create-clean")
    assert play("team_create", user="third-private", op="create-clean") == result
    assert "止水道友" in result.text() and "队伍编号" not in result.text()
    requests = sql(game[1], "SELECT * FROM team_requests")
    assert len(requests) == 1 and requests[0]["candidate_id"] == "member-private"
    assert resources(game) == before


def test_member_leave_is_free_and_invalidates_remaining_readiness(game, play):
    team_id = prepare(game, play, size=3)
    ready_all(game, team_id)
    before = resources(game)
    result = play("team_leave", user="member-private", op="leave-once")
    assert play("team_leave", user="member-private", op="leave-once") == result
    assert {row["user_id"] for row in members(game, team_id)} == {"leader-private", "third-private"}
    assert not any(row["ready_pet_id"] for row in members(game, team_id))
    assert resources(game) == before
    with pytest.raises(GameError):
        play("team_leave", user="member-private")


def test_leader_leave_requires_explicit_transfer_or_disband(game, play):
    team_id = prepare(game, play)
    ready_all(game, team_id)
    before = members(game, team_id), resources(game)
    with pytest.raises(GameError, match="队长.*(转让|解散)"):
        play("team_leave", user="leader-private")
    assert (members(game, team_id), resources(game)) == before


def test_ready_and_unready_do_not_change_resources_or_other_members(game, play):
    team_id = prepare(game, play)
    sql(game[1], "UPDATE pets SET energy=15, energy_updated=1")
    before = resources(game)
    play("team_ready", user="member-private")
    assert next(row for row in members(game, team_id) if row["user_id"] == "member-private")["ready_pet_id"] is not None
    assert next(row for row in members(game, team_id) if row["user_id"] == "leader-private")["ready_pet_id"] is None
    assert "灵宠取消准备" in play("team_status", user="member-private").commands
    play("team_unready", user="member-private")
    assert not any(row["ready_pet_id"] for row in members(game, team_id))
    assert resources(game) == before


def test_kick_only_targets_other_members_of_own_team(game, play):
    team_id = prepare(game, play, size=3)
    play("team_create", user="outsider-private")
    other_team = sql(game[1], "SELECT team_id FROM teams WHERE leader_id='outsider-private'")[0]["team_id"]
    ready_all(game, team_id)
    ready_all(game, other_team)
    before = members(game, team_id), members(game, other_team), resources(game)
    for actor, target in (("member-private", "止水道友"), ("leader-private", "领队青云"),
                          ("leader-private", "乘风道友"), ("leader-private", "不存在")):
        with pytest.raises(GameError):
            play("team_kick", target, user=actor)
    assert (members(game, team_id), members(game, other_team), resources(game)) == before
    result = play("team_kick", "听雨道友", user="leader-private", op="kick-once")
    assert play("team_kick", "听雨道友", user="leader-private", op="kick-once") == result
    assert "听雨道友" in result.text()
    assert not any(user in result.text() for user in USERS)
    assert {row["user_id"] for row in members(game, team_id)} == {"leader-private", "third-private"}
    assert not any(row["ready_pet_id"] for row in members(game, team_id))
    assert members(game, other_team) == before[1]
    assert resources(game) == before[2]


def test_transfer_revalidates_authority_and_clears_all_ready(game, play):
    team_id = prepare(game, play, size=3)
    ready_all(game, team_id)
    before = resources(game)
    for actor, target in (("member-private", "止水道友"), ("leader-private", "领队青云"),
                          ("leader-private", "乘风道友")):
        with pytest.raises(GameError):
            play("team_transfer", target, user=actor)
    result = play("team_transfer", "听雨道友", user="leader-private", op="transfer-once")
    assert play("team_transfer", "听雨道友", user="leader-private", op="transfer-once") == result
    assert sql(game[1], "SELECT leader_id FROM teams WHERE team_id=?", (team_id,))[0]["leader_id"] == "member-private"
    assert len(members(game, team_id)) == 3
    assert not any(row["ready_pet_id"] for row in members(game, team_id))
    assert resources(game) == before
    with pytest.raises(GameError):
        play("team_kick", "止水道友", user="leader-private")
    play("team_leave", user="leader-private")
    assert {row["user_id"] for row in members(game, team_id)} == {"member-private", "third-private"}


def test_transfer_discards_own_team_requests_only(game, play):
    team_id = prepare(game, play)
    play("team_create", user="outsider-private")
    other_team = sql(game[1], "SELECT team_id FROM teams WHERE leader_id='outsider-private'")[0]["team_id"]
    play("adopt", "青鸾", user="fifth-private")
    request(game, team_id, "third-private")
    request(game, team_id, "fifth-private", "invite")
    request(game, other_team, "third-private", "invite")
    other_requests = sql(game[1], "SELECT * FROM team_requests WHERE team_id=?", (other_team,))
    play("team_transfer", "听雨道友", user="leader-private")
    assert not sql(game[1], "SELECT * FROM team_requests WHERE team_id=?", (team_id,))
    assert sql(game[1], "SELECT * FROM team_requests WHERE team_id=?", (other_team,)) == other_requests


def test_disband_is_explicit_current_leader_only_and_costs_nothing(game, play):
    team_id = prepare(game, play)
    play("team_create", user="outsider-private")
    other_team = sql(game[1], "SELECT team_id FROM teams WHERE leader_id='outsider-private'")[0]["team_id"]
    request(game, team_id, "third-private")
    request(game, other_team, "third-private", "invite")
    other_requests = sql(game[1], "SELECT * FROM team_requests WHERE team_id=?", (other_team,))
    before = resources(game)
    with pytest.raises(GameError):
        play("team_disband", user="member-private")
    result = play("team_disband", user="leader-private", op="disband-once")
    assert play("team_disband", user="leader-private", op="disband-once") == result
    assert not members(game, team_id)
    assert not sql(game[1], "SELECT * FROM teams WHERE team_id=?", (team_id,))
    assert sql(game[1], "SELECT leader_id FROM teams")[0]["leader_id"] == "outsider-private"
    assert not sql(game[1], "SELECT * FROM team_requests WHERE team_id=?", (team_id,))
    assert sql(game[1], "SELECT * FROM team_requests WHERE team_id=?", (other_team,)) == other_requests
    assert resources(game) == before


def test_team_challenge_still_requires_members_ready_and_rolls_back_resources(game, play):
    team_id = prepare(game, play)
    with pytest.raises(GameError, match="仅队长"):
        play("team_challenge", user="member-private")
    with pytest.raises(GameError, match="全体"):
        play("team_challenge", user="leader-private")
    ready_all(game, team_id)
    with pytest.raises(GameError, match="单人"):
        play("team_challenge", "青岚林", user="leader-private")
    sql(game[1], "UPDATE pets SET layer=5")
    sql(game[1], "UPDATE pets SET energy=0 WHERE user_id='member-private'")
    before = members(game, team_id), resources(game)
    with pytest.raises(GameError, match="精力不足"):
        play("team_challenge", user="leader-private")
    assert (members(game, team_id), resources(game)) == before


def test_ready_after_membership_change_is_required_before_shared_battle(game, play):
    team_id = prepare(game, play, size=3)
    sql(game[1], "UPDATE pets SET layer=5")
    ready_all(game, team_id)
    play("team_kick", "止水道友", user="leader-private")
    with pytest.raises(GameError, match="全体"):
        play("team_challenge", user="leader-private")
    play("team_ready", user="leader-private")
    play("team_ready", user="member-private")
    result = play("team_challenge", user="leader-private", op="team-battle")
    assert result.title == "秘境获胜"
    assert play("team_challenge", user="leader-private", op="team-battle") == result
    assert pet(game[1], "leader-private")["energy"] == pet(game[1], "member-private")["energy"] == 70
    assert not any(row["ready_pet_id"] for row in members(game, team_id))


def test_concurrent_transfers_have_one_current_authority(game, play):
    team_id = prepare(game, play, size=3)

    def transfer(target):
        try:
            game[0].execute("leader-private", "team_transfer", target, f"transfer-{target}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(transfer, ("听雨道友", "止水道友"))) == 1
    leader = sql(game[1], "SELECT leader_id FROM teams WHERE team_id=?", (team_id,))[0]["leader_id"]
    assert leader in {"member-private", "third-private"}
    assert len(members(game, team_id)) == 3
