"""Guardian telegraphs and durable duel action snapshots."""

import json
from dataclasses import replace
from datetime import datetime

from ..application.context import Context
from ..domain.content import DuelRule
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.arguments import quantity
from ..utils.time import BEIJING

NAMES = {"assault": "抢攻", "guard": "稳守", "feint": "游斗"}
COUNTER = {"assault": "guard", "guard": "feint", "feint": "assault"}


def preview_pet(ctx: Context):
    player = ctx.player()
    if player.active_pet_id is None:
        raise ctx.missing_pet()
    pet = ctx.repo.pet(player.active_pet_id)
    if pet.archived:
        raise ctx.archived_active_pet(pet, ctx.user_id)
    pet = replace(pet)
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    return pet


def opening(ctx: Context, pet, opponent, *, legacy=False) -> dict:
    return {
        "id": ctx.operation_id, "pet_id": pet.pet_id, "pet_name": pet.name,
        "opponent": opponent.model_dump(mode="json"),
        "rule": ctx.content.rules.duel.model_dump(mode="json"), "legacy": legacy,
    }


def rule(ctx: Context, current: dict | None) -> DuelRule:
    if current and current.get("bout"):
        return DuelRule.model_validate(current["bout"]["rule"])
    return ctx.content.rules.duel


def intent(current: dict) -> str | None:
    if not current.get("bout") or current["bout"]["legacy"]:
        return None
    cycle = current["opponent"].intents
    return cycle[(current["round"] - 1) % len(cycle)]


def response(move: str | None, stance: str) -> tuple[str, float, float]:
    if move is None:
        return "旧局平招", 1.0, 1.0
    if COUNTER[move] == stance:
        return "破招", 1.15, 0.85
    if move == stance:
        return "平招", 1.0, 1.0
    return "受制", 0.85, 1.15


def preview_lines(ctx: Context, current: dict) -> list[str]:
    move = intent(current)
    rules = rule(ctx, current)
    lines = [f"护法将出：{NAMES[move]}" if move else "旧局沿用平招；本场结束后启用观招。"]
    for key, stance in rules.stances.items():
        outcome, dealt, taken = response(move, key)
        lines.append(f"{stance.name}：{outcome} · 出手出伤 ×{stance.dealt * dealt:.3f} / 承伤 ×{stance.taken * taken:.3f}")
    return lines


def blocked(ctx: Context, pet, current: dict | None = None) -> str | None:
    if current and current.get("bout") and pet.pet_id != current["bout"]["pet_id"]:
        return f"本场由{current['bout']['pet_name']}（编号 {current['bout']['pet_id']}）开局，请将原伙伴调回首位，或认输。"
    expedition = ctx.repo.active_expedition(pet.pet_id)
    if expedition is not None:
        state = "正在外出派遣" if ctx.now < expedition["finishes_at"] else "派遣已完成，奖励待领取"
        return f"{pet.name}{state}，斗法暂时无法继续。"
    cost = rule(ctx, current).energy
    if pet.energy < cost:
        return f"{pet.name}精力不足，斗法每回合需要 {cost} 点。"
    return None


def record(ctx: Context, bout: dict, event: str, status: str, reply: Reply, **details) -> Reply:
    ctx.repo.record_duel_action(
        ctx.operation_id, ctx.user_id, ctx.now,
        {"bout": bout, "event": event, "status": status, **details}, reply,
    )
    return reply


