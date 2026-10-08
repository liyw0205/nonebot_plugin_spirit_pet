from dataclasses import dataclass, field

from ..content.catalog import Catalog
from ..domain.content import Enemy, Stats
from ..domain.battle_content import Element, Skill, Talent
from ..domain.state import Pet
from ..utils.elements import element_ancestors
from . import effects, talents
from .effects import EffectState
from .lineage import stat_multipliers


def pet_stats(pet: Pet, content: Catalog) -> Stats:
    multiplier = (
        content.realms[pet.realm].multiplier
        * content.layers[pet.layer].multiplier
        * content.bloodlines[pet.bloodline].multiplier
        * (1 + pet.affinity / 1000)
    )
    base = content.species[pet.species_id].stats
    growth = stat_multipliers(pet, content).model_dump()
    return Stats(**{key: max(1, int(value * multiplier * growth[key])) for key, value in base.model_dump().items()})


@dataclass
class Fighter:
    name: str
    stats: Stats
    hp: int
    elements: tuple[str, ...] = ()
    skills: tuple[Skill, ...] = ()
    actions: int = 0
    primary_element: str | None = None
    pet_id: int | None = None
    talent: Talent | None = None
    skill_multipliers: dict[str, float] = field(default_factory=dict)
    skill_uses: dict[str, int] = field(default_factory=dict)
    attacks: int = 0
    shield: int = 0
    poison_damage: int = 0
    poison_turns: int = 0
    effects: EffectState = field(default_factory=EffectState)
    turns: int = 0
    resonance_name: str | None = None
    equipment_sets: tuple[str, ...] = ()
    skill_interval: int = 1
    affinity: int | None = None
    bond_protection_used: bool = False

    @classmethod
    def create(
        cls, name: str, stats: Stats, elements=(), skills=(), *, primary_element=None,
        pet_id=None, talent=None, skill_multipliers=None, resonance_name=None, skill_interval=1,
        affinity=None, equipment_sets=(),
    ):
        if type(skill_interval) is not int or skill_interval < 1:
            raise ValueError("skill interval must be a positive integer")
        if affinity is not None and (type(affinity) is not int or not 0 <= affinity <= 100):
            raise ValueError("affinity must be between 0 and 100")
        return cls(
            name, stats, stats.hp, tuple(elements), tuple(skills),
            primary_element=primary_element,
            pet_id=pet_id, talent=talent, skill_multipliers=dict(skill_multipliers or {}),
            resonance_name=resonance_name, equipment_sets=tuple(equipment_sets),
            skill_interval=skill_interval, affinity=affinity,
        )


def enemy_fighter(enemy: Enemy, skills: dict[str, Skill]) -> Fighter:
    signature = skills[enemy.signature_skill] if enemy.signature_skill else None
    return Fighter.create(
        enemy.name, enemy.stats, tuple(enemy.elements), (signature,) if signature else (),
        primary_element=enemy.primary_element,
        skill_interval=enemy.skill_every or 1,
    )


@dataclass(frozen=True)
class Battle:
    winner: int
    rounds: int
    lines: tuple[str, ...]
    skill_uses: tuple[dict[int, dict[str, int]], dict[int, dict[str, int]]]
    # Full event history is persisted in battle reports; old callers may still
    # construct Battle with the original four positional fields.
    history: tuple[str, ...] = ()


class _BattleLog(list[str]):
    """Keep a bounded display log and an unbounded (per encounter) history."""

    def __init__(self):
        super().__init__()
        self.history: list[str] = []


def fight(left: list[Fighter], right: list[Fighter], rng, elements: dict[str, Element] | None = None) -> Battle:
    """Custom bounded turn combat; health is local to a single encounter."""
    teams = (left, right)
    initiative = [(unit, side, rng.random()) for side, team in enumerate(teams) for unit in team]
    turns = sorted(initiative, key=lambda entry: (entry[0].stats.speed, entry[2]), reverse=True)
    log = _BattleLog()
    definitions = elements or {}
    for unit, _, _ in turns:
        event = talents.initialize(unit)
        if event:
            _record(log, event)
    for round_number in range(1, 41):
        for unit, side, _ in turns:
            if unit.hp <= 0:
                continue
            targets = [enemy for enemy in teams[1 - side] if enemy.hp > 0]
            if not targets:
                return _result(side, round_number, teams, log)
            unit.turns += 1
            _record(log, *talents.before_action(unit))
            if unit.hp > 0:
                if effects.skip_action(unit):
                    _record(log, f"{unit.name}受控无法行动，随后获得一次行动的免控。")
                else:
                    _act(unit, teams[side], targets, rng, definitions, log)
            effects.finish_action(unit)
            if not any(enemy.hp > 0 for enemy in teams[1 - side]):
                return _result(side, round_number, teams, log)
            if not any(ally.hp > 0 for ally in teams[side]):
                return _result(1 - side, round_number, teams, log)
    return _result(-1, 40, teams, log)


