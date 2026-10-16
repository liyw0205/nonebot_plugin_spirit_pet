import re

from ..application.context import Context
from ..domain.content import Range, Reward
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.pagination import paginate
from .mastery import progress_text
from .rewards import grant

CLAIM_PREFIX = "skill_mastery_reward_"
PAGE_SIZE = 5
REWARD_STONES = 120


def claim_id(pet_id: int, skill_id: str) -> str:
    return f"{CLAIM_PREFIX}{pet_id}_{skill_id}"


def claimed(ctx: Context, user_id: str, pet_id: int, skill_id: str) -> bool:
    row = ctx.repo.conn.execute(
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id, claim_id(pet_id, skill_id)),
    ).fetchone()
    return bool(row and row["claimed"])


def claim_count(ctx: Context, user_id: str) -> int:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND claimed=1 "
        "AND substr(quest_id, 1, ?) = ?",
        (user_id, len(CLAIM_PREFIX), CLAIM_PREFIX),
    ).fetchall()
    pattern = re.compile(r"[1-9][0-9]*_[a-z][a-z0-9_]{0,39}")
    return sum(
        re.fullmatch(pattern, row["quest_id"][len(CLAIM_PREFIX):]) is not None
        for row in rows
    )


def _rows(ctx: Context, user_id: str):
    return ctx.repo.conn.execute(
        "SELECT p.pet_id, p.name AS pet_name, p.archived, s.skill_id, s.level, s.proficiency "
        "FROM pets p JOIN learned_skills s ON s.pet_id=p.pet_id "
        "WHERE p.user_id=? ORDER BY p.pet_id, s.skill_id",
        (user_id,),
    ).fetchall()


def _max_level(ctx: Context) -> int:
    return max(ctx.content.skill_levels)


def _book_status(ctx: Context, skill_id: str) -> tuple[str, str, str | None]:
    skill = ctx.content.skills.get(skill_id)
    if skill is None:
        return f"技能 {skill_id}", "技能定义缺失", None
    item = ctx.content.items.get(skill.book_item)
    if item is None or item.kind != "skill_book" or item.skill_id != skill_id:
        return skill.name, "奖励秘笈定义缺失", None
    return skill.name, f"奖励：灵石 {REWARD_STONES}、{item.name} 1", item.name


def catalog(ctx: Context, arg: str) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠灵术赏 1/1", ("尚未结契，先完成领养，再培养伙伴的灵术。",),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    entries = _rows(ctx, player.user_id)
    page = paginate(entries, arg, "灵宠灵术赏", "灵宠灵术赏", PAGE_SIZE)
    lines, links = [], []
    maximum = _max_level(ctx)
    for row in page.entries:
        skill_name, reward, book_name = _book_status(ctx, row["skill_id"])
        pet_state = " · 已封存" if row["archived"] else ""
        valid_level = row["level"] in ctx.content.skill_levels
        progress = (
            "修习数据异常" if not valid_level else
            "五阶精通" if row["level"] == maximum else
            progress_text(ctx, row["level"], row["proficiency"])
        )
        if not valid_level:
            state = "需检查存档"
        elif row["level"] == maximum:
            state = "已领取" if claimed(ctx, player.user_id, row["pet_id"], row["skill_id"]) else "可领取"
        else:
            state = "修习中"
        if book_name is None and state == "可领取":
            state = "奖励待修复"
        lines.append(
            f"灵宠 {row['pet_id']} · {row['pet_name']}{pet_state} · {skill_name} · "
            f"{progress} · {reward} · {state}"
        )
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取精进奖励",
                f"灵宠灵术领奖 {row['pet_id']} {skill_name}",
            ))

    if not entries:
        lines.append("尚未学习灵术。")
    lines.append(f"五阶精通奖励已领取 {claim_count(ctx, player.user_id)} 项。")
    commands = [*page.navigation, "灵宠技能", "灵宠目标"]
    return Reply(f"灵宠灵术赏 {page.number}/{page.total}", tuple(lines), tuple(commands), tuple(links))


def claim(ctx: Context, arg: str) -> Reply:
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        raise GameError("格式：灵宠灵术领奖 宠物编号 技能名。")
    pet_id = quantity(parts[0], 9_223_372_036_854_775_807)
    skill = next((entry for entry in ctx.content.skills.values() if entry.name == parts[1]), None)
    if skill is None:
        raise GameError("未找到该灵术，请检查名称。")

    player = ctx.player()
    row = ctx.repo.conn.execute(
        "SELECT p.name AS pet_name, s.level FROM pets p "
        "JOIN learned_skills s ON s.pet_id=p.pet_id "
        "WHERE p.user_id=? AND p.pet_id=? AND s.skill_id=?",
        (player.user_id, pet_id, skill.id),
    ).fetchone()
    if row is None:
        raise GameError("没有这只属于你的已学灵术的灵宠。")
    if row["level"] not in ctx.content.skill_levels:
        raise GameError("该灵宠的灵术等级记录异常，请联系管理员检查存档。")
    if row["level"] != _max_level(ctx):
        raise GameError(f"{row['pet_name']}的{skill.name}尚未达到五阶精通。")
    if claimed(ctx, player.user_id, pet_id, skill.id):
        raise GameError("这只灵宠的该灵术精进奖励已领取。")

    book = ctx.content.items.get(skill.book_item)
    if book is None or book.kind != "skill_book" or book.skill_id != skill.id:
        raise GameError("精进奖励所需秘笈定义缺失，请联系管理员修复内容；尚未领取。")

    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=REWARD_STONES, maximum=REWARD_STONES),
        items={skill.book_item: Range(minimum=1, maximum=1)},
    )
    result = grant(ctx, reward, player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1, claimed=1",
        (player.user_id, claim_id(pet_id, skill.id)),
    )
    return Reply("灵术精进奖励", (
        f"灵宠 {pet_id} 的{skill.name}精进奖励已领取。", *result,
    ), ("灵宠灵术赏", "灵宠目标"))
