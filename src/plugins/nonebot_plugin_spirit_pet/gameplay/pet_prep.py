"""灵宠整备: one read-only page per roster pet.

This page gathers a pet's gear, skills and sigils and hands out links that carry the
`伙伴 <名字|编号>` selector, so each next step acts on the pet the page is about.
"""

from dataclasses import replace

from ..application.context import Context
from ..domain.models import InlineCommand, Reply
from ..utils.time import beijing_day, cooldown_left
from ..utils.energy import restore_energy
from . import bond_levels
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
    player = ctx.repo.player(ctx.user_id)
    selector = arg.strip() or (str(player.active_pet_id) if player.active_pet_id is not None else "")
    if not selector:
        raise ctx.missing_pet()
    pet = replace(named_pet(ctx, selector, "整备", refresh_energy=False))
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    roster = {member.pet_id for member in ctx.repo.active_pets(ctx.user_id)}
    marker = " · 当前出战" if pet.pet_id in roster else ""
    suffix = f" 伙伴 {pet.pet_id}"
    lines = [f"{pet.name}（编号 {pet.pet_id}）{marker}。"]
    links = []

    realm = ctx.content.realms[pet.realm]
    bloodline = ctx.content.bloodlines[pet.bloodline]
    lines.extend((
        "基础成长：",
        f"  境界：{realm.name} {pet.layer}层 · 血脉：{bloodline.name}",
        f"  修为：{pet.exp} · 灵石：{player.stones} · 精力：{pet.energy}/100 · 亲密：{pet.affinity}/100",
    ))
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition is not None:
        state = "外出中" if ctx.now < expedition["finishes_at"] else "已完成待领取"
        lines.append(f"  每日养成：行程「{expedition['task_name']}」{state}，领取后才能继续。")
        lines.append("  进阶：行程结束并领取后，才能突破或进化。")
    else:
        daily_line = len(lines)
        remaining = cooldown_left(player.last_train, ctx.now, ctx.config.spirit_pet_train_cooldown)
        food = ctx.repo.inventory(ctx.user_id).get("spirit_food", 0)
        daily = [f"修炼调息中（{remaining}秒）" if remaining else "修炼可用"]
        if food:
            daily.append(f"灵粮 {food} 份")
        else:
            daily.append("灵粮不足")
        if player.last_bond_day >= beijing_day(ctx.now):
            daily.append("互动今日已完成")
        else:
            daily.append("互动可用")
        lines.append("  每日养成：" + " · ".join(daily))
        if not remaining:
            links.append(InlineCommand(daily_line, "修炼", f"灵宠修炼 {pet.pet_id}"))
        if food:
            links.append(InlineCommand(daily_line, "喂养", f"灵宠喂养 {pet.pet_id}"))
        if player.last_bond_day < beijing_day(ctx.now):
            links.append(InlineCommand(daily_line, "互动", f"灵宠互动 {pet.pet_id}"))

        advance_line = len(lines)
        breakthrough = (
            ctx.content.realms[pet.realm].advancement
            if pet.layer == 10 else ctx.content.layers[pet.layer].advancement
        )
        evolution = bloodline.evolution
        advance = []
        if breakthrough is None:
            advance.append("突破已达最高境界")
        else:
            advance.append("突破可尝试")
            links.append(InlineCommand(advance_line, "突破", f"灵宠突破 {pet.pet_id}"))
        if evolution is None:
            advance.append("进化已达最高血脉")
        else:
            advance.append("进化可尝试")
            links.append(InlineCommand(advance_line, "进化", f"灵宠进化 {pet.pet_id}"))
        lines.append("  进阶：" + " · ".join(advance))

    bond_line = len(lines)
    lines.append(
        f"  羁绊：等级 {bond_levels.current_level(ctx, pet.pet_id)} · "
        f"经验 {bond_levels.exp(ctx, pet.pet_id)} · 可从「灵宠羁绊」查看长期成长。"
    )
    links.append(InlineCommand(bond_line, "查看羁绊", "灵宠羁绊"))

    worn = equipment.loadout(ctx, pet.pet_id)
    lines.append(f"装备 {len(worn)}/{len(equipment.SLOTS)}：")
    for slot, label in equipment.SLOTS.items():
        if slot not in worn:
            lines.append(f"  {label}：未装备")
            links.append(InlineCommand(len(lines) - 1, "去挑装备", f"灵宠装备图鉴{suffix}"))
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
        links.append(InlineCommand(
            len(lines) - 1, "挑选灵术", f"灵宠技能图鉴 伙伴 {pet.pet_id}",
        ))
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
    return Reply(TITLE, tuple(lines), (f"灵宠历练{suffix}", f"灵宠装备{suffix}",
                 f"灵宠技能{suffix}", f"灵宠符印{suffix}"), tuple(links))
