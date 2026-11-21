"""Route-based wild encounters and the durable capture journal."""

import json
from datetime import datetime

from ..application.context import Context
from ..domain.content import Range, Reward, Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity
from ..utils.randomness import weighted_choice
from ..utils.time import BEIJING, beijing_day
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .rewards import grant

TITLE = "灵宠野外"
PAGE_SIZE = 5
RARITY_NAMES = {"common": "常见", "uncommon": "少见", "rare": "稀有"}
RARITY_ALIASES = {"常见": "common", "少见": "uncommon", "稀有": "rare"}
STATE_NAMES = {"pending": "待收服", "captured": "已收服", "released": "已放归", "escaped": "已逃脱"}


def _route_rules(ctx: Context, route_id: str):
    return next(route for route in ctx.content.wild_capture.routes if route.route == route_id)


def _number(value: str, label: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise GameError(f"请填写有效的{label}编号。")
    number = int(value)
    if number < 1:
        raise GameError(f"请填写有效的{label}编号。")
    return number


def _latest_time(ctx: Context, user_id: str) -> int | None:
    row = ctx.repo.conn.execute(
        "SELECT MAX(value) AS latest FROM ("
        "SELECT started_at AS value FROM wild_capture_runs WHERE user_id=? "
        "UNION ALL SELECT finished_at FROM wild_capture_runs WHERE user_id=? AND finished_at IS NOT NULL "
        "UNION ALL SELECT a.attempted_at FROM wild_capture_attempts a "
        "JOIN wild_capture_runs r USING(run_id) WHERE r.user_id=?"
        ")",
        (user_id, user_id, user_id),
    ).fetchone()
    return int(row["latest"]) if row["latest"] is not None else None


def _check_clock(ctx: Context, user_id: str) -> str:
    today = beijing_day(ctx.now)
    row = ctx.repo.conn.execute(
        "SELECT MAX(day_key) AS latest_day FROM wild_capture_runs WHERE user_id=?", (user_id,),
    ).fetchone()
    if row["latest_day"] and today < row["latest_day"]:
        raise GameError("系统日期早于野外遭遇记录，请等待日期恢复。")
    latest = _latest_time(ctx, user_id)
    if latest is not None and ctx.now < latest:
        raise GameError("系统时间早于最近一次野外行动，请等待时钟恢复。")
    return today


def _expire_pending(ctx: Context, user_id: str):
    row = ctx.repo.conn.execute(
        "SELECT * FROM wild_capture_runs WHERE user_id=? AND state='pending'", (user_id,),
    ).fetchone()
    if row is None:
        return None
    if ctx.now < row["started_at"]:
        raise GameError("系统时间早于野外遭遇，请等待时钟恢复。")
    latest_attempt = ctx.repo.conn.execute(
        "SELECT MAX(attempted_at) FROM wild_capture_attempts WHERE run_id=?", (row["run_id"],),
    ).fetchone()[0]
    if latest_attempt is not None and ctx.now < latest_attempt:
        raise GameError("系统时间早于最近一次收服尝试，请等待时钟恢复。")
    if ctx.now >= row["expires_at"]:
        ctx.repo.conn.execute(
            "UPDATE wild_capture_runs SET state='escaped', terminal_reason='expired', finished_at=? "
            "WHERE run_id=? AND state='pending'",
            (ctx.now, row["run_id"]),
        )
        return None
    return row


def start_from_exploration(ctx: Context, route, selector: str = "") -> Reply:
    from . import adventure_travel
    from .pet_targets import target_pet
    from .quests import advance

    if adventure_travel.state(ctx):
        raise GameError("山海远行进行中，请继续或退出当前行程后再历练。")
    player = ctx.player()
    pet = target_pet(ctx, selector, "历练")
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == route.min_realm)
    if pet.realm < minimum:
        raise GameError(f"{route.name}需要{ctx.content.realms[minimum].name}境界。")

    day = _check_clock(ctx, ctx.user_id)
    existing_pending = ctx.repo.conn.execute(
        "SELECT run_id FROM wild_capture_runs WHERE user_id=? AND state='pending'", (ctx.user_id,),
    ).fetchone()
    pending = _expire_pending(ctx, ctx.user_id)
    if pending is not None:
        raise GameError(f"仍有野外遭遇待处理，请先收服或放归：发送 {TITLE}。")
    if existing_pending is not None:
        return Reply("野外遭遇已结束", (
            f"遭遇 #{existing_pending['run_id']} 已过期，野生灵宠逃脱；这次历练没有开始。",
        ), (TITLE, "灵宠历练", f"{TITLE} 战历"))
    count = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM wild_capture_runs WHERE user_id=? AND day_key=?",
        (ctx.user_id, day),
    ).fetchone()[0])
    if count >= ctx.content.wild_capture.daily_encounters:
        raise GameError("今日野外遭遇次数已用完，明日再来。")

    energy = ctx.content.rules.explore_energy
    ctx.check_action(player, pet, "explore", energy, ctx.config.spirit_pet_explore_cooldown)

    rules = ctx.content.wild_capture
    route_rules = _route_rules(ctx, route.id)
    rare_run = ctx.repo.conn.execute(
        "SELECT MAX(run_id) FROM wild_capture_runs WHERE user_id=? AND rarity='rare'",
        (ctx.user_id,),
    ).fetchone()[0]
    since_rare = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM wild_capture_runs WHERE user_id=? AND run_id>?",
        (ctx.user_id, rare_run or 0),
    ).fetchone()[0])
    pity_due = since_rare >= rules.rare_pity - 1
    entries = [entry for entry in route_rules.entries if not pity_due or entry.rarity == "rare"]
    entry = weighted_choice(ctx.rng, entries, [item.weight for item in entries])
    species = ctx.content.species[entry.species]
    enemy_definition = ctx.content.enemies[entry.enemy]

    pet.energy -= energy
    player.last_explore = ctx.now
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    advance(ctx, "explore")

    ally = combatant(ctx, ctx.user_id, recover_energy=False, pet_id=pet.pet_id)
    enemy = enemy_fighter(enemy_definition, ctx.content.skills)
    base_stats = enemy.stats.model_dump()
    enemy.stats = Stats(**{
        key: max(1, int(value * entry.enemy_scale + 0.5))
        for key, value in base_stats.items()
    })
    enemy.hp = enemy.stats.hp
    teams = ([ally], [enemy])
    capture = capture_snapshot(ctx, teams, ([ctx.user_id], []))
    battle = fight(*teams, ctx.rng, ctx.content.elements)
    lines = [f"{route.name} · 野外遭遇 · {species.name}（{RARITY_NAMES[entry.rarity]}）", *battle.lines]
    lines.extend(award_mastery(
        ctx, ctx.user_id, battle.skill_uses[0].get(pet.pet_id, {}), pet_id=pet.pet_id,
    ))
    if battle.winner == 0:
        state, reason = "pending", None
        lines.extend((
            f"{species.name}已被制伏，收服期限至 {datetime.fromtimestamp(ctx.now + rules.capture_window_seconds, BEIJING):%m-%d %H:%M}。",
            f"捕灵索：{rules.capture_rates[entry.rarity]:.0%} 基础成功率，最多 {rules.capture_attempts} 次；末次必定成功。",
        ))
    else:
        state = "escaped"
        reason = "battle_lost" if battle.winner == 1 else "battle_draw"
        lines.append("野生灵宠趁隙逃走，这次遭遇已结束。")
    lines.append(f"精力 -{energy}。")
    reply = Reply(
        "野外遭遇战胜" if battle.winner == 0 else "野外遭遇结束",
        tuple(lines), (TITLE, "灵宠战报", "灵宠历练", "灵宠目标"),
    )
    battle_id = record_battle(
        ctx, kind="pve", battle_key=f"wild_{route.id}", battle_name=f"{route.name}野外 · {species.name}",
        battle=battle, capture=capture, reply=reply,
    )
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now, {
        "kind": "wild_capture_encounter", "route_id": route.id, "pet_id": pet.pet_id,
        "species_id": species.id, "rarity": entry.rarity,
    }, reply)
    snapshot = {
        "entry": entry.model_dump(), "species": species.model_dump(),
        "enemy": enemy_definition.model_dump(), "enemy_stats": enemy.stats.model_dump(),
        "rules": {
            "capture_item_id": rules.capture_item,
            "capture_item_name": ctx.content.items[rules.capture_item].name,
            "capture_rate": rules.capture_rates[entry.rarity],
            "max_attempts": rules.capture_attempts,
            "same_species_limit": rules.same_species_limit,
        },
    }
    ctx.repo.conn.execute(
        "INSERT INTO wild_capture_runs(operation_id,user_id,route_id,route_name,day_key,species_id,"
        "species_name,rarity,enemy_id,enemy_name,enemy_snapshot,capture_item_id,capture_item_name,"
        "capture_rate,max_attempts,same_species_limit,state,terminal_reason,battle_id,started_at,"
        "expires_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ctx.operation_id, ctx.user_id, route.id, route.name, day, species.id, species.name,
            entry.rarity, enemy_definition.id, enemy_definition.name,
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            rules.capture_item, ctx.content.items[rules.capture_item].name,
            rules.capture_rates[entry.rarity], rules.capture_attempts, rules.same_species_limit,
            state, reason, battle_id, ctx.now, ctx.now + rules.capture_window_seconds,
            ctx.now if state != "pending" else None,
        ),
    )
    return reply


