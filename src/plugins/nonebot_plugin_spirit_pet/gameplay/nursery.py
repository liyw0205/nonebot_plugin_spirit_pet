"""One reserved egg, a fixed guardian and two optional growth lessons.

All paid choices and terminal replies share the permanent action ledger; the
original egg and rule snapshot remain recoverable when the roster changes.
"""

from hashlib import sha256

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import beijing_day
from . import bond_levels
from .pet_targets import pet_id, split_selector

TITLE = "灵宠护育"
DAY_PREFIX = "nursery_day_"


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    last = ctx.repo.latest_nursery_action(user_id or ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return row["quantity"] if row else 0


def _used(ctx: Context, user_id: str | None = None) -> bool:
    # Keep later days as a high-water mark so a clock rollback cannot reopen a day.
    return ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id GLOB 'nursery_day_*' "
        "AND quest_id>=? LIMIT 1", (user_id or ctx.user_id, DAY_PREFIX + beijing_day(ctx.now)),
    ).fetchone() is not None


def _guardian(ctx: Context, value: str = "", nest: dict | None = None):
    owner = ctx.player()
    target = nest["guardian_id"] if nest else (pet_id(value) if value else owner.active_pet_id)
    if target is None:
        raise ctx.missing_pet()
    row = ctx.repo.conn.execute(
        "SELECT pet_id,archived,name FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, target),
    ).fetchone()
    if row is None:
        raise GameError("原护育伙伴不存在，请撤回灵卵；不能改换护育伙伴。" if nest else
                        "没有属于你的在册灵宠，请查看 灵宠列表 中的编号。")
    from .release import released
    if released(ctx, target):
        raise GameError(f"{row['name']}已归灵，请撤回灵卵；不能改换护育伙伴。")
    if row["archived"]:
        raise GameError(f"{row['name']}已封存，请先复原后继续护育，或撤回灵卵。")
    return ctx.repo.pet(target)


def _available_energy(ctx: Context, pet) -> int:
    return min(100, pet.energy + max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval)


def _blocker(ctx: Context, pet) -> str:
    trip = ctx.repo.active_expedition(pet.pet_id)
    if trip:
        return "正在外出派遣，先完成行程" if ctx.now < trip["finishes_at"] else "派遣已完成，奖励待领取"
    return ""


def _egg(ctx: Context, text: str):
    item = named(ctx.content.items, text)
    if item.kind != "pet_egg":
        raise GameError(f"{item.name}不是灵卵，护育需要一枚灵卵。")
    return item


def _growth(values) -> str:
    return f"修为 +{values['exp']} · 亲密 +{values['affinity']} · 羁绊经验 +{values['bond']}"


def _command(nest: dict, action: str) -> str:
    return f"{TITLE} {action} 巢 {nest['nest_id']} 步 {len(nest['history']) + 1}"


def _record(ctx: Context, nest: dict, reply: Reply) -> Reply:
    ctx.repo.record_nursery_action(ctx.operation_id, ctx.user_id, ctx.now,
                                 {**nest, "updated_at": ctx.now}, reply)
    return reply


