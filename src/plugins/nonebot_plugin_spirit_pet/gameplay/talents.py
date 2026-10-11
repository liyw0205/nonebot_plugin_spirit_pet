from __future__ import annotations

from typing import TYPE_CHECKING

from ..utils.elements import element_ancestors
from . import effects

if TYPE_CHECKING:
    from ..domain.battle_content import Element
    from .combat import Fighter


def initialize(unit: Fighter) -> str | None:
    if unit.talent and unit.talent.kind == "shield":
        unit.shield = max(1, int(unit.stats.hp * unit.talent.power))
        return f"{unit.name}以天赋{unit.talent.name}凝聚 {unit.shield} 护盾。"
    return None


def before_action(unit: Fighter) -> tuple[str, ...]:
    events = []
    if unit.poison_turns:
        damage = min(unit.hp, unit.poison_damage)
        unit.hp -= damage
        unit.poison_turns -= 1
        if unit.poison_turns == 0:
            unit.poison_damage = 0
        events.append(f"{unit.name}受到毒伤 {damage}。")
    if unit.hp > 0 and unit.talent and unit.talent.kind == "regeneration":
        restored = min(unit.stats.hp - unit.hp, max(1, int(unit.stats.hp * unit.talent.power)))
        if restored:
            unit.hp += restored
            events.append(f"{unit.name}以天赋{unit.talent.name}恢复 {restored} 气血。")
    return tuple(events)


def attack_modifiers(
    unit: Fighter, target: Fighter, element: str | None, definitions: dict[str, Element],
) -> tuple[float, int, str | None]:
    multiplier = 1.0
    defense = target.stats.defense
    talent = unit.talent
    if talent is None:
        return multiplier, defense, None
    active = False
    if talent.kind == "fury":
        lineage = element_ancestors(element, definitions) if element and definitions else {element}
        active = talent.element is None or talent.element in lineage
    elif talent.kind == "first_strike":
        active = unit.attacks == 0
    elif talent.kind == "execute":
        active = target.hp <= target.stats.hp * 0.4
    elif talent.kind == "pierce":
        defense = int(defense * (1 - talent.power))
        return multiplier, defense, talent.name
    if active:
        multiplier += talent.power
    return multiplier, defense, talent.name if active else None


def evades(unit: Fighter, rng) -> bool:
    return bool(unit.talent and unit.talent.kind == "evasion" and rng.random() < unit.talent.power)


def receive_damage(unit: Fighter, amount: int) -> tuple[int, int]:
    temporary = effects.absorb_ward(unit, amount)
    permanent = min(unit.shield, amount - temporary)
    absorbed = temporary + permanent
    unit.shield -= permanent
    lost = min(unit.hp, amount - absorbed)
    unit.hp -= lost
    return lost, absorbed


def after_hit(unit: Fighter, target: Fighter, damage: int) -> tuple[str, ...]:
    """Only the original direct hit triggers talents; poison and counters never recurse."""
    if not damage:
        return ()
    events = []
    talent = unit.talent
    if unit.hp > 0 and talent and talent.kind == "lifesteal":
        healing = min(unit.stats.hp - unit.hp, max(1, int(damage * talent.power)))
        if healing:
            unit.hp += healing
            events.append(f"{unit.name}以天赋{talent.name}汲取 {healing} 气血。")
    if target.hp > 0 and talent and talent.kind == "venom":
        target.poison_damage = max(target.poison_damage, max(1, int(target.stats.hp * talent.power)))
        target.poison_turns = 3
        events.append(f"{unit.name}以天赋{talent.name}附毒，每次 {target.poison_damage}，持续三次行动。")
    retaliation = target.talent
    if target.hp > 0 and retaliation and retaliation.kind == "counter":
        amount = max(1, int(effects.attack(target) * retaliation.power) - unit.stats.defense // 2)
        lost, absorbed = receive_damage(unit, amount)
        blocked = f"，护盾吸收 {absorbed}" if absorbed else ""
        events.append(f"{target.name}以天赋{retaliation.name}反击 {unit.name}，造成 {lost} 伤害{blocked}。")
    return tuple(events)