def review(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if parts and parts[0] == "查看":
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit() or len(parts[1]) > 18:
            raise GameError("格式：灵宠斗法 回顾 查看 编号。")
        row = ctx.repo.conn.execute(
            "SELECT * FROM duel_actions WHERE user_id=? AND action_id=?", (ctx.user_id, int(parts[1])),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") in ("stage_tactic", "cooking", "tracking", "herbalism", "nursery", "play_course", "training", "convoy", "farm_care", "pill_furnace", "angling"):
            raise GameError("未找到本人的斗法回合记录。")
        saved = Reply.from_data(json.loads(row["reply"]))
        # Historical actions must not expose live attack/surrender controls.
        return Reply("斗法回顾 · " + saved.title, saved.lines, ("灵宠斗法 回顾", "灵宠斗法", "我的灵宠"))
    count = ctx.repo.conn.execute(
        "SELECT COUNT(*) FROM duel_actions WHERE user_id=? "
        "AND (json_extract(snapshot, '$.kind') IS NULL OR json_extract(snapshot, '$.kind') NOT IN ('stage_tactic','cooking','tracking','herbalism','nursery','play_course','training','convoy','farm_care','pill_furnace','angling'))",
        (ctx.user_id,),
    ).fetchone()[0]
    number = quantity(arg or "1", 999)
    pages = max(1, (count + 4) // 5)
    if number > pages:
        raise GameError(f"斗法回顾共 {pages} 页。")
    rows = ctx.repo.conn.execute(
        "SELECT action_id,created_at,snapshot FROM duel_actions WHERE user_id=? "
        "AND (json_extract(snapshot, '$.kind') IS NULL OR json_extract(snapshot, '$.kind') NOT IN ('stage_tactic','cooking','tracking','herbalism','nursery','play_course','training','convoy','farm_care','pill_furnace','angling')) "
        "ORDER BY action_id DESC LIMIT 5 OFFSET ?",
        (ctx.user_id, (number - 1) * 5),
    ).fetchall()
    lines, links = [], []
    for row in rows:
        entry = json.loads(row["snapshot"])
        bout = entry["bout"]
        stamp = datetime.fromtimestamp(row["created_at"], BEIJING).strftime("%Y-%m-%d %H:%M")
        event = {"start": "开局", "exchange": "出手", "forfeit": "认输"}[entry["event"]]
        lines.append(f"{row['action_id']} · {stamp} · {bout['pet_name']} 对 {bout['opponent']['name']} · {event} {entry.get('round', 1)}")
        links.append(InlineCommand(len(lines) - 1, "查看回合", f"灵宠斗法 回顾 查看 {row['action_id']}"))
    if not rows:
        lines.append("尚无回合记录；往期胜绩仍可在斗法战历中查看。")
    commands = []
    if number > 1:
        commands.append(f"灵宠斗法 回顾 {number - 1}")
    if number < pages:
        commands.append(f"灵宠斗法 回顾 {number + 1}")
    return Reply(f"斗法回顾 · {number}/{pages}", tuple(lines), (*commands, "灵宠斗法", "灵宠斗法 战历"), tuple(links))


def detail(ctx: Context, arg: str) -> Reply:
    from . import duel

    opponent = duel._opponent(ctx, arg)
    current = {"opponent": opponent, "round": 1, "bout": {"legacy": False}}
    current["bout"]["rule"] = ctx.content.rules.duel.model_dump(mode="json")
    lines = [opponent.description, "招式循环：" + " → ".join(NAMES[key] for key in opponent.intents),
             "稳守克抢攻，游斗克稳守，抢攻克游斗。", *preview_lines(ctx, current),
             f"气血 {opponent.stats.hp} · 攻击 {opponent.stats.attack} · 防御 {opponent.stats.defense} · 速度 {opponent.stats.speed}",
             "本周奖励：" + duel._reward_text(ctx, opponent.reward)]
    links = []
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先领养伙伴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        pet = preview_pet(ctx)
        reason = blocked(ctx, pet)
        if duel.state(ctx):
            reason = "当前斗法尚未结束，请先出手或认输。"
        elif duel.claimed(ctx, ctx.user_id, opponent):
            reason = "本周已胜过该护法，下周再来。"
        elif pet.realm < duel.realm_index(ctx, opponent.realm):
            reason = f"需 {ctx.content.realms[duel.realm_index(ctx, opponent.realm)].name} 境界。"
        lines.append(reason or f"可挑战 · 每回合精力 {ctx.content.rules.duel.energy} · 上限 {ctx.content.rules.duel.exchanges} 回合")
        if reason is None:
            links.append(InlineCommand(len(lines) - 1, "挑战", f"灵宠斗法 {opponent.name}"))
    return Reply("斗法观招 · " + opponent.name, tuple(lines), ("灵宠斗法", "我的灵宠"), tuple(links))
