from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named
from ..utils.pagination import paginate
from ..utils.time import beijing_day, cooldown_left
from .achievements import _metric
from .rewards import grant

MAIN_QUEST_PAGE_SIZE = 5


def _training_step(ctx: Context, pet):
    from .cultivation import _available_energy
    remaining = cooldown_left(ctx.player().last_train, ctx.now, ctx.config.spirit_pet_train_cooldown)
    if remaining:
        return "查看每日任务", "灵宠任务", f"修为不足，还需调息 {remaining} 秒，可先完成其他任务"
    if _available_energy(ctx, pet) < ctx.content.rules.training_energy:
        if ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) > 0:
            return "喂养恢复", f"灵宠喂养 {pet.pet_id}", "精力不足，先用灵粮恢复"
        return "购置灵粮", "灵宠商店 灵粮", "修为与精力不足，先补给或休息"
    return "积攒修为", f"灵宠修炼 {pet.pet_id}", "先修炼积攒所需修为"


def _advancement_step(ctx: Context, pet, metric: str):
    evolution = metric == "max_bloodline"
    cost = ctx.content.bloodlines[pet.bloodline].evolution if evolution else (
        ctx.content.realms[pet.realm].advancement if pet.layer == 10 else ctx.content.layers[pet.layer].advancement
    )
    if cost is None:
        return "选择其他伙伴", "灵宠列表", "该伙伴已达到当前上限"
    scale = 1 if evolution or pet.layer == 10 else pet.realm + 1
    exp, stones = cost.exp * scale, cost.stones * scale
    if pet.exp < exp:
        return _training_step(ctx, pet)
    if ctx.player().stones < stones:
        return "完成每日任务", "灵宠任务", f"灵石不足，需要 {stones} 灵石"
    inventory = ctx.repo.inventory(ctx.user_id)
    for item_id, amount in cost.items.items():
        if inventory.get(item_id, 0) < amount:
            item = ctx.content.items[item_id]
            command = f"灵宠商店 {item.name}" if item.price is not None else f"灵宠图鉴 掉落 {item.name}"
            return "寻找材料", command, f"{item.name}不足，需要 {amount} 份"
    action = "进化" if evolution else "突破"
    return f"尝试{action}", f"灵宠{action} {pet.pet_id}", f"{action}需 {exp} 修为、{stones} 灵石，按既有规则结算"


def _guidance(ctx: Context, quest):
    metric = quest.metric
    if metric == "pets_owned":
        if len(ctx.repo.owned_pets(ctx.user_id)) >= ctx.config.spirit_pet_max_pets:
            return "名册已满，先整理伙伴。", (("整理名册", "灵宠列表"),)
        if ctx.player().stones < ctx.content.pools["standard"].stones:
            return "召唤灵石不足，也可查看每周免费召唤。", (("查看每周召唤", "灵宠每周召唤"),)
        return "再寻一位伙伴；召唤不会改变当前出战。", (("召唤一位伙伴", "灵宠召唤 1"),)
    routes = {
        "adventures_discovered": ("选择历练路线发现奇闻。", "灵宠历练"),
        "stage_clears": ("选择章节关卡，完成首场挑战。", "灵宠关卡"),
        "pvp_wins": ("从论剑榜选择对手，积累真实胜场。", "灵宠论剑榜"),
        "expedition_claims": ("派遣伙伴并在归来后领取委托奖励。", "灵宠行程"),
        "tower_depth": ("查看万灵塔准入与下一层挑战。", "灵宠万灵塔"),
    }
    if metric in routes:
        note, command = routes[metric]
        return note, (("前往目标玩法", command),)
    if metric == "team_pve_wins":
        from .teams.common import membership
        command = "灵宠队伍 秘境" if membership(ctx) is not None else "灵宠组队"
        return "与队友准备后共同挑战组队秘境。", (("前往组队", command),)

    player = ctx.player()
    pet = ctx.repo.pet(player.active_pet_id) if player.active_pet_id is not None else None
    if pet is None:
        owned = ctx.repo.conn.execute("SELECT pet_id FROM pets WHERE user_id=? ORDER BY archived,pet_id LIMIT 1",
                                      (ctx.user_id,)).fetchone()
        pet = ctx.repo.pet(owned["pet_id"]) if owned else None
    if pet is None:
        return "尚无伙伴，请先从名册寻找养成对象。", (("查看名册", "灵宠列表"),)
    note = f"养成伙伴：{pet.name}（编号 {pet.pet_id}）。"
    if player.active_pet_id is None:
        note += "当前尚未出战，养成操作仍固定此编号。"
    if pet.archived:
        return note + "伙伴已封存，先复原。", (("复原伙伴", f"灵宠复原 {pet.pet_id}"),)
    if ctx.repo.active_expedition(pet.pet_id) is not None:
        return note + "伙伴派遣中或奖励待领取，先完成行程。", (("查看行程", "灵宠行程"),)
    steps = [("查看整备", f"灵宠整备 {pet.pet_id}")]
    if metric in {"max_layer", "max_realm", "max_bloodline"}:
        label, command, detail = _advancement_step(ctx, pet, metric)
        note += detail + "。"
    elif metric in {"skills_learned", "max_skill_level"}:
        label, command = "挑选灵术", f"灵宠技能图鉴 伙伴 {pet.pet_id}"
    elif metric == "max_affinity":
        if ctx.repo.inventory(ctx.user_id).get("spirit_food", 0) > 0:
            label, command = "喂养伙伴", f"灵宠喂养 {pet.pet_id}"
        elif player.last_bond_day < beijing_day(ctx.now):
            label, command = "陪伴伙伴", f"灵宠互动 {pet.pet_id}"
        else:
            label, command = "购置灵粮", "灵宠商店 灵粮"
    elif metric == "lineage_branches":
        if player.active_pet_id != pet.pet_id:
            label, command = "选择领队", f"灵宠切换 {pet.pet_id}"
            note += "选择血脉分支前需让这位伙伴担任领队。"
        else:
            label, command = "查看血脉分支", f"灵宠血脉 {ctx.content.species[pet.species_id].name}"
    else:
        raise ValueError(f"unsupported main quest guidance metric: {metric}")
    steps.append((label, command))
    return note, tuple(steps)