def _pending_page(ctx: Context, *, expire: bool) -> Reply:
    player = ctx.repo.player(ctx.user_id)
    if player is None:
        return Reply(TITLE, ("尚未结契，先完成领养，再到历练路线寻找野外灵宠。",),
                     ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))
    day = beijing_day(ctx.now)
    expired = False
    if expire:
        day = _check_clock(ctx, player.user_id)
        existing_pending = ctx.repo.conn.execute(
            "SELECT run_id FROM wild_capture_runs WHERE user_id=? AND state='pending'",
            (player.user_id,),
        ).fetchone()
        pending = _expire_pending(ctx, player.user_id)
        expired = existing_pending is not None and pending is None
    else:
        pending = ctx.repo.conn.execute(
            "SELECT * FROM wild_capture_runs WHERE user_id=? AND state='pending'", (player.user_id,),
        ).fetchone()
    used = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM wild_capture_runs WHERE user_id=? AND day_key=?",
        (player.user_id, day),
    ).fetchone()[0])
    found = int(ctx.repo.conn.execute(
        "SELECT COUNT(DISTINCT species_id) FROM wild_capture_runs WHERE user_id=? AND state='captured'",
        (player.user_id,),
    ).fetchone()[0])
    total_species = len({entry.species for route in ctx.content.wild_capture.routes for entry in route.entries})
    capture_name = pending["capture_item_name"] if pending is not None else ctx.content.items[
        ctx.content.wild_capture.capture_item
    ].name
    lines = [
        f"今日野外遭遇：{used}/{ctx.content.wild_capture.daily_encounters}。",
        f"收服图鉴：{found}/{total_species} 种 · 收服道具：{capture_name}。",
        _survey_progress_summary(ctx, player.user_id),
    ]
    if expired:
        lines.append("上一场野外遭遇已过期，野生灵宠逃脱。")
    links = []
    if pending is not None:
        species = ctx.content.species[pending["species_id"]]
        lines.append(
            f"遭遇 #{pending['run_id']}：{pending['route_name']} · {species.name}（{RARITY_NAMES[pending['rarity']]}）"
        )
        count = pending["attempt_count"]
        lines.append(f"已尝试 {count}/{pending['max_attempts']} 次 · {pending['expires_at'] - ctx.now} 秒后逃脱。")
        inventory = ctx.repo.inventory(player.user_id).get(pending["capture_item_id"], 0)
        if inventory:
            lines.append(f"{pending['capture_item_name']} {inventory} 枚 · 当前概率 {pending['capture_rate']:.0%}。")
            links.append(InlineCommand(
                len(lines) - 1, "尝试收服",
                f"{TITLE} 尝试 {pending['run_id']} {count + 1}",
            ))
        else:
            lines.append("背包里没有捕灵索；可查看今日特供。")
            links.append(InlineCommand(len(lines) - 1, "查看特供", "灵宠特供"))
        lines.append("也可以放归，让下一次历练寻找新的遭遇。")
        links.append(InlineCommand(
            len(lines) - 1, "放归", f"{TITLE} 放归 {pending['run_id']} {count}",
        ))
    else:
        lines.append("没有待处理遭遇；从历练路线页选择野外入口。")
        links.append(InlineCommand(len(lines) - 1, "查看历练路线", "灵宠历练"))
    return Reply(
        TITLE, tuple(lines), (TITLE, f"{TITLE} 图鉴", f"{TITLE} 调查", f"{TITLE} 战历"), tuple(links),
    )


