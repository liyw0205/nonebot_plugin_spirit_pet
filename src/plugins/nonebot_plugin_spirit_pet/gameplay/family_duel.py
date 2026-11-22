"""Weekly real-combat encounters for a verified direct parent and child."""

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.energy import restore_energy
from ..utils.pagination import paginate
from ..utils.time import BEIJING, beijing_week
from . import battle_pass
from . import family_duel_league
from .battle_records import capture_snapshot, record_battle
from .combat import enemy_fighter, fight
from .loadout import combatant
from .mastery import award_mastery
from .pet_targets import pet_id
from .quests import advance
from .release import released
from .rewards import grant

TITLE = "灵宠亲子合战"
KIND = "family_duel"
WEEK_SECONDS = 7 * 86400
PAGE_SIZE = 6


def read_only(argument: str) -> bool:
    if argument.split()[:1] == ["联赛"]:
        return family_duel_league.read_only(argument)
    return (
        not argument.split() or argument.split()[0] in {"亲子", "预览", "记录", "详情"}
    )


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _time(value: int) -> str:
    return datetime.fromtimestamp(value, BEIJING).strftime("%Y-%m-%d %H:%M")


def week_start(ctx: Context) -> int:
    return beijing_week(ctx.now)[0]


def _week_index(start: int) -> int:
    return (start - 316800) // WEEK_SECONDS


def current_duel(ctx: Context, start: int | None = None):
    begin = week_start(ctx) if start is None else start
    league_duel = family_duel_league.duel_id_for_week(ctx, begin)
    duel_id = league_duel or ctx.content.family_duel_rotation[
        _week_index(begin) % len(ctx.content.family_duel_rotation)
    ]
    return ctx.content.family_duels[duel_id]


def _pet(ctx: Context, number: int, user_id: str):
    owner = ctx.repo.conn.execute(
        "SELECT 1 FROM pets WHERE user_id=? AND pet_id=?", (user_id, number),
    ).fetchone()
    if owner is None:
        raise GameError("没有属于你的亲子合战伙伴，请从本人亲子列表选择。")
    pet = ctx.repo.pet(number)
    if pet.archived or released(ctx, number):
        raise GameError(f"{pet.name}已封存或归灵，当前不能参加合战。")
    ctx.require_idle_pet(pet)
    return pet


def _eligible(ctx: Context, parent_id: int, child_id: int, user_id: str | None = None):
    owner = user_id or ctx.user_id
    parent, child = _pet(ctx, parent_id, owner), _pet(ctx, child_id, owner)
    egg = ctx.repo.conn.execute(
        "SELECT * FROM pet_lineage_eggs WHERE user_id=? AND status='hatched' AND child_pet_id=? "
        "AND (parent_a_id=? OR parent_b_id=?)",
        (owner, child_id, parent_id, parent_id),
    ).fetchone()
    if egg is None:
        raise GameError("亲子合战须使用本人真实孵化凭证中的直接亲本与后代；兄弟姐妹、旁支或无凭证伙伴不能代替。")
    if ctx.now < egg["finished_at"]:
        raise GameError("时间早于真实孵化凭证，请等待时钟恢复。")
    return parent, child, dict(egg)


def _run(ctx: Context, user_id: str, start: int | None = None):
    query = "SELECT * FROM family_duel_runs WHERE user_id=?"
    args: list[object] = [user_id]
    if start is not None:
        query += " AND week_start=?"
        args.append(start)
    return ctx.repo.conn.execute(query, args).fetchone()


def _rating(duel, battle, parent_id: int, child_id: int):
    if battle.winner != 0 or battle.rounds > duel.max_rounds:
        return None
    uses = battle.skill_uses[0]
    both_skilled = all(sum(uses.get(pet_id, {}).values()) > 0 for pet_id in (parent_id, child_id))
    both_alive = len(battle.remaining_hp[0]) >= 2 and all(hp > 0 for hp in battle.remaining_hp[0][:2])
    for rating in reversed(duel.ratings):
        if battle.rounds > rating.max_rounds:
            continue
        if rating.require_both_skills and not both_skilled:
            continue
        if rating.require_both_alive and not both_alive:
            continue
        return rating
    return None


def _outcome(battle, max_rounds: int) -> str:
    if battle.winner == 0 and battle.rounds <= max_rounds:
        return "won"
    if battle.winner == 1:
        return "lost"
    return "timeout" if battle.rounds >= max_rounds else "draw"


def _outcome_label(outcome: str) -> str:
    return {"won": "胜利", "lost": "败北", "draw": "平局", "timeout": "超回合"}[outcome]


