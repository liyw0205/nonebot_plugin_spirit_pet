"""Lineup presets: save/apply/clear three rosters, with every eligibility rule re-checked."""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import lineup_presets
from nonebot_plugin_spirit_pet.gameplay.compatibility import check_requirements
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def add_pet(game, species_id, name, user="u1"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated) VALUES (?, ?, ?, 0, ?)",
        (user, species_id, name, NOW),
    )
    return max(row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets WHERE user_id=?", (user,)))


def ready(game, play):
    play("adopt", "青鸾")
    second = add_pet(game, "xuanhu", "玄狐二号")
    third = add_pet(game, "baize", "白泽三号")
    return second, third


def roster(game):
    return tuple(row["pet_id"] for row in sql(
        game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot",
    ))


def slot_rows(game, slot):
    return sorted(row["quest_id"] for row in sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ?",
        (f"lineup_preset_{slot}%",),
    ))


def first_pet_id(game):
    return sql(game[1], "SELECT active_pet_id FROM players WHERE user_id='u1'")[0]["active_pet_id"]


def compatible_gear(game, pet_id):
    ctx = ctx_of(game)
    pet = ctx.repo.pet(pet_id)
    for slot in ("weapon", "armor", "charm"):
        for item in ctx.content.items.values():
            if item.kind != "equipment" or item.equipment_id is None:
                continue
            gear = ctx.content.equipment.get(item.equipment_id)
            if gear is None or gear.slot != slot:
                continue
            try:
                check_requirements(ctx, pet, gear.requirements)
            except GameError:
                continue
            return slot, item
    pytest.fail("the starter companion needs at least one compatible equipment item")


def compatible_skill(game, pet_id):
    ctx = ctx_of(game)
    pet = ctx.repo.pet(pet_id)
    for skill in ctx.content.skills.values():
        try:
            check_requirements(ctx, pet, skill.requirements)
        except GameError:
            continue
        return skill
    pytest.fail("the starter companion needs at least one compatible skill")


def seed_tactical_plan(game, play):
    second, third = ready(game, play)
    first = first_pet_id(game)
    play("lineup", f"{first} {second}", op="tactical-pair")
    slot, original = compatible_gear(game, first)
    sql(game[1], "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, 0)",
        (first, slot, original.id))
    skill = compatible_skill(game, first)
    sql(game[1], "INSERT INTO learned_skills(pet_id, skill_id, equipped) VALUES (?, ?, 1)",
        (first, skill.id))
    play("formation", f"{first} 后援", op="tactical-rear")
    play("lineup_presets", "保存 1", op="tactical-save")
    return first, second, third, slot, original, skill


def switch_to_ungeared_configuration(game, play, first, third, slot, original, skill):
    sql(game[1], "DELETE FROM equipment WHERE pet_id=? AND slot=?", (first, slot))
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, 1) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity", (original.id,))
    sql(game[1], "UPDATE learned_skills SET equipped=0 WHERE pet_id=? AND skill_id=?",
        (first, skill.id))
    play("formation", f"{first} 前锋", op="tactical-front")
    play("lineup", str(third), op="tactical-away")


