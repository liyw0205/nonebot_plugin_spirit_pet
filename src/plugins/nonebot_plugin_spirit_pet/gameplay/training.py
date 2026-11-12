"""Manual skill exchanges against telegraphed, level-scaled training targets."""

from dataclasses import asdict
from hashlib import sha256

from ..application.context import Context
from ..domain.battle_content import Element, Skill, Talent
from ..domain.content import Stats
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import quantity
from ..utils.energy import restore_energy
from ..utils.table import table
from ..utils.time import beijing_day
from . import bond_levels, effects, mastery, talents
from .combat import Fighter, _act
from .loadout import combatant

TITLE = "灵宠连携演练"
DAY_PREFIX = "training_day_"
MOVES = {"probe": "试探", "strike": "进攻", "brace": "护持", "charge": "蓄势", "burst": "重击"}
MOVE_DETAIL = {"probe": "出伤55%", "strike": "正常进攻", "brace": "不攻击，承伤45%",
               "charge": "不攻击，下回合重击", "burst": "出伤200%"}


class TrainingRoll:
    def randint(self, start, stop):
        return 100 if (start, stop) == (90, 110) else start

    def random(self):
        return 1.0


def _pack(unit: Fighter) -> dict:
    data = asdict(unit)
    data["stats"] = unit.stats.model_dump(mode="json")
    data["skills"] = [skill.model_dump(mode="json") for skill in unit.skills]
    data["talent"] = unit.talent.model_dump(mode="json") if unit.talent else None
    return data


def _unpack(value: dict) -> Fighter:
    data = dict(value)
    data["stats"] = Stats.model_validate(data["stats"])
    data["skills"] = tuple(Skill.model_validate(skill) for skill in data["skills"])
    data["talent"] = Talent.model_validate(data["talent"]) if data["talent"] else None
    data["elements"] = tuple(data["elements"])
    data["equipment_sets"] = tuple(data["equipment_sets"])
    state = dict(data["effects"])
    for key in ("weaken", "empower", "ward", "taunt"):
        state[key] = effects.TimedEffect(**state[key]) if state[key] else None
    data["effects"] = effects.EffectState(**state)
    return Fighter(**data)


def state(ctx: Context, user_id: str | None = None) -> dict | None:
    last = ctx.repo.latest_training_action(user_id or ctx.user_id)
    return last["snapshot"] if last and last["snapshot"]["status"] == "active" else None


def _time(ctx: Context, run: dict) -> None:
    if ctx.now < run["updated_at"]:
        raise GameError("时间早于上次连携演练，请等待时钟恢复；本局进度保留。")


def _quota(ctx: Context) -> int:
    key = DAY_PREFIX + beijing_day(ctx.now)
    later = ctx.repo.conn.execute(
        "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id GLOB 'training_day_*' "
        "AND quest_id>? AND progress>0 LIMIT 1", (ctx.user_id, key),
    ).fetchone()
    if later:
        raise GameError("日期早于已使用的演练名额，请等待时钟恢复；不能重复使用历史日期名额。")
    row = ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (ctx.user_id, key),
    ).fetchone()
    return int(row["progress"]) if row else 0


