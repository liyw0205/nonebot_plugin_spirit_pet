from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import Reply
from nonebot_plugin_spirit_pet.gameplay import adventure
from nonebot_plugin_spirit_pet.gameplay.combat import fight
from nonebot_plugin_spirit_pet.gameplay.mastery import award_mastery
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql


def prepare(game, play, user="u1", species="青鸾", skill_name="风刃术"):
    play("adopt", species, user=user)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id=?", (user,))
    play("buy", skill_name + "诀", user=user)
    play("learn", skill_name, user=user)


def skill(game, user="u1"):
    return sql(game[1], "SELECT s.* FROM learned_skills s JOIN pets p ON p.pet_id=s.pet_id "
               "WHERE p.user_id=? AND s.skill_id='wind_slash' ORDER BY p.pet_id", (user,))[0]


def award(game, uses, user="u1", operation="mastery", fail=False):
    service, store = game

    def execute(conn):
        repo = Repository(conn)
        ctx = Context(repo, service.content, service.config, service.rng, user, 1_800_000_000)
        lines = award_mastery(ctx, user, uses)
        if fail:
            raise RuntimeError("abort battle settlement")
        repo.save()
        return Reply("熟练度结算", lines)

    return store.transact(user, operation, 1_800_000_000, execute)


def total_proficiency(game, row):
    levels = game[0].content.skill_levels
    return row["proficiency"] + sum(levels[index].required_proficiency for index in range(1, row["level"]))


def capture_pve(monkeypatch, enemy_attack):
    battles = []

    def observe(left, right, rng, elements):
        for unit in left:
            unit.talent = None
        for unit in right:
            unit.stats = Stats(hp=100000, attack=enemy_attack, defense=0, speed=1)
            unit.hp = unit.stats.hp
        battle = fight(left, right, rng, elements)
        battles.append(battle)
        return battle

    monkeypatch.setattr(adventure, "fight", observe)
    return battles


def test_new_skill_starts_at_level_one_and_view_shows_progress(game, play):
    prepare(game, play)
    assert skill(game)["level"] == 1
    assert skill(game)["proficiency"] == 0
    required = game[0].content.skill_levels[1].required_proficiency
    assert f"1级 · 熟练度 0/{required}" in play("skills").text()


def test_mastery_is_awarded_only_for_used_equipped_learned_skills(game, play):
    prepare(game, play)
    award(game, {"wind_slash": 1, "unknown_skill": 1000})
    assert skill(game)["proficiency"] == game[0].content.rules.skill_proficiency_per_use
    play("unequip_skill", "风刃术")
    before = skill(game)
    assert not award(game, {"wind_slash": 99}, operation="inactive").lines
    assert skill(game) == before


def test_crossing_multiple_levels_keeps_the_remainder(game, play):
    prepare(game, play)
    content = game[0].content
    per_use = content.rules.skill_proficiency_per_use
    required = sum(content.skill_levels[level].required_proficiency for level in (1, 2))
    count = (required + per_use - 1) // per_use + 1
    award(game, {"wind_slash": count})
    row = skill(game)
    assert row["level"] == 3
    assert row["proficiency"] == count * per_use - required


def test_max_level_discards_excess_and_stops_gaining(game, play):
    prepare(game, play)
    top = max(game[0].content.skill_levels)
    award(game, {"wind_slash": 1_000_000})
    assert skill(game)["level"] == top
    assert skill(game)["proficiency"] == 0
    assert not award(game, {"wind_slash": 5}, operation="maxed").lines


def test_level_up_invalidates_ready_but_small_gain_does_not(game, play):
    prepare(game, play)
    play("team_create")
    play("team_ready")
    award(game, {"wind_slash": 1})
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is not None
    award(game, {"wind_slash": 1000}, operation="level-up")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None


@pytest.mark.parametrize("count", [-1, 1.5, True, "2"])
def test_invalid_counts_cannot_change_mastery(game, play, count):
    prepare(game, play)
    before = skill(game)
    with pytest.raises(ValueError, match="nonnegative integers"):
        award(game, {"wind_slash": count})
    assert skill(game) == before


def test_mastery_does_not_cross_player_ids(game, play):
    prepare(game, play)
    prepare(game, play, "u2")
    before = skill(game)
    award(game, {"wind_slash": 1}, user="u2")
    assert skill(game) == before
    assert skill(game, "u2")["proficiency"] == game[0].content.rules.skill_proficiency_per_use


