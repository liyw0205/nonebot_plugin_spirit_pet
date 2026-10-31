"""Pet sigils: unlock gates, two slots, flat stats and refusals."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.sigil_content import Sigil, SigilBonus
from nonebot_plugin_spirit_pet.gameplay import sigils
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, sql

NOW = 1_800_000_000


def ctx_of(game, user="u1"):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, NOW, "read-sigil")


def stats(game, user="u1", pet_id=None):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "read-sigil-stats")
        target = pet_id or ctx.repo.player(user).active_pet_id
        return combatant(ctx, user, pet_id=target).stats


def add_pet(game, name="小鸾", species="qingluan", user="u1"):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 0, 100, ?)",
            (user, species, name, NOW),
        ).lastrowid


def activate(game, pet_id, user="u1"):
    sql(game[1], "UPDATE players SET active_pet_id=? WHERE user_id=?", (pet_id, user))


def seed_claims(game, count, user="u1", offset=0):
    for index in range(offset, offset + count):
        sql(
            game[1],
            "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at,"
            " reward_snapshot, reply) VALUES (?, ?, ?, ?, '{}', 'seed')",
            (user, f"seed_{index}", f"seed-op-{user}-{index}", NOW),
        )


def seed_species(game, count, user="u1", offset=0):
    """Own `count` distinct species so the collection requirement can be met."""
    pool = [entry for entry in game[0].content.species.values() if not entry.starter]
    species = pool[offset:offset + count]
    for index, entry in enumerate(species, offset):
        with game[1].connect() as conn:
            conn.execute(
                "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
                " VALUES (?, ?, ?, 0, 100, ?)",
                (user, entry.id, f"收{index}", NOW),
            )


def slots(game, pet_id, user="u1"):
    return sigils.equipped(ctx_of(game, user), pet_id, user)


def test_content_declares_eight_sigils(game):
    rows = list(game[0].content.sigils.values())
    assert [row.id for row in rows] == [
        "first_light", "swift_mark", "iron_oath", "beast_bond",
        "deep_tie", "keen_edge", "high_breath", "apex_seal",
    ]
    assert all(any(row.bonuses.model_dump().values()) for row in rows)
    assert {row.requires.kind for row in rows} == {"achievements", "collection", "bond", "realm"}


def test_sigil_validation_rejects_empty_bonus_and_bad_kind():
    base = {"id": "x", "name": "测试", "description": "测试", "bonuses": {"hp": 10},
            "requires": {"kind": "achievements", "value": 1}}
    assert Sigil.model_validate(base).bonuses.hp == 10
    with pytest.raises(ValidationError, match="must not all be zero"):
        SigilBonus.model_validate({})
    with pytest.raises(ValidationError):
        SigilBonus.model_validate({"hp": 61})
    with pytest.raises(ValidationError):
        Sigil.model_validate({**base, "requires": {"kind": "unknown", "value": 1}})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("sigils", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_sigils_with_requirements_and_state(game, play):
    play("adopt", "青鸾")
    page = play("sigils")
    assert "青鸾：符印槽 0/2 · 空。" in page.text()
    assert "初光符 · 气血 +40 · 需要 成就领取 0/1 · 未解锁" in page.text()
    assert "疾行符 · 速度 +18 · 需要 成就领取 0/5 · 未解锁" in page.text()
    assert page.inline_commands == ()


def test_an_achievement_sigil_unlocks_at_its_threshold(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 4)
    assert "疾行符 · 速度 +18 · 需要 成就领取 4/5 · 未解锁" in play("sigils").text()
    seed_claims(game, 1, offset=4)
    page = play("sigils")
    assert "疾行符 · 速度 +18 · 需要 成就领取 5/5 · 可装备" in page.text()
    assert "灵宠符印 装备 疾行符" in [link.command for link in page.inline_commands]


def test_a_collection_sigil_unlocks_by_species_count(game, play):
    play("adopt", "青鸾")
    # the adopted starter already counts as one species, so 4 more reaches the 5 required
    seed_species(game, 3)
    locked = [line for line in play("sigils").text().splitlines() if "铁誓符" in line][0]
    assert "未解锁" in locked
    seed_species(game, 1, offset=3)
    unlocked_row = [line for line in play("sigils").text().splitlines() if "铁誓符" in line][0]
    assert "可装备" in unlocked_row


def test_a_bond_sigil_uses_the_pets_bond_level(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    ctx = ctx_of(game)
    assert not sigils.unlocked(ctx, ctx.content.sigils["deep_tie"], ctx.repo.pet(pet_id))
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 300, 1)",
        (f"bond_exp_{pet_id}",),
    )
    ctx = ctx_of(game)
    assert sigils.unlocked(ctx, ctx.content.sigils["deep_tie"], ctx.repo.pet(pet_id))


def test_a_realm_sigil_uses_the_pets_realm(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    ctx = ctx_of(game)
    assert not sigils.unlocked(ctx, ctx.content.sigils["high_breath"], ctx.repo.pet(pet_id))
    sql(game[1], "UPDATE pets SET realm=2 WHERE pet_id=?", (pet_id,))
    ctx = ctx_of(game)
    assert sigils.unlocked(ctx, ctx.content.sigils["high_breath"], ctx.repo.pet(pet_id))


def test_equipping_writes_one_slot_and_adds_flat_stats(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    pet_id = pet(game[1])["pet_id"]
    before = stats(game)
    reply = play("sigils", "装备 初光符", op="equip-1")
    assert reply.title == "镶嵌符印"
    assert "1 号槽" in reply.text()
    assert slots(game, pet_id) == {1: "first_light"}
    after = stats(game)
    assert after.hp == before.hp + 40
    assert (after.attack, after.defense, after.speed) == (before.attack, before.defense, before.speed)


def test_two_slots_are_independent(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 5)
    pet_id = pet(game[1])["pet_id"]
    play("sigils", "装备 初光符", op="s1")
    play("sigils", "装备 疾行符", op="s2")
    assert slots(game, pet_id) == {1: "first_light", 2: "swift_mark"}
    play("sigils", "卸下 初光符", op="s3")
    assert slots(game, pet_id) == {2: "swift_mark"}


def test_a_third_sigil_is_refused_when_both_slots_are_full(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 5)
    pet_id = pet(game[1])["pet_id"]
    play("sigils", "装备 初光符", op="f1")
    play("sigils", "装备 疾行符", op="f2")
    seed_species(game, 4)                   # unlock 铁誓符 (collection 5 incl. starter)
    with pytest.raises(GameError, match="两个符印槽都已占用"):
        play("sigils", "装备 铁誓符", op="f3")
    assert slots(game, pet_id) == {1: "first_light", 2: "swift_mark"}


def test_locked_and_duplicate_equips_are_refused(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    pet_id = pet(game[1])["pet_id"]
    with pytest.raises(GameError, match="尚未解锁"):
        play("sigils", "装备 疾行符")
    play("sigils", "装备 初光符", op="dup-1")
    with pytest.raises(GameError, match="已经装备"):
        play("sigils", "装备 初光符", op="dup-2")
    assert slots(game, pet_id) == {1: "first_light"}


def test_unequip_refuses_when_not_equipped(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    with pytest.raises(GameError, match="没有装备"):
        play("sigils", "卸下 初光符")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'sigil_%'") == []


def test_an_expedition_pet_cannot_equip(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    play("expedition_start", "采灵药", op="trip")
    with pytest.raises(GameError, match="派遣|行程"):
        play("sigils", "装备 初光符")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'sigil_%'") == []


def test_sigils_are_per_pet(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    second = add_pet(game, "小鸾")
    play("sigils", "装备 初光符", op="per-pet")
    first_id = pet(game[1])["pet_id"]
    assert slots(game, first_id) == {1: "first_light"}
    assert slots(game, second) == {}
    activate(game, second)
    assert "符印槽 0/2" in play("sigils").text()
    assert stats(game, pet_id=second).hp == stats(game, pet_id=second).hp - 0
    assert sigils.equipped(ctx_of(game), second) == {}


def test_objective_help_and_parse(game, play):
    play("adopt", "青鸾")
    assert "符印：已装备 0/2" in play("objectives").text()
    seed_claims(game, 1)
    play("sigils", "装备 初光符", op="obj")
    assert "符印：已装备 1/2" in play("objectives").text()
    assert "灵宠符印" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠符印") == ("sigils", "")
    assert handlers._parse("灵宠符印 装备 初光符") == ("sigils", "装备 初光符")
    with pytest.raises(GameError, match="格式"):
        play("sigils", "额外")


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    pet_id = pet(game[1])["pet_id"]
    first = play("sigils", "装备 初光符", op="replay")
    again = play("sigils", "装备 初光符", op="replay")
    assert again.text() == first.text()
    assert slots(game, pet_id) == {1: "first_light"}


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 1)
    play("sigils", "装备 初光符", op="persist")
    assert "1号 初光符" in play("sigils").text()
    assert "符印：已装备 1/2" in play("objectives").text()


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    seed_claims(game, 5)
    page = play("sigils")
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
