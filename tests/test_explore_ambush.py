import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql

NOW = 1_800_000_000


def force_ambush(game):
    """randint(1,100) is the ambush roll; force it to 1 so the ambush always fires."""
    game[0].rng.randint = lambda start, stop: start


def skip_ambush(game):
    """Force the ambush roll high while leaving other randint rolls untouched."""
    original = game[0].rng.randint
    game[0].rng.randint = lambda start, stop: stop if stop == 100 else original(start, stop)


def test_ambush_triggers_fights_the_exploring_pet_and_awards_mastery_once(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100, exp=0")
    play("summon", now=NOW, op="second-pet")  # second roster pet, not in explore action
    force_ambush(game)
    before_other = sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")[1]

    reply = play("explore", "灵泉修行", now=NOW + 1, op="ambush-fight")
    assert reply.title == "山海历练 · 灵泉修行"
    assert "伏击！林间傀儡从暗处扑出" in reply.lines[0]
    assert "伏击者被击退" in reply.text()
    assert "修为 +" in reply.text() and "灵石 +" in reply.text()
    # Single-acting-pet rule: the exploring pet paid explore energy; the other
    # roster pet keeps its energy untouched.
    assert sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")[1] == before_other
    # Mastery: the fighting pet gains proficiency from real casts.
    assert sql(game[1], "SELECT proficiency FROM learned_skills WHERE pet_id=1") == []
    # Battle report persisted with the ambush key.
    assert sql(game[1], "SELECT kind, battle_key FROM battle_records") == [
        {"kind": "pve", "battle_key": "ambush_spirit_spring"},
    ]


def test_ambush_defeat_costs_extra_energy_and_no_loot(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_ambush(game)
    game[0].rng.randint = lambda start, stop: start  # minimum damage -> pet loses
    reply = play("explore", "劫云问道", now=NOW + 1, op="ambush-lose")
    assert "仓皇撤退" in reply.text()
    assert "额外精力 -10" in reply.text()
    assert "伏击者被击退" not in reply.text()
    # 25 explore + 10 defeat, bounded by remaining energy.
    assert pet(game[1])["energy"] == 100 - 25 - 10
    assert sql(game[1], "SELECT battle_key FROM battle_records")[0]["battle_key"] == "ambush_tribulation_clouds"


def test_ambush_and_encounter_are_mutually_exclusive_single_settlement(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_ambush(game)
    reply = play("explore", "灵泉修行", now=NOW + 1, op="ambush-exclusive")
    assert "伏击！" in reply.text()
    assert "奇遇：" not in reply.text()
    # No discovery was recorded and the daily task advanced exactly once.
    assert sql(game[1], "SELECT encounter_id FROM adventure_discoveries") == []
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='explore_once'")[0]["progress"] == 1


def test_ambush_replay_returns_original_reply_without_double_rewards(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_ambush(game)
    first = play("explore", "灵泉修行", now=NOW + 1, op="ambush-replay")
    again = play("explore", "灵泉修行", now=NOW + 2, op="ambush-replay")
    assert again == first
    assert len(sql(game[1], "SELECT battle_id FROM battle_records")) == 1
    # FixedRandom minimum of the 60-120 range on top of the 100 starter stones.
    assert player(game[1])["stones"] == 160


def test_route_catalog_lists_ambush_chance(game, play):
    listing = play("explore", now=NOW)
    assert "伏击概率：20% · 胜利可获额外战利品，失利额外损失精力" in listing.lines


def test_existing_gates_unchanged(game, play):
    play("adopt", "青鸾", now=NOW)
    force_ambush(game)
    with pytest.raises(GameError, match="古洞寻珍需要筑基境界"):
        play("explore", "古洞寻珍", now=NOW + 1)
    sql(game[1], "UPDATE pets SET realm=1, energy=10")
    with pytest.raises(GameError, match="精力不足"):
        play("explore", "星谷采集", now=NOW + 2)


def test_per_route_ambush_rewards_follow_route_theme(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_ambush(game)
    play("explore", "古洞寻珍", now=NOW + 1, op="ambue-cave")
    loot = items(game[1])
    # Starter items include 3 灵粮; the cave ambush adds only its own theme drop.
    assert loot.get("bloodline_essence", 0) == 1
    assert loot.get("spirit_food", 0) == 3  # unchanged starter amount, no spring drop


def test_native_presentation_matches_battle_reports(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    force_ambush(game)
    reply = play("explore", "灵泉修行", now=NOW + 1, op="ambush-native")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    assert message["markdown"] or message.get("keyboard")
    assert reply.title == "山海历练 · 灵泉修行"