def _filtered_entries(ctx: Context, parts: list[str]):
    routes = {route.route: route for route in ctx.content.wild_capture.routes}
    route_filter = None
    rarity_filter = None
    page = 1
    if not parts:
        pass
    elif parts[0] == "路线" and len(parts) in (2, 3):
        selected = named(ctx.content.exploration_routes, parts[1])
        route_filter = selected.id
        page = quantity(parts[2], 999) if len(parts) == 3 else 1
    elif parts[0] == "稀有度" and len(parts) in (2, 3):
        rarity_filter = RARITY_ALIASES.get(parts[1], parts[1])
        if rarity_filter not in RARITY_NAMES:
            raise GameError("稀有度可选：常见、少见、稀有。")
        page = quantity(parts[2], 999) if len(parts) == 3 else 1
    elif len(parts) == 1:
        page = quantity(parts[0], 999)
    elif len(parts) == 2 and parts[0] == "页":
        page = quantity(parts[1], 999)
    else:
        raise GameError(f"格式：{TITLE} 图鉴 [页码|路线 路线名 [页码]|稀有度 常见|少见|稀有 [页码]]。")

    entries = [
        (route.route, entry)
        for route in ctx.content.wild_capture.routes
        if route_filter is None or route.route == route_filter
        for entry in route.entries
        if rarity_filter is None or entry.rarity == rarity_filter
    ]
    return routes, entries, page, route_filter, rarity_filter


