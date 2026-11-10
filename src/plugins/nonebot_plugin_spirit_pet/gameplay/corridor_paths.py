"""Five-floor choices and permanent receipts for non-battle corridor actions."""

from hashlib import sha256

from ..application.context import Context
from ..domain.corridor_content import Corridor, CorridorPath
from ..domain.models import GameError

PATH_PREFIX = "corridor_path_"
RECEIPT_PREFIX = "corridor_receipt_"
SEGMENT_SIZE = 5
SNAPSHOT_FIELDS = ("energy", "hp_percent", "attack_percent", "speed_percent", "reward_percent")


def segment_start(floor: int) -> int:
    return (floor - 1) // SEGMENT_SIZE * SEGMENT_SIZE + 1


def current(ctx: Context, entry: Corridor, floor: int, user_id: str | None = None) -> CorridorPath:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (user_id or ctx.user_id, len(PATH_PREFIX), PATH_PREFIX),
    ).fetchall()
    values = {row["quest_id"][len(PATH_PREFIX):]: row["progress"] for row in rows}
    if values.get("start") != segment_start(floor):
        return CorridorPath(id="common", name="常道", energy=entry.energy)
    identities = [key[3:] for key in values if key.startswith("id_")]
    if len(identities) != 1 or any(field not in values for field in SNAPSHOT_FIELDS):
        raise GameError("回廊路线记录不完整，请联系管理员检查。")
    identity = identities[0]
    name = next((path.name for path in entry.paths if path.id == identity), identity)
    return CorridorPath(id=identity, name=name, **{field: values[field] for field in SNAPSHOT_FIELDS})


def describe(path: CorridorPath) -> str:
    return (
        f"{path.name} · 每宠精力 {path.energy}"
        f" · 敌气血 {path.hp_percent}% / 攻击 {path.attack_percent}% / 速度 {path.speed_percent}%"
        f" · 灵石与修为 {path.reward_percent}%"
    )


def save(ctx: Context, floor: int, path: CorridorPath) -> None:
    clear(ctx)
    values = {"start": floor, f"id_{path.id}": 1}
    values.update({field: getattr(path, field) for field in SNAPSHOT_FIELDS})
    ctx.repo.conn.executemany(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        [(ctx.user_id, f"{PATH_PREFIX}{key}", value) for key, value in values.items()],
    )


def clear(ctx: Context) -> None:
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(PATH_PREFIX), PATH_PREFIX),
    )


def _receipt_key(ctx: Context) -> str:
    return RECEIPT_PREFIX + sha256(ctx.operation_id.encode()).hexdigest()


def check_receipt(ctx: Context) -> None:
    if ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _receipt_key(ctx)),
    ).fetchone():
        raise GameError("该回廊消息已处理，请重新打开 灵宠回廊。")


def mark_receipt(ctx: Context, floor: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (ctx.user_id, _receipt_key(ctx), floor),
    )