def test_page_without_a_pet_is_read_only(game, play):
    page = play("lineup_presets", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_three_empty_slots(game, play):
    ready(game, play)
    page = play("lineup_presets")
    assert "预设 1：空" in page.text()
    assert "预设 3：空" in page.text()
    assert {link.command for link in page.inline_commands} == {f"灵宠出战预设 保存 {n}" for n in (1, 2, 3)}


def test_saving_snapshots_the_roster_without_switching(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="two")
    current = roster(game)
    reply = play("lineup_presets", "保存 2", op="save")
    assert reply.title == "预设已保存"
    assert lineup_presets.stored(ctx_of(game), 2) == current
    assert roster(game) == current


def test_new_preset_restores_the_players_member_order(game, play):
    second, _ = ready(game, play)
    first = first_pet_id(game)
    play("lineup", f"{second} {first}", op="order-save-lineup")
    play("lineup_presets", "保存 1", op="order-save-plan")
    assert lineup_presets.stored(ctx_of(game), 1) == (second, first)

    play("lineup", str(first), op="order-change")
    play("lineup_presets", "应用 1", op="order-apply-plan")

    assert roster(game) == (second, first)


def test_saving_refuses_an_empty_roster_and_bad_slots(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="格式"):
        play("lineup_presets", "保存 4")
    with pytest.raises(GameError, match="格式"):
        play("lineup_presets", "保存")
    # roster emptied behind the player's back
    sql(game[1], "DELETE FROM active_pet_slots WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    with pytest.raises(GameError, match="没有出战阵容"):
        play("lineup_presets", "保存 1")


def test_applying_switches_the_roster(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair")
    play("lineup_presets", "保存 1", op="save-1")
    first = roster(game)[0]
    play("lineup", str(first), op="solo")
    assert roster(game) == (first,)
    reply = play("lineup_presets", "应用 1", op="apply-1")
    assert reply.title == "预设已应用"
    assert roster(game) == (second, third)


def test_applying_the_current_roster_is_a_no_op(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-2")
    play("lineup_presets", "保存 1", op="save-2")
    reply = play("lineup_presets", "应用 1", op="apply-2")
    assert "与当前阵容一致" in reply.text()
    assert roster(game) == (second, third)


def test_applying_an_empty_slot_is_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未保存"):
        play("lineup_presets", "应用 3")


def test_a_sealed_member_blocks_the_preset(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-3")
    play("lineup_presets", "保存 1", op="save-3")
    play("lineup", str(second), op="keep-one")
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (third,))
    with pytest.raises(GameError, match="已封存"):
        play("lineup_presets", "应用 1")
    assert roster(game) == (second,)


def test_an_expedition_member_blocks_the_preset(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-4")
    play("lineup_presets", "保存 1", op="save-4")
    play("lineup", str(second), op="solo-4")
    play("expedition_start", "采灵药", op="trip", now=NOW)
    with pytest.raises(GameError, match="派遣"):
        play("lineup_presets", "应用 1", now=NOW + 10)


def test_a_removed_member_blocks_the_preset(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-5")
    play("lineup_presets", "保存 1", op="save-5")
    play("lineup", str(second), op="solo-5")
    sql(game[1], "DELETE FROM pets WHERE pet_id=?", (third,))
    with pytest.raises(GameError, match="不在名册"):
        play("lineup_presets", "应用 1")
    assert roster(game) == (second,)


def test_clearing_removes_only_that_slot(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-6")
    play("lineup_presets", "保存 1", op="save-6a")
    play("lineup_presets", "保存 2", op="save-6b")
    before = roster(game)
    reply = play("lineup_presets", "清除 1", op="clear-1")
    assert reply.title == "预设已清除"
    assert slot_rows(game, 1) == []
    assert slot_rows(game, 2)
    assert not lineup_presets._tactic_exists(ctx_of(game), 1)
    assert lineup_presets._tactic_exists(ctx_of(game), 2)
    assert roster(game) == before
    with pytest.raises(GameError, match="尚未保存"):
        play("lineup_presets", "清除 1")


def test_saving_over_a_slot_replaces_members(game, play):
    second, third = ready(game, play)
    first = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' AND name='青鸾'")[0]["pet_id"]
    play("lineup", str(first), op="one")
    play("lineup_presets", "保存 1", op="save-old")
    play("lineup", f"{second} {third}", op="two")
    play("lineup_presets", "保存 1", op="save-new")
    assert lineup_presets.stored(ctx_of(game), 1) == (second, third)
    assert slot_rows(game, 1) == sorted([
        "lineup_preset_1",
        f"lineup_preset_1_{second}",
        f"lineup_preset_1_{third}",
    ])


def test_objective_help_and_parse(game, play):
    second, third = ready(game, play)
    assert "出战预设：尚未保存" in play("objectives").text()
    play("lineup_presets", "保存 1", op="obj")
    assert "出战预设：已保存 1/3" in play("objectives").text()
    assert "灵宠出战预设" in play("help", "结契").text()
    assert handlers._parse("灵宠出战预设") == ("lineup_presets", "")
    assert handlers._parse("灵宠出战预设 应用 2") == ("lineup_presets", "应用 2")


def test_same_operation_replays_identically(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-7")
    first_reply = play("lineup_presets", "保存 1", op="replay-save")
    again = play("lineup_presets", "保存 1", op="replay-save")
    assert again.text() == first_reply.text()
    assert len(slot_rows(game, 1)) == 3


def test_state_survives_a_restart(game, play):
    second, third = ready(game, play)
    play("lineup", f"{second} {third}", op="pair-8")
    play("lineup_presets", "保存 3", op="restart")
    assert "可应用" in play("lineup_presets").text()
    assert lineup_presets.stored(ctx_of(game), 3) == (second, third)
    assert lineup_presets._tactic_snapshot(ctx_of(game), 3, (second, third)) is not None


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("lineup_presets")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4


def test_tactical_snapshot_restores_formation_skills_and_real_gear(game, play):
    first, second, third, slot, original, skill = seed_tactical_plan(game, play)
    switch_to_ungeared_configuration(game, play, first, third, slot, original, skill)

    reply = play("lineup_presets", "应用 1", op="tactical-apply")

    assert "已恢复阵位、携带灵术与真实装备" in reply.text()
    assert roster(game) == (first, second)
    ctx = ctx_of(game)
    assert lineup_presets.formation.position_of(ctx, first) == "rear"
    assert ctx.repo.conn.execute(
        "SELECT equipped FROM learned_skills WHERE pet_id=? AND skill_id=?", (first, skill.id),
    ).fetchone()[0] == 1
    assert lineup_presets.equipment.loadout(ctx, first)[slot] == (original.id, 0)
    quantities = dict((row["item_id"], row["quantity"]) for row in sql(
        game[1], "SELECT item_id, quantity FROM inventory WHERE user_id='u1' AND item_id=?",
        (original.id,),
    ))
    assert quantities == {original.id: 0}


def test_tactical_snapshot_round_trips_enhanced_equipment(game, play):
    ready(game, play)
    first = first_pet_id(game)
    play("lineup", str(first), op="enhanced-gear-lineup")
    slot, item = compatible_gear(game, first)
    sql(game[1], "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, 1)",
        (first, slot, item.id))
    play("lineup_presets", "保存 2", op="enhanced-gear-save")
    sql(game[1], "DELETE FROM equipment WHERE pet_id=? AND slot=?", (first, slot))
    sql(game[1], "INSERT INTO unequipped_equipment(user_id, item_id, enhancement, quantity) "
        "VALUES ('u1', ?, 1, 1)", (item.id,))

    reply = play("lineup_presets", "应用 2", op="enhanced-gear-apply")

    assert "已恢复阵位" in reply.text()
    assert lineup_presets.equipment.loadout(ctx_of(game), first)[slot] == (item.id, 1)
    assert sql(game[1], "SELECT quantity FROM unequipped_equipment WHERE user_id='u1' AND item_id=? "
        "AND enhancement=1", (item.id,))[0]["quantity"] == 0


def test_tactical_plan_rejects_missing_gear_before_switching_anything(game, play):
    first, second, third, slot, original, skill = seed_tactical_plan(game, play)
    switch_to_ungeared_configuration(game, play, first, third, slot, original, skill)
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id=?", (original.id,))
    before_roster = roster(game)
    before_gear = sql(game[1], "SELECT pet_id, slot, item_id FROM equipment ORDER BY pet_id, slot")
    before_skill = sql(game[1], "SELECT pet_id, skill_id, equipped FROM learned_skills ORDER BY pet_id, skill_id")

    with pytest.raises(GameError, match="战术装备不足"):
        play("lineup_presets", "应用 1")

    assert roster(game) == before_roster
    assert sql(game[1], "SELECT pet_id, slot, item_id FROM equipment ORDER BY pet_id, slot") == before_gear
    assert sql(game[1], "SELECT pet_id, skill_id, equipped FROM learned_skills ORDER BY pet_id, skill_id") == before_skill


def test_tactical_apply_rolls_back_roster_skills_formation_and_inventory_on_write_failure(game, play):
    first, second, third, slot, original, skill = seed_tactical_plan(game, play)
    switch_to_ungeared_configuration(game, play, first, third, slot, original, skill)
    before_roster = roster(game)
    before_gear = sql(game[1], "SELECT pet_id, slot, item_id FROM equipment ORDER BY pet_id, slot")
    before_inventory = sql(game[1], "SELECT item_id, quantity FROM inventory WHERE user_id='u1' ORDER BY item_id")
    before_skills = sql(game[1], "SELECT pet_id, skill_id, equipped FROM learned_skills ORDER BY pet_id, skill_id")
    sql(game[1], "CREATE TRIGGER fail_tactical_gear BEFORE INSERT ON equipment "
        "BEGIN SELECT RAISE(ABORT, 'injected tactical failure'); END")

    with pytest.raises(sqlite3.IntegrityError, match="injected tactical failure"):
        play("lineup_presets", "应用 1", op="tactical-failed-apply")

    assert roster(game) == before_roster
    assert sql(game[1], "SELECT pet_id, slot, item_id FROM equipment ORDER BY pet_id, slot") == before_gear
    assert sql(game[1], "SELECT item_id, quantity FROM inventory WHERE user_id='u1' ORDER BY item_id") == before_inventory
    assert sql(game[1], "SELECT pet_id, skill_id, equipped FROM learned_skills ORDER BY pet_id, skill_id") == before_skills
    assert lineup_presets.formation.position_of(ctx_of(game), first) == "vanguard"


def test_old_roster_only_preset_remains_applicable_without_changing_pet_builds(game, play):
    second, third = ready(game, play)
    first = first_pet_id(game)
    play("formation", f"{first} 后援", op="legacy-position")
    skill = compatible_skill(game, first)
    sql(game[1], "INSERT INTO learned_skills(pet_id, skill_id, equipped) VALUES (?, ?, 1)",
        (first, skill.id))
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) "
        "VALUES ('u1', 'lineup_preset_1', 2, 0), ('u1', ?, 1, 0), ('u1', ?, 1, 0)",
        (f"lineup_preset_1_{second}", f"lineup_preset_1_{third}"))

    reply = play("lineup_presets", "应用 1", op="legacy-apply")

    assert "旧版阵容预设" in reply.text()
    assert roster(game) == (second, third)
    assert lineup_presets.formation.position_of(ctx_of(game), first) == "rear"
    assert sql(game[1], "SELECT equipped FROM learned_skills WHERE pet_id=? AND skill_id=?",
        (first, skill.id))[0]["equipped"] == 1
    assert "旧式阵容" in play("lineup_presets").text()


def test_tactical_apply_replay_returns_receipt_without_reapplying_later_state(game, play):
    first, _, third, slot, original, skill = seed_tactical_plan(game, play)
    switch_to_ungeared_configuration(game, play, first, third, slot, original, skill)
    first_reply = play("lineup_presets", "应用 1", op="tactical-replay")
    play("lineup", str(third), op="after-tactical-replay")

    replay = play("lineup_presets", "应用 1", op="tactical-replay")

    assert replay.text() == first_reply.text()
    assert roster(game) == (third,)


def test_two_concurrent_tactical_applies_leave_one_complete_persisted_plan(game, play):
    first, second, third, _, _, _ = seed_tactical_plan(game, play)
    play("lineup", str(third), op="concurrent-away")

    def apply(op):
        return game[0].execute("u1", "lineup_presets", "应用 1", op, NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(apply, ("concurrent-plan-a", "concurrent-plan-b")))

    assert all(reply.title == "预设已应用" for reply in replies)
    assert roster(game) == (first, second)
    ctx = ctx_of(game)
    snapshot = lineup_presets._tactic_snapshot(ctx, 1, (first, second))
    assert lineup_presets._tactic_matches_current(ctx, (first, second), snapshot)
