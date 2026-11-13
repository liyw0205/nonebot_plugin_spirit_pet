"""灵宠整备: one read-only page per roster pet.

This page gathers a pet's gear, skills and sigils and hands out links that carry the
`伙伴 <名字|编号>` selector, so each next step acts on the pet the page is about.
"""

from ..application.context import Context
from ..domain.models import InlineCommand, Reply
from . import equipment, sigils, skills
from .ascension_rules import skill_slots
from .pet_targets import named_pet

TITLE = "灵宠整备"
STAT_LABELS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def _total_text(totals: dict[str, int]) -> str:
    parts = [f"{STAT_LABELS[key]} +{value}" for key, value in totals.items() if value]
    return "、".join(parts) if parts else "无固定加成"


def prep(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能为伙伴整备。",
                "整备页只读：列出装备、灵术与符印，并给出可直接执行的下一步。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    pet = named_pet(ctx, arg, "整备") if arg.strip() else ctx.pet()
    roster = {member.pet_id for member in ctx.repo.active_pets(ctx.user_id)}
    marker = " · 当前出战" if pet.pet_id in roster else ""
    suffix = "" if pet.pet_id in roster else f" 伙伴 {pet.pet_id}"
    lines = [f"{pet.name}（编号 {pet.pet_id}）{marker}。"]
    links = []

    worn = equipment.loadout(ctx, pet.pet_id)
    lines.append(f"装备 {len(worn)}/{len(equipment.SLOTS)}：")
    for slot, label in equipment.SLOTS.items():
        if slot not in worn:
            lines.append(f"  {label}：未装备")
            links.append(InlineCommand(len(lines) - 1, "去挑装备", "灵宠装备图鉴"))
            continue
        item_id, level = worn[slot]
        lines.append(f"  {label}：{ctx.content.items[item_id].name} +{level}")
        row = len(lines) - 1
        if ctx.content.forge_levels[level].upgrade_stones is not None:
            links.append(InlineCommand(row, "强化", f"灵宠强化 {label}{suffix}"))
        links.append(InlineCommand(row, "卸下", f"灵宠卸装 {label}{suffix}"))

    learned = skills.learned(ctx, pet.pet_id)
    mastery = skills.progress(ctx, pet.pet_id)
    carried = sum(1 for active in learned.values() if active)
    lines.append(f"灵术 {carried}/{skill_slots(ctx, pet)} 携带 · 已学 {len(learned)} 门：")
    if not learned:
        lines.append("  尚未学习灵术。")
    for skill_id, active in learned.items():
        skill = ctx.content.skills[skill_id]
        lines.append(
            f"  {skill.name} · {skills.progress_text(ctx, *mastery[skill_id])}"
            f" · {'已携带' if active else '未携带'}"
        )
        links.append(InlineCommand(
            len(lines) - 1,
            "卸下" if active else "携带",
            f"灵宠卸技 {skill.name}{suffix}" if active else f"灵宠携带 {skill.name}{suffix}",
        ))

    filled = sigils.equipped(ctx, pet.pet_id)
    lines.append(f"符印 {len(filled)}/{sigils.SLOTS} · {_total_text(sigils.total_bonus(ctx, pet.pet_id))}：")
    if not filled:
        lines.append("  未装备符印。")
    for slot, sigil_id in sorted(filled.items()):
        sigil = ctx.content.sigils[sigil_id]
        lines.append(f"  {slot}号槽：{sigil.name} · {sigils.bonus_text(ctx, sigil)}")
        links.append(InlineCommand(len(lines) - 1, "卸下", f"灵宠符印 卸下 {sigil.name}{suffix}"))
    if len(filled) < sigils.SLOTS:
        ready = [
            sigil for sigil in ctx.content.sigils.values()
            if sigil.id not in filled.values() and sigils.unlocked(ctx, sigil, pet)
        ]
        if ready:
            lines.append("  可镶嵌：" + "、".join(sigil.name for sigil in ready))
            links.append(InlineCommand(
                len(lines) - 1, "镶嵌", f"灵宠符印 装备 {ready[0].name}{suffix}",
            ))

    lines.append("整备只读：不切换出战、不消耗材料；每一步都按本页伙伴执行。")
    return Reply(TITLE, tuple(lines), (TITLE, "灵宠装备", "灵宠技能", "灵宠符印"), tuple(links))