def _codex(ctx: Context, parts: list[str]) -> Reply:
    routes, entries, page, route_filter, rarity_filter = _filtered_entries(ctx, parts)
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"野外图鉴共 {pages} 页。")
    captured = {
        row["species_id"] for row in ctx.repo.conn.execute(
            "SELECT DISTINCT species_id FROM wild_capture_runs WHERE user_id=? AND state='captured'",
            (ctx.user_id,),
        )
    }
    selected = entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = [f"收服发现：{len(captured)}/{len({entry.species for _, entry in entries})} 种。"]
    links = []
    for route_id, entry in selected:
        species = ctx.content.species[entry.species]
        state = "已收服" if species.id in captured else "未收服"
        route = ctx.content.exploration_routes[route_id]
        lines.append(f"[{state}] {species.name} · {route.name} · {RARITY_NAMES[entry.rarity]}")
        links.append(InlineCommand(
            len(lines) - 1, "前往此路线",
            f"灵宠历练 {route.name} 野外",
        ))
    def page_command(value: int) -> str:
        if route_filter:
            return f"{TITLE} 图鉴 路线 {routes[route_filter].name} {value}"
        if rarity_filter:
            return f"{TITLE} 图鉴 稀有度 {RARITY_NAMES[rarity_filter]} {value}"
        return f"{TITLE} 图鉴 {value}"
    commands = [TITLE]
    if page > 1:
        commands.append(page_command(page - 1))
    if page < pages:
        commands.append(page_command(page + 1))
    commands.append(f"{TITLE} 战历")
    return Reply(f"{TITLE}图鉴 {page}/{pages}", tuple(lines), tuple(commands[:4]), tuple(links))