def _nest_reply(ctx: Context, nest: dict, prefix: tuple[str, ...] = ()) -> Reply:
    rule = nest["rule"]
    count = len(nest["history"])
    ready = max(0, nest["ready_at"] - ctx.now)
    wait = max(0, nest["next_lesson_at"] - ctx.now)
    lines = [*prefix,
             f"巢中：{nest['egg_name']} · 护育伙伴 {nest['guardian_name']}（编号 {nest['guardian_id']}）。",
             f"已照料 {count}/{rule['lessons']} 次 · 迎接等待 {ready} 秒 · 下一次照料等待 {wait} 秒。",
             f"待获成长：{_growth(nest['growth'])}；可重复同一方向，也可分配。",
             "成长只在迎接时落实；可以不补满照料次数。灵卵不会过期。"]
    links = []
    blocker = ""
    can_care = False
    try:
        guardian = _guardian(ctx, nest=nest)
    except GameError as exc:
        blocker = str(exc)
    else:
        blocker = _blocker(ctx, guardian)
        lines.append(f"原伙伴可用精力 {_available_energy(ctx, guardian)} · {blocker or '在册闲置'}。")
        can_care = not blocker and _available_energy(ctx, guardian) >= rule["energy"] and _owned(ctx, rule["item_id"]) >= 1
        if not blocker and not can_care and count < rule["lessons"]:
            lines.append(f"照料需{nest['food_name']}1（持有{_owned(ctx, rule['item_id'])}）、原伙伴精力{rule['energy']}。")
    if blocker:
        lines.append(blocker)
        if "封存" in blocker:
            links.append(InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库"))
        elif "派遣" in blocker:
            links.append(InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"))
    if count < rule["lessons"]:
        for choice in rule["choices"]:
            lines.append(f"{choice['name']}：{_growth(choice)} · 消耗{nest['food_name']} 1、原伙伴精力 {rule['energy']}。")
            if not wait and can_care:
                links.append(InlineCommand(len(lines) - 1, "照料" + choice["name"],
                                           _command(nest, "照料 " + choice["name"])))
    lines.append("撤回会返还巢中灵卵；已消耗的灵粮和精力不退，不获得护育成长。")
    links.append(InlineCommand(len(lines) - 1, "撤回灵卵", _command(nest, "撤回")))
    room = len(ctx.repo.owned_pets(ctx.user_id)) < ctx.config.spirit_pet_max_pets
    if not room:
        lines.append("名册容量不足，先封存另一位伙伴再迎接；灵卵与成长保留在巢中。")
    commands = [_command(nest, "迎接")] if not ready and not blocker and room else []
    return Reply(TITLE + " · 巢中", tuple(lines), (*commands, TITLE + " 记录", "灵宠背包"), tuple(links))


def page(ctx: Context, arg: str = "") -> Reply:
    owner = ctx.repo.player(ctx.user_id)
    if owner is None:
        return Reply(TITLE, ("尚未结契，先完成领养，再让伙伴护育灵卵。",), ("灵宠帮助",),
                     (InlineCommand(0, "开始领养", "灵宠领养 "),))
    nest = state(ctx)
    if nest:
        if arg:
            raise GameError("已有灵卵在巢中，请直接查看 灵宠护育。")
        return _nest_reply(ctx, nest)
    eggs = [item for item in ctx.content.items.values() if item.kind == "pet_egg" and _owned(ctx, item.id)]
    rule = ctx.content.nursery
    lines = [f"每日北京时间最多入巢一次，每人同时护育一枚；{rule.lessons}次照料可集中或分配成长方向。",
             f"入巢保管灵卵，{rule.interval * rule.lessons}秒后可迎接；每次照料间隔{rule.interval}秒，消耗{ctx.content.items[rule.item_id].name}1、原伙伴精力{rule.energy}。",
             "今日已入巢，明日再开启。" if _used(ctx) else "今日尚未入巢。"]
    if not eggs:
        return Reply(TITLE, (*lines, "背包暂无灵卵，可从同族培育或秘境获取。"),
                     ("灵宠培育", "灵宠秘境", TITLE + " 记录"))
    page_data = paginate(eggs, arg, TITLE, TITLE, page_size=4)
    links = []
    for item in page_data.entries:
        lines.append(f"{item.name} ×{_owned(ctx, item.id)} · 种族 {ctx.content.species[item.species_id].name}。")
        links.append(InlineCommand(len(lines) - 1, "查看护育", f"{TITLE} 预览 {item.name}"))
    return Reply(f"{TITLE} {page_data.number}/{page_data.total}", tuple(lines),
                 (*page_data.navigation, TITLE + " 记录", "灵宠列表"), tuple(links))


def preview(ctx: Context, arg: str) -> Reply:
    text, selector = split_selector(arg)
    egg = _egg(ctx, text)
    rule = ctx.content.nursery
    lines = [f"{egg.name} · 种族 {ctx.content.species[egg.species_id].name} · 持有 {_owned(ctx, egg.id)}。",
             f"保管一枚灵卵，{rule.interval * rule.lessons} 秒后可迎接；最多照料 {rule.lessons} 次。"]
    for choice in rule.choices:
        lines.append(f"{choice.name}：{_growth(choice.model_dump())}。{choice.description}")
    lines.append(f"每次消耗{ctx.content.items[rule.item_id].name}1、原伙伴精力{rule.energy}；照料间隔{rule.interval}秒。")
    links = []
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先完成领养。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        try:
            guardian = _guardian(ctx, selector)
        except GameError as exc:
            lines.append(str(exc))
        else:
            blocker = _blocker(ctx, guardian)
            lines.append(f"护育伙伴 {guardian.name}（编号 {guardian.pet_id}）· 可用精力 {_available_energy(ctx, guardian)} · {blocker or '在册闲置'}。")
            if state(ctx):
                lines.append("已有灵卵在巢中，先迎接或撤回。")
            elif _used(ctx):
                lines.append("今日已入巢，明日再开启。")
            elif not _owned(ctx, egg.id):
                lines.append(f"{egg.name}不足，需要一枚。")
            elif not blocker:
                links.append(InlineCommand(len(lines) - 1, "入巢护育",
                                           f"{TITLE} 入巢 {egg.name} 伙伴 {guardian.pet_id}"))
    return Reply(TITLE + " · " + egg.name, tuple(lines), (TITLE, "灵宠列表", "灵宠培育"), tuple(links))


def start(ctx: Context, arg: str) -> Reply:
    ctx.player()
    text, selector = split_selector(arg)
    egg = _egg(ctx, text)
    last = ctx.repo.latest_nursery_action(ctx.user_id)
    if last:
        _check_time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有灵卵在巢中，请迎接或撤回后再入巢。")
    if _used(ctx):
        raise GameError("今日已经入巢过，撤回也不能重开；明日 00:00（北京时间）恢复。")
    guardian = _guardian(ctx, selector)
    ctx.require_idle_pet(guardian)
    if not _owned(ctx, egg.id):
        raise GameError(f"{egg.name}不足：当前持有 0，需要 1。")
    rule = ctx.content.nursery.model_dump()
    species = ctx.content.species[egg.species_id]
    nest = {"status": "active", "nest_id": sha256(ctx.operation_id.encode()).hexdigest()[:16],
            "egg_id": egg.id, "egg_name": egg.name, "species_id": species.id,
            "species_name": species.name, "initial_affinity": species.initial_affinity,
            "guardian_id": guardian.pet_id, "guardian_name": guardian.name,
            "food_name": ctx.content.items[rule["item_id"]].name, "rule": rule,
            "started_at": ctx.now, "ready_at": ctx.now + rule["interval"] * rule["lessons"],
            "next_lesson_at": ctx.now + rule["interval"], "history": [],
            "growth": {"exp": 0, "affinity": 0, "bond": 0}}
    ctx.repo.consume_item(ctx.user_id, egg.id, 1)
    ctx.repo.conn.execute("INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
                          (ctx.user_id, DAY_PREFIX + beijing_day(ctx.now)))
    return _record(ctx, nest, _nest_reply(ctx, nest, (f"已将{egg.name}一枚放入灵巢，未消耗护育伙伴精力。",)))


def _check_time(ctx: Context, nest: dict) -> None:
    if ctx.now < nest["updated_at"]:
        raise GameError("时间早于上次护育，请等待时钟恢复后再操作；灵卵仍在巢中。")


def _active(ctx: Context, guard: list[str]) -> dict:
    ctx.player()
    nest = state(ctx)
    if nest is None:
        raise GameError("当前没有巢中灵卵，请先查看 灵宠护育。")
    _check_time(ctx, nest)
    if guard:
        if len(guard) != 4 or guard[0] != "巢" or guard[2] != "步":
            raise GameError("护育操作凭证格式不正确，请重新查看 灵宠护育。")
        step = quantity(guard[3], 3)
        if guard[1] != nest["nest_id"]:
            raise GameError("这是另一枚灵卵的护育入口，请重新查看当前灵巢。")
        if step != len(nest["history"]) + 1:
            raise GameError("这一步照料已经执行，请查看当前灵巢后再选择。")
    return nest


def care(ctx: Context, choice_name: str, guard: list[str]) -> Reply:
    nest = _active(ctx, guard)
    rule = nest["rule"]
    choice = next((c for c in rule["choices"] if choice_name in (c["id"], c["name"])), None)
    if choice is None:
        raise GameError("没有这个护育方向，请选择修行、亲和或默契。")
    if len(nest["history"]) >= rule["lessons"]:
        raise GameError("本巢照料次数已用尽，请迎接新伙伴或撤回灵卵。")
    wait = max(0, nest["next_lesson_at"] - ctx.now)
    if wait:
        raise GameError(f"这枚灵卵还需休息 {wait} 秒，之后才能再次照料。")
    guardian = _guardian(ctx, nest=nest)
    ctx.require_idle_pet(guardian)
    if _available_energy(ctx, guardian) < rule["energy"]:
        raise GameError(f"{guardian.name}精力不足：当前 {_available_energy(ctx, guardian)}，需要 {rule['energy']}。")
    if _owned(ctx, rule["item_id"]) < 1:
        raise GameError(f"{nest['food_name']}不足：当前持有 0，需要 1。")
    ctx.repo.consume_item(ctx.user_id, rule["item_id"], 1)
    restore_energy(guardian, ctx.now, ctx.config.spirit_pet_energy_interval)
    guardian.energy -= rule["energy"]
    ctx.repo.invalidate_pet_ready(ctx.user_id, guardian.pet_id)
    nest["history"].append(choice["name"])
    for field in nest["growth"]:
        nest["growth"][field] += choice[field]
    nest["next_lesson_at"] = ctx.now + rule["interval"]
    return _record(ctx, nest, _nest_reply(ctx, nest, (
        f"已选择{choice['name']}：{nest['food_name']} -1，{guardian.name}精力 -{rule['energy']}。",
    )))


def finish(ctx: Context, guard: list[str]) -> Reply:
    nest = _active(ctx, guard)
    wait = max(0, nest["ready_at"] - ctx.now)
    if wait:
        raise GameError(f"灵卵尚未准备好，还需 {wait} 秒才能迎接。")
    guardian = _guardian(ctx, nest=nest)
    ctx.require_idle_pet(guardian)
    if len(ctx.repo.owned_pets(ctx.user_id)) >= ctx.config.spirit_pet_max_pets:
        raise GameError("灵宠名册容量不足，灵卵与护育成长仍保留在巢中；先封存伙伴再迎接，或撤回灵卵。")
    baby = ctx.repo.create_pet(ctx.user_id, nest["species_id"], nest["species_name"],
                               nest["initial_affinity"], ctx.now)
    baby.exp += nest["growth"]["exp"]
    gained = min(100 - baby.affinity, nest["growth"]["affinity"])
    baby.affinity += gained
    if nest["growth"]["bond"]:
        bond_levels.add_exp(ctx, baby.pet_id, nest["growth"]["bond"])
    guardian_gain = nest["rule"]["guardian_bond"] if nest["history"] else 0
    if guardian_gain:
        bond_levels.add_exp(ctx, guardian.pet_id, guardian_gain)
        ctx.repo.invalidate_pet_ready(ctx.user_id, guardian.pet_id)
    nest.update(status="hatched", baby_id=baby.pet_id, guardian_gain=guardian_gain, actual_affinity=gained)
    return _record(ctx, nest, Reply(TITLE + " · 破壳相见", (
        f"{nest['egg_name']}已孵化：{baby.name}（编号 {baby.pet_id}），未自动更换出战伙伴。",
        f"护育选择：{' → '.join(nest['history']) or '自然等待，未照料'}。",
        f"新伙伴修为 +{baby.exp} · 亲密 +{gained} · 羁绊经验 +{nest['growth']['bond']}。",
        f"原伙伴{nest['guardian_name']}羁绊经验 +{guardian_gain}。",
    ), ("灵宠列表", "灵宠羁绊", TITLE),
        (InlineCommand(2, "查看新伙伴", f"灵宠整备 {baby.pet_id}"),)))


def withdraw(ctx: Context, guard: list[str]) -> Reply:
    nest = _active(ctx, guard)
    ctx.repo.add_item(ctx.user_id, nest["egg_id"], 1)
    nest["status"] = "withdrawn"
    return _record(ctx, nest, Reply(TITLE + " · 撤回", (
        f"已取回{nest['egg_name']}一枚；已花灵粮和精力不返还。",
        "未获得新伙伴或护育成长；原入巢日的次数不恢复。",
    ), (TITLE, "灵宠背包", "灵宠列表")))


def history(ctx: Context) -> Reply:
    last = ctx.repo.latest_nursery_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply(TITLE + " · 记录", ("暂无已结束的护育记录。",), (TITLE,))
    saved = Reply.from_data(last["reply"])
    return Reply(TITLE + " · 记录", saved.lines, (TITLE, "灵宠列表"))


def objective_line(ctx: Context, user_id: str) -> str:
    nest = state(ctx, user_id)
    if nest:
        wait = max(0, nest["ready_at"] - ctx.now)
        return f"灵卵护育：{nest['egg_name']} · 照料 {len(nest['history'])}/{nest['rule']['lessons']} · " + (
            f"迎接等待 {wait} 秒" if wait else "可迎接（原伙伴须在册闲置、名册须有空位）")
    return "灵卵护育：今日已入巢" if _used(ctx, user_id) else "灵卵护育：今日可入巢一枚"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    head = parts[0]
    if head in ("预览", "入巢"):
        if len(parts) < 2:
            raise GameError(f"格式：{TITLE} {head} 灵卵名 [伙伴 编号]。")
        return (preview if head == "预览" else start)(ctx, " ".join(parts[1:]))
    if head == "照料":
        if len(parts) < 2:
            raise GameError(f"格式：{TITLE} 照料 修行|亲和|默契。")
        return care(ctx, parts[1], parts[2:])
    if head in ("迎接", "撤回"):
        return (finish if head == "迎接" else withdraw)(ctx, parts[1:])
    if head == "记录":
        if len(parts) != 1:
            raise GameError(f"{TITLE} 记录 不接受额外参数。")
        return history(ctx)
    return page(ctx, arg)
