from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from .rewards import grant
from .sweep import _cleared

PAGE_SIZE = 5
CLAIM_PREFIX = "journey_"


def claim_id(chapter_id: str) -> str:
    return CLAIM_PREFIX + chapter_id


def _claimed(ctx: Context, user_id: str, chapter_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(chapter_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def _realm_index(ctx: Context, realm_id: str) -> int:
    return next(index for index, realm in enumerate(ctx.content.realms) if realm.id == realm_id)


def _realm_name(ctx: Context, realm_id: str) -> str:
    return ctx.content.realms[_realm_index(ctx, realm_id)].name


def _task_text(ctx: Context, task) -> str:
    if task.kind == "clear_dungeon":
        return f"通关{ctx.content.dungeons[task.target].name}"
    if task.kind == "win_at":
        return f"在{ctx.content.dungeons[task.target].name}获胜 {task.count} 场"
    if task.kind == "discover":
        return f"发现奇闻「{ctx.content.encounters[task.target].name}」"
    if task.kind == "collect_species":
        return f"收得{ctx.content.species[task.target].name}"
    if task.kind == "enable_resonance":
        return f"启用共鸣「{ctx.content.resonances[task.target].name}」"
    return f"达到{_realm_name(ctx, task.target)}"


def _value(ctx: Context, user_id: str, task) -> int:
    """Chapter progress, always derived from permanent state."""
    conn = ctx.repo.conn
    if task.kind == "clear_dungeon":
        return 1 if _cleared(ctx, task.target) else 0
    if task.kind == "win_at":
        row = conn.execute(
            "SELECT COUNT(*) AS amount FROM battle_records b "
            "JOIN battle_participants p USING(battle_id) "
            "WHERE p.user_id=? AND b.kind='pve' AND b.battle_key=? AND b.winner_side=p.side",
            (user_id, task.target),
        ).fetchone()
        return int(row["amount"])
    if task.kind == "discover":
        row = conn.execute(
            "SELECT 1 FROM adventure_discoveries WHERE user_id=? AND encounter_id=?",
            (user_id, task.target),
        ).fetchone()
        return 1 if row else 0
    if task.kind == "collect_species":
        row = conn.execute(
            "SELECT 1 FROM pets WHERE user_id=? AND species_id=?", (user_id, task.target),
        ).fetchone()
        return 1 if row else 0
    if task.kind == "enable_resonance":
        row = conn.execute(
            "SELECT 1 FROM player_resonance WHERE user_id=? AND resonance_id=?",
            (user_id, task.target),
        ).fetchone()
        return 1 if row else 0
    best = conn.execute(
        "SELECT COALESCE(MAX(realm),-1) AS realm FROM pets WHERE user_id=?", (user_id,),
    ).fetchone()["realm"]
    return 1 if best >= _realm_index(ctx, task.target) else 0


def _state(ctx: Context, user_id: str, chapter) -> str:
    if _claimed(ctx, user_id, chapter.id):
        return "已完成"
    if chapter.previous_id is not None and not _claimed(ctx, user_id, chapter.previous_id):
        return "未解锁"
    value = _value(ctx, user_id, chapter.task)
    if value >= chapter.task.count:
        return "可领取"
    return f"进行中（{value}/{chapter.task.count}）"


def catalog(ctx: Context, arg: str) -> Reply:
    entries = tuple(ctx.content.journey.values())
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵宠行纪共 {pages} 页。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("山海行纪", (
            "行纪按境界分章，每章一个任务与一份一次性奖励；完成前置章节后解锁下一章。",
            f"共 {len(entries)} 章，从「{entries[0].name}」开始。",
            "尚未结契，先完成领养，再踏上行纪。",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    selected = entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = []
    links = []
    for chapter in selected:
        state = _state(ctx, player.user_id, chapter)
        lines.append(f"{chapter.name} · {_realm_name(ctx, chapter.realm)} · {state}")
        lines.append(chapter.story)
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 2, "领取本章奖励", f"灵宠行纪领奖 {chapter.name}",
            ))
    done = sum(1 for chapter in entries if _claimed(ctx, player.user_id, chapter.id))
    claimable = sum(1 for chapter in entries if _state(ctx, player.user_id, chapter) == "可领取")
    lines.append(f"共 {len(entries)} 章，已完成 {done} 章，尚有 {claimable} 章可领取。")
    commands = []
    if page > 1:
        commands.append(f"灵宠行纪 {page - 1}")
    if page < pages:
        commands.append(f"灵宠行纪 {page + 1}")
    commands.extend(("灵宠主线", "灵宠目标"))
    return Reply(f"山海行纪 {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    chapter = named(ctx.content.journey, arg)
    if _claimed(ctx, player.user_id, chapter.id):
        raise GameError(f"{chapter.name}的奖励已领取，不能重复领取。")
    if chapter.previous_id is not None and not _claimed(ctx, player.user_id, chapter.previous_id):
        raise GameError(f"请先完成前置章节：{ctx.content.journey[chapter.previous_id].name}。")
    value = _value(ctx, player.user_id, chapter.task)
    if value < chapter.task.count:
        raise GameError(
            f"本章尚未完成：{_task_text(ctx, chapter.task)}（{value}/{chapter.task.count}）。"
        )
    result = grant(ctx, chapter.reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
        (player.user_id, claim_id(chapter.id)),
    )
    following = [c for c in ctx.content.journey.values() if c.previous_id == chapter.id]
    hint = f"下一章「{following[0].name}」已解锁。" if following else "山海行纪已全部完成。"
    return Reply("行纪奖励已领取", (
        f"{chapter.name} · {chapter.story}", *result, hint,
    ), ("灵宠行纪", "灵宠主线", "灵宠目标"))