def _reward_text(ctx: Context, reward) -> str:
    parts = [f"修为 {reward.exp.minimum}-{reward.exp.maximum}",
             f"灵石 {reward.stones.minimum}-{reward.stones.maximum}"]
    parts.extend(f"{ctx.content.items[key].name} ×{amount.minimum}-{amount.maximum}"
                 for key, amount in reward.items.items())
    return "、".join(parts)


def overview(ctx: Context) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(TITLE, ("尚未结契，先领养伙伴并建立真实谱系。",), ("灵宠帮助",))
    start = week_start(ctx)
    duel = current_duel(ctx, start)
    row = _run(ctx, ctx.user_id, start)
    commands = (f"{TITLE} 亲子", f"{TITLE} 记录", "灵宠谱系", f"{TITLE} 联赛")
    if row is not None:
        reward = ctx.repo.conn.execute(
            "SELECT rating_id FROM family_duel_rewards WHERE run_id=?", (row["run_id"],),
        ).fetchone()
        rating_name = next((rating.name for rating in duel.ratings
                            if reward and rating.id == reward["rating_id"]), None)
        lines = [f"本周 {duel.name} · 已参战 {_time(row['started_at'])}。",
                 f"{row['parent_id']}号亲本与{row['child_id']}号后代 · {_outcome_label(row['outcome'])} · {row['rounds']} 回合。",
                 f"评级：{rating_name or '未达奖励档'} · 每周仅一次，结果与战报永久保留。"]
        return Reply(TITLE, tuple(lines), commands,
                     (InlineCommand(1, "查看战报", f"灵宠战报 查看 {row['battle_id']}"),))
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == duel.min_realm)
    lines = [f"本周 {duel.name} · {duel.description}",
             f"敌阵：{'、'.join(ctx.content.enemies[key].name for key in duel.enemies)} · "
             f"双方至少{ctx.content.realms[minimum].name} · 双宠各消耗精力 {duel.energy} · "
             f"最多 {duel.max_rounds} 回合。"]
    lines.extend(
        f"{rating.name}：胜利且 {rating.max_rounds} 回合内，"
        f"{'双宠存活、' if rating.require_both_alive else ''}双方都实际施放技能；奖励 {_reward_text(ctx, rating.reward)}。"
        for rating in duel.ratings
    )
    lines.append("先查看合格亲子，再预览本周规则；页面只读，不占挑战名额。")
    return Reply(TITLE, tuple(lines), commands,
                 (InlineCommand(2, "选择亲子", f"{TITLE} 亲子"),))


def pairs(ctx: Context, argument: str) -> Reply:
    ctx.player()
    entries = []
    locked = family_duel_league.entry_for_week(ctx, week_start(ctx))
    for egg in ctx.repo.lineage_eggs(ctx.user_id):
        for parent_id in (int(egg["parent_a_id"]), int(egg["parent_b_id"])):
            try:
                parent, child, lineage = _eligible(ctx, parent_id, int(egg["child_pet_id"]))
            except GameError:
                continue
            if locked is not None and (
                parent.pet_id != int(locked["parent_id"])
                or child.pet_id != int(locked["child_id"])
                or int(lineage["egg_record_id"]) != int(locked["egg_record_id"])
            ):
                continue
            entries.append((parent, child))
    page = paginate(entries, argument or "1", TITLE, f"{TITLE} 亲子", PAGE_SIZE)
    lines = [f"合格直接亲子 {len(entries)} 对 · 第 {page.number}/{page.total} 页。"]
    links = []
    start = week_start(ctx)
    for parent, child in page.entries:
        lines.append(f"{parent.name}（#{parent.pet_id}）与{child.name}（#{child.pet_id}）")
        links.append(InlineCommand(len(lines) - 1, "本周预览",
                                   f"{TITLE} 预览 {parent.pet_id} {child.pet_id} {start}"))
    if not entries:
        lines.append("尚无可出战的真实直接亲子；需要本人孵化凭证，且双宠都须在册、未归灵并无待领取派遣。")
    return Reply(TITLE + " · 亲子", tuple(lines), (*page.navigation, TITLE, "灵宠谱系")[:4], tuple(links))