def _append_guidance(ctx: Context, quest, lines: list, links: list):
    value = _metric(ctx, ctx.user_id, quest.metric)
    if value >= quest.target:
        command = f"灵宠主线领奖 {quest.name}"
        if command not in {link.command for link in links}:
            links.append(InlineCommand(len(lines) - 1, "领取奖励", command))
        return
    note, steps = _guidance(ctx, quest)
    lines.append(note)
    for label, command in steps:
        links.append(InlineCommand(len(lines) - 1, label, command))


def _ordered(ctx: Context) -> list:
    return sorted(ctx.content.main_quests.values(), key=lambda quest: quest.order)


def _claimed(ctx: Context, user_id: str) -> set[str]:
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND claimed=1", (user_id,),
    )
    return {row["quest_id"] for row in rows} & set(ctx.content.main_quests)


def _current(ctx: Context, user_id: str):
    """The first step that is neither claimed nor blocked by an unclaimed predecessor."""
    claimed = _claimed(ctx, user_id)
    return next((quest for quest in _ordered(ctx) if quest.id not in claimed), None)


def _state(ctx: Context, user_id: str, quest, claimed: set[str], current) -> tuple[str, int]:
    if quest.id in claimed:
        return "已完成", quest.target
    if current is not None and quest.id == current.id:
        value = _metric(ctx, user_id, quest.metric)
        return ("可领奖" if value >= quest.target else "进行中"), value
    return "未解锁", 0


def _reward_summary(ctx: Context, quest) -> str:
    parts = [f"灵石 {quest.reward.stones.minimum}"]
    parts.extend(
        f"{ctx.content.items[item].name} {bounds.minimum}"
        for item, bounds in quest.reward.items.items()
    )
    return "，".join(parts)


def catalog(ctx: Context, arg: str) -> Reply:
    quests = _ordered(ctx)
    page = paginate(quests, arg, "灵宠主线", "灵宠主线", page_size=MAIN_QUEST_PAGE_SIZE)
    lines = ["主线按序推进：达成当前一步并领取奖励，下一步才会解锁。"]
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        lines.append("尚未结契，先完成领养，再踏上主线。")
        return Reply("灵宠主线", tuple(lines), ("灵宠帮助",), (
            InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "),
        ))

    claimed = _claimed(ctx, player.user_id)
    current = _current(ctx, player.user_id)
    links = []
    for quest in page.entries:
        state, value = _state(ctx, player.user_id, quest, claimed, current)
        progress = f" · {value}/{quest.target}" if state in {"进行中", "可领奖"} else ""
        lines.append(
            f"{quest.order}. {quest.name} · {state}{progress} · {_reward_summary(ctx, quest)}"
        )
        if state == "可领奖":
            links.append(InlineCommand(
                len(lines) - 1, "领取奖励", f"灵宠主线领奖 {quest.name}",
            ))
    if current is None:
        lines.append("主线已全部完成，感谢一路同行。")
    else:
        lines.append(f"当前目标：{current.name} · {current.description}")
        _append_guidance(ctx, current, lines, links)
    commands = (*page.navigation, "灵宠任务") if current else (*page.navigation, "灵宠周常", "灵宠目标")
    return Reply(
        f"灵宠主线 {page.number}/{page.total}", tuple(lines),
        commands, tuple(links),
    )


def claim(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    quest = named(ctx.content.main_quests, arg)
    if quest.id in _claimed(ctx, player.user_id):
        raise GameError("该主线奖励已领取，不能重复领取。")
    current = _current(ctx, player.user_id)
    if current is None or current.id != quest.id:
        blocker = current.name if current is not None else "主线已全部完成"
        raise GameError(f"主线须按序推进，请先完成「{blocker}」。")
    value = _metric(ctx, player.user_id, quest.metric)
    if value < quest.target:
        raise GameError(
            f"主线尚未达成：{quest.description}（进度 {value}/{quest.target}）"
        )
    result = grant(ctx, quest.reward)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
        (player.user_id, quest.id, value),
    )
    following = _current(ctx, player.user_id)
    lines = [f"{quest.name}已完成。", *result]
    lines.append(f"下一步：{following.name}。" if following else "主线已全部完成，感谢一路同行。")
    links = []
    if following:
        value = _metric(ctx, player.user_id, following.metric)
        lines.append(f"{following.description}（进度 {value}/{following.target}）")
        _append_guidance(ctx, following, lines, links)
    commands = ("灵宠主线", "灵宠任务") if following else ("灵宠周常", "灵宠目标")
    return Reply("主线奖励已领取", tuple(lines), commands, tuple(links))
