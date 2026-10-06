from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from ..domain.models import GameError
from .arguments import quantity

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    entries: tuple[T, ...]
    number: int
    total: int
    navigation: tuple[str, ...]


def paginate(entries: Iterable[T], argument: str, title: str, command: str, page_size: int = 5) -> Page[T]:
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page size must be a positive integer")
    values = tuple(entries)
    number = quantity(argument or "1", 999)
    total = max(1, (len(values) + page_size - 1) // page_size)
    if number > total:
        raise GameError(f"{title}共 {total} 页。")
    navigation = []
    if number > 1:
        navigation.append(f"{command} {number - 1}")
    if number < total:
        navigation.append(f"{command} {number + 1}")
    return Page(values[(number - 1) * page_size:number * page_size], number, total, tuple(navigation))
