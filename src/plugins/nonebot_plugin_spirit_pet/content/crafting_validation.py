from ..domain.crafting_content import salvage_yield


def validate_crafting_content(content) -> None:
    equipment_items = {item.id for item in content.items.values() if item.kind == "equipment"}
    outputs = [recipe.item_id for recipe in content.recipes.values()]
    if len(set(outputs)) != len(outputs) or set(outputs) != equipment_items:
        raise ValueError("recipes must cover every equipment item exactly once")
    available = {key for key, item in content.items.items() if item.price is not None}
    available.update(content.rules.starter_items)
    rewards = (
        content.rules.daily_reward, *(quest.reward for quest in content.quests.values()),
        *(entry.reward for entry in content.encounters.values()),
        *(dungeon.reward for dungeon in content.dungeons.values()),
    )
    for reward in rewards:
        available.update(key for key, bounds in reward.items.items() if bounds.maximum > 0)
    forge_items = {key for level in content.forge_levels.values() for key in level.upgrade_items}
    for recipe in content.recipes.values():
        item = content.items[recipe.item_id]
        if recipe.name != item.name:
            raise ValueError("recipe names must match equipment item names")
        referenced = set(recipe.materials) | set(recipe.salvage_materials) | forge_items
        content._require(referenced, content.items, "crafting materials")
        if any(content.items[key].kind != "material" for key in referenced):
            raise ValueError("crafting and salvage ingredients must be materials")
        if not referenced <= available:
            raise ValueError("crafting materials must have a non-salvage acquisition source")
        invested = dict(recipe.materials)
        stones = recipe.stones
        purchase_cost = item.price
        for level in sorted(content.forge_levels):
            if level:
                previous = content.forge_levels[level - 1]
                stones += previous.upgrade_stones
                if purchase_cost is not None:
                    purchase_cost += previous.upgrade_stones
                for key, amount in previous.upgrade_items.items():
                    invested[key] = invested.get(key, 0) + amount
                    price = content.items[key].price
                    purchase_cost = None if price is None or purchase_cost is None else purchase_cost + amount * price
            returned = salvage_yield(recipe, content.forge_levels, level)
            if any(amount > invested.get(key, 0) for key, amount in returned.items()) or all(
                returned.get(key, 0) == amount for key, amount in invested.items()
            ):
                raise ValueError("salvage must return strictly fewer materials than invested")
            if all(content.items[key].price is not None for key in returned):
                refund_value = sum(amount * content.items[key].price for key, amount in returned.items())
                if purchase_cost is not None and refund_value > purchase_cost:
                    raise ValueError("buying and salvaging equipment cannot yield cheaper materials")
                if all(content.items[key].price is not None for key in invested):
                    crafting_cost = stones + sum(amount * content.items[key].price for key, amount in invested.items())
                    if refund_value >= crafting_cost:
                        raise ValueError("crafting and salvaging must have a positive resource sink")
