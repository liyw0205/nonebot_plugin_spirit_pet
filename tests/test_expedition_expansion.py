import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql

NOW = 1_800_000_000
NEW_IDS = (
    "spring_soak", "pill_brew", "feather_forge", "fang_forge", "scale_hunt", "shell_dig", "bell_temper",
    "beak_carve", "silk_weave", "scale_cure", "root_graft", "horn_polish", "scythe_forge", "prism_cut",
)
REALMS = ("qiling", "ningqi", "zhuji", "jindan", "yuanying", "huashen", "dujie")


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def test_every_realm_now_offers_three_expeditions(game):
    content = game[0].content
    assert len(content.expeditions) == 21
    for realm in REALMS:
        offered = [entry for entry in content.expeditions.values() if entry.min_realm == realm]
        assert len(offered) == 3
    assert set(NEW_IDS) <= set(content.expeditions)
    assert len({entry.name for entry in content.expeditions.values()}) == 21


def test_new_expeditions_are_well_formed_and_use_distinct_materials(game):
    content = game[0].content
    materials = []
    for identifier in NEW_IDS:
        expedition = content.expeditions[identifier]
        assert expedition.min_realm in REALMS
        assert 0 < expedition.energy <= 100
        assert expedition.reward.exp.minimum < expedition.reward.exp.maximum
        assert expedition.reward.stones.minimum < expedition.reward.stones.maximum
        assert len(expedition.reward.items) == 1
        item, bounds = next(iter(expedition.reward.items.items()))
        assert item in content.items
        assert (bounds.minimum, bounds.maximum) == (0, 1)
        materials.append(item)
    assert len(set(materials)) == len(materials)


def test_new_expedition_gates_by_realm_and_settles_once(game, play):
    account(game, play)
    with pytest.raises(GameError, match="需要"):
        play("expedition_start", "锻镰")

    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    before = (pet(game[1])["exp"], player(game[1])["stones"])
    start = play("expedition_start", "锻镰", op="exp-new")
    assert pet(game[1])["energy"] == 100 - 78
    assert start is not None

    with pytest.raises(GameError, match="已有外出委托"):
        play("expedition_start", "琢晶")

    finishes_at = sql(game[1], "SELECT finishes_at FROM expeditions WHERE user_id='u1'")[0]["finishes_at"]
    claim = play("expedition_claim", "1", op="exp-new-claim", now=finishes_at)
    assert claim is not None
    assert (pet(game[1])["exp"], player(game[1])["stones"]) != before
    assert play("expedition_claim", "1", op="exp-new-claim", now=finishes_at).lines == claim.lines


def test_expedition_catalog_pages_through_every_realm(game, play):
    account(game, play)
    first = play("expedition_catalog")
    assert first.lines[0].startswith("采灵药 · 启灵起")
    assert first.title == "山海委托 1/5"
    last = play("expedition_catalog", "5")
    assert last.title == "山海委托 5/5"
    assert "琢晶" in last.text()
    with pytest.raises(GameError, match="共 5 页"):
        play("expedition_catalog", "6")
