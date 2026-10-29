"""Pet tempering: spend same-species eggs and stones to add permanent stat layers.

Each layer is a flat percentage on all four stats and is stored per pet in
``quest_progress`` as ``temper_<pet_id>`` (progress = layers), so no schema change is
needed. ``loadout.combatant`` applies the multiplier right after the sect passive.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply

LAYER_KEY = "temper_"


def max_layers(ctx: Context) -> int:
    return ctx.content.rules.temper.max_layers


def rate(ctx: Context) -> float:
    return ctx.content.rules.temper.rate


def layers_of(ctx: Context, pet_id: int, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, f"{LAYER_KEY}{pet_id}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def egg_id(ctx: Context, species_id: str) -> str:
    return f"egg_{species_id}"


def _owned(ctx: Context, item_id: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?",
        (user_id or ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _pets(ctx: Context):
    return sorted(ctx.repo.owned_pets(ctx.user_id), key=lambda pet: pet.pet_id)


def _lookup(ctx: Context, name: str):
    row = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND name=? ORDER BY pet_id LIMIT 1",
        (ctx.user_id, name),
    ).fetchone()
    return None if row is None else ctx.repo.pet(int(row["pet_id"]))


def _bonus(ctx: Context, layers: int) -> str:
    return f"+{layers * rate(ctx):.0%}"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠淬魂 <宠物名> [层数]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠淬魂",
            (
                "尚未结契，先完成领养，才能为伙伴淬魂。",
                "淬魂消耗该族灵卵与灵石，每层让伙伴的全属性永久 +1%，最多 10 层。",
                "灵卵来自培育与秘境掉落；淬魂只作用于选中的那一只伙伴。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    player = ctx.player()
    cap = max_layers(ctx)
    stones_per = ctx.content.rules.temper.stones_per_layer
    lines = [f"淬魂：每层全属性 +{rate(ctx):.0%}，最多 {cap} 层；每层 {stones_per} 灵石与 1 枚同族灵卵。"]
    links = []
    for pet in _pets(ctx):
        layers = layers_of(ctx, pet.pet_id)
        egg = egg_id(ctx, pet.species_id)
        eggs = _owned(ctx, egg)
        name = ctx.content.items[egg].name
        if layers >= cap:
            lines.append(f"{pet.name} · {layers} 层（{_bonus(ctx, layers)}）· 已满，无需再淬。")
            continue
        lines.append(
            f"{pet.name} · {layers} 层（{_bonus(ctx, layers)}）· {name} {eggs} 枚"
            f" · 下一层 灵石 {stones_per} + {name} 1"
        )
        if eggs > 0 and player.stones >= stones_per:
            links.append(InlineCommand(len(lines) - 1, "淬魂", f"灵宠淬魂 {pet.name}"))
    if not _pets(ctx):
        lines.append("当前没有可淬魂的伙伴。")
    lines.append("淬魂会改变伙伴属性，也会取消组队准备；层数不可回退或转移。")
    return Reply("灵宠淬魂", tuple(lines), ("灵宠淬魂", "我的灵宠", "灵宠背包"), tuple(links))


def temper(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    parts = arg.split()
    count = 1
    if parts and parts[-1].isdecimal():
        count = int(parts[-1])
        parts = parts[:-1]
    name = " ".join(parts).strip()
    if not name:
        raise GameError("格式：灵宠淬魂 <宠物名> [层数]。")
    pet = _lookup(ctx, name)
    if pet is None:
        raise GameError(f"没有找到名为{name}的伙伴。")
    if pet.archived:
        raise GameError(f"{pet.name}已封存，无法淬魂。")
    ctx.require_idle_pet(pet)
    cap = max_layers(ctx)
    layers = layers_of(ctx, pet.pet_id)
    if layers >= cap:
        raise GameError(f"{pet.name}已淬满 {cap} 层。")
    remaining = cap - layers
    if count < 1 or count > remaining:
        raise GameError(f"{pet.name}最多还能淬 {remaining} 层，本次请求 {count} 层。")

    stones = count * ctx.content.rules.temper.stones_per_layer
    egg = egg_id(ctx, pet.species_id)
    eggs = _owned(ctx, egg)
    if player.stones < stones:
        raise GameError(f"灵石不足：淬 {count} 层需要 {stones}，当前 {player.stones}。")
    if eggs < count:
        raise GameError(f"{ctx.content.items[egg].name}不足：需要 {count} 枚，当前 {eggs} 枚。")

    player.stones -= stones
    ctx.repo.consume_item(ctx.user_id, egg, count)
    after = layers + count
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{LAYER_KEY}{pet.pet_id}", after),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    lines = [
        f"{pet.name} 淬魂 +{count} 层：{layers} → {after} 层，全属性 {_bonus(ctx, after)}。",
        f"灵石 -{stones}，{ctx.content.items[egg].name} -{count}（剩余 {eggs - count} 枚）。",
    ]
    if after >= cap:
        lines.append(f"已淬满 {cap} 层。")
    return Reply("灵宠淬魂", tuple(lines), ("灵宠淬魂", "我的灵宠", "灵宠背包"))


def dispatch(ctx: Context, arg: str) -> Reply:
    if not arg.strip():
        return page(ctx, "")
    return temper(ctx, arg)


def objective_line(ctx: Context, user_id: str) -> str:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user_id or ctx.user_id, f"{LAYER_KEY}%"),
    )
    values = [int(row["progress"]) for row in rows]
    return f"淬魂：累计 {sum(values)} 层 · 最高 {max(values, default=0)} 层"