def test_mastery_stays_with_pet_and_survives_skill_unequip(game, play):
    prepare(game, play)
    award(game, {"wind_slash": 20})
    before = skill(game)
    play("unequip_skill", "风刃术")
    play("equip_skill", "风刃术")
    assert skill(game) == before
    sql(game[1], "INSERT INTO pets(user_id, species_id, name, energy_updated) "
        "VALUES ('u1', 'qingluan', '新青鸾', 1800000000)")
    new_pet = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]
    play("switch", str(new_pet))
    play("buy", "风刃术诀")
    play("learn", "风刃术")
    award(game, {"wind_slash": 1}, operation="second-pet")
    rows = sql(game[1], "SELECT * FROM learned_skills ORDER BY pet_id")
    assert rows[0] == before
    assert rows[1]["level"] == 1
    assert rows[1]["proficiency"] == game[0].content.rules.skill_proficiency_per_use


def test_mastery_rollback_and_concurrent_redelivery(game, play):
    prepare(game, play)
    before = skill(game)
    with pytest.raises(RuntimeError, match="abort"):
        award(game, {"wind_slash": 20}, fail=True)
    assert skill(game) == before
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: award(game, {"wind_slash": 1}), range(8)))
    assert all(result == results[0] for result in results)
    assert skill(game)["proficiency"] == game[0].content.rules.skill_proficiency_per_use


def test_pve_awards_once_while_friendly_spar_awards_nothing(game, play):
    prepare(game, play)
    before = skill(game)
    battle = play("challenge", "青岚林", op="mastery-pve")
    after = skill(game)
    assert (after["level"], after["proficiency"]) != (before["level"], before["proficiency"])
    assert play("challenge", "青岚林", op="mastery-pve") == battle
    assert skill(game) == after
    prepare(game, play, "u2")
    play("dao_name", "对战道友", user="u2")
    before_other = skill(game, "u2")
    play("spar", "对战道友")
    play("accept", user="u2")
    assert skill(game) == after
    assert skill(game, "u2") == before_other


def test_ranked_pvp_awards_both_players_once(game, play):
    prepare(game, play)
    prepare(game, play, "u2")
    play("dao_name", "对战道友", user="u2")
    play("pvp", "对战道友")
    battle = play("accept", user="u2", op="ranked-mastery")
    rows = [skill(game, user) for user in ("u1", "u2")]
    assert all(total_proficiency(game, row) > 0 for row in rows)
    assert play("accept", user="u2", op="ranked-mastery") == battle
    assert [skill(game, user) for user in ("u1", "u2")] == rows


@pytest.mark.parametrize("enemy_attack,title", [(100000, "秘境败退"), (1, "秘境平局")])
def test_loss_and_draw_award_only_actual_casts(game, play, monkeypatch, enemy_attack, title):
    prepare(game, play)
    battles = capture_pve(monkeypatch, enemy_attack)
    result = play("challenge", "青岚林")
    assert result.title == title
    row = skill(game)
    count = battles[0].skill_uses[0][row["pet_id"]]["wind_slash"]
    assert count > 0
    assert total_proficiency(game, row) == count * game[0].content.rules.skill_proficiency_per_use


def test_team_distributes_mastery_by_pet_without_crossing_skill_accounts(game, play, monkeypatch):
    prepare(game, play)
    prepare(game, play, "u2", "玄狐", "赤焰术")
    play("team_create")
    team_id = sql(game[1], "SELECT team_id FROM teams")[0]["team_id"]
    play("team_join", str(team_id), user="u2")
    play("team_ready")
    play("team_ready", user="u2")
    battles = capture_pve(monkeypatch, 1)
    result = play("team_challenge", "上古灵殿", op="team-mastery")
    assert result.title == "秘境平局"
    rows = sql(game[1], "SELECT * FROM learned_skills ORDER BY pet_id")
    assert {row["skill_id"] for row in rows} == {"wind_slash", "fireball"}
    for row in rows:
        counts = battles[0].skill_uses[0][row["pet_id"]]
        assert set(counts) == {row["skill_id"]}
        assert counts[row["skill_id"]] == 40
        assert total_proficiency(game, row) == counts[row["skill_id"]] * game[0].content.rules.skill_proficiency_per_use
    assert play("team_challenge", "上古灵殿", op="team-mastery") == result
    assert sql(game[1], "SELECT * FROM learned_skills ORDER BY pet_id") == rows
