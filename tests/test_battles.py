from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.domain.battle_content import Skill, Talent
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, enemy_fighter, fight

from .support import items, pet, player, sql


def test_enemy_signature_skill_uses_configured_interval(game):
    class FixedCombatRng:
        def random(self):
            return 0.5

        def randint(self, start, stop):
            return start

    service = game[0]
    definition = service.content.enemies["ember_wraith"].model_copy(update={
        "stats": Stats(hp=1000, attack=1, defense=0, speed=10),
    })
    enemy = enemy_fighter(definition, service.content.skills)
    ally = Fighter.create("测试灵宠", Stats(hp=10000, attack=1, defense=0, speed=1))

    result = fight([ally], [enemy], FixedCombatRng())

    casts = [line for line in result.history if "施展赤焰术攻击" in line]
    normal_attacks = [line for line in result.history if line.startswith("焚天炎灵攻击")]
    assert result.rounds == 40
    assert len(casts) == 13
    assert len(normal_attacks) == 27


def test_all_target_skill_hits_each_living_enemy_and_counts_one_cast_per_action():
    class FixedCombatRng:
        def random(self):
            return 0.5

        def randint(self, start, stop):
            return 100 if (start, stop) == (90, 110) else start

    skill = Skill(
        id="spirit_wave", name="灵潮荡阵", description="群攻", element=None,
        requirements={"min_realm": "ningqi"}, kind="damage", targeting="all",
        coefficient=0.65, book_item="book_spirit_wave",
    )
    caster = Fighter.create(
        "灵宠", Stats(hp=100, attack=100, defense=0, speed=100), skills=(skill,), pet_id=1,
    )
    targets = [
        Fighter.create(name, Stats(hp=100, attack=1, defense=0, speed=1))
        for name in ("甲", "乙")
    ]

    result = fight([caster], targets, FixedCombatRng())

    assert result.winner == 0
    assert all(target.hp == 0 for target in targets)
    assert result.skill_uses[0][1] == {"spirit_wave": 2}
    assert sum("施展灵潮荡阵，攻击全体存活敌人" in line for line in result.history) == 2
    for target in targets:
        assert sum(f"灵潮荡阵命中{target.name}" in line for line in result.history) == 2


def test_all_target_skill_finishes_locked_targets_after_counter_kills_caster():
    class FixedCombatRng:
        def random(self):
            return 0.5

        def randint(self, start, stop):
            return 100 if (start, stop) == (90, 110) else start

    skill = Skill(
        id="spirit_wave", name="灵潮荡阵", description="群攻", element=None,
        requirements={"min_realm": "ningqi"}, kind="damage", targeting="all",
        coefficient=0.65, book_item="book_spirit_wave",
    )
    caster = Fighter.create(
        "灵宠", Stats(hp=20, attack=100, defense=0, speed=100), skills=(skill,), pet_id=1,
        talent=Talent(id="lifesteal", name="汲灵", description="吸血", kind="lifesteal", power=0.5),
    )
    counter = Fighter.create(
        "反震甲", Stats(hp=100, attack=100, defense=0, speed=1),
        talent=Talent(id="counter", name="反震", description="反击", kind="counter", power=1),
    )
    second = Fighter.create("后排", Stats(hp=100, attack=1, defense=0, speed=1))

    result = fight([caster], [counter, second], FixedCombatRng())

    assert caster.hp == 0
    assert second.hp < second.stats.hp
    assert any("灵潮荡阵命中后排" in line for line in result.history)