def _history(ctx: Context, parts: list[str]) -> Reply:
    if not parts:
        page = 1
    elif len(parts) == 1:
        page = quantity(parts[0], 999)
    elif len(parts) == 2 and parts[0] == "页":
        page = quantity(parts[1], 999)
    else:
        raise GameError(f"格式：{TITLE} 战历 [页码]。")
    total = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM wild_capture_runs WHERE user_id=?", (ctx.user_id,),
    ).fetchone()[0])
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"野外战历共 {pages} 页。")
    rows = ctx.repo.conn.execute(
        "SELECT run_id,route_name,species_name,rarity,state,attempt_count,battle_id,started_at,expires_at "
        "FROM wild_capture_runs WHERE user_id=? ORDER BY run_id DESC LIMIT ? OFFSET ?",
        (ctx.user_id, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    lines = [f"遭遇记录 {total} 次 · 第 {page}/{pages} 页。"]
    links = []
    for row in rows:
        state = "期限已过·待结算" if row["state"] == "pending" and ctx.now >= row["expires_at"] else STATE_NAMES[row["state"]]
        lines.append(
            f"#{row['run_id']} · {row['route_name']} · {row['species_name']}（{RARITY_NAMES[row['rarity']]}）"
            f"· {state} · 捕获尝试 {row['attempt_count']} 次"
        )
        links.append(InlineCommand(
            len(lines) - 1, "查看战报", f"灵宠战报 查看 {row['battle_id']}",
        ))
    commands = [TITLE]
    if page > 1:
        commands.append(f"{TITLE} 战历 {page - 1}")
    if page < pages:
        commands.append(f"{TITLE} 战历 {page + 1}")
    commands.append(f"{TITLE} 图鉴")
    return Reply(f"{TITLE}战历 {page}/{pages}", tuple(lines), tuple(commands[:4]), tuple(links))


def _survey_evidence(ctx: Context, user_id: str, route_id: str) -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    rows = ctx.repo.conn.execute(
        "SELECT species_id,species_name,rarity FROM wild_capture_runs "
        "WHERE user_id=? AND route_id=? ORDER BY run_id",
        (user_id, route_id),
    )
    for row in rows:
        entry = evidence.setdefault(row["species_id"], {
            "name": row["species_name"], "rarities": set(),
        })
        entry["rarities"].add(row["rarity"])
    return evidence


def _survey_claims(ctx: Context, user_id: str, route_id: str | None = None) -> set[tuple[str, str]]:
    query = "SELECT route_id,tier_id FROM wild_survey_claims WHERE user_id=?"
    parameters: tuple = (user_id,)
    if route_id is not None:
        query += " AND route_id=?"
        parameters += (route_id,)
    return {
        (row["route_id"], row["tier_id"])
        for row in ctx.repo.conn.execute(query, parameters)
    }


def _survey_progress_summary(ctx: Context, user_id: str) -> str:
    claims = _survey_claims(ctx, user_id)
    found_count = 0
    total_count = 0
    claimable_count = 0
    next_target = None
    for route_rules in ctx.content.wild_capture.routes:
        route = ctx.content.exploration_routes[route_rules.route]
        survey = ctx.content.wild_surveys[route.id]
        evidence = _survey_evidence(ctx, user_id, route.id)
        route_species = {entry.species for entry in route_rules.entries}
        seen = set(evidence) & route_species
        rarities = {rarity for entry in evidence.values() for rarity in entry["rarities"]}
        found_count += len(seen)
        total_count += len(route_species)
        for tier in survey.tiers:
            met = _survey_tier_met(tier, seen, rarities)
            claimed = (route.id, tier.id) in claims
            if met and not claimed:
                claimable_count += 1
            elif not claimed and next_target is None:
                next_target = (survey.title, tier.name)
    if claimable_count:
        return f"栖地调查：已见 {found_count}/{total_count} 种 · 可领奖 {claimable_count} 档。"
    if next_target:
        return f"栖地调查：已见 {found_count}/{total_count} 种 · 下一档 {next_target[0]}·{next_target[1]}。"
    return f"栖地调查：全路线档位已领 · {found_count}/{total_count} 种。"


def _survey_tier_met(tier, species_ids: set[str], rarities: set[str]) -> bool:
    return len(species_ids) >= tier.species_count and set(tier.required_rarities) <= rarities


def _survey_reward_label(ctx: Context, tier) -> str:
    reward = tier.reward
    values = [f"灵石 {reward.stones}"] if reward.stones else []
    values.extend(f"{ctx.content.items[item_id].name} {amount}" for item_id, amount in reward.items.items())
    return "、".join(values)


def _survey_tier_state(tier, route_id: str, seen: set[str], rarities: set[str], claims: set[tuple[str, str]]) -> str:
    if (route_id, tier.id) in claims:
        return "已领取"
    if _survey_tier_met(tier, seen, rarities):
        return "可领取"
    requirements = [f"物种 {len(seen)}/{tier.species_count}"]
    missing_rarities = set(tier.required_rarities) - rarities
    if missing_rarities:
        requirements.append("待见 " + "、".join(RARITY_NAMES[item] for item in sorted(missing_rarities)))
    return "待完成：" + " · ".join(requirements)


def _survey_overview(ctx: Context, page: int) -> Reply:
    routes = [ctx.content.exploration_routes[route.route] for route in ctx.content.wild_capture.routes]
    pages = max(1, (len(routes) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"栖地调查共 {pages} 页。")
    claims = _survey_claims(ctx, ctx.user_id)
    selected = routes[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = ["调查只统计真实野外遭遇；同一路线内重复遇见同一物种只计一次。"]
    links = []
    for route in selected:
        survey = ctx.content.wild_surveys[route.id]
        evidence = _survey_evidence(ctx, ctx.user_id, route.id)
        species = {entry.species for entry in _route_rules(ctx, route.id).entries}
        seen = species & evidence.keys()
        rarities = {rarity for entry in evidence.values() for rarity in entry["rarities"]}
        claimable = sum(
            _survey_tier_met(tier, seen, rarities) and (route.id, tier.id) not in claims
            for tier in survey.tiers
        )
        next_tier = next((tier for tier in survey.tiers if (route.id, tier.id) not in claims), None)
        if next_tier is None:
            progress = "全部档位已领"
        else:
            progress = _survey_tier_state(next_tier, route.id, seen, rarities, claims)
        suffix = f" · 可领奖 {claimable} 档" if claimable else ""
        lines.append(f"{survey.title} · 物种 {len(seen)}/{len(species)} · {progress}{suffix}")
        links.append(InlineCommand(len(lines) - 1, "查看栖地", f"{TITLE} 调查 {route.name}"))
    commands = [TITLE]
    if page > 1:
        commands.append(f"{TITLE} 调查 {page - 1}")
    if page < pages:
        commands.append(f"{TITLE} 调查 {page + 1}")
    commands.extend((f"{TITLE} 图鉴", "灵宠历练"))
    return Reply(f"{TITLE}栖地调查 {page}/{pages}", tuple(lines), tuple(commands[:4]), tuple(links))


def _survey_route(ctx: Context, route, page: int = 1) -> Reply:
    survey = ctx.content.wild_surveys[route.id]
    entries = _route_rules(ctx, route.id).entries
    pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise GameError(f"{survey.title}物种记录共 {pages} 页。")
    evidence = _survey_evidence(ctx, ctx.user_id, route.id)
    species_ids = set(evidence) & {entry.species for entry in entries}
    rarities = {rarity for entry in evidence.values() for rarity in entry["rarities"]}
    claims = _survey_claims(ctx, ctx.user_id, route.id)
    lines = [survey.description, f"已观察 {len(species_ids)}/{len(entries)} 种 · 稀有发现："]
    observed_rarities = sorted(rarities, key=("common", "uncommon", "rare").index)
    lines[-1] += "、".join(RARITY_NAMES[item] for item in observed_rarities) if observed_rarities else "暂无"
    links = []
    for entry in entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        species = ctx.content.species[entry.species]
        record = evidence.get(entry.species)
        if record:
            rarity_text = "、".join(
                RARITY_NAMES[item] for item in sorted(record["rarities"], key=("common", "uncommon", "rare").index)
            )
            lines.append(f"[已见] {species.name} · {rarity_text}")
        else:
            lines.append(f"[未见] {species.name} · {RARITY_NAMES[entry.rarity]}")
    for tier in survey.tiers:
        state = _survey_tier_state(tier, route.id, species_ids, rarities, claims)
        lines.append(f"{tier.name}（{tier.id}）· {_survey_reward_label(ctx, tier)} · {state}")
        if state == "可领取":
            links.append(InlineCommand(
                len(lines) - 1, "领取调查奖励", f"{TITLE} 调查领奖 {route.name} {tier.id}",
            ))
    commands = [TITLE, f"{TITLE} 调查"]
    if page > 1:
        commands.append(f"{TITLE} 调查 {route.name} {page - 1}")
    if page < pages:
        commands.append(f"{TITLE} 调查 {route.name} {page + 1}")
    commands.append(f"灵宠历练 {route.name}")
    return Reply(f"{survey.title}调查 {page}/{pages}", tuple(lines), tuple(commands[:4]), tuple(links))


def _survey(ctx: Context, parts: list[str]) -> Reply:
    if not parts:
        return _survey_overview(ctx, 1)
    if len(parts) == 1 and parts[0] in {"页", "路线"}:
        raise GameError(f"格式：{TITLE} 调查 [页码|路线名 [页码]]。")
    if len(parts) == 1 and parts[0].isascii() and parts[0].isdecimal():
        return _survey_overview(ctx, quantity(parts[0], 999))
    if len(parts) == 2 and parts[0] == "页":
        return _survey_overview(ctx, quantity(parts[1], 999))
    route_arg = parts[0]
    route = named(ctx.content.exploration_routes, route_arg)
    page = 1
    if len(parts) == 2:
        page = quantity(parts[1], 999)
    elif len(parts) == 3 and parts[1] == "页":
        page = quantity(parts[2], 999)
    elif len(parts) != 1:
        raise GameError(f"格式：{TITLE} 调查 [页码|路线名 [页码]]。")
    return _survey_route(ctx, route, page)


def _survey_claim(ctx: Context, parts: list[str]) -> Reply:
    if len(parts) != 2:
        raise GameError(f"格式：{TITLE} 调查领奖 路线名 档位ID。")
    player = ctx.player()
    route = named(ctx.content.exploration_routes, parts[0])
    survey = ctx.content.wild_surveys[route.id]
    tier = next((entry for entry in survey.tiers if entry.id == parts[1]), None)
    if tier is None:
        raise GameError("未找到该栖地调查档位。")
    prior = ctx.repo.conn.execute(
        "SELECT user_id,reply FROM wild_survey_claims WHERE operation_id=?", (ctx.operation_id,),
    ).fetchone()
    if prior is not None:
        if prior["user_id"] != player.user_id:
            raise GameError("该调查领奖操作已由其他身份处理，不能复用。")
        return Reply.from_data(json.loads(prior["reply"]))
    if ctx.repo.conn.execute(
        "SELECT 1 FROM wild_survey_claims WHERE user_id=? AND route_id=? AND tier_id=?",
        (player.user_id, route.id, tier.id),
    ).fetchone() is not None:
        raise GameError("该栖地调查档位已经领取。")
    evidence = _survey_evidence(ctx, player.user_id, route.id)
    route_species = {entry.species for entry in _route_rules(ctx, route.id).entries}
    seen = set(evidence) & route_species
    rarities = {rarity for entry in evidence.values() for rarity in entry["rarities"]}
    if not _survey_tier_met(tier, seen, rarities):
        raise GameError("真实野外观察尚未达到该调查档位。")
    reward = Reward(
        exp=Range(minimum=0, maximum=0),
        stones=Range(minimum=tier.reward.stones, maximum=tier.reward.stones),
        items={item_id: Range(minimum=amount, maximum=amount) for item_id, amount in tier.reward.items.items()},
    )
    granted = grant(ctx, reward, player.user_id)
    reply = Reply(
        "栖地调查奖励", (f"{survey.title}·{tier.name}已领取。", *granted),
        (f"{TITLE} 调查 {route.name}", f"{TITLE} 调查", "灵宠目标"),
    )
    reward_snapshot = json.dumps(tier.reward.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    reply_data = json.dumps({
        "title": reply.title,
        "lines": reply.lines,
        "commands": reply.commands,
        "inline_commands": reply.inline_commands,
    }, ensure_ascii=False)
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
        "kind": "wild_survey_claim", "route_id": route.id, "tier_id": tier.id,
        "reward": json.loads(reward_snapshot),
    }, reply)
    ctx.repo.conn.execute(
        "INSERT INTO wild_survey_claims(user_id,route_id,tier_id,operation_id,claimed_at,reward_snapshot,reply) "
        "VALUES (?,?,?,?,?,?,?)",
        (player.user_id, route.id, tier.id, ctx.operation_id, ctx.now, reward_snapshot, reply_data),
    )
    return reply


def _attempt(ctx: Context, run_id: int, attempt_no: int) -> Reply:
    player = ctx.player()
    run = ctx.repo.conn.execute(
        "SELECT * FROM wild_capture_runs WHERE run_id=? AND user_id=?", (run_id, player.user_id),
    ).fetchone()
    if run is None:
        raise GameError("野外遭遇不存在，或不属于你。")
    if run["state"] != "pending":
        raise GameError("这次野外遭遇已经结束，请查看野外战历。")
    if ctx.now < run["started_at"]:
        raise GameError("系统时间早于野外遭遇，请等待时钟恢复。")
    if ctx.now >= run["expires_at"]:
        reply = Reply("野外遭遇已结束", ("收服期限已过，野生灵宠已经逃脱。",), (TITLE, f"{TITLE} 战历"))
        ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
            "kind": "wild_capture_expire", "run_id": run_id, "attempt_no": attempt_no,
        }, reply)
        ctx.repo.conn.execute(
            "UPDATE wild_capture_runs SET state='escaped',terminal_reason='expired',finished_at=? "
            "WHERE run_id=? AND state='pending'", (ctx.now, run_id),
        )
        return reply
    if attempt_no != run["attempt_count"] + 1:
        raise GameError(f"收服次数已变化；下一次应为第 {run['attempt_count'] + 1} 次。请重新打开 {TITLE}。")
    max_attempts = int(run["max_attempts"])
    if attempt_no > max_attempts:
        raise GameError("这次遭遇已达到捕获尝试上限，请收取保底或放归。")
    item_id, item_name = run["capture_item_id"], run["capture_item_name"]
    if ctx.repo.inventory(player.user_id).get(item_id, 0) < 1:
        raise GameError(f"缺少{item_name}，请查看 灵宠特供。")
    roster_count = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM pets WHERE user_id=? AND archived=0", (player.user_id,),
    ).fetchone()[0])
    species_count = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM pets WHERE user_id=? AND species_id=? AND archived=0",
        (player.user_id, run["species_id"]),
    ).fetchone()[0])
    if roster_count >= ctx.config.spirit_pet_max_pets:
        raise GameError(f"在册名额已满（{roster_count}/{ctx.config.spirit_pet_max_pets}），整理名册后可继续；本次未消耗捕灵索。")
    if species_count >= run["same_species_limit"]:
        raise GameError(f"在册{run['species_name']}已达同种上限 {run['same_species_limit']} 只，整理名册后可继续；本次未消耗捕灵索。")

    latest_attempt = ctx.repo.conn.execute(
        "SELECT MAX(attempted_at) FROM wild_capture_attempts WHERE run_id=?", (run_id,),
    ).fetchone()[0]
    if latest_attempt is not None and ctx.now < latest_attempt:
        raise GameError("系统时间早于最近一次收服尝试，请等待时钟恢复。")
    rate = float(run["capture_rate"])
    roll = ctx.rng.random()
    success = attempt_no == max_attempts or roll < rate
    next_state = "captured" if success else "pending"
    next_attempts = attempt_no
    lines = []
    pet = None
    first_species = success and ctx.repo.conn.execute(
        "SELECT 1 FROM wild_capture_runs WHERE user_id=? AND species_id=? AND state='captured' LIMIT 1",
        (player.user_id, run["species_id"]),
    ).fetchone() is None
    if success:
        species_snapshot = json.loads(run["enemy_snapshot"])["species"]
        pet = ctx.repo.create_pet(
            player.user_id, run["species_id"], species_snapshot["name"],
            species_snapshot["initial_affinity"], ctx.now,
        )
        if first_species:
            ctx.repo.conn.execute(
                "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?, 'wild_capture_codex', 1, 0) "
                "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=progress+1",
                (player.user_id,),
            )
        lines.append(f"收服成功：{pet.name}加入在册名册，编号 {pet.pet_id}。出战阵容未更改。")
        if first_species:
            lines.append("新物种已记录进野外收服图鉴与目标进度。")
    else:
        lines.append(f"{item_name}化作灵光，{run['species_name']}仍未归契。")
        lines.append(f"已尝试 {next_attempts}/{max_attempts} 次。")
    reply = Reply(
        "野外收服成功" if success else "野外收服未成",
        tuple(lines), (TITLE, "灵宠列表", f"{TITLE} 图鉴", f"{TITLE} 战历"),
    )
    ctx.repo.consume_item(player.user_id, item_id, 1)
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
        "kind": "wild_capture_attempt", "run_id": run_id, "attempt_no": attempt_no,
        "item_id": item_id, "success": success, "pet_id": pet.pet_id if pet else None,
    }, reply)
    cursor = ctx.repo.conn.execute(
        "INSERT INTO wild_capture_attempts(run_id,operation_id,attempt_no,item_id,catch_rate,roll,succeeded,attempted_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (run_id, ctx.operation_id, attempt_no, item_id, rate, roll, int(success), ctx.now),
    )
    if cursor.rowcount != 1:
        raise GameError("收服回执写入失败，请重试。")
    update = ctx.repo.conn.execute(
        "UPDATE wild_capture_runs SET attempt_count=?,state=?,terminal_reason=?,captured_pet_id=?,finished_at=? "
        "WHERE run_id=? AND user_id=? AND state='pending' AND attempt_count=?",
        (
            next_attempts, next_state, "caught" if success else None, pet.pet_id if pet else None,
            ctx.now if success else None, run_id, player.user_id, attempt_no - 1,
        ),
    )
    if update.rowcount != 1:
        raise GameError("这次遭遇已被其他操作处理，请重新打开野外页面。")
    return reply


