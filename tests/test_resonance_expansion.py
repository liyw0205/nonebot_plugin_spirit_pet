import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
NEW_IDS = (
    "windfire_soar", "fox_spirit", "metal_wing", "dragon_thunder", "mountain_pact", "snow_deer", "frost_wing",
)


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def add_pet(game, species, user="u1"):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, 100, ?)",
            (user, species, species, NOW),
        ).lastrowid


def test_catalog_has_seven_more_unique_cross_branch_pairs(game):
    content = game[0].content
    assert len(content.resonances) == 21
    pairs = [frozenset(entry.required_species) for entry in content.resonances.values()]
    assert len(set(pairs)) == len(pairs)
    covered = {species for entry in content.resonances.values() for species in entry.required_species}
    assert covered == set(content.species)
    for identifier in NEW_IDS:
        entry = content.resonances[identifier]
        assert len(entry.required_species) == 2
        assert entry.name and entry.description
        assert sum(entry.bonuses.model_dump().values()) > 0
        assert all(species in content.species for species in entry.required_species)


def test_new_pairs_join_species_that_were_not_paired_together(game):
    content = game[0].content
    old_pairs = {
        frozenset(entry.required_species)
        for identifier, entry in content.resonances.items() if identifier not in NEW_IDS
    }
    for identifier in NEW_IDS:
        pair = frozenset(content.resonances[identifier].required_species)
        assert pair not in old_pairs


def test_new_pair_activates_once_and_boosts_both_pets(game, play):
    account(game, play)
    add_pet(game, "bifang")
    sql(game[1], "UPDATE players SET stones=5000")
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'bloodline_essence', 10)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=10")

    listing = next(
        page for page in (play("resonance", str(index)) for index in range(1, 6))
        if "风火同翔" in page.text()
    )

    before = (player(game[1])["stones"], items(game[1])["bloodline_essence"])
    cost = game[0].content.rules.resonance_cost
    activated = play("resonance", "激活 风火同翔", op="resonance-new")
    assert activated == play("resonance", "激活 风火同翔", op="resonance-new")
    assert player(game[1])["stones"] == before[0] - cost.stones
    assert items(game[1])["bloodline_essence"] == before[1] - cost.items["bloodline_essence"]
    assert sql(game[1], "SELECT resonance_id FROM player_resonance WHERE user_id='u1'") == [
        {"resonance_id": "windfire_soar"}
    ]

    # Re-activating the same pair is idempotent: it reports the current resonance without spending again.
    again = play("resonance", "激活 风火同翔", op="resonance-new-again")
    assert again.title == "共鸣已启用"
    assert player(game[1])["stones"] == before[0] - cost.stones
    assert items(game[1])["bloodline_essence"] == before[1] - cost.items["bloodline_essence"]


def test_new_pair_needs_both_species(game, play):
    account(game, play)
    with pytest.raises(GameError, match="尚未集齐共鸣灵宠"):
        play("resonance", "激活 风火同翔")
