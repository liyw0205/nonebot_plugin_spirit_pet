"""Fate arcs: three-chapter stories where each chapter offers two rewarding choices.

State lives in the existing ``quest_progress`` table:

* ``arc_<id>_step`` — next chapter to read (1-based; length+1 means the story is finished)
* ``arc_<id>_pick_<chapter>`` — 1-based index of the option taken in that chapter
* ``arc_<id>_done`` — 1 once the finale reward has been paid
"""

from ..application.context import Context
from ..domain.arc_content import Arc, ArcOption
from ..domain.models import GameError, InlineCommand, Reply

STEP = "arc_"
PICK = "_pick_"
DONE = "_done"


def arcs(ctx: Context) -> list[Arc]:
    return sorted(ctx.content.arcs.values(), key=lambda arc: arc.order)


def _progress(ctx: Context, key: str, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _set(ctx: Context, key: str, value: int, user_id: str | None = None) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user_id or ctx.user_id, key, value),
    )


def step_of(ctx: Context, arc: Arc, user_id: str | None = None) -> int:
    return _progress(ctx, f"{STEP}{arc.id}_step", user_id) or 1


def done(ctx: Context, arc: Arc, user_id: str | None = None) -> bool:
    return bool(_progress(ctx, f"{STEP}{arc.id}{DONE}", user_id))


def pick_of(ctx: Context, arc: Arc, chapter: int, user_id: str | None = None) -> int:
    return _progress(ctx, f"{STEP}{arc.id}{PICK}{chapter}", user_id)


def _realm_index(ctx: Context, realm_id: str) -> int:
    return next(index for index, realm in enumerate(ctx.content.realms) if realm.id == realm_id)


def unlock_reason(ctx: Context, arc: Arc, user_id: str | None = None) -> str | None:
    """None when the arc can be entered, otherwise the reason it cannot."""
    if arc.requires is not None:
        previous = ctx.content.arcs[arc.requires]
        if not done(ctx, previous, user_id):
            return f"需先完成{previous.name}"
    minimum = _realm_index(ctx, arc.min_realm)
    best = max((pet.realm for pet in ctx.repo.owned_pets(user_id or ctx.user_id)), default=-1)
    if best < minimum:
        return f"需要{ctx.content.realms[minimum].name}伙伴"
    return None