def preview(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) not in (2, 3):
        raise GameError(f"格式：{TITLE} 预览 亲本编号 后代编号 [周起点]。")
    start = week_start(ctx)
    if len(parts) == 3 and parts[2] != str(start):
        raise GameError("预览入口已跨周，请重新查看本周亲子合战。")
    parent, child, egg = _eligible(ctx, pet_id(parts[0]), pet_id(parts[1]))
    league_entry = family_duel_league.entry_for_week(ctx, start)
    if league_entry is not None and (
        int(league_entry["parent_id"]) != parent.pet_id
        or int(league_entry["child_id"]) != child.pet_id
        or int(league_entry["egg_record_id"]) != int(egg["egg_record_id"])
    ):
        raise GameError("本赛季只能预览报名时锁定的亲子组合。")
    duel = current_duel(ctx, start)
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == duel.min_realm)
    lines = [f"{duel.name} · {parent.name}（#{parent.pet_id}）与{child.name}（#{child.pet_id}）",
             f"真实已孵化凭证 #{egg['egg_record_id']} · 敌阵："
             f"{'、'.join(ctx.content.enemies[key].name for key in duel.enemies)}。",
             f"双方至少{ctx.content.realms[minimum].name}，各消耗精力 {duel.energy}；"
             "使用当前各自真实整备，胜负后均结算熟练度并记录战报。",
             "本周只可开始一次；失败、平局或超回合仍消耗周名额与精力。"]
    lines.extend(f"{rating.name}：{rating.max_rounds} 回合内胜利、双方均施放技能，"
                 f"{'且双宠存活；' if rating.require_both_alive else ''}奖励 {_reward_text(ctx, rating.reward)}。"
                 for rating in duel.ratings)
    player = ctx.player()
    if player.last_pve is not None and ctx.now < player.last_pve:
        lines.append("系统时间早于最近 PVE 行为，暂不能出战。")
        commands = (TITLE, f"{TITLE} 亲子", "灵宠目标")
    elif _run(ctx, ctx.user_id, start) is not None:
        lines.append("你本周已经开始过亲子合战。")
        commands = (TITLE, f"{TITLE} 记录", "灵宠战报")
    else:
        commands = (f"{TITLE} 挑战 {start} {parent.pet_id} {child.pet_id}",
                    f"{TITLE} 亲子", "灵宠家族试炼", "灵宠亲子伴游")
    return Reply(TITLE + " · 预览", tuple(lines), commands)


