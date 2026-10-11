from ..utils.elements import element_ancestors, expand_elements


def validate_battle_content(content):
    require = content._require
    realm_ids = {realm.id for realm in content.realms}
    for element in content.elements.values():
        require(element.strong_against, content.elements, "element relationships")
        if element.parent is not None:
            require([element.parent], content.elements, "element parent")
        ancestors = element_ancestors(element.id, content.elements)
        if set(element.strong_against) & ancestors:
            raise ValueError("element cannot counter itself or its parent")
        if len(set(element.strong_against)) != len(element.strong_against):
            raise ValueError("duplicate element relationships")
    for talent in content.talents.values():
        if talent.element is not None:
            require([talent.element], content.elements, "talent element")
    for species in content.species.values():
        require([species.category], content.categories, "pet category")
        require(species.elements, content.elements, "pet elements")
        require([species.talent], content.talents, "pet talent")
        if len(set(species.elements)) != len(species.elements):
            raise ValueError("duplicate pet elements")
        if species.primary_element not in species.elements:
            raise ValueError("pet primary element must belong to its elements")
        talent = content.talents[species.talent]
        if talent.element is not None and talent.element not in expand_elements(species.elements, content.elements):
            raise ValueError("pet cannot use its elemental talent")
    for definition in (*content.equipment.values(), *content.skills.values()):
        rules = definition.requirements
        require(rules.elements, content.elements, "required elements")
        require(rules.categories, content.categories, "required categories")
        require([rules.min_realm], realm_ids, "required realm")
        if len(set(rules.elements)) != len(rules.elements) or len(set(rules.categories)) != len(rules.categories):
            raise ValueError("duplicate compatibility requirements")
        if not any(
            set(rules.elements).issubset(expand_elements(species.elements, content.elements))
            and (not rules.categories or species.category in rules.categories)
            for species in content.species.values()
        ):
            raise ValueError(f"no compatible species for {definition.id}")
    for skill in content.skills.values():
        if skill.element:
            require([skill.element], content.elements, "skill element")
            if skill.element not in expand_elements(skill.requirements.elements, content.elements):
                raise ValueError("skill element must be required by the skill")
        if skill.kind == "heal" and skill.coefficient > 1:
            raise ValueError("healing coefficient cannot exceed full health")
        require([skill.book_item], content.items, "skill book")
        book = content.items[skill.book_item]
        if book.kind != "skill_book" or book.skill_id != skill.id:
            raise ValueError("skill and book must reference each other")
    equipment_items = []
    for item in content.items.values():
        if item.equipment_id:
            require([item.equipment_id], content.equipment, "equipment item")
            equipment_items.append(item.equipment_id)
        if item.skill_id:
            require([item.skill_id], content.skills, "skill book target")
            if content.skills[item.skill_id].book_item != item.id:
                raise ValueError("skill book target does not point back")
        if item.species_id:
            require([item.species_id], content.species, "pet egg species")
    if set(equipment_items) != set(content.equipment):
        raise ValueError("all equipment needs an inventory item")
    if len(equipment_items) != len(set(equipment_items)):
        raise ValueError("equipment must have exactly one inventory item")
    for enemy in content.enemies.values():
        require(enemy.elements, content.elements, "enemy elements")
        if len(set(enemy.elements)) != len(enemy.elements):
            raise ValueError("duplicate enemy elements")
        if enemy.primary_element not in enemy.elements:
            raise ValueError("enemy primary element must belong to its elements")
        if enemy.signature_skill is not None:
            require([enemy.signature_skill], content.skills, "enemy signature skill")
            skill = content.skills[enemy.signature_skill]
            if skill.requirements.categories or not set(skill.requirements.elements).issubset(
                expand_elements(enemy.elements, content.elements)
            ):
                raise ValueError("enemy signature skill is incompatible with enemy elements")
    validate_pet_acquisition(content)


def validate_pet_acquisition(content):
    available_items = {item.id for item in content.items.values() if item.price is not None}
    available_items.update(content.rules.starter_items)
    for reward in (
        content.rules.daily_reward, *(quest.reward for quest in content.quests.values()),
        *(encounter.reward for encounter in content.encounters.values()),
        *(dungeon.reward for dungeon in content.dungeons.values()),
    ):
        available_items.update(item for item, amount in reward.items.items() if amount.maximum > 0)
    reachable = {pet.id for pet in content.species.values() if pet.starter}
    reachable.update(entry.species for entry in content.pools["standard"].entries)
    reachable.update(
        content.items[item].species_id for item in available_items
        if content.items[item].kind == "pet_egg"
    )
    missing = set(content.species) - reachable
    if missing:
        raise ValueError(f"pet species have no acquisition route: {sorted(missing)}")