def two_players(play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    play("dao_name", "青云")
    play("dao_name", "赤霄", user="u2")


def ranked_players(game, play):
    two_players(play)
    sql(game[1], "UPDATE pets SET realm=1")


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
    with pytest.raises(GameError, match="成就尚未完成"):
        play("achievement_claim", "并肩初捷")
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
    play("explore", "灵泉修行")
    play("challenge", "青岚林")
    assert pet(game[1])["energy"] == 55
    with pytest.raises(GameError, match="调息"):
        play("explore", "灵泉修行")


def test_pvp_directly_resolves_and_only_charges_challenger_once(game, play):
    ranked_players(game, play)
    sql(game[1], "UPDATE pets SET layer=10,bloodline=4,affinity=100 WHERE user_id='u1'")
    before = player(game[1], "u2"), pet(game[1], "u2")
    result = play("pvp", "赤霄", op="ranked-once")
    assert play("pvp", "赤霄", op="ranked-once") == result
    assert result.title == "论剑结算"
    assert pet(game[1])["energy"] == 80
    assert (player(game[1], "u2"), pet(game[1], "u2")) == before
    assert sorted(row["rating"] for row in sql(game[1], "SELECT rating FROM season_entries")) == [980, 1020]
    assert player(game[1])["stones"] == player(game[1], "u2")["stones"] == 100
    assert sql(game[1], "SELECT winner_id FROM pvp_results") == [{"winner_id": "u1"}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='pvp_once'") == [
        {"progress": 1},
    ]
    assert "论剑扬名：1/1" in play("quests").text()
    with pytest.raises(GameError):
        play("pvp", "赤霄")


def test_ranked_loss_does_not_advance_the_daily_pvp_quest(game, play):
    ranked_players(game, play)
    sql(game[1], "UPDATE pets SET layer=10,bloodline=4,affinity=100 WHERE user_id='u2'")
    play("pvp", "赤霄")
    assert sql(game[1], "SELECT winner_id FROM pvp_results") == [{"winner_id": "u2"}]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='pvp_once'")


def test_pvp_validates_challenger_resources_before_settling(game, play):
    ranked_players(game, play)
    sql(game[1], "UPDATE pets SET energy=0 WHERE user_id='u1'")
    with pytest.raises(GameError, match="精力不足"):
        play("pvp", "赤霄")
    assert pet(game[1], "u2")["energy"] == 100
    assert not sql(game[1], "SELECT * FROM pvp_results")


def test_self_unknown_and_instant_named_spar(game, play):
    two_players(play)
    play("adopt", user="u3")
    with pytest.raises(GameError, match="自己"):
        play("pvp", "青云")
    with pytest.raises(GameError, match="不存在"):
        play("pvp", "missing")
    assert play("spar", "赤霄").title == "切磋结算"
    assert play("spar", "赤霄", user="u3").title == "切磋结算"


def test_spar_has_no_resources_ratings_rewards_or_cooldown(game, play):
    two_players(play)
    before = [(player(game[1], user), pet(game[1], user), items(game[1], user)) for user in ("u1", "u2")]
    assert play("spar", "赤霄").title == "切磋结算"
    after = [(player(game[1], user), pet(game[1], user), items(game[1], user)) for user in ("u1", "u2")]
    assert after == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='pvp_once'")


def test_daily_pvp_pair_limit_is_symmetric(game, play):
    ranked_players(game, play)
    play("pvp", "赤霄")
    with pytest.raises(GameError, match="今日已结算"):
        play("pvp", "青云", user="u2", now=1_800_001_000)
    play("spar", "青云", user="u2", now=1_800_001_000)


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
    assert sql(game[1], "SELECT user_id, progress FROM quest_progress WHERE quest_id='pve_once' ORDER BY user_id") == [
        {"user_id": "u1", "progress": 1}, {"user_id": "u2", "progress": 1},
    ]
    for user in ("u1", "u2"):
        assert pet(game[1], user)["energy"] == 70
        assert items(game[1], user)["bloodline_essence"] == 1
        assert player(game[1], user)["last_pve"] is not None
        assert play("achievement_claim", "并肩初捷", user=user).title == "成就奖励已领取"
    assert sql(game[1], "SELECT user_id, achievement_id FROM achievement_claims ORDER BY user_id") == [
        {"user_id": "u1", "achievement_id": "team_first_victory"},
        {"user_id": "u2", "achievement_id": "team_first_victory"},
    ]
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


def test_concurrent_ranked_challenges_only_charge_once(game, play):
    ranked_players(game, play)

    def accept(index):
        try:
            game[0].execute("u1", "pvp", "赤霄", f"ranked-{index}", 1_800_000_000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(accept, range(8))) == 1
    assert pet(game[1])["energy"] == 80
    assert pet(game[1], "u2")["energy"] == 100


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
