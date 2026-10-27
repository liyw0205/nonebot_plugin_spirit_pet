from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from . import battle_pass

PLOT_COUNT = 4
OPEN_COST = (200, 500, 1200, 2500)
RENEW_COST = 80
RENEW_FRACTION = 10  # percent of remaining time cut, once per growth
TIER_COST = (800, 2000)  # per-plot upgrade levels 1 and 2
TIER_TIME_CUT = 15  # percent of growth duration per tier level
WILT_AFTER = 48 * 3600  # unharvested crops wilt after 48 hours

OPEN_PREFIX = "farm_open_"
CROP_PREFIX = "farm_crop_"
RENEW_PREFIX = "farm_renew_"
TIER_PREFIX = "farm_tier_"

# Seed drop tiers by realm index: qiling→灵稻, ningqi→矿苗, zhuji/jindan→灵血草,
# yuanying and above→蕴灵穗. Crops are content, so the mapping stays data-driven.
SEED_DROPS = (
    ("seed_spirit_rice", "spirit_rice"),
    ("seed_ore_sprout", "ore_sprout"),
    ("seed_blood_herb", "blood_herb"),
    ("seed_aura_ear", "aura_ear"),
)


def _tier(ctx: Context, plot: int) -> int:
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{TIER_PREFIX}{plot}"),
    ).fetchone()
    return row["progress"] if row else 0


def _effective_duration(ctx: Context, plot: int, base_duration: int) -> int:
    return base_duration * (100 - _tier(ctx, plot) * TIER_TIME_CUT) // 100


def _renew_cut(ctx: Context, plot: int) -> int:
    """Seconds already taken off this plot's current growth by 灵宠翻新."""
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{RENEW_PREFIX}{plot}"),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _growth_seconds(ctx: Context, plot: int, crop) -> int:
    """The growth time this plot actually needs: tier cut and 翻新 cut applied.

    Every reader (overview, harvest, renew, replant preview) must use this so the
    remaining time a player is shown is the time the settlement enforces.
    """
    return max(1, _effective_duration(ctx, plot, crop.duration) - _renew_cut(ctx, plot))


def seed_for_realm(ctx: Context, realm_id: str) -> str | None:
    """The seed item id for a realm tier, or None when the realm is unknown."""
    realm_ids = [realm.id for realm in ctx.content.realms]
    if realm_id not in realm_ids:
        return None
    index = min(realm_ids.index(realm_id), len(SEED_DROPS) - 1)
    return SEED_DROPS[index][0]


# Seed supply chances, one per settlement path. Single source of truth: the
# rolls below and the 图鉴 drop lookup both read these, so a page can never
# advertise a chance the settlement does not use.
SEED_DROP_CHANCE = {"ambush": 25, "dungeon": 8, "sweep": 8, "expedition": 15}
# Labels for the settlement path each chance belongs to, shared with the lookup.
SEED_DROP_PATH_LABEL = {
    "ambush": "历练伏击",
    "dungeon": "秘境",
    "sweep": "秘境",
    "expedition": "委托",
}


def roll_seed_drop(ctx: Context, realm_id: str, path: str) -> str | None:
    """Roll one seed drop for a settlement path; returns the item id or None.

    `path` must be a key of SEED_DROP_CHANCE so every caller shares one chance.
    """
    seed_id = seed_for_realm(ctx, realm_id)
    if seed_id is None:
        return None
    return seed_id if ctx.rng.randint(1, 100) <= SEED_DROP_CHANCE[path] else None


def _plot_arg(ctx: Context, arg: str) -> int:
    plot = quantity(arg, PLOT_COUNT)
    if not 1 <= plot <= PLOT_COUNT:
        raise GameError(f"田位编号是 1-{PLOT_COUNT}。")
    return plot


def _open_row(ctx: Context, plot: int):
    return ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{OPEN_PREFIX}{plot}"),
    ).fetchone()


