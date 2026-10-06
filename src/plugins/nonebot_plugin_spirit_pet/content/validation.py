def validate_battle_content(content):
    require = content._require
    realm_ids = {realm.id for realm in content.realms}
    for species in content.species.values():
        require([species.category], content.categories, "pet category")
        require(species.elements, content.elements, "pet elements")
        if len(set(species.elements)) != len(species.elements):
            raise ValueError("duplicate pet elements")
    for element in content.elements.values():
        require(element.strong_against, content.elements, "element relationships")
        if element.id in element.strong_against:
            raise ValueError("element cannot counter itself")
    for definition in (*content.equipment.values(), *content.skills.values()):
        rules = definition.requirements
        require(rules.elements, content.elements, "required elements")
        require(rules.categories, content.categories, "required categories")
        require([rules.min_realm], realm_ids, "required realm")
        if not any(
            set(rules.elements).issubset(species.elements)
            and (not rules.categories or species.category in rules.categories)
            for species in content.species.values()
        ):
            raise ValueError(f"no compatible species for {definition.id}")
    for skill in content.skills.values():
        if skill.element:
            require([skill.element], content.elements, "skill element")
            if skill.element not in skill.requirements.elements:
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
    if set(equipment_items) != set(content.equipment):
        raise ValueError("all equipment needs an inventory item")
    if len(equipment_items) != len(set(equipment_items)):
        raise ValueError("equipment must have exactly one inventory item")
    for enemy in content.enemies.values():
        require(enemy.elements, content.elements, "enemy elements")
    names = content.dao_names
    if len(set(names.prefixes)) != len(names.prefixes) or len(set(names.suffixes)) != len(names.suffixes):
        raise ValueError("duplicate dao name components")
