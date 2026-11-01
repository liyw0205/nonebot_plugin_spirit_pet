"""Pet pair bond: one partner per pet, bonus only while both are deployed together."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import loadout, pair_bond
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def grant_items(game, item_id, amount, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def add_pet(game, species_id, name):
    """Insert a second pet of a different species; the roster forbids duplicate species."""
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated)"
        " VALUES ('u1', ?, ?, 100, ?)",
        (species_id, name, NOW),
    )
    return max(pet_ids(game))


def ready(game, play, *, stones=5000, extra=0):
    """Adopt a starter, optionally add a second species, and give every pet enough affinity."""
    play("adopt", "青鸾")
    if extra:
        add_pet(game, "xuanhu", "玄狐二号")
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (stones,))
    sql(game[1], "UPDATE pets SET affinity=100 WHERE user_id='u1'")
    grant_items(game, "bloodline_essence", 5)


def pet_ids(game):
    return [row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' ORDER BY pet_id")]


def roster(game):
    return [row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot")]


def bond_rows(game):
    return [
        row["quest_id"] for row in sql(
            game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'bonded_%'",
        )
    ]


def make_pair(game, play):
    """Adopt two pets, put both in the roster, and bond them."""
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", f"{first} {second}", op="lineup")
    names = [
        sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (pet_id,))[0]["name"]
        for pet_id in (first, second)
    ]
    play("pair_bond", f"结契 {names[0]} {names[1]}", op="bond")
    return first, second, names


def test_rule_is_wired_into_content(game):
    rule = game[0].content.rules.pair_bond
    assert rule.stones >= 1
    assert rule.rates and all(0 < rate <= 0.5 for rate in rule.rates.values())
    assert rule.min_affinity >= 0


def test_rule_validation_rejects_free_or_empty_bonds():
    from nonebot_plugin_spirit_pet.domain.content import PairBondRule

    good = {"stones": 100, "items": {}, "min_affinity": 10, "rates": {"attack": 0.1}}
    assert PairBondRule.model_validate(good).stones == 100
    with pytest.raises(ValidationError, match="cost something"):
        PairBondRule.model_validate({**good, "stones": 0})
    with pytest.raises(ValidationError, match="at least one rate"):
        PairBondRule.model_validate({**good, "rates": {}})
    with pytest.raises(ValidationError):
        PairBondRule.model_validate({**good, "rates": {"attack": 0.9}})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("pair_bond", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_offers_legal_pairs_and_shows_cost(game, play):
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", f"{first} {second}", op="lineup-2")
    page = play("pair_bond")
    assert "未结契" in page.text()
    assert "可结契" in page.text()
    assert "灵石" in page.text()
    assert len(page.inline_commands) == 1  # exactly one legal pair


def test_bonding_writes_one_symmetric_row_and_charges_once(game, play):
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", f"{first} {second}", op="lineup-3")
    names = [sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (pet_id,))[0]["name"] for pet_id in (first, second)]
    stones = player(game[1])["stones"]
    reply = play("pair_bond", f"结契 {names[0]} {names[1]}", op="bond-charge")
    assert reply.title == "同心结契"
    assert bond_rows(game) == [f"bonded_{min(first, second)}_{max(first, second)}"]
    assert player(game[1])["stones"] == stones - game[0].content.rules.pair_bond.stones
    ctx = ctx_of(game)
    assert pair_bond.partner_of(ctx, first) == second
    assert pair_bond.partner_of(ctx, second) == first


def test_bonus_applies_only_while_both_are_deployed(game, play):
    first, second, names = make_pair(game, play)
    ctx = ctx_of(game)
    assert pair_bond.deployed_together(ctx, first)
    both = loadout.combatant(ctx, "u1", pet_id=first)

    play("lineup", str(first), op="solo")
    solo_ctx = ctx_of(game)
    assert not pair_bond.deployed_together(solo_ctx, first)
    solo = loadout.combatant(solo_ctx, "u1", pet_id=first)

    rate = game[0].content.rules.pair_bond.rates["attack"]
    assert both.stats.attack > solo.stats.attack
    assert both.stats.attack == int(solo.stats.attack * (1 + rate) + 0.5)


def test_the_bonus_scales_base_stats_only(game, play):
    first, second, names = make_pair(game, play)
    content = game[0].content
    from nonebot_plugin_spirit_pet.utils.elements import expand_elements

    species = content.species[sql(game[1], "SELECT species_id FROM pets WHERE pet_id=?", (first,))[0]["species_id"]]
    wearable = expand_elements(species.elements, content.elements)
    item = next(
        entry for entry in content.items.values()
        if entry.equipment_id
        and content.equipment[entry.equipment_id].slot == "weapon"
        and set(content.equipment[entry.equipment_id].requirements.elements) <= wearable
        and (
            not content.equipment[entry.equipment_id].requirements.categories
            or species.category in content.equipment[entry.equipment_id].requirements.categories
        )
    )
    weapon = content.equipment[item.equipment_id]
    before = loadout.combatant(ctx_of(game), "u1", pet_id=first).stats.attack
    sql(game[1], "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, 'weapon', ?, 0)",
        (first, item.id))
    after = loadout.combatant(ctx_of(game), "u1", pet_id=first).stats.attack
    assert after == before + weapon.bonuses.attack


def test_a_second_bond_for_the_same_pet_is_refused(game, play):
    first, second, names = make_pair(game, play)
    third = add_pet(game, "baize", "白泽三号")
    play("lineup", f"{first} {second} {third}", op="lineup-3pets")
    third_name = sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (third,))[0]["name"]
    with pytest.raises(GameError, match="已有同心"):
        play("pair_bond", f"结契 {names[0]} {third_name}")
    assert len(bond_rows(game)) == 1


def test_bonding_requires_the_roster(game, play):
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", str(first), op="solo-roster")
    names = [sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (pet_id,))[0]["name"] for pet_id in (first, second)]
    with pytest.raises(GameError, match="出战阵容"):
        play("pair_bond", f"结契 {names[0]} {names[1]}")
    assert bond_rows(game) == []


def test_affinity_floor_and_cost_are_enforced(game, play):
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", f"{first} {second}", op="lineup-aff")
    names = [sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (pet_id,))[0]["name"] for pet_id in (first, second)]
    sql(game[1], "UPDATE pets SET affinity=0 WHERE pet_id=?", (second,))
    with pytest.raises(GameError, match="亲密不足"):
        play("pair_bond", f"结契 {names[0]} {names[1]}")
    assert bond_rows(game) == []

    sql(game[1], "UPDATE pets SET affinity=100 WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET stones=0 WHERE user_id='u1'")
    with pytest.raises(GameError, match="灵石不足"):
        play("pair_bond", f"结契 {names[0]} {names[1]}")
    assert bond_rows(game) == []

    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='u1'")
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='bloodline_essence'")
    with pytest.raises(GameError, match="材料不足"):
        play("pair_bond", f"结契 {names[0]} {names[1]}")
    assert bond_rows(game) == []


def test_unknown_and_same_pets_are_refused(game, play):
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", f"{first} {second}", op="lineup-same")
    name = sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (first,))[0]["name"]
    with pytest.raises(GameError, match="不同的伙伴"):
        play("pair_bond", f"结契 {name} {name}")
    with pytest.raises(GameError, match="没有找到这只伙伴"):
        play("pair_bond", "结契 无名 青鸾")
    with pytest.raises(GameError, match="格式"):
        play("pair_bond", "结契 只有一个")


def test_dissolving_clears_both_sides_without_refund(game, play):
    first, second, names = make_pair(game, play)
    stones = player(game[1])["stones"]
    reply = play("pair_bond", f"解契 {names[0]}", op="dissolve")
    assert reply.title == "同心已解"
    assert bond_rows(game) == []
    ctx = ctx_of(game)
    assert pair_bond.partner_of(ctx, first) is None
    assert pair_bond.partner_of(ctx, second) is None
    assert player(game[1])["stones"] == stones
    assert player(game[1])["stones"] == 5000 - game[0].content.rules.pair_bond.stones


def test_dissolving_an_unbonded_pet_is_refused(game, play):
    ready(game, play)
    name = sql(game[1], "SELECT name FROM pets WHERE user_id='u1'")[0]["name"]
    with pytest.raises(GameError, match="尚未结契"):
        play("pair_bond", f"解契 {name}")


def test_objective_help_and_parse(game, play):
    first, second, names = make_pair(game, play)
    text = play("objectives").text()
    assert "同心：" in text
    assert "2/2" in text
    assert "灵宠同心" in play("help", "成长").text()
    assert handlers._parse("灵宠同心") == ("pair_bond", "")
    assert handlers._parse("灵宠同心 解契 青鸾") == ("pair_bond", "解契 青鸾")


def test_same_operation_replays_identically(game, play):
    ready(game, play, extra=1)
    first, second = pet_ids(game)
    play("lineup", f"{first} {second}", op="lineup-replay")
    names = [sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (pet_id,))[0]["name"] for pet_id in (first, second)]
    first_reply = play("pair_bond", f"结契 {names[0]} {names[1]}", op="replay-bond")
    stones = player(game[1])["stones"]
    again = play("pair_bond", f"结契 {names[0]} {names[1]}", op="replay-bond")
    assert again.text() == first_reply.text()
    assert player(game[1])["stones"] == stones


def test_state_survives_a_restart(game, play):
    first, second, names = make_pair(game, play)
    assert "同心" in play("pair_bond").text()
    assert pair_bond.partner_of(ctx_of(game), second) == first


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    first, second, names = make_pair(game, play)
    page = play("pair_bond")
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