def challenge(ctx: Context, parts: list[str]) -> Reply:
    ctx.player()
    if len(parts) != 3 or parts[0] != str(week_start(ctx)):
        raise GameError("挑战入口已过期，请重新预览本周亲子合战。")
    start = int(parts[0])
    family_duel_league.finalize_ended(ctx)
    family_duel_league.ensure_open(ctx, family_duel_league.league_start(start))
    parent, child, egg = _eligible(ctx, pet_id(parts[1]), pet_id(parts[2]))
    league_entry = family_duel_league.entry_for_week(ctx, start)
    if league_entry is not None:
        if ctx.now < int(league_entry["registered_at"]):
            raise GameError("系统时间早于联赛报名，请等待时钟恢复。")
        if (int(league_entry["parent_id"]), int(league_entry["child_id"])) != (
            pet_id(parts[1]), pet_id(parts[2]),
        ) or int(league_entry["egg_record_id"]) != int(egg["egg_record_id"]):
            raise GameError("本赛季只能使用报名时锁定的亲子组合与孵化凭证。")
    if _run(ctx, ctx.user_id, start) is not None:
        raise GameError("本周亲子合战名额已使用；失败也不返还。")
    duel = current_duel(ctx, start)
    minimum = next(index for index, realm in enumerate(ctx.content.realms) if realm.id == duel.min_realm)
    if parent.realm < minimum or child.realm < minimum:
        raise GameError(f"亲本与后代都需要达到{ctx.content.realms[minimum].name}。")
    player = ctx.player()
    if player.last_pve is not None and ctx.now < player.last_pve:
        raise GameError("系统时间早于最近 PVE 行为，请等待时钟恢复。")
    restore_energy(parent, ctx.now, ctx.config.spirit_pet_energy_interval)
    restore_energy(child, ctx.now, ctx.config.spirit_pet_energy_interval)
    ctx.check_action(player, parent, "pve", duel.energy, ctx.config.spirit_pet_pve_cooldown)
    if child.energy < duel.energy:
        raise GameError(f"{child.name}精力不足，需要 {duel.energy} 点。")

    allies = [combatant(ctx, pet_id=pet.pet_id, recover_energy=False)
              for pet in (parent, child)]
    enemies = [enemy_fighter(ctx.content.enemies[key], ctx.content.skills) for key in duel.enemies]
    capture = capture_snapshot(ctx, (allies, enemies), ([ctx.user_id, ctx.user_id], []))
    battle = fight(allies, enemies, ctx.rng, ctx.content.elements, max_rounds=duel.max_rounds)
    outcome = _outcome(battle, duel.max_rounds)
    rating = _rating(duel, battle, parent.pet_id, child.pet_id)

    parent.energy -= duel.energy
    child.energy -= duel.energy
    player.last_pve = ctx.now
    lines = [f"{duel.name} · {_outcome_label(outcome)} · {battle.rounds}/{duel.max_rounds} 回合。",
             f"亲本与后代精力各 -{duel.energy} · PVE 调息 {ctx.config.spirit_pet_pve_cooldown} 秒。",
             *battle.lines]
    skill_uses = battle.skill_uses[0]
    for pet in (parent, child):
        lines.extend(award_mastery(ctx, ctx.user_id, skill_uses.get(pet.pet_id, {}), pet_id=pet.pet_id))
    reward_snapshot = None
    if outcome == "won":
        advance(ctx, "pve")
        battle_pass.add_experience(ctx, "pve_win")
        if rating is not None:
            player_stones = player.stones
            child_exp = child.exp
            inventory_before = ctx.repo.inventory(ctx.user_id)
            lines.append(f"评级：{rating.name} · 奖励已结算：" + "，".join(
                grant(ctx, rating.reward, pet_id=child.pet_id)
            ))
            inventory_after = ctx.repo.inventory(ctx.user_id)
            reward_snapshot = {
                "rating": rating.model_dump(mode="json"),
                "actual": {
                    "exp": child.exp - child_exp,
                    "stones": player.stones - player_stones,
                    "items": {key: inventory_after.get(key, 0) - inventory_before.get(key, 0)
                              for key in rating.reward.items},
                },
            }
        else:
            lines.append("战斗获胜，但未满足本周奖励档的回合与双方施法条件，或高档双宠存活条件；无额外奖励。")
    else:
        lines.append("本次未胜，保留准确战报并消耗本周名额；没有额外奖励。")
    lines.append("战斗详情已保存，可从本页或战历打开永久战报。")
    reply = Reply(TITLE + (" · " + rating.name if rating else " · " + _outcome_label(outcome)),
                  tuple(lines), (TITLE, f"{TITLE} 记录", "灵宠目标"))
    battle_id = record_battle(
        ctx, kind="pve_stage", battle_key=f"family_duel_{duel.id}", battle_name=duel.name,
        battle=battle, capture=capture, reply=reply,
    )
    reply = Reply(reply.title, reply.lines, reply.commands,
                  (InlineCommand(0, "查看本场战报", f"灵宠战报 查看 {battle_id}"),))
    ctx.repo.conn.execute("UPDATE battle_records SET reply=? WHERE battle_id=?",
                          (_json(asdict(reply)), battle_id))
    run_id = sha256(ctx.operation_id.encode()).hexdigest()[:16]
    snapshot = {
        "version": 1,
        "duel": duel.model_dump(mode="json"),
        "parents": {"parent": {"pet_id": parent.pet_id, "name": parent.name,
                                 "species_id": parent.species_id},
                    "child": {"pet_id": child.pet_id, "name": child.name,
                               "species_id": child.species_id}},
        "egg": {key: egg[key] for key in (
            "egg_record_id", "parent_a_id", "parent_b_id", "child_pet_id", "finished_at",
        )},
        "enemies": [ctx.content.enemies[key].model_dump(mode="json") for key in duel.enemies],
    }
    ctx.repo.record_duel_action(ctx.operation_id, ctx.user_id, ctx.now,
                                {"kind": KIND, "run_id": run_id, "week_start": start,
                                 "duel_id": duel.id}, reply)
    ctx.repo.conn.execute(
        "INSERT INTO family_duel_runs(run_id,user_id,week_start,duel_id,parent_id,child_id,egg_record_id,"
        "operation_id,battle_id,outcome,rating_id,rounds,remaining_hp,skill_uses,started_at,snapshot,reply) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, ctx.user_id, start, duel.id, parent.pet_id, child.pet_id, egg["egg_record_id"],
         ctx.operation_id, battle_id, outcome, rating.id if rating else None, battle.rounds,
         _json(battle.remaining_hp), _json(skill_uses), ctx.now, _json(snapshot), _json(asdict(reply))),
    )
    family_duel_league.record_run(ctx, start, run_id)
    if rating is not None and reward_snapshot is not None:
        ctx.repo.conn.execute(
            "INSERT INTO family_duel_rewards(run_id,user_id,operation_id,rating_id,granted_at,reward_snapshot) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, ctx.user_id, ctx.operation_id, rating.id, ctx.now, _json(reward_snapshot)),
        )
    ctx.repo.invalidate_ready(ctx.user_id)
    return reply


