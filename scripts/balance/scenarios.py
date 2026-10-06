from contextlib import closing
from dataclasses import dataclass
from random import Random

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter
from nonebot_plugin_spirit_pet.gameplay.compatibility import check_requirements
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository


@dataclass(frozen=True)
class Scenario:
    id: str
    dungeon_id: str
    realm: int
    profile: str
    species: tuple[str, ...]


def scenarios(content: Catalog) -> list[Scenario]:
    result = []
    starters = tuple(pet.id for pet in content.species.values() if pet.starter)
    realm_ids = [realm.id for realm in content.realms]
    for dungeon in content.dungeons.values():
        realm = realm_ids.index(dungeon.min_realm)
        if dungeon.team:
            parties = [tuple(starters[(i + j) % len(starters)] for j in range(size))
                       for size in (2, 3) for i in range(len(starters))]
            parties += [("xuanhu", "bifang"), ("xuanwu", "lingxi", "jiaolong")]
        else:
            parties = [(key,) for key in content.species]
        for profile in ("entry", "prepared"):
            for party in parties:
                key = f"{dungeon.id}/{profile}/{'-'.join(party)}"
                result.append(Scenario(key, dungeon.id, realm, profile, party))
    return result


def build_fighters(store: Store, content: Catalog, config: Config, species_ids: tuple[str, ...],
                   realm: int, profile: str, *, skill_ids=None, lineage_ids=None, bloodlines=None) -> list[Fighter]:
    """Build through the production loadout in a rolled-back simulation transaction."""
    for overrides in (skill_ids, lineage_ids, bloodlines):
        if overrides is not None and len(overrides) != len(species_ids):
            raise ValueError("simulation overrides must match the number of fighters")
    if profile not in {"entry", "prepared"} or not 0 <= realm < len(content.realms):
        raise ValueError("invalid simulation profile or realm")
    with closing(store.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            repo = Repository(conn)
            result = []
            for index, species_id in enumerate(species_ids):
                species = content.species[species_id]
                user_id = f"simulation-{index}"
                owner = repo.create_player(user_id, f"模拟道友{index}", 0)
                pet = repo.create_pet(user_id, species_id, species.name, species.initial_affinity, 0)
                owner.active_pet_id = pet.pet_id
                pet.realm = realm
                prepared = profile == "prepared"
                pet.layer = 5 if prepared else 1
                pet.bloodline = min(realm // 2, max(content.bloodlines)) if prepared else 0
                if bloodlines is not None:
                    if type(bloodlines[index]) is not int or bloodlines[index] not in content.bloodlines:
                        raise ValueError("invalid simulation bloodline")
                    pet.bloodline = bloodlines[index]
                if lineage_ids is not None:
                    pet.lineage_id = lineage_ids[index]
                pet.affinity = 30 if prepared else species.initial_affinity
                ctx = Context(repo, content, config, Random(0), user_id, 0)
                if prepared:
                    _equip(ctx, pet, skill_ids[index] if skill_ids is not None else None)
                elif skill_ids is not None:
                    raise ValueError("explicit skill loadouts require a prepared profile")
                result.append(combatant(ctx))
            return result
        finally:
            conn.rollback()


def _equip(ctx, pet, skill_ids=None):
    def allowed(definition):
        try:
            check_requirements(ctx, pet, definition.requirements)
        except GameError:
            return False
        return True

    gear_by_slot = {}
    for gear in ctx.content.equipment.values():
        if allowed(gear):
            score = gear.bonuses.hp + gear.bonuses.attack * 4 + gear.bonuses.defense * 3 + gear.bonuses.speed
            if gear.slot not in gear_by_slot or score > gear_by_slot[gear.slot][0]:
                gear_by_slot[gear.slot] = (score, gear)
    for slot, (_, gear) in gear_by_slot.items():
        item = next(item for item in ctx.content.items.values() if item.equipment_id == gear.id)
        ctx.repo.conn.execute("INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, ?)",
                              (pet.pet_id, slot, item.id, min(pet.realm, max(ctx.content.forge_levels))))
    compatible = [skill for skill in ctx.content.skills.values() if allowed(skill)]
    damage = sorted((skill for skill in compatible if skill.kind == "damage"),
                    key=lambda skill: (skill.coefficient, skill.id), reverse=True)
    healing = sorted((skill for skill in compatible if skill.kind == "heal"),
                     key=lambda skill: (skill.coefficient, skill.id), reverse=True)
    selected = (damage[:1] + healing[:1])[:ctx.content.rules.max_skill_slots]
    if skill_ids is not None:
        if len(skill_ids) > ctx.content.rules.max_skill_slots or len(set(skill_ids)) != len(skill_ids):
            raise ValueError("invalid simulation skill slots")
        selected = [ctx.content.skills[key] for key in skill_ids]
        for skill in selected:
            check_requirements(ctx, pet, skill.requirements)
    for skill in selected:
        ctx.repo.conn.execute(
            "INSERT INTO learned_skills(pet_id, skill_id, equipped, level) VALUES (?, ?, 1, ?)",
            (pet.pet_id, skill.id, min(1 + pet.realm // 2, max(ctx.content.skill_levels))),
        )
