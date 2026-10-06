from ..application.context import Context
from ..domain.models import GameError, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from .compatibility import check_requirements, requirement_text
from .mastery import progress, progress_text


def learned(ctx: Context, pet_id: int) -> dict[str, int]:
    return dict(ctx.repo.conn.execute(
        "SELECT skill_id, equipped FROM learned_skills WHERE pet_id=? ORDER BY skill_id", (pet_id,),
    ))


def view(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    skills = learned(ctx, pet.pet_id)
    mastery = progress(ctx, pet.pet_id)
    lines = tuple(
        f"{ctx.content.skills[key].name} · {progress_text(ctx, *mastery[key])}"
        f" · {'已携带' if active else '未携带'}"
        for key, active in skills.items()
    ) or ("尚未学习灵术。",)
    return Reply(f"{pet.name}的技能", (*lines, f"携带上限：{ctx.content.rules.max_skill_slots} 个。"),
                 ("灵宠技能图鉴", "灵宠商店"))


def catalog(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        skill = named(ctx.content.skills, arg)
        book = ctx.content.items[skill.book_item]
        commands = [f"灵宠学习 {skill.name}"]
        if book.price is not None:
            commands.append(f"灵宠商店 {book.name}")
        return Reply(f"万法灵谱 · {skill.name}", (
            skill.description, f"适用：{requirement_text(ctx, skill.requirements)}。",
            f"学习秘笈：{book.name}。",
        ), (*commands, "灵宠技能图鉴", "灵宠技能"))
    page = paginate(ctx.content.skills.values(), arg, "万法灵谱", "灵宠技能图鉴")
    return Reply(f"万法灵谱 {page.number}/{page.total}", tuple(
        f"{skill.name}：{skill.description} · {requirement_text(ctx, skill.requirements)}"
        f" · 需 {ctx.content.items[skill.book_item].name}"
        for skill in page.entries
    ), (*(f"灵宠技能图鉴 {skill.name}" for skill in page.entries), *page.navigation, "灵宠技能"))


def learn(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    skill = named(ctx.content.skills, arg)
    check_requirements(ctx, pet, skill.requirements)
    current = learned(ctx, pet.pet_id)
    if skill.id in current:
        raise GameError("该宠物已经学会此技能，不会重复消耗秘笈。")
    ctx.repo.consume_item(ctx.user_id, skill.book_item, 1)
    active = int(sum(current.values()) < ctx.content.rules.max_skill_slots)
    ctx.repo.conn.execute(
        "INSERT INTO learned_skills(pet_id, skill_id, equipped) VALUES (?, ?, ?)",
        (pet.pet_id, skill.id, active),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("领悟灵术", (
        f"{pet.name}学会了{skill.name}，消耗 {ctx.content.items[skill.book_item].name} 1 本。",
        "已自动携带。" if active else "携带位已满，本技能已学会但未携带。",
    ))


def equip(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    skill = named(ctx.content.skills, arg)
    check_requirements(ctx, pet, skill.requirements)
    current = learned(ctx, pet.pet_id)
    if skill.id not in current:
        raise GameError("当前宠物尚未学会该技能。")
    if current[skill.id]:
        raise GameError("该技能已携带。")
    if sum(current.values()) >= ctx.content.rules.max_skill_slots:
        raise GameError("技能位已满，请先卸下一个技能。")
    ctx.repo.conn.execute(
        "UPDATE learned_skills SET equipped=1 WHERE pet_id=? AND skill_id=?", (pet.pet_id, skill.id),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("携带灵术", (f"{pet.name}已携带{skill.name}。",))


def unequip(ctx: Context, arg: str) -> Reply:
    pet = ctx.pet()
    skill = named(ctx.content.skills, arg)
    if not learned(ctx, pet.pet_id).get(skill.id):
        raise GameError("当前宠物未携带该技能。")
    ctx.repo.conn.execute(
        "UPDATE learned_skills SET equipped=0 WHERE pet_id=? AND skill_id=?", (pet.pet_id, skill.id),
    )
    ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("卸下灵术", (f"已卸下{skill.name}，仍保留学习记录。",))
