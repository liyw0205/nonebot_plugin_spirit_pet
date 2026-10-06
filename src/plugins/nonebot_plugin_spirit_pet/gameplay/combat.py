from dataclasses import dataclass

from ..content.catalog import Catalog
from ..domain.content import Stats
from ..domain.battle_content import Element, Skill
from ..domain.state import Pet


def pet_stats(pet: Pet, content: Catalog) -> Stats:
    multiplier = (
        content.realms[pet.realm].multiplier
        * content.layers[pet.layer].multiplier
        * content.bloodlines[pet.bloodline].multiplier
        * (1 + pet.affinity / 1000)
    )
    base = content.species[pet.species_id].stats
    return Stats(**{key: max(1, int(value * multiplier)) for key, value in base.model_dump().items()})


@dataclass
class Fighter:
    name: str
    stats: Stats
    hp: int
    elements: tuple[str, ...] = ()
    skills: tuple[Skill, ...] = ()
    actions: int = 0

    @classmethod
    def create(cls, name: str, stats: Stats, elements=(), skills=()):
        return cls(name, stats, stats.hp, elements, skills)


@dataclass(frozen=True)
class Battle:
    winner: int
    rounds: int
    lines: tuple[str, ...]


def fight(left: list[Fighter], right: list[Fighter], rng, elements: dict[str, Element] | None = None) -> Battle:
    """Custom bounded turn combat; health is local to a single encounter."""
    teams = (left, right)
    initiative = [(unit, side, rng.random()) for side, team in enumerate(teams) for unit in team]
    turns = sorted(initiative, key=lambda entry: (entry[0].stats.speed, entry[2]), reverse=True)
    log = []
    for round_number in range(1, 41):
        for unit, side, _ in turns:
            if unit.hp <= 0:
                continue
            targets = [enemy for enemy in teams[1 - side] if enemy.hp > 0]
            if not targets:
                return _result(side, round_number, teams, log)
            skill = unit.skills[unit.actions % len(unit.skills)] if unit.skills else None
            unit.actions += 1
            if skill and skill.kind == "heal" and unit.hp < unit.stats.hp:
                healing = min(unit.stats.hp - unit.hp, max(1, int(unit.stats.hp * skill.coefficient)))
                unit.hp += healing
                if len(log) < 6:
                    log.append(f"{unit.name}施展{skill.name}，恢复 {healing} 气血。")
                continue
            target = targets[rng.randint(0, len(targets) - 1)]
            power = skill.coefficient if skill and skill.kind == "damage" else 1
            element = skill.element if skill and skill.kind == "damage" else None
            factor = effectiveness(element, target.elements, elements or {})
            damage = max(1, int(unit.stats.attack * rng.randint(90, 110) / 100 * power * factor) - target.stats.defense)
            target.hp = max(0, target.hp - damage)
            if len(log) < 6:
                move = f"施展{skill.name}攻击" if skill and skill.kind == "damage" else "攻击"
                log.append(f"{unit.name}{move}{target.name}，造成 {damage} 伤害。")
            if not any(enemy.hp > 0 for enemy in teams[1 - side]):
                return _result(side, round_number, teams, log)
    return _result(-1, 40, teams, log)


def effectiveness(element: str | None, targets: tuple[str, ...], definitions: dict[str, Element]) -> float:
    if element is None:
        return 1.0
    strong = any(target in definitions[element].strong_against for target in targets)
    weak = any(element in definitions[target].strong_against for target in targets)
    return 1.0 if strong == weak else (1.25 if strong else 0.8)


def _result(winner, rounds, teams, log):
    remaining = tuple(
        f"{'我方' if side == 0 else '对方'} {unit.name}：气血 {unit.hp}/{unit.stats.hp}"
        for side, team in enumerate(teams) for unit in team
    )
    return Battle(winner, rounds, (*log, *remaining))
