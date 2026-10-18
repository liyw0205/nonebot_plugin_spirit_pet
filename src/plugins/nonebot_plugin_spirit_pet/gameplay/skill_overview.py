from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from .mastery import progress_text

PAGE_SIZE = 6


def _rows(ctx: Context, user_id: str):
    skill_ids = tuple(ctx.content.skills)
    if not skill_ids:
        return ()
    placeholders = ",".join("?" for _ in skill_ids)
    return ctx.repo.conn.execute(
        "SELECT s.skill_id AS skill_id, COUNT(*) AS learners, MAX(s.level) AS max_level, "
        "SUM(s.proficiency) AS total_proficiency "
        "FROM learned_skills s JOIN pets p USING(pet_id) "
        "WHERE p.user_id=? AND s.skill_id IN (" + placeholders + ") "
        "GROUP BY s.skill_id",
        (user_id, *skill_ids),
    ).fetchall()


def _learner_rows(ctx: Context, user_id: str, skill_id: str):
    return ctx.repo.conn.execute(
        "SELECT p.pet_id AS pet_id, p.name AS name, p.realm AS realm, p.layer AS layer, "
        "p.archived AS archived, s.level AS level, s.proficiency AS proficiency, "
        "s.equipped AS equipped "
        "FROM learned_skills s JOIN pets p USING(pet_id) "
        "WHERE p.user_id=? AND s.skill_id=? "
        "ORDER BY p.realm DESC, p.layer DESC, p.pet_id ASC",
        (user_id, skill_id),
    ).fetchall()


def catalog(ctx: Context, arg: str) -> Reply:
    value = arg.strip()
    if value and not value.isdecimal():
        return detail(ctx, value)
    page = quantity(value or "1", 999999)
    player = ctx.repo.player(ctx.user_id)
    title = "万法总览"
    if player is None:
        return Reply(title, (
            "万法总览按灵术汇总你全部伙伴的修习进度，封存伙伴也计入。",
            "尚未结契，先完成领养，学习灵术后这里会汇总修习情况。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    rows = {row["skill_id"]: row for row in _rows(ctx, player.user_id)}
    skills = tuple(ctx.content.skills.values())
    pages = max(1, (len(skills) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"万法总览共 {pages} 页。")
    selected = skills[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines, links = [], []
    for skill in selected:
        row = rows.get(skill.id)
        if row is None:
            lines.append(f"{skill.name} · 尚未修习")
        else:
            lines.append(
                f"{skill.name} · 修习 {row['learners']} 宠 · 最高 {row['max_level']} 级"
                f" · 总熟练度 {row['total_proficiency']}"
            )
        links.append(InlineCommand(len(lines) - 1, "查看修习", f"灵宠万法总览 {skill.name}"))
    commands = [link.command for link in links]
    if page > 1:
        commands.append(f"灵宠万法总览 {page - 1}")
    if page < pages:
        commands.append(f"灵宠万法总览 {page + 1}")
    commands.extend(("灵宠技能图鉴", "灵宠灵术赏"))
    return Reply(f"{title} {page}/{pages}", tuple(lines), tuple(commands), tuple(links))


def detail(ctx: Context, arg: str) -> Reply:
    skill = named(ctx.content.skills, arg)
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        raise GameError("尚未结契，先完成领养再查看灵术修习。")
    learners = _learner_rows(ctx, player.user_id, skill.id)
    if not learners:
        raise GameError(f"还没有伙伴修习{skill.name}；可先在 灵宠技能图鉴 查看学习条件。")
    lines = [f"{skill.name} · 共 {len(learners)} 位伙伴修习。"]
    for row in learners:
        suffix = "（封存）" if row["archived"] else ""
        lines.append(
            f"{row['name']}（编号 {row['pet_id']}）{suffix} · "
            f"{progress_text(ctx, row['level'], row['proficiency'])} · "
            f"{'已携带' if row['equipped'] else '未携带'}"
        )
    return Reply(f"万法总览 · {skill.name}", tuple(lines), (
        f"灵宠技能图鉴 {skill.name}", "灵宠万法总览", "灵宠灵术赏",
    ), (
        InlineCommand(0, "查看灵术图鉴", f"灵宠技能图鉴 {skill.name}"),
        InlineCommand(0, "查看灵术赏", "灵宠灵术赏"),
    ))