def _release(ctx: Context, run_id: int, attempt_no: int) -> Reply:
    player = ctx.player()
    run = ctx.repo.conn.execute(
        "SELECT * FROM wild_capture_runs WHERE run_id=? AND user_id=?", (run_id, player.user_id),
    ).fetchone()
    if run is None:
        raise GameError("野外遭遇不存在，或不属于你。")
    if run["state"] != "pending":
        raise GameError("这次野外遭遇已经结束，请查看野外战历。")
    if ctx.now < run["started_at"]:
        raise GameError("系统时间早于野外遭遇，请等待时钟恢复。")
    if ctx.now >= run["expires_at"]:
        reply = Reply("野外遭遇已结束", ("收服期限已过，野生灵宠已经逃脱。",), (TITLE, f"{TITLE} 战历"))
        ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
            "kind": "wild_capture_expire", "run_id": run_id, "attempt_no": attempt_no,
        }, reply)
        ctx.repo.conn.execute(
            "UPDATE wild_capture_runs SET state='escaped',terminal_reason='expired',finished_at=? "
            "WHERE run_id=? AND state='pending'", (run["expires_at"], run_id),
        )
        return reply
    latest_attempt = ctx.repo.conn.execute(
        "SELECT MAX(attempted_at) FROM wild_capture_attempts WHERE run_id=?", (run_id,),
    ).fetchone()[0]
    if latest_attempt is not None and ctx.now < latest_attempt:
        raise GameError("系统时间早于最近一次收服尝试，请等待时钟恢复。")
    if attempt_no != run["attempt_count"]:
        raise GameError("遭遇状态已变化，请重新打开野外页面后再放归。")
    reply = Reply("野外灵宠已放归", (
        f"{run['species_name']}已回到山海之间，#{run_id} 遭遇结束。",
        "捕灵索未消耗。",
    ), (TITLE, f"{TITLE} 图鉴", f"{TITLE} 战历"))
    ctx.repo.record_duel_action(ctx.operation_id, player.user_id, ctx.now, {
        "kind": "wild_capture_release", "run_id": run_id, "attempt_no": attempt_no,
    }, reply)
    ctx.repo.conn.execute(
        "UPDATE wild_capture_runs SET state='released',terminal_reason='released',finished_at=? "
        "WHERE run_id=? AND user_id=? AND state='pending' AND attempt_count=?",
        (ctx.now, run_id, player.user_id, attempt_no),
    )
    return reply


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts or parts[0] in {"当前", "遭遇"}:
        return _pending_page(ctx, expire=True)
    action, rest = parts[0], parts[1:]
    if action == "图鉴":
        if ctx.repo.player(ctx.user_id) is None:
            return Reply(TITLE + "图鉴", ("尚未结契。",), ("灵宠帮助",))
        return _codex(ctx, rest)
    if action == "调查":
        return _survey(ctx, rest)
    if action == "调查领奖":
        return _survey_claim(ctx, rest)
    if action == "战历":
        if ctx.repo.player(ctx.user_id) is None:
            return Reply(TITLE + "战历", ("尚未结契。",), ("灵宠帮助",))
        return _history(ctx, rest)
    if action == "尝试" and len(rest) == 2:
        return _attempt(ctx, _number(rest[0], "遭遇"), quantity(rest[1], 5))
    if action == "放归" and len(rest) == 2:
        return _release(ctx, _number(rest[0], "遭遇"), quantity(rest[1], 5) if rest[1] != "0" else 0)
    raise GameError(
        f"格式：{TITLE} [当前|图鉴 [页码|路线 路线名|稀有度 常见|少见|稀有]|调查 [路线名 [页码]]|调查领奖 路线名 档位ID|战历 [页码]|尝试 遭遇编号 次数|放归 遭遇编号 已尝试次数]。"
    )