def _state(ctx: Context, arc: Arc) -> str:
    if done(ctx, arc):
        return "已完成"
    if step_of(ctx, arc) > 1:
        return f"进行中 · 第 {step_of(ctx, arc)}/{arc.length} 章"
    reason = unlock_reason(ctx, arc)
    return f"未开启（{reason}）" if reason else "可开启"


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠奇缘 [奇缘名] [选项]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠奇缘",
            (
                "尚未结契，先完成领养，才能走进这些故事。",
                "三条奇缘各分三章，每章两个选项，选择会立刻带来不同的收获。",
                "后一条奇缘需要先完成前一条，并对伙伴境界有要求。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    lines = [f"奇缘：已完成 {sum(1 for arc in arcs(ctx) if done(ctx, arc))}/{len(arcs(ctx))} 条。"]
    links = []
    for arc in arcs(ctx):
        lines.append(f"{arc.name} · {_state(ctx, arc)} · {ctx.content.realms[_realm_index(ctx, arc.min_realm)].name}起")
        if not done(ctx, arc) and unlock_reason(ctx, arc) is None:
            links.append(InlineCommand(len(lines) - 1, "进入", f"灵宠奇缘 {arc.name}"))
    lines.append("每条奇缘三章，每章两个选项；通关后不可重走。")
    return Reply("灵宠奇缘", tuple(lines), ("灵宠奇缘", "灵宠目标", "灵宠奇遇"), tuple(links))


def _reward_text(ctx: Context, reward) -> str:
    parts = []
    if reward.exp.maximum:
        parts.append(f"修为 {reward.exp.minimum}")
    if reward.stones.maximum:
        parts.append(f"灵石 {reward.stones.minimum}")
    parts.extend(
        f"{ctx.content.items[item_id].name} {bounds.minimum}"
        for item_id, bounds in reward.items.items()
    )
    return " · ".join(parts) if parts else "无额外收获"


def detail(ctx: Context, arc: Arc) -> Reply:
    reason = unlock_reason(ctx, arc)
    if reason is not None:
        raise GameError(f"{arc.name}尚未开启：{reason}。")
    if done(ctx, arc):
        raise GameError(f"{arc.name}已完成，无法重走。")
    current = step_of(ctx, arc)
    if current > arc.length:
        raise GameError(f"{arc.name}已完成，无法重走。")
    chapter = arc.chapters[current - 1]
    lines = [f"{arc.name} · 第 {current}/{arc.length} 章", chapter.title, chapter.text]
    links = []
    for option in chapter.options:
        lines.append(f"{option.label}：{option.text} · 奖励 {_reward_text(ctx, option.reward)}")
        links.append(InlineCommand(len(lines) - 1, option.label, f"灵宠奇缘 {arc.name} {option.label}"))
    return Reply(f"{arc.name}", tuple(lines), ("灵宠奇缘", "灵宠目标"), tuple(links))


def _pay(ctx: Context, reward, lines: list[str]) -> None:
    player = ctx.player()
    stones = ctx.rng.randint(reward.stones.minimum, reward.stones.maximum)
    exp = ctx.rng.randint(reward.exp.minimum, reward.exp.maximum)
    player.stones += stones
    parts = []
    if stones:
        parts.append(f"灵石 +{stones}")
    if exp:
        if player.active_pet_id is not None:
            ctx.repo.pet(player.active_pet_id).exp += exp
        parts.append(f"修为 +{exp}")
    for item_id, bounds in reward.items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        if amount:
            ctx.repo.add_item(ctx.user_id, item_id, amount)
            parts.append(f"{ctx.content.items[item_id].name} +{amount}")
    lines.append("获得：" + ("，".join(parts) if parts else "无额外收获"))


def choose(ctx: Context, arc: Arc, text: str) -> Reply:
    reason = unlock_reason(ctx, arc)
    if reason is not None:
        raise GameError(f"{arc.name}尚未开启：{reason}。")
    if done(ctx, arc):
        raise GameError(f"{arc.name}已完成，无法重走。")
    current = step_of(ctx, arc)
    if current > arc.length:
        raise GameError(f"{arc.name}已完成，无法重走。")
    chapter = arc.chapters[current - 1]
    option: ArcOption | None = next(
        (item for item in chapter.options if item.label == text or item.id == text), None,
    )
    if option is None:
        raise GameError(f"{arc.name}第 {current} 章没有该选项：{text}。")

    lines = [f"{arc.name} · 第 {current} 章 · {chapter.title}", option.text]
    _pay(ctx, option.reward, lines)
    _set(ctx, f"{STEP}{arc.id}{PICK}{current}", chapter.options.index(option) + 1)
    _set(ctx, f"{STEP}{arc.id}_step", current + 1)

    if current >= arc.length:
        _set(ctx, f"{STEP}{arc.id}{DONE}", 1)
        lines.append(f"【{arc.name} · 终章】{arc.finale.text}")
        _pay(ctx, arc.finale.reward, lines)
        return Reply(f"{arc.name} · 完", tuple(lines), ("灵宠奇缘", "灵宠目标", "我的灵宠"))

    following = arc.chapters[current]
    lines.append(f"下一章：{following.title}（灵宠奇缘 {arc.name} 继续）。")
    return Reply(f"{arc.name} · 第 {current} 章", tuple(lines), ("灵宠奇缘", "灵宠目标"))


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    arc = next((item for item in arcs(ctx) if item.name == parts[0] or item.id == parts[0]), None)
    if arc is None:
        raise GameError("未找到该奇缘，先发送 灵宠奇缘 查看列表。")
    if len(parts) == 1:
        return detail(ctx, arc)
    return choose(ctx, arc, " ".join(parts[1:]))


def objective_line(ctx: Context, user_id: str) -> str:
    completed = sum(1 for arc in arcs(ctx) if done(ctx, arc, user_id))
    active = next(
        (arc for arc in arcs(ctx) if not done(ctx, arc, user_id) and step_of(ctx, arc, user_id) > 1),
        None,
    )
    if active is not None:
        return f"奇缘：已完成 {completed}/{len(arcs(ctx))} · 进行中 {active.name}"
    return f"奇缘：已完成 {completed}/{len(arcs(ctx))} · 尚未开启"