def _crop_row(ctx: Context, plot: int):
    return ctx.repo.conn.execute(
        "SELECT quest_id, progress, claimed FROM quest_progress "
        "WHERE user_id=? AND quest_id LIKE ?",
        (ctx.user_id, f"{CROP_PREFIX}{plot}_%"),
    ).fetchone()


def _renew_row(ctx: Context, plot: int):
    return ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, f"{RENEW_PREFIX}{plot}"),
    ).fetchone()


def _plot_state(ctx: Context, plot: int):
    """Return (opened, crop_row, renew_row) for one plot."""
    return _open_row(ctx, plot) is not None, _crop_row(ctx, plot), _renew_row(ctx, plot)


def _crop(ctx: Context, crop_row):
    crop_id = crop_row["quest_id"][len(f"{CROP_PREFIX}"):].split("_", 1)[-1]
    return ctx.content.crops[crop_id]


def _hasten_cost(ctx: Context, crop_row) -> int:
    crop = _crop(ctx, crop_row)
    planted = crop_row["progress"]
    if ctx.now < planted:
        raise GameError("当前时间早于种植时间，请稍后再操作。")
    remaining = crop.duration - (ctx.now - planted)
    return max(1, remaining * RENEW_FRACTION // 100)


def _grant_reward(ctx: Context, crop) -> tuple[str, ...]:
    lines = []
    if crop.reward_exp:
        pet = ctx.pet()
        pet.exp += crop.reward_exp
        lines.append(f"修为 +{crop.reward_exp}")
    if crop.reward_stones:
        player = ctx.player()
        player.stones += crop.reward_stones
        lines.append(f"灵石 +{crop.reward_stones}")
    for item_id, bounds in crop.reward_items.items():
        amount = ctx.rng.randint(bounds.minimum, bounds.maximum)
        ctx.repo.add_item(ctx.user_id, item_id, amount)
        if amount:
            lines.append(f"{ctx.content.items[item_id].name} +{amount}")
    return tuple(lines)


def _seed_arg(ctx: Context, query: str):
    """A crop by name, id, or seed name, or None."""
    return next(
        (entry for entry in ctx.content.crops.values()
         if entry.name == query or entry.id == query
         or ctx.content.items[entry.seed_item].name == query),
        None,
    )


def catalog(ctx: Context, arg: str) -> Reply:
    if arg.strip():
        raise GameError("灵宠灵田 不接受参数，直接发送即可。")
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply("灵宠灵田", (
            "灵田可以播种种子，等待成熟后收获灵粮与材料。",
            "尚未结契，先完成领养，再开垦自己的灵田。",
        ), ("灵宠帮助",), (InlineCommand(1, "开始领养", "灵宠领养 "),))

    lines = []
    links = []
    for plot in range(1, PLOT_COUNT + 1):
        opened, crop_row, _ = _plot_state(ctx, plot)
        if not opened:
            cost = OPEN_COST[plot - 1]
            lines.append(f"田位 {plot} · 待开垦（{cost} 灵石）")
            links.append(InlineCommand(len(lines) - 1, "开垦灵田", f"灵宠开垦 {plot}"))
        elif crop_row is None:
            lines.append(f"田位 {plot} · 待播种")
            links.append(InlineCommand(len(lines) - 1, "查看种子", "灵宠商店"))
        else:
            crop = _crop(ctx, crop_row)
            planted = crop_row["progress"]
            duration = _growth_seconds(ctx, plot, crop)
            if ctx.now - planted >= duration + WILT_AFTER:
                lines.append(f"田位 {plot} · {crop.name}已枯萎，收获仅返还种子")
                links.append(InlineCommand(len(lines) - 1, "清理枯萎", f"灵宠收获 {plot}"))
            elif ctx.now - planted >= duration:
                lines.append(f"田位 {plot} · {crop.name}已成熟，可收获")
                links.append(InlineCommand(len(lines) - 1, "收获作物", f"灵宠收获 {plot}"))
            else:
                renew = "（已翻新）" if crop_row["claimed"] else ""
                lines.append(
                    f"田位 {plot} · {crop.name}生长中，剩余 {duration - (ctx.now - planted)} 秒{renew}"
                )
                links.append(InlineCommand(len(lines) - 1, "查看种子", "灵宠商店"))
        if opened and _tier(ctx, plot) < len(TIER_COST):
            lines.append(f"  可升级：{TIER_COST[_tier(ctx, plot)]} 灵石缩短该田 15% 生长时长")
            links.append(InlineCommand(len(lines) - 1, "升级灵田", f"灵宠升级 {plot}"))
    return Reply("灵宠灵田", tuple(lines), ("灵宠商店", "灵宠背包", "灵宠目标"), tuple(links))


def open_plot(ctx: Context, arg: str) -> Reply:
    plot = _plot_arg(ctx, arg)
    opened, _, _ = _plot_state(ctx, plot)
    if opened:
        raise GameError(f"田位 {plot} 已经开垦。")
    cost = OPEN_COST[plot - 1]
    player = ctx.player()
    if player.stones < cost:
        raise GameError(f"开垦田位 {plot} 需要 {cost} 灵石，当前灵石不足。")
    player.stones -= cost
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=1",
        (ctx.user_id, f"{OPEN_PREFIX}{plot}"),
    )
    return Reply("灵田开垦", (
        f"田位 {plot} 已开垦，花费 {cost} 灵石。",
        "现在可以播种种子了。",
    ), ("灵宠灵田", "灵宠商店"))