def _act(unit, allies, targets, rng, definitions, log):
    skill_due = unit.actions % unit.skill_interval == unit.skill_interval - 1
    skill = unit.skills[unit.actions % len(unit.skills)] if unit.skills and skill_due else None
    unit.actions += 1
    multiplier = unit.skill_multipliers.get(skill.id, 1) if skill else 1
    if skill and skill.targeting == "all":
        _attack_all(unit, skill, targets, rng, definitions, log, multiplier)
        return
    target = effects.enemy_target(skill, targets, multiplier, rng)
    planned = effects.plan(unit, skill, target, allies) if skill else ()
    if skill and skill.kind in {"heal", "utility"}:
        healing = (
            min(unit.stats.hp - unit.hp, max(1, int(unit.stats.hp * skill.coefficient * multiplier)))
            if skill.kind == "heal" else 0
        )
        if healing or planned:
            _cast(unit, skill)
            if any(effect.target == "enemy" for effect in skill.effects) and talents.evades(target, rng):
                _record(log, f"{target.name}以天赋{target.talent.name}闪避了{unit.name}的{skill.name}。")
                return
            unit.hp += healing
            detail = f"，恢复 {healing} 气血" if healing else ""
            _record(log, f"{unit.name}施展{skill.name}{detail}。", *effects.apply(unit, skill, planned))
            return
        skill = None
    power = skill.coefficient * multiplier if skill else 1
    element = skill.element if skill else unit.primary_element
    factor = effectiveness(element, target.primary_element, definitions)
    bonus, defense, talent_name = talents.attack_modifiers(unit, target, element, definitions)
    unit.attacks += 1
    if skill:
        _cast(unit, skill)
    if talents.evades(target, rng):
        _record(log, f"{target.name}以天赋{target.talent.name}闪避了{unit.name}的攻击。")
        return
    amount = max(1, int(effects.attack(unit) * rng.randint(90, 110) / 100 * power * factor * bonus) - defense)
    damage, absorbed = talents.receive_damage(target, amount)
    move = f"施展{skill.name}攻击" if skill else "攻击"
    details = f"，天赋{talent_name}" if talent_name else ""
    details += "，属性克制" if factor > 1 else ("，属性受克" if factor < 1 else "")
    details += f"，护盾吸收 {absorbed}" if absorbed else ""
    _record(log, f"{unit.name}{move}{target.name}，造成 {damage} 伤害{details}。")
    _record(log, *talents.after_hit(unit, target, damage))
    if skill:
        _record(log, *effects.apply(unit, skill, planned))


def _attack_all(unit, skill, targets, rng, definitions, log, multiplier):
    _cast(unit, skill)
    _record(log, f"{unit.name}施展{skill.name}，攻击全体存活敌人。")
    for target in targets:
        if target.hp <= 0:
            continue
        if talents.evades(target, rng):
            _record(log, f"{target.name}以天赋{target.talent.name}闪避了{unit.name}的{skill.name}。")
            continue
        factor = effectiveness(skill.element, target.primary_element, definitions)
        bonus, defense, talent_name = talents.attack_modifiers(unit, target, skill.element, definitions)
        amount = max(1, int(effects.attack(unit) * rng.randint(90, 110) / 100
                             * skill.coefficient * multiplier * factor * bonus) - defense)
        damage, absorbed = talents.receive_damage(target, amount)
        details = f"，天赋{talent_name}" if talent_name else ""
        details += "，属性克制" if factor > 1 else ("，属性受克" if factor < 1 else "")
        details += f"，护盾吸收 {absorbed}" if absorbed else ""
        _record(log, f"{unit.name}的{skill.name}命中{target.name}，造成 {damage} 伤害{details}。")
        _record(log, *talents.after_hit(unit, target, damage))
    unit.attacks += 1


def effectiveness(element: str | None, target: str | None, definitions: dict[str, Element]) -> float:
    if element is None or target is None or not definitions:
        return 1.0
    attack_elements = element_ancestors(element, definitions)
    defense_elements = element_ancestors(target, definitions)
    strong = any(defense_elements.intersection(definitions[key].strong_against) for key in attack_elements)
    weak = any(attack_elements.intersection(definitions[key].strong_against) for key in defense_elements)
    return 1.0 if strong == weak else (1.25 if strong else 0.8)


def _cast(unit: Fighter, skill: Skill):
    unit.skill_uses[skill.id] = unit.skill_uses.get(skill.id, 0) + 1


def _record(log: list[str], *events: str):
    if isinstance(log, _BattleLog):
        log.history.extend(events)
    log.extend(events[:max(0, 6 - len(log))])


def _result(winner, rounds, teams, log):
    remaining = tuple(
        f"{'我方' if side == 0 else '对方'} {unit.name}：气血 {unit.hp}/{unit.stats.hp}"
        for side, team in enumerate(teams) for unit in team
    )
    uses = tuple({unit.pet_id: dict(unit.skill_uses) for unit in team if unit.pet_id is not None} for team in teams)
    history = tuple(getattr(log, "history", log)) + remaining
    return Battle(winner, rounds, (*log, *remaining), uses, history)