def read_only(argument: str) -> bool:
    parts = argument.split()
    return bool(parts and parts[0] in {"图鉴", "战历", "调查"})


def today_line(ctx: Context, user_id: str) -> str:
    player = ctx.repo.player(user_id)
    if player is None:
        return ""
    day = beijing_day(ctx.now)
    used = int(ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM wild_capture_runs WHERE user_id=? AND day_key=?", (user_id, day),
    ).fetchone()[0])
    pending = ctx.repo.conn.execute(
        "SELECT run_id,species_name,expires_at FROM wild_capture_runs "
        "WHERE user_id=? AND state='pending'", (user_id,),
    ).fetchone()
    if pending:
        detail = "期限已过，请打开野外页结算逃脱" if ctx.now >= pending["expires_at"] else f"{pending['species_name']}待收服"
        return f"野外遭遇：{detail} · 局号 {pending['run_id']} · {_survey_progress_summary(ctx, user_id)}"
    remaining = max(0, ctx.content.wild_capture.daily_encounters - used)
    if remaining:
        return f"野外遭遇：今日还可寻找 {remaining} 次 · {_survey_progress_summary(ctx, user_id)}"
    summary = _survey_progress_summary(ctx, user_id)
    return "" if summary.startswith("栖地调查：全路线档位已领") else summary


def objective_line(ctx: Context, user_id: str) -> str:
    found = int(ctx.repo.conn.execute(
        "SELECT COUNT(DISTINCT species_id) FROM wild_capture_runs WHERE user_id=? AND state='captured'",
        (user_id,),
    ).fetchone()[0])
    total = len({entry.species for route in ctx.content.wild_capture.routes for entry in route.entries})
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='wild_capture_codex'", (user_id,),
    ).fetchone()
    progress = int(row["progress"]) if row else 0
    return f"野外收服：图鉴 {found}/{total} 种 · 新物种目标进度 {progress}。 {_survey_progress_summary(ctx, user_id)}"