def plant(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠播种 <田位> <种子名>。")
    plot = _plot_arg(ctx, parts[0])
    opened, crop_row, _ = _plot_state(ctx, plot)
    if not opened:
        raise GameError(f"田位 {plot} 尚未开垦，请先发送 灵宠开垦 {plot}。")
    if crop_row is not None:
        raise GameError(f"田位 {plot} 已有作物在生长或待收获。")
    crop = _seed_arg(ctx, parts[1])
    if crop is None:
        raise GameError("未找到该作物，请检查种子名称。")
    _sow(ctx, plot, crop)
    seed = ctx.content.items[crop.seed_item]
    return Reply("灵田播种", (
        f"田位 {plot} 播下了{seed.name}，{_effective_duration(ctx, plot, crop.duration)} 秒后成熟。",
        "成熟后可在灵宠灵田收获。",
    ), ("灵宠灵田", "灵宠背包"))


def _sow(ctx: Context, plot: int, crop) -> None:
    """Consume one seed and start a growth row on the plot."""
    ctx.repo.consume_item(ctx.user_id, crop.seed_item, 1)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=0",
        (ctx.user_id, f"{CROP_PREFIX}{plot}_{crop.id}", ctx.now),
    )


def harvest(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) not in (1, 2):
        raise GameError("格式：灵宠收获 <田位> [补种种子名]。")
    plot = _plot_arg(ctx, parts[0])
    replant = _seed_arg(ctx, parts[1]) if len(parts) == 2 else None
    if replant is None and len(parts) == 2:
        raise GameError("未找到该作物，请检查种子名称。")
    opened, crop_row, _ = _plot_state(ctx, plot)
    if not opened:
        raise GameError(f"田位 {plot} 尚未开垦。")
    if crop_row is None:
        raise GameError(f"田位 {plot} 还没有播种。")
    crop = _crop(ctx, crop_row)
    planted = crop_row["progress"]
    duration = _growth_seconds(ctx, plot, crop)
    if ctx.now < planted:
        raise GameError("当前时间早于种植时间，请稍后再收获。")
    elapsed = ctx.now - planted
    if elapsed < duration:
        raise GameError(f"{crop.name}还在生长，剩余 {duration - elapsed} 秒。")
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id IN (?, ?)",
        (ctx.user_id, crop_row["quest_id"], f"{RENEW_PREFIX}{plot}"),
    )
    if elapsed >= duration + WILT_AFTER:
        if replant is not None:
            raise GameError(f"{crop.name}已枯萎，不能补种。")
        # Wilted: no yield, only the seed back.
        ctx.repo.add_item(ctx.user_id, crop.seed_item, 1)
        return Reply("灵田清理", (
            f"田位 {plot} 的{crop.name}已枯萎，只返还了种子。",
            "下次记得及时收获。",
        ), ("灵宠灵田", "灵宠背包"))
    gained = _grant_reward(ctx, crop)
    battle_pass.add_experience(ctx, "farm_harvest")
    if replant is not None:
        _sow(ctx, plot, replant)
        return Reply("灵田补种", (
            f"田位 {plot} 的{crop.name}成熟收获并已补种。",
            *gained,
            f"已消耗 1 个{ctx.content.items[replant.seed_item].name}，"
            f"{_effective_duration(ctx, plot, replant.duration)} 秒后成熟。",
        ), ("灵宠灵田", "灵宠背包"))
    return Reply("灵田收获", (
        f"田位 {plot} 的{crop.name}成熟收获。",
        *gained,
    ), ("灵宠灵田", "灵宠背包"))