def history(ctx: Context, argument: str) -> Reply:
    ctx.player()
    rows = ctx.repo.conn.execute(
        "SELECT * FROM family_duel_runs WHERE user_id=? ORDER BY week_start DESC,run_id DESC",
        (ctx.user_id,),
    ).fetchall()
    page = paginate(rows, argument or "1", TITLE, f"{TITLE} 记录", PAGE_SIZE)
    lines = [f"共 {len(rows)} 场 · 第 {page.number}/{page.total} 页，最近周在前。"]
    links = []
    for row in page.entries:
        duel = json.loads(row["snapshot"])["duel"]
        rating = next((item["name"] for item in duel["ratings"] if item["id"] == row["rating_id"]), None)
        lines.append(f"{duel['name']} · {_time(row['started_at'])} · {_outcome_label(row['outcome'])} · "
                     f"{row['rounds']} 回合 · {rating or '未达奖励档'}。")
        links.append(InlineCommand(len(lines) - 1, "查看战历", f"{TITLE} 详情 {row['run_id']}"))
    return Reply(TITLE + " · 记录", tuple(lines), (*page.navigation, TITLE, "灵宠谱系")[:4], tuple(links))


def detail(ctx: Context, run_id: str) -> Reply:
    ctx.player()
    if len(run_id) != 16 or any(char not in "0123456789abcdef" for char in run_id):
        raise GameError(f"格式：{TITLE} 详情 轮次编号。")
    row = ctx.repo.conn.execute(
        "SELECT * FROM family_duel_runs WHERE user_id=? AND run_id=?", (ctx.user_id, run_id),
    ).fetchone()
    if row is None:
        raise GameError("这场亲子合战不存在或不属于你。")
    snapshot = json.loads(row["snapshot"])
    parent, child = snapshot["parents"]["parent"], snapshot["parents"]["child"]
    rating = next((item["name"] for item in snapshot["duel"]["ratings"]
                   if item["id"] == row["rating_id"]), None)
    hp = "、".join(map(str, json.loads(row["remaining_hp"])[0]))
    lines = [f"{snapshot['duel']['name']} · {_time(row['started_at'])} · {_outcome_label(row['outcome'])} · "
             f"{row['rounds']} 回合。",
             f"{parent['name']}（#{parent['pet_id']}）与{child['name']}（#{child['pet_id']}） · "
             f"我方剩余气血 {hp} · 评级 {rating or '未达奖励档'}。",
             "结果按该周冻结规则与真实战斗结构字段评定；历史不重新计算或补发奖励。"]
    return Reply(TITLE + " · 战历详情", tuple(lines),
                 (f"灵宠战报 查看 {row['battle_id']}", f"{TITLE} 记录", "灵宠谱系"))


def dispatch(ctx: Context, argument: str) -> Reply:
    parts = argument.split()
    if not parts:
        return overview(ctx)
    if parts[0] == "联赛":
        return family_duel_league.dispatch(ctx, " ".join(parts[1:]))
    if parts[0] == "亲子" and len(parts) <= 2:
        return pairs(ctx, parts[1] if len(parts) == 2 else "1")
    if parts[0] == "预览":
        return preview(ctx, parts[1:])
    if parts[0] == "挑战":
        return challenge(ctx, parts[1:])
    if parts[0] == "记录" and len(parts) <= 2:
        return history(ctx, parts[1] if len(parts) == 2 else "1")
    if parts[0] == "详情" and len(parts) == 2:
        return detail(ctx, parts[1])
    raise GameError(f"格式：{TITLE} [亲子 [页码]|预览 亲本 后代 [周起点]|挑战 周起点 亲本 后代|记录 [页码]|详情 编号]。")


def objective_line(ctx: Context, user_id: str) -> str:
    row = _run(ctx, user_id, week_start(ctx))
    if row is not None:
        return f"亲子合战：{_outcome_label(row['outcome'])} · 本周已参战；{family_duel_league.objective_line(ctx, user_id)}"
    return f"亲子合战：本周 {current_duel(ctx).name} 尚未参战；{family_duel_league.objective_line(ctx, user_id)}"


def today_state(ctx: Context, user_id: str) -> str | None:
    row = _run(ctx, user_id, week_start(ctx))
    if row is not None:
        return family_duel_league.today_state(ctx, user_id)
    return family_duel_league.today_state(ctx, user_id) or objective_line(ctx, user_id)
