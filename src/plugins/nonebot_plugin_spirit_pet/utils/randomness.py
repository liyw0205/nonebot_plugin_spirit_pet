from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def weighted_choice(rng, values: Sequence[T], weights: Sequence[float]) -> T:
    if not values or len(values) != len(weights) or any(weight < 0 for weight in weights):
        raise ValueError("invalid weighted choice")
    total = sum(weights)
    if total <= 0:
        raise ValueError("weighted choice has no positive weight")
    needle = rng.random() * total
    for value, weight in zip(values, weights):
        needle -= weight
        if needle < 0:
            return value
    return values[-1]
