"""Pet pair bond: two specific pets that only help each other while deployed together.

Every other bonus in the game is a function of one pet or of the account. A pair bond is the first
that lives *between* two pets: each pet may hold exactly one partner, and the rates apply only while
both stand in the same lineup. With three roster slots that means a lineup can realise at most one
pair, so choosing the pair is a decision rather than another free stat.

State is one symmetric ``quest_progress`` row, ``bonded_<lower_id>_<higher_id>``, which makes "one
partner per pet" a property of the key instead of a second table. Rates scale **base** stats only, in
the same place as mood and formation, so flat bonuses keep their documented integers.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from .pet_targets import named_pet
from ..utils.time import beijing_day

KEY = "bonded_"
PRACTICE_DAY = "pair_practice_day_"
THRESHOLDS = (1, 3, 6)
STAT_NAMES = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}


def rule(ctx: Context):
    return ctx.content.rules.pair_bond


def _pair_key(low: int, high: int) -> str:
    return f"{KEY}{min(low, high)}_{max(low, high)}"


def partner_of(ctx: Context, pet_id: int, user_id: str | None = None) -> int | None:
    """The pet this one is bonded to, if any."""
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (owner, f"{KEY}%"),
    ).fetchall()
    for row in rows:
        ids = row["quest_id"][len(KEY):].split("_")
        if len(ids) != 2 or not all(part.isdecimal() for part in ids):
            continue
        low, high = int(ids[0]), int(ids[1])
        if pet_id in (low, high):
            return high if pet_id == low else low
    return None


def roster_ids(ctx: Context, user_id: str | None = None) -> set[int]:
    return {pet.pet_id for pet in ctx.repo.active_pets(user_id or ctx.user_id)}


def deployed_together(ctx: Context, pet_id: int, user_id: str | None = None) -> bool:
    partner = partner_of(ctx, pet_id, user_id)
    if partner is None:
        return False
    roster = roster_ids(ctx, user_id)
    return pet_id in roster and partner in roster


def rate_of(ctx: Context, pet_id: int, user_id: str | None = None) -> dict[str, float]:
    """Rates this pet gains from its bond, and only while the pair is deployed together."""
    if not deployed_together(ctx, pet_id, user_id):
        return {}
    partner = partner_of(ctx, pet_id, user_id)
    rank = practice_rank(ctx, pet_id, partner, user_id)
    return {key: rate + rank * 0.01 for key, rate in rule(ctx).rates.items()}


def _pair_suffix(left: int, right: int) -> str:
    return f"{min(left, right)}_{max(left, right)}"


def practice_progress(ctx: Context, left: int, right: int, user_id: str | None = None) -> int:
    row = ctx.repo.conn.execute("SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user_id or ctx.user_id, "pair_practice_" + _pair_suffix(left, right))).fetchone()
    return min(6, int(row["progress"])) if row else 0


def practice_rank(ctx: Context, left: int, right: int, user_id: str | None = None) -> int:
    progress = practice_progress(ctx, left, right, user_id)
    return sum(progress >= threshold for threshold in THRESHOLDS)


def _epoch(ctx: Context, left: int, right: int) -> int:
    row = ctx.repo.conn.execute("SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, "pair_epoch_" + _pair_suffix(left, right))).fetchone()
    return row["progress"] if row else 0


def _record(ctx: Context, kind: str, left: int, right: int, reply: Reply) -> Reply:
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now,
        {"kind": kind, "pair": [left, right]}, reply)
    return reply


def rate_text(ctx: Context, rates: dict[str, float]) -> str:
    if not rates:
        return "无加成"
    return " · ".join(
        f"{STAT_NAMES[stat]} +{rate * 100:.0f}%" for stat, rate in rates.items()
    )


def cost_text(ctx: Context) -> str:
    items = "、".join(
        f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in rule(ctx).items.items()
    )
    return f"灵石 {rule(ctx).stones}" + (f" · {items}" if items else "")


def _owned(ctx: Context, item_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (ctx.user_id, item_id),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _roster_pets(ctx: Context):
    return ctx.repo.active_pets(ctx.user_id)


def page(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("格式：灵宠同心 [结契 <伙伴A> <伙伴B> | 解契 <伙伴>]。")
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            "灵宠同心",
            (
                "尚未结契，先完成领养，才能与伙伴立下同心。",
                "同心只对同一出战阵容里的两位伙伴生效，且每位伙伴只能有一位同心。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    roster = _roster_pets(ctx)
    if not roster:
        return Reply("灵宠同心", ("出战阵容还没有伙伴。",), ("灵宠出战", "灵宠帮助"))
    lines = [
        f"同心加成只在两位伙伴同时出战时生效：{rate_text(ctx, rule(ctx).rates)}；"
        f"每位伙伴只能有一位同心，结契 {cost_text(ctx)}。"
    ]
    links = []
    for pet in roster:
        partner = partner_of(ctx, pet.pet_id)
        if partner is None:
            lines.append(f"{pet.name}（#{pet.pet_id}）· 未结契 · 亲密 {pet.affinity}")
            continue
        partner_pet = ctx.repo.pet(partner)
        together = "同时出战" if deployed_together(ctx, pet.pet_id) else "未同时出战"
        lines.append(
            f"{pet.name}（#{pet.pet_id}）· 同心 {partner_pet.name} · {together}"
            f" · {rate_text(ctx, rate_of(ctx, pet.pet_id))}"
        )
        links.append(InlineCommand(len(lines) - 1, "解契", f"灵宠同心 解契 {pet.pet_id} 对 {partner} 契 {_epoch(ctx, pet.pet_id, partner)}"))
        if pet.pet_id < partner:
            progress = practice_progress(ctx, pet.pet_id, partner)
            lines.append(f"双方默契 {progress}/6 · {practice_rank(ctx, pet.pet_id, partner)} 阶；同时出战时每阶额外攻击、防御、速度各 +1%。")
            if together == "同时出战" and progress < 6:
                links.append(InlineCommand(len(lines) - 1, "选择合练", f"灵宠同心 合练 {pet.pet_id} {partner}"))
    free = [pet for pet in roster if partner_of(ctx, pet.pet_id) is None]
    for index, left in enumerate(free):
        for right in free[index + 1:]:
            lines.append(
                f"可结契：{left.name} × {right.name}"
                f"（亲密 {left.affinity}/{right.affinity}，需各 {rule(ctx).min_affinity}）"
            )
            links.append(InlineCommand(
                len(lines) - 1, "结契", f"灵宠同心 结契 {left.pet_id} {right.pet_id}",
            ))
    return Reply("灵宠同心", tuple(lines), ("灵宠同心", "我的灵宠", "灵宠属性"), tuple(links))


def _pet_named(ctx: Context, name: str):
    return named_pet(ctx, name, "同心", refresh_energy=False).pet_id


def bond(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠同心 结契 <伙伴A> <伙伴B>。")
    player = ctx.player()
    left_id, right_id = (_pet_named(ctx, parts[0]), _pet_named(ctx, parts[1]))
    if left_id is None or right_id is None:
        raise GameError("没有找到这只伙伴，请检查名字。")
    if left_id == right_id:
        raise GameError("同心需要两位不同的伙伴。")
    roster = roster_ids(ctx)
    if left_id not in roster or right_id not in roster:
        raise GameError("只有出战阵容里的伙伴才能结契，请先用 灵宠出战 安排。")
    for pet_id in (left_id, right_id):
        if partner_of(ctx, pet_id) is not None:
            raise GameError(f"{ctx.repo.pet(pet_id).name}已有同心，请先解契。")
    left, right = ctx.repo.pet(left_id), ctx.repo.pet(right_id)
    for pet in (left, right):
        ctx.require_idle_pet(pet)
    short = [
        f"{pet.name} 亲密 {pet.affinity}/{rule(ctx).min_affinity}"
        for pet in (left, right) if pet.affinity < rule(ctx).min_affinity
    ]
    if short:
        raise GameError(f"亲密不足：{'、'.join(short)}。")
    if player.stones < rule(ctx).stones:
        raise GameError(f"灵石不足：结契需要 {rule(ctx).stones}，当前 {player.stones}。")
    missing = [
        f"{ctx.content.items[item_id].name} {amount - _owned(ctx, item_id)}"
        for item_id, amount in rule(ctx).items.items()
        if _owned(ctx, item_id) < amount
    ]
    if missing:
        raise GameError(f"材料不足：结契还需{'、'.join(missing)}。")

    player.stones -= rule(ctx).stones
    for item_id, amount in rule(ctx).items.items():
        ctx.repo.consume_item(ctx.user_id, item_id, amount)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0)",
        (ctx.user_id, _pair_key(left_id, right_id)),
    )
    ctx.repo.invalidate_ready(player.user_id)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=progress+1",
        (ctx.user_id, "pair_epoch_" + _pair_suffix(left_id, right_id)),
    )
    lines = [
        f"{left.name} 与 {right.name} 立下同心：{cost_text(ctx)}已扣除。",
        f"同时出战时双方 {rate_text(ctx, rule(ctx).rates)}。",
        "每位伙伴只能有一位同心；解契免费，但不退回材料。",
    ]
    return _record(ctx, "pair_bond", left_id, right_id,
        Reply("同心结契", tuple(lines), ("灵宠同心", "灵宠出战"),
              (InlineCommand(1, "选择合练", f"灵宠同心 合练 {left_id} {right_id}"),)))


def dissolve(ctx: Context, arg: str) -> Reply:
    name, separator, epoch = arg.rpartition(" 契 ")
    name = name if separator else arg.strip()
    target, paired, expected_partner = name.partition(" 对 ")
    name = target if paired else name
    if not name:
        raise GameError("格式：灵宠同心 解契 <伙伴>。")
    player = ctx.player()
    pet_id = _pet_named(ctx, name)
    if pet_id is None:
        raise GameError("没有找到这只伙伴，请检查名字。")
    partner = partner_of(ctx, pet_id)
    if partner is None:
        raise GameError(f"{name}尚未结契。")
    if separator and (epoch != str(_epoch(ctx, pet_id, partner)) or (paired and expected_partner != str(partner))):
        raise GameError("同心契约已变更，请重新查看当前同心。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, _pair_key(pet_id, partner)),
    )
    ctx.repo.invalidate_ready(player.user_id)
    return _record(ctx, "pair_dissolve", pet_id, partner, Reply(
        "同心已解",
        (
            f"{ctx.repo.pet(pet_id).name} 与 {ctx.repo.pet(partner).name} 的同心已解除。",
            "解契不消耗资源，也不退回当初的材料。",
        ),
        ("灵宠同心", "我的灵宠"),
    ))


def _practice_pair(ctx: Context, left: str, right: str):
    ctx.player()
    pets = [named_pet(ctx, value, "合练", refresh_energy=False) for value in (left, right)]
    if pets[0].pet_id == pets[1].pet_id or partner_of(ctx, pets[0].pet_id) != pets[1].pet_id:
        raise GameError("合练需要当前已结契的两位不同伙伴。")
    roster = roster_ids(ctx)
    if any(pet.pet_id not in roster for pet in pets):
        raise GameError("两位同心伙伴须同时出战后合练，请先安排灵宠出战。")
    for pet in pets:
        ctx.require_idle_pet(pet)
    return pets


def _practice_quota(ctx: Context) -> None:
    key = PRACTICE_DAY + beijing_day(ctx.now)
    latest = ctx.repo.conn.execute(
        "SELECT MAX(quest_id) FROM quest_progress WHERE user_id=? AND quest_id GLOB ? AND progress>0",
        (ctx.user_id, PRACTICE_DAY + "*"),
    ).fetchone()[0]
    if latest and latest > key:
        raise GameError("系统日期早于合练记录，请等待恢复。")
    if latest == key:
        raise GameError("今日合练机会已使用，明日再来。")


def practice(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) not in (2, 7):
        raise GameError("格式：灵宠同心 合练 编号A 编号B [试题 契 契号 日 日期]。")
    left, right = _practice_pair(ctx, parts[0], parts[1])
    progress = practice_progress(ctx, left.pet_id, right.pet_id)
    epoch = _epoch(ctx, left.pet_id, right.pet_id)
    if len(parts) == 2:
        lines = [f"{left.name}（编号 {left.pet_id}）× {right.name}（编号 {right.pet_id}）· 默契 {progress}/6。",
                 "每日全账号合练一次，双方各支付 12 精力，另耗灵粮 1、锻灵矿 1；胜利积累默契，失败不退费。",
                 "默契达到 1/3/6 时升为一/二/三阶，同时出战的原配对各额外攻击、防御、速度 +1%/2%/3%。"]
        inventory = ctx.repo.inventory(ctx.user_id)
        lines.append(f"当前灵粮 {inventory.get('spirit_food', 0)}、锻灵矿 {inventory.get('forge_ore', 0)}；每次各需 1。")
        links = []
        try:
            _practice_quota(ctx)
        except GameError as error:
            lines.append(str(error))
            allowed = False
        else:
            allowed = progress < 6
        for trial in ctx.content.pair_practices.values():
            lines.append(f"{trial.name}：{trial.description}")
            for enemy_id in trial.enemies:
                enemy = ctx.content.enemies[enemy_id]
                lines.append(f"{enemy.name} · 气血 {enemy.stats.hp} · 攻 {enemy.stats.attack} 防 {enemy.stats.defense} 速 {enemy.stats.speed}")
            if allowed:
                links.append(InlineCommand(len(lines) - 1, "开始" + trial.name,
                    f"灵宠同心 合练 {left.pet_id} {right.pet_id} {trial.name} 契 {epoch} 日 {beijing_day(ctx.now)}"))
        lines.append("材料来自山海重游；精力不足可喂养原伙伴；三阶后可进秘境检验。")
        links.extend((InlineCommand(len(lines) - 1, "山海重游", "灵宠山海远行"),
                      InlineCommand(0, "整备甲", f"灵宠整备 {left.pet_id}"),
                      InlineCommand(0, "整备乙", f"灵宠整备 {right.pet_id}")))
        return Reply("同心合练", tuple(lines), ("灵宠同心", "灵宠秘境"), tuple(links))
    if parts[3] != "契" or parts[5] != "日" or parts[4] != str(epoch) or parts[6] != beijing_day(ctx.now):
        raise GameError("合练入口已过期或契约变更，请重新查看。")
    _practice_quota(ctx)
    if progress >= 6:
        raise GameError("这对伙伴默契已达三阶，可前往秘境检验。")
    from ..utils.arguments import named
    from ..utils.energy import restore_energy
    from .battle_records import capture_snapshot, record_battle
    from .combat import enemy_fighter, fight
    from .loadout import combatant
    trial = named(ctx.content.pair_practices, parts[2])
    for pet in (left, right):
        restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
        if pet.energy < 12:
            raise GameError(f"{pet.name}精力不足，合练需要 12。")
    for key in ("spirit_food", "forge_ore"):
        ctx.repo.consume_item(ctx.user_id, key, 1)
    attackers = [combatant(ctx, pet_id=pet.pet_id, recover_energy=False) for pet in (left, right)]
    defenders = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in trial.enemies]
    capture = capture_snapshot(ctx, (attackers, defenders), ([ctx.user_id], []))
    battle = fight(attackers, defenders, ctx.rng, ctx.content.elements)
    reached = min(6, progress + trial.progress) if battle.winner == 0 else progress
    for pet in (left, right):
        pet.energy -= 12
        ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    ctx.repo.conn.execute("INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,1,1)",
                          (ctx.user_id, PRACTICE_DAY + beijing_day(ctx.now)))
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, "pair_practice_" + _pair_suffix(left.pet_id, right.pet_id), reached),
    )
    reply = Reply("同心合练" + ("胜利" if battle.winner == 0 else "未通过"),
        (f"{trial.name} · {battle.rounds} 回合 · {left.name}与{right.name}。", *battle.lines,
         f"双方精力各 -12，灵粮 -1、锻灵矿 -1；默契 {progress} → {reached}/6。",
         "合练不发灵石、物品或普通秘境奖励；气血只在本场结算。"),
        ("灵宠同心", "灵宠战报", "灵宠秘境"),
        (InlineCommand(0, "整备甲", f"灵宠整备 {left.pet_id}"),
         InlineCommand(0, "整备乙", f"灵宠整备 {right.pet_id}")))
    record_battle(ctx, kind="pve_stage", battle_key="pair_practice_" + trial.id,
                  battle_name=trial.name, battle=battle, capture=capture, reply=reply)
    return _record(ctx, "pair_practice", left.pet_id, right.pet_id, reply)


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx, "")
    if parts[0] == "结契":
        return bond(ctx, " ".join(parts[1:]))
    if parts[0] == "解契":
        return dissolve(ctx, " ".join(parts[1:]))
    if parts[0] == "合练":
        return practice(ctx, parts[1:])
    raise GameError("格式：灵宠同心 [结契 <伙伴A> <伙伴B> | 解契 <伙伴>]。")


def objective_line(ctx: Context, user_id: str) -> str:
    if ctx.repo.player(user_id) is None:
        return "同心：尚未结契"
    roster = ctx.repo.active_pets(user_id)
    bonded = sum(1 for pet in roster if partner_of(ctx, pet.pet_id, user_id) is not None)
    active = sum(1 for pet in roster if deployed_together(ctx, pet.pet_id, user_id))
    if not bonded:
        return "同心：尚未结契"
    return f"同心：{bonded}/{len(roster)} 只已结契（{active} 只在阵中生效）"
