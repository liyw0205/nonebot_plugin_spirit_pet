import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.resonance_content import Resonance, ResonanceBonuses
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql


NOW = 1_800_000_000


def test_resonance_definitions_are_bounded_unique_and_cover_the_roster(game):
    content = game[0].content
    assert len(content.resonances) == 14
    assert {key for entry in content.resonances.values() for key in entry.required_species} == set(content.species)
    with pytest.raises(ValidationError, match="total at most 10%"):
        ResonanceBonuses(hp=0.08, attack=0.08, defense=0, speed=0)
    with pytest.raises(ValidationError, match="two different species"):
        Resonance(
            id="duplicate_pair", name="重复共鸣", description="不可重复种族。",
            required_species=["qingluan", "qingluan"],
            bonuses={"hp": 0.05, "attack": 0, "defense": 0, "speed": 0},
        )

    broken = dict(content.resonances)
    broken.pop("ghostwing")
    with pytest.raises(ValueError, match="every species"):
        replace(content, resonances=broken)._validate_resonances()


def own_species(game, species_id, user="u1"):
    species = game[0].content.species[species_id]
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        (user, species_id, species.name, NOW),
    )


def add_essence(game, amount=5, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, 'bloodline_essence', ?) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, amount),
    )


def stats(game, user="u1"):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "read-stats")
        return combatant(ctx)


def test_resonance_catalog_is_read_only_and_explains_missing_species(game, play):
    play("adopt", "青鸾")
    before = player(game[1]), items(game[1])
    first = play("resonance")
    assert first.title == "灵宠共鸣 1/3"
    assert len(first.lines) == 5
    assert "青岚双翼 · 未集齐" in first.text()
    assert "灵宠共鸣 查看 青岚双翼" in first.commands
    detail = play("resonance", "查看 青岚双翼")
    assert "还需寒翎鹰" in detail.text()
    with pytest.raises(GameError, match="共 3 页"):
        play("resonance", "4")
    assert (player(game[1]), items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM player_resonance")


def test_activation_requires_distinct_owned_species_and_spends_once(game, play):
    play("adopt", "青鸾")
    add_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    before = player(game[1]), items(game[1])
    with pytest.raises(GameError, match="尚未集齐"):
        play("resonance", "激活 青岚双翼")
    assert (player(game[1]), items(game[1])) == before

    own_species(game, "hanying")
    initial = stats(game)
    activated = play("resonance", "激活 青岚双翼", op="activate-wind")
    assert play("resonance", "激活 青岚双翼", op="activate-wind") == activated
    assert player(game[1])["stones"] == 800
    assert items(game[1])["bloodline_essence"] == 4
    current = stats(game)
    assert current.resonance_name == "青岚双翼"
    assert current.stats.attack > initial.stats.attack
    assert current.stats.speed > initial.stats.speed
    assert "战斗共鸣：青岚双翼" in play("status").text()
    assert sql(game[1], "SELECT resonance_id FROM player_resonance")[0]["resonance_id"] == "wind_wings"

    unchanged = player(game[1]), items(game[1])
    assert play("resonance", "激活 青岚双翼").title == "共鸣已启用"
    assert (player(game[1]), items(game[1])) == unchanged


def test_only_one_resonance_applies_to_matching_active_species_and_deactivation_is_free(game, play):
    play("adopt", "青鸾")
    own_species(game, "hanying")
    own_species(game, "xuanhu")
    own_species(game, "xuehu")
    add_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    play("resonance", "激活 青岚双翼")

    xuanhu_id = sql(game[1], "SELECT pet_id FROM pets WHERE species_id='xuanhu'")[0]["pet_id"]
    sql(game[1], "UPDATE players SET active_pet_id=? WHERE user_id='u1'", (xuanhu_id,))
    without_match = stats(game)
    assert without_match.resonance_name is None
    assert "战斗共鸣：青岚双翼（当前出战灵宠不匹配）" in play("status").text()
    before_switch = player(game[1]), items(game[1])
    play("resonance", "激活 月狐照影")
    baseline = stats(game)
    assert baseline.resonance_name == "月狐照影"
    assert baseline.stats.attack > without_match.stats.attack
    assert len(sql(game[1], "SELECT * FROM player_resonance")) == 1
    assert player(game[1])["stones"] == before_switch[0]["stones"] - 200
    assert items(game[1])["bloodline_essence"] == before_switch[1]["bloodline_essence"] - 1

    paid = player(game[1]), items(game[1])
    play("resonance", "停用")
    assert stats(game).resonance_name is None
    assert "战斗共鸣：无" in play("status").text()
    assert (player(game[1]), items(game[1])) == paid
    with pytest.raises(GameError, match="没有启用"):
        play("resonance", "停用")


def test_resonance_invalidation_clears_team_readiness_and_concurrent_activation_spends_once(game, play):
    play("adopt", "青鸾")
    own_species(game, "hanying")
    add_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    play("team_create")
    play("team_ready")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is not None

    def activate(index):
        return game[0].execute("u1", "resonance", "激活 青岚双翼", f"parallel-{index}", NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(activate, range(8)))
    assert sum(reply.title == "灵契共鸣已启用" for reply in replies) == 1
    assert sum(reply.title == "共鸣已启用" for reply in replies) == 7
    assert player(game[1])["stones"] == 800
    assert items(game[1])["bloodline_essence"] == 4
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None


def test_battle_snapshot_records_applied_resonance_and_other_users_cannot_borrow_it(game, play):
    play("adopt", "青鸾")
    own_species(game, "hanying")
    play("adopt", "青鸾", user="u2")
    sql(game[1], "UPDATE pets SET species_id='xuanhu' WHERE user_id='u2'")
    own_species(game, "hanying", user="u2")
    add_essence(game)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    play("resonance", "激活 青岚双翼")
    with pytest.raises(GameError, match="尚未集齐"):
        play("resonance", "激活 青岚双翼", user="u2")

    play("challenge", "青岚林")
    row = sql(game[1], "SELECT snapshot FROM battle_records ORDER BY battle_id DESC LIMIT 1")[0]
    snapshot = json.loads(row["snapshot"])
    member = snapshot["teams"][0]["members"][0]
    assert member["resonance"] == "青岚双翼"
    report = play("battle_reports", f"查看 {sql(game[1], 'SELECT MAX(battle_id) AS id FROM battle_records')[0]['id']}")
    assert "共鸣 青岚双翼" in report.text()


def test_resonance_cost_failure_rolls_back_and_no_pet_species_borrowing(game, play):
    play("adopt", "青鸾")
    own_species(game, "hanying")
    before = player(game[1]), items(game[1])
    with pytest.raises(GameError, match="需要 200 灵石"):
        play("resonance", "激活 青岚双翼")
    assert (player(game[1]), items(game[1])) == before

    sql(game[1], "UPDATE players SET stones=1000")
    before = player(game[1]), items(game[1])
    with pytest.raises(GameError, match="道具数量不足"):
        play("resonance", "激活 青岚双翼")
    assert (player(game[1]), items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM player_resonance")
