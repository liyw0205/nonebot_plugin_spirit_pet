import re

from ..domain.models import GameError


def quantity(value: str, maximum: int = 99) -> int:
    if len(value) > len(str(maximum)) or not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= maximum:
        raise GameError(f"数量须为 1-{maximum} 的整数。")
    return int(value)


def item_amount(argument: str) -> tuple[str, int]:
    parts = argument.split()
    if not 1 <= len(parts) <= 2:
        raise GameError("格式：道具名称 数量，例如 灵粮 3。")
    return parts[0], quantity(parts[1]) if len(parts) == 2 else 1


def named(entries: dict, value: str):
    item = entries.get(value)
    if item is None:
        item = next((entry for entry in entries.values() if entry.name == value), None)
    if item is None:
        raise GameError("未找到该内容，请检查名称或编号。")
    return item
