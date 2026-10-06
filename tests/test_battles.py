from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql


def two_players(play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    play("dao_name", "青云")
    play("dao_name", "赤霄", user="u2")


def setup_team(game, play):
    two_players(play)
    sql(game[1], "UPDATE pets SET layer=5")
    play("team_create")
    team_id = sql(game[1], "SELECT team_id FROM teams")[0]["team_id"]
    play("team_join", "青云", user="u2")
    play("team_accept", "赤霄")
    return team_id


def test_pve_rewards_and_redelivery(game, play):
    play("adopt", "青鸾")
    first = play("challenge", "青岚林", op="pve")
    assert first.title == "秘境获胜"
    assert play("challenge", "青岚林", op="pve") == first
    assert pet(game[1])["energy"] == 80
    assert items(game[1])["bloodline_essence"] == 1
    assert "斩破迷障：1/1" in play("quests").text()
    with pytest.raises(GameError, match="调息"):
        play("challenge", "青岚林")


def test_pve_realm_gate_and_loss_cost(game, play):
    play("adopt")
    with pytest.raises(GameError, match="境界不足"):
        play("challenge", "月影谷")
    assert pet(game[1])["energy"] == 100
    sql(game[1], "UPDATE pets SET realm=2")
    result = play("challenge", "雷泽")
    assert result.title == "秘境败退"
    assert pet(game[1])["energy"] == 70
    assert pet(game[1])["exp"] == 0
    assert player(game[1])["stones"] == 100


def test_exploration_and_pve_have_independent_cooldowns(game, play):
    play("adopt")
    play("explore")
    play("challenge", "青岚林")
    assert pet(game[1])["energy"] == 55
    with pytest.raises(GameError, match="调息"):
        play("explore")


def test_pvp_needs_target_consent_and_resolves_once(game, play):
    two_players(play)
    play("pvp", "赤霄")
    before = pet(game[1]), pet(game[1], "u2")
    with pytest.raises(GameError, match="没有可应战"):
        play("accept")
    assert (pet(game[1]), pet(game[1], "u2")) == before
    result = play("accept", user="u2", op="accept")
    assert play("accept", user="u2", op="accept") == result
    assert result.title == "论剑结算"
    assert pet(game[1])["energy"] == pet(game[1], "u2")["energy"] == 80
    assert sorted([player(game[1])["rating"], player(game[1], "u2")["rating"]]) == [980, 1020]
    assert player(game[1])["stones"] == player(game[1], "u2")["stones"] == 100
    with pytest.raises(GameError):
        play("accept", user="u2")


def test_pvp_revalidates_resources_on_accept_and_preserves_invite(game, play):
    two_players(play)
    play("pvp", "赤霄")
    sql(game[1], "UPDATE pets SET energy=0 WHERE user_id='u1'")
    with pytest.raises(GameError, match="精力不足"):
        play("accept", user="u2")
    assert pet(game[1], "u2")["energy"] == 100
    assert len(sql(game[1], "SELECT * FROM duels")) == 1
    play("reject", user="u2")
    assert not sql(game[1], "SELECT * FROM duels")


def test_self_unknown_expired_and_third_party_invitation(game, play):
    two_players(play)
    play("adopt", user="u3")
    with pytest.raises(GameError, match="自己"):
        play("pvp", "青云")
    with pytest.raises(GameError, match="不存在"):
        play("pvp", "missing")
    play("spar", "赤霄", now=1000)
    with pytest.raises(GameError):
        play("accept", user="u3", now=1000)
    with pytest.raises(GameError, match="已有"):
        play("spar", "赤霄", user="u3", now=1000)
    with pytest.raises(GameError, match="过期"):
        play("accept", user="u2", now=1300)
    play("spar", "赤霄", now=1300)
    play("reject", now=1300)
    assert not sql(game[1], "SELECT * FROM duels")


def test_spar_has_no_resources_ratings_rewards_or_cooldown(game, play):
    two_players(play)
    before = [(player(game[1], user), pet(game[1], user), items(game[1], user)) for user in ("u1", "u2")]
    play("spar", "赤霄")
    assert play("accept", user="u2").title == "切磋结算"
    after = [(player(game[1], user), pet(game[1], user), items(game[1], user)) for user in ("u1", "u2")]
    assert after == before


def test_daily_pvp_pair_limit_is_symmetric(game, play):
    two_players(play)
    play("pvp", "赤霄")
    play("accept", user="u2")
    with pytest.raises(GameError, match="今日已结算"):
        play("pvp", "青云", user="u2", now=1_800_001_000)
    play("spar", "青云", user="u2", now=1_800_001_000)
    play("accept", now=1_800_001_000)


def test_team_requires_two_members_all_ready_and_leader(game, play):
    team_id = setup_team(game, play)
    with pytest.raises(GameError, match="仅队长"):
        play("team_challenge", user="u2")
    with pytest.raises(GameError, match="全体"):
        play("team_challenge")
    play("team_ready")
    play("team_ready", user="u2")
    result = play("team_challenge", op="team-battle")
    assert result.title == "秘境获胜"
    assert play("team_challenge", op="team-battle") == result
    for user in ("u1", "u2"):
        assert pet(game[1], user)["energy"] == 70
        assert items(game[1], user)["bloodline_essence"] == 1
        assert player(game[1], user)["last_pve"] is not None
    assert not any(row["ready_pet_id"] for row in sql(game[1], "SELECT * FROM team_members"))
    assert "青云" in play("team_status").title


def test_team_failure_rolls_back_every_member(game, play):
    setup_team(game, play)
    play("team_ready")
    play("team_ready", user="u2")
    sql(game[1], "UPDATE pets SET energy=0 WHERE user_id='u2'")
    before = [pet(game[1], user) for user in ("u1", "u2")]
    with pytest.raises(GameError, match="精力不足"):
        play("team_challenge")
    assert [pet(game[1], user) for user in ("u1", "u2")] == before
    assert all(row["ready_pet_id"] for row in sql(game[1], "SELECT * FROM team_members"))


def test_switch_and_training_invalidate_team_consent(game, play):
    setup_team(game, play)
    play("team_ready")
    play("train")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'")[0]["ready_pet_id"] is None
    play("team_ready")
    play("switch", str(pet(game[1])["pet_id"]))
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'")[0]["ready_pet_id"] is None


def test_team_capacity_leave_disband_and_concurrent_last_slot(game, play):
    team_id = setup_team(game, play)
    for user in ("u3", "u4"):
        play("adopt", user=user)
        play("team_join", "青云", user=user)

    def join(user):
        try:
            game[0].execute("u1", "team_accept", player(game[1], user)["dao_name"],
                            f"accept-{user}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(join, ("u3", "u4"))) == 1
    play("team_leave", user="u2")
    assert len(sql(game[1], "SELECT * FROM team_members")) == 2
    with pytest.raises(GameError, match="队长"):
        play("team_leave")
    play("team_disband")
    assert not sql(game[1], "SELECT * FROM team_members")
    assert not sql(game[1], "SELECT * FROM teams")


def test_concurrent_accepts_only_charge_once(game, play):
    two_players(play)
    play("pvp", "赤霄")

    def accept(index):
        try:
            game[0].execute("u2", "accept", "", f"accept-{index}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(accept, range(8))) == 1
    assert pet(game[1])["energy"] == 80
    assert pet(game[1], "u2")["energy"] == 80


def test_battle_is_bounded_and_does_not_persist_health(game):
    from nonebot_plugin_spirit_pet.domain.content import Stats
    from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, fight

    stats = Stats(hp=1000, attack=1, defense=100, speed=1)
    result = fight([Fighter.create("left", stats)], [Fighter.create("right", stats)], game[0].rng)
    assert result.winner == -1 and result.rounds == 40


def test_simultaneous_team_battle_charges_everyone_once(game, play):
    setup_team(game, play)
    play("team_ready")
    play("team_ready", user="u2")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: game[0].execute("u1", "team_challenge", "", "same-team-event", 1_800_000_000),
            range(8),
        ))
    assert all(result == results[0] for result in results)
    assert pet(game[1])["energy"] == pet(game[1], "u2")["energy"] == 70
    assert items(game[1])["bloodline_essence"] == items(game[1], "u2")["bloodline_essence"] == 1