def _food(ctx: Context) -> int:
    row = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id='spirit_food'", (ctx.user_id,),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def _energy(ctx: Context, pet) -> int:
    return min(100, pet.energy + max(0, ctx.now - pet.energy_updated) // ctx.config.spirit_pet_energy_interval)


def _partner(ctx: Context, run: dict | None = None):
    owner = ctx.player()
    target = run["pet_id"] if run else owner.active_pet_id
    if target is None:
        raise ctx.missing_pet()
    row = ctx.repo.conn.execute(
        "SELECT name,archived FROM pets WHERE user_id=? AND pet_id=?", (ctx.user_id, target),
    ).fetchone()
    if row is None:
        raise GameError("原演练伙伴不存在，请退出本局；不能中途改换伙伴。")
    from .release import released
    if released(ctx, target):
        raise GameError(f"{row['name']}已归灵，请退出本局；不能中途改换伙伴。")
    if row["archived"]:
        raise GameError(f"{row['name']}已封存，请复原后继续演练，或退出本局。")
    pet = ctx.repo.pet(target)
    ctx.require_idle_pet(pet)
    if run:
        rows = mastery.progress(ctx, pet.pet_id)
        missing = [s["name"] for s in run["player"]["skills"] if s["id"] not in rows]
        if missing:
            raise GameError("原演练灵术已遗忘：" + "、".join(missing) + "，请重新学会后继续，或退出本局。")
    return pet


def _trial(ctx: Context, name: str):
    trial = ctx.content.training_trials.get(name)
    if trial is None:
        trial = next((trial for trial in ctx.content.training_trials.values() if trial.name == name), None)
    if trial is None:
        raise GameError("没有这份演练试题，可选：" + "、".join(t.name for t in ctx.content.training_trials.values()) + "。")
    return trial


def _require_start(ctx: Context):
    last = ctx.repo.latest_training_action(ctx.user_id)
    if last:
        _time(ctx, last["snapshot"])
        if last["snapshot"]["status"] == "active":
            raise GameError("已有连携演练进行中，请继续或退出原试题。")
    rule = ctx.content.training_rule
    pet = _partner(ctx)
    if _quota(ctx) >= rule.daily_limit:
        raise GameError(f"今日连携演练名额已用尽（每日{rule.daily_limit}局，北京时间00:00刷新）。")
    if _energy(ctx, pet) < rule.energy:
        raise GameError(f"{pet.name}精力不足：开局需要{rule.energy}，当前{_energy(ctx, pet)}。")
    if _food(ctx) < rule.food:
        raise GameError(f"灵粮不足：开局需要{rule.food}份，当前{_food(ctx)}份；可在灵宠商店购买。")
    return pet


def _target(player: Fighter, trial) -> Fighter:
    # Training scales to the opening loadout, not to the user's current realm after resuming.
    stats = Stats(hp=min(1_000_000, max(1, int(player.stats.attack * trial.health))),
                  attack=min(1_000_000, player.stats.defense + max(1, int(player.stats.hp * trial.pressure))),
                  defense=int(player.stats.attack * trial.defense), speed=1)
    return Fighter.create(trial.name + "灵靶", stats)


def _turn(unit: Fighter, target: Fighter, skill: Skill | None, passive: bool, definitions: dict,
          lines: list[str]) -> None:
    unit.turns += 1
    lines.extend(talents.before_action(unit))
    if unit.hp > 0 and target.hp > 0:
        if effects.skip_action(unit):
            lines.append(f"{unit.name}受控无法行动，随后获得一次行动的免控。")
        elif passive:
            lines.append(f"{unit.name}本回合不攻击。")
        else:
            carried = unit.skills
            old_interval, old_actions = unit.skill_interval, unit.actions
            unit.skill_interval, unit.actions = 1, 0
            unit.skills = (skill,) if skill else ()
            _act(unit, [unit], [target], TrainingRoll(), definitions, lines)
            unit.skills = carried
            unit.skill_interval, unit.actions = old_interval, old_actions + 1
    effects.finish_action(unit)


def _exchange(run: dict, action: str) -> tuple[Fighter, Fighter, tuple[str, ...]]:
    player, enemy = _unpack(run["player"]), _unpack(run["enemy"])
    skill = next((s for s in player.skills if s.name == action or s.id == action), None)
    move = run["trial"]["moves"][len(run["history"])]
    definitions = {key: Element.model_validate(value) for key, value in run["elements"].items()}
    old_taken, old_enemy_taken, old_enemy_dealt = player.taken, enemy.taken, enemy.dealt
    if action == "护持":
        player.taken *= 0.35
    if move == "brace":
        enemy.taken *= 0.45
    elif move in ("probe", "burst"):
        enemy.dealt *= 0.55 if move == "probe" else 2.0
    lines = []
    _turn(player, enemy, skill, action == "护持", definitions, lines)
    if player.hp > 0 and enemy.hp > 0:
        _turn(enemy, player, None, move in ("brace", "charge"), definitions, lines)
    player.taken, enemy.taken, enemy.dealt = old_taken, old_enemy_taken, old_enemy_dealt
    return player, enemy, tuple(lines)


def _choices(run: dict) -> list[tuple[str, str]]:
    previous = run["history"][-1]["action"] if run["history"] else None
    return [("普攻", "普攻"), ("护持", "护持")] + [
        (skill["name"], skill["id"]) for skill in run["player"]["skills"] if skill["id"] != previous
    ]


def _command(run: dict, action: str) -> str:
    return f"{TITLE} {action} 局 {run['run_id']} 步 {len(run['history']) + 1}"


def _record(ctx: Context, run: dict, reply: Reply) -> Reply:
    ctx.repo.record_training_action(ctx.operation_id, ctx.user_id, ctx.now,
                                    {**run, "updated_at": ctx.now}, reply)
    return reply


def _run_page(ctx: Context, run: dict, prefix: tuple[str, ...] = ()) -> Reply:
    index = len(run["history"])
    move = run["trial"]["moves"][index]
    lines = [*prefix, f"{run['trial']['name']} · {run['pet_name']}（编号{run['pet_id']}）",
             f"第{index + 1}/5回合 · 我方气血{run['player']['hp']}/{run['player']['stats']['hp']} · 灵靶气血{run['enemy']['hp']}/{run['enemy']['stats']['hp']}。",
             f"灵靶将出{MOVES[move]}：{MOVE_DETAIL[move]}。",
             "出手顺序固定为伙伴先行、灵靶后行；伤害无随机浮动、不判闪避。",
             "护持不攻击、承伤35%；同一灵术不能连续选择，满血回春或无效辅助沿战斗规则转为普攻，不计施法。"]
    commands, links = [], []
    try:
        _time(ctx, run)
        _partner(ctx, run)
    except GameError as exc:
        lines.append(str(exc))
    else:
        for label, action in _choices(run):
            player, enemy, events = _exchange(run, action)
            lines.append(f"{label}后：我方气血{player.hp}，灵靶气血{enemy.hp}。")
            if events:
                lines.append("预演：" + events[0])
            if action in ("普攻", "护持"):
                commands.append(_command(run, "出手 " + label))
            else:
                links.append(InlineCommand(len(lines) - 1, "施展" + label, _command(run, "出手 " + label)))
    lines.append("本局已付费，离线不自动结算；退出不退费、不获成长，当日名额不恢复。")
    links.append(InlineCommand(len(lines) - 1, "退出本局", _command(run, "退出")))
    lines.append("离线、跨日或换出战后仍由原伙伴续练；派遣/封存时暂停，归灵只能退出。")
    links.extend((InlineCommand(len(lines) - 1, "查看行程", "灵宠行程"),
                  InlineCommand(len(lines) - 1, "查看封存库", "灵宠封存库")))
    return Reply(TITLE + " · 第" + str(index + 1) + "回合", tuple(lines), tuple(commands), tuple(links))


def _sources(lines: list[str], links: list[InlineCommand]) -> None:
    lines.append("准备灵粮与伙伴适用的秘笈；灵术不是入场门槛，普攻和护持始终可选。")
    links.extend((InlineCommand(len(lines) - 1, "灵粮详情", "灵宠商店 灵粮"),
                  InlineCommand(len(lines) - 1, "挑选灵术", "灵宠技能图鉴"),
                  InlineCommand(len(lines) - 1, "携带灵术", "灵宠技能")))


def page(ctx: Context) -> Reply:
    run = state(ctx)
    if run:
        return _run_page(ctx, run)
    rule = ctx.content.training_rule
    lines = [f"每局消耗{rule.energy}精力、灵粮{rule.food}份，每日{rule.daily_limit}局；五回合内击倒灵靶且存活才通过。",
             f"通过：按实际施法每次+{rule.proficiency_per_cast}熟练度，全局最多{rule.proficiency_cap}，原伙伴羁绊+{rule.win_bond}；未通过仅羁绊+{rule.loss_bond}，退出无成长。"]
    links = []
    for trial in ctx.content.training_trials.values():
        lines.append(f"{trial.name}：{trial.description}")
        links.append(InlineCommand(len(lines) - 1, "预览试题", f"{TITLE} 预览 {trial.name}"))
    _sources(lines, links)
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先领养伙伴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        try:
            used = _quota(ctx)
            lines.append(f"今日演练已用{used}/{rule.daily_limit}局。")
        except GameError as exc:
            lines.append(str(exc))
    return Reply(TITLE, tuple(lines), (TITLE + " 记录", "灵宠连携", "我的灵宠"), tuple(links))


def preview(ctx: Context, name: str) -> Reply:
    trial = _trial(ctx, name)
    lines = [trial.description, *table(("回合", "灵靶动作", "效果"),
                                      ((index, MOVES[move], MOVE_DETAIL[move]) for index, move in enumerate(trial.moves, 1))),
             f"灵靶气血=开局伙伴攻击×{trial.health}，防御=伙伴攻击×{trial.defense:.0%}，攻击=伙伴防御+伙伴气血×{trial.pressure:.0%}（取整）。",
             "按开局真实配装、灵术等级、连携与羁绊固定；伤害无随机浮动、不判闪避，伙伴先行。",
             "护持不攻击、承伤35%；同一灵术不能连续选择。五回合内击倒灵靶且存活才通过。"]
    rule = ctx.content.training_rule
    lines.append(f"开局{rule.energy}精力、灵粮{rule.food}份；通过按实际施法每次+{rule.proficiency_per_cast}熟练度（共至多{rule.proficiency_cap}）、羁绊+{rule.win_bond}；未通过仅羁绊+{rule.loss_bond}。退出不退费无成长。")
    commands, links = [], []
    _sources(lines, links)
    if ctx.repo.player(ctx.user_id) is None:
        lines.append("尚未结契，先领养伙伴。")
        links.append(InlineCommand(len(lines) - 1, "开始领养", "灵宠领养 "))
    else:
        try:
            pet = _partner(ctx)
            player = combatant(ctx, pet_id=pet.pet_id, recover_energy=False)
            enemy = _target(player, trial)
            lines.append(f"{pet.name}（编号{pet.pet_id}）· 精力{_energy(ctx, pet)} · 灵粮{_food(ctx)}份 · 灵靶气血{enemy.hp}。")
            lines.append("携带灵术：" + ("、".join(s.name for s in player.skills) or "无（仍可普攻/护持）") + "。")
            _require_start(ctx)
        except GameError as exc:
            lines.append(str(exc))
        else:
            commands.append(f"{TITLE} 开始 {trial.name}")
    return Reply(TITLE + " · " + trial.name, tuple(lines), (*commands, TITLE), tuple(links))


def start(ctx: Context, name: str) -> Reply:
    ctx.player()
    trial = _trial(ctx, name)
    pet = _require_start(ctx)
    player = combatant(ctx, pet_id=pet.pet_id, recover_energy=False)
    enemy = _target(player, trial)
    initial = tuple(event for unit in (player, enemy) if (event := talents.initialize(unit)))
    rule = ctx.content.training_rule
    run = {"status": "active", "run_id": sha256(ctx.operation_id.encode()).hexdigest()[:16],
           "trial": trial.model_dump(), "rule": rule.model_dump(), "pet_id": pet.pet_id,
           "pet_name": pet.name, "player": _pack(player), "enemy": _pack(enemy),
           "elements": {key: value.model_dump() for key, value in ctx.content.elements.items()},
           "history": [], "started_at": ctx.now, "updated_at": ctx.now}
    used = _quota(ctx)
    restore_energy(pet, ctx.now, ctx.config.spirit_pet_energy_interval)
    pet.energy -= rule.energy
    ctx.repo.consume_item(ctx.user_id, "spirit_food", rule.food)
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES (?,?,?,1) "
        "ON CONFLICT(user_id,quest_id) DO UPDATE SET progress=excluded.progress",
        (ctx.user_id, DAY_PREFIX + beijing_day(ctx.now), used + 1),
    )
    ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    return _record(ctx, run, _run_page(ctx, run, (f"{pet.name}精力-{rule.energy}，灵粮-{rule.food}份；占用今日演练名额。", *initial)))


