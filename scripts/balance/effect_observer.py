from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from unittest.mock import patch

from nonebot_plugin_spirit_pet.gameplay import effects


def _snapshot(kind, unit):
    state = unit.effects
    if kind in {"weaken", "empower", "ward"}:
        value = getattr(state, kind)
        return asdict(value) if value else None
    if kind == "stun":
        return state.stunned
    if kind == "cleanse":
        return (unit.poison_damage, unit.poison_turns, _snapshot("weaken", unit), state.stunned)
    return (unit.shield, _snapshot("ward", unit), _snapshot("empower", unit))


@contextmanager
def observe_effects():
    """Scoped single-process instrumentation; count actual state changes, not planned casts."""
    actual = Counter()
    original = effects.apply

    def observed(unit, skill, planned):
        unique = {(id(target), effect.kind): (effect.kind, target) for effect, target in planned}
        before = {key: _snapshot(kind, target) for key, (kind, target) in unique.items()}
        events = original(unit, skill, planned)
        if events:
            for key, (kind, target) in unique.items():
                if before[key] != _snapshot(kind, target):
                    actual[(skill.id, kind)] += 1
        return events

    with patch.object(effects, "apply", observed):
        yield actual