def renew(ctx: Context, arg: str) -> Reply:
    plot = _plot_arg(ctx, arg)
    opened, crop_row, renew_row = _plot_state(ctx, plot)
    if not opened:
        raise GameError(f"田位 {plot} 尚未开垦。")
    if crop_row is None:
        raise GameError(f"田位 {plot} 还没有播种。")
    if crop_row["claimed"]:
        raise GameError(f"田位 {plot} 本次生长已经翻新过。")
    crop = _crop(ctx, crop_row)
    planted = crop_row["progress"]
    if ctx.now < planted:
        raise GameError("当前时间早于种植时间，请稍后再翻新。")
    remaining = _growth_seconds(ctx, plot, crop) - (ctx.now - planted)
    if remaining <= 0:
        raise GameError(f"{crop.name}已经成熟，无需翻新，请直接收获。")
    cost = max(1, remaining * RENEW_FRACTION // 100)
    cut = max(1, remaining * RENEW_FRACTION // 100)
    player = ctx.player()
    if player.stones < cost:
        raise GameError(f"翻新需要 {cost} 灵石，当前灵石不足。")
    player.stones -= cost
    # Persist the cut so harvest honours it, and flag the crop row so this growth
    # can only be renewed once. Both rows move in the caller's transaction.
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{RENEW_PREFIX}{plot}", cut),
    )
    ctx.repo.conn.execute(
        "UPDATE quest_progress SET claimed=1 WHERE user_id=? AND quest_id=?",
        (ctx.user_id, crop_row["quest_id"]),
    )
    return Reply("灵田翻新", (
        f"田位 {plot} 已翻新，花费 {cost} 灵石，成熟时间缩短 {cut} 秒。",
    ), ("灵宠灵田",))


def upgrade(ctx: Context, arg: str) -> Reply:
    plot = _plot_arg(ctx, arg)
    opened, _, _ = _plot_state(ctx, plot)
    if not opened:
        raise GameError(f"田位 {plot} 尚未开垦，请先发送 灵宠开垦 {plot}。")
    level = _tier(ctx, plot)
    if level >= len(TIER_COST):
        raise GameError(f"田位 {plot} 已升至最高等级。")
    cost = TIER_COST[level]
    player = ctx.player()
    if player.stones < cost:
        raise GameError(f"升级田位 {plot} 需要 {cost} 灵石，当前灵石不足。")
    player.stones -= cost
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, f"{TIER_PREFIX}{plot}", level + 1),
    )
    return Reply("灵田升级", (
        f"田位 {plot} 升至 {level + 1} 级，花费 {cost} 灵石。",
        f"该田生长时长缩短 {TIER_TIME_CUT}%。",
    ), ("灵宠灵田",))