def _active(ctx: Context, guard: list[str]) -> dict:
    ctx.player()
    last = ctx.repo.latest_training_action(ctx.user_id)
    if last is None:
        raise GameError("当前没有连携演练，请先选择试题开始。")
    run = last["snapshot"]
    if guard:
        if len(guard) != 4 or guard[0] != "局" or guard[2] != "步":
            raise GameError("局步参数格式：局 <局号> 步 <回合数>。")
        step = quantity(guard[3], 6)
        if guard[1] != run["run_id"]:
            raise GameError("这是另一局演练的旧入口，请查看当前试题。")
        if step != len(run["history"]) + 1:
            raise GameError("这一步演练已经执行，请查看当前回合。")
    if run["status"] != "active":
        raise GameError("该局演练已结束，请查看记录或选择新试题。")
    _time(ctx, run)
    return run


def advance(ctx: Context, action: str, guard: list[str]) -> Reply:
    run = _active(ctx, guard)
    pet = _partner(ctx, run)
    selected = next((skill for skill in run["player"]["skills"] if action in (skill["name"], skill["id"])), None)
    normalized = selected["id"] if selected else action
    if not selected and action not in ("普攻", "护持"):
        raise GameError(f"{run['pet_name']}开局未携带这门灵术：{action}，请从本局出手中选择。")
    if selected and run["history"] and run["history"][-1]["action"] == normalized:
        raise GameError(f"{selected['name']}不能连续选择，请先普攻、护持或选择另一门灵术。")
    player, enemy, events = _exchange(run, normalized)
    run["history"].append({"action": normalized, "label": selected["name"] if selected else action,
                           "move": run["trial"]["moves"][len(run["history"])], "events": list(events),
                           "hp": player.hp, "enemy_hp": enemy.hp})
    run["player"], run["enemy"] = _pack(player), _pack(enemy)
    if player.hp > 0 and enemy.hp > 0 and len(run["history"]) < 5:
        return _record(ctx, run, _run_page(ctx, run, events))
    passed = player.hp > 0 and enemy.hp <= 0
    run["status"] = "won" if passed else "lost"
    growth = []
    if passed:
        remaining = run["rule"]["proficiency_cap"]
        for skill_id, count in player.skill_uses.items():
            gain = min(remaining, count * run["rule"]["proficiency_per_cast"])
            if not gain:
                break
            level, before = mastery.progress(ctx, pet.pet_id)[skill_id]
            name = next(s["name"] for s in run["player"]["skills"] if s["id"] == skill_id)
            if ctx.content.skill_levels[level].required_proficiency is None:
                growth.append(f"{name}已满级，不增加熟练度。")
                continue
            after, proficiency, upgraded = mastery.study(ctx, pet.pet_id, skill_id, gain)
            remaining -= gain
            growth.append(f"{name}实际施展{count}次，熟练度+{gain}（{mastery.progress_text(ctx, after, proficiency)}）。")
            if upgraded:
                ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
        if not player.skill_uses:
            growth.append("本局未实际施展灵术，不增加熟练度。")
    amount = run["rule"]["win_bond"] if passed else run["rule"]["loss_bond"]
    before_level = bond_levels.current_level(ctx, pet.pet_id)
    if amount:
        total = bond_levels.add_exp(ctx, pet.pet_id, amount)
        if before_level != bond_levels.level(total):
            ctx.repo.invalidate_pet_ready(ctx.user_id, pet.pet_id)
    cause = "灵靶已击倒，伙伴存活，通过演练。" if passed else (
        "伙伴气血耗尽，未通过演练。" if player.hp <= 0 else "五回合用尽，灵靶仍存活，未通过演练。")
    lines = [f"{run['trial']['name']} · {run['pet_name']}（编号{pet.pet_id}）", *events, cause,
             *growth, f"原伙伴羁绊经验+{amount}；当前累计{bond_levels.exp(ctx, pet.pet_id)}，羁绊等级{bond_levels.current_level(ctx, pet.pet_id)}。",
             "气血仅用于本局，不改变伙伴真实精力或亲密。"]
    run["growth"] = growth
    return _record(ctx, run, Reply("连携演练结算", tuple(lines), (TITLE, "我的灵宠", "灵宠背包"),
                                  (InlineCommand(len(lines) - 2, "查看羁绊", "灵宠羁绊"),
                                   InlineCommand(len(lines) - 2, "查看灵术成长", f"灵宠技能 伙伴 {pet.pet_id}"))))


def quit_run(ctx: Context, guard: list[str]) -> Reply:
    run = _active(ctx, guard)
    run["status"] = "quit"
    return _record(ctx, run, Reply("连携演练退出", (f"已退出{run['trial']['name']}，保留{len(run['history'])}回合回顾。",
                                                  "不退精力或灵粮，不增加熟练度或羁绊；当日名额不恢复。"),
                                  (TITLE, TITLE + " 记录")))


def result(ctx: Context) -> Reply:
    last = ctx.repo.latest_training_action(ctx.user_id, finished_only=True)
    if last is None:
        return Reply(TITLE + "记录", ("还没有结束的连携演练。",), (TITLE,))
    run = last["snapshot"]
    saved = Reply.from_data(last["reply"])
    lines = list(saved.lines)
    for index, turn in enumerate(run["history"], 1):
        lines.append(f"第{index}回合：{turn['label']} / 灵靶{MOVES[turn['move']]} · 我方{turn['hp']}，灵靶{turn['enemy_hp']}。")
        lines.extend(turn["events"])
    return Reply(TITLE + "记录", tuple(lines), (TITLE, "我的灵宠"))


def objective_line(ctx: Context, user_id: str) -> str:
    run = state(ctx, user_id)
    if run:
        return f"连携演练：{run['pet_name']}正在{run['trial']['name']}，待第{len(run['history']) + 1}回合"
    return "连携演练：选择攻防节奏试题，与伙伴磨合灵术"


def dispatch(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts:
        return page(ctx)
    if parts == ["记录"]:
        return result(ctx)
    if len(parts) == 2 and parts[0] in ("预览", "开始"):
        return preview(ctx, parts[1]) if parts[0] == "预览" else start(ctx, parts[1])
    if len(parts) >= 2 and parts[0] == "出手":
        return advance(ctx, parts[1], parts[2:])
    if parts[0] == "退出":
        return quit_run(ctx, parts[1:])
    raise GameError("格式：灵宠连携演练 [预览/开始 试题名 | 出手 普攻/护持/灵术名 | 退出 | 记录]。")
