"""Gear words: random stat affixes stored per equipment stack.

Words attach to a stack keyed by ``(item_id, enhancement)`` because the
inventory collapses identical stacks into a quantity. Each word is one row in
``quest_progress``:

- ``gear_words_<item_id>_<enh>_<index>_<word_id>`` with ``progress`` holding
  the rolled value.

Reading collects and sorts those rows; generation rolls 1-3 words based on the
enhancement level (``1 + level // 4``, capped at 3); reforge rerolls every word
of a stack without reducing the count. Schema 20 stays untouched.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import named, quantity

WORD_PREFIX = "gear_words_"
MAX_WORDS = 3
REFORGE_STONES = 300
REFORGE_GRAIN = 5  # spirit_food, farm output
SELECTIVE_STONES = 150
SELECTIVE_GRAIN = 3
STATS = {"hp": "气血", "attack": "攻击", "defense": "防御", "speed": "速度"}
STAT_INPUTS = {**{key: key for key in STATS}, **{label: key for key, label in STATS.items()}}
PAGE_SIZE = 5


def stack_key(item_id: str, enhancement: int, index: int, word_id: str) -> str:
    return f"{WORD_PREFIX}{item_id}_{enhancement}_{index}_{word_id}"


def _prefix(item_id: str, enhancement: int) -> str:
    return f"{WORD_PREFIX}{item_id}_{enhancement}_"


def rows(
    ctx: Context, item_id: str, enhancement: int, user_id: str | None = None,
) -> list[tuple[str, int]]:
    """Sorted [(word_id, value)] for the stack, oldest word first."""
    prefix = _prefix(item_id, enhancement)
    owner = user_id or ctx.user_id
    rows = ctx.repo.conn.execute(
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND claimed=1 "
        "AND substr(quest_id, 1, ?)=?",
        (owner, len(prefix), prefix),
    ).fetchall()
    entries = []
    for row in rows:
        remainder = row["quest_id"][len(prefix):]
        try:
            index, word_id = remainder.split("_", 1)
            entries.append((int(index), word_id, row["progress"]))
        except ValueError:
            continue
    return [(word_id, value) for _, word_id, value in sorted(entries)]


def describe(ctx: Context, item_id: str, enhancement: int) -> str:
    """Human summary of a stack's words, or an empty string when none exist."""
    words = rows(ctx, item_id, enhancement)
    if not words:
        return ""
    return "词条：" + "、".join(
        f"{ctx.content.gear_words[word_id].name} +{value}" for word_id, value in words
    )


def _clear(ctx: Context, item_id: str, enhancement: int) -> None:
    prefix = _prefix(item_id, enhancement)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(prefix), prefix),
    )


def _owned_stacks(ctx: Context, user_id: str | None = None) -> dict[tuple[str, int], dict]:
    stacks: dict[tuple[str, int], dict] = {}
    owner = user_id or ctx.user_id

    def stack(item_id: str, enhancement: int) -> dict:
        return stacks.setdefault((item_id, enhancement), {
            "item_id": item_id, "enhancement": enhancement, "bag": 0, "pets": [],
        })

    for row in ctx.repo.conn.execute(
        "SELECT item_id, quantity FROM inventory WHERE user_id=? AND quantity>0",
        (owner,),
    ):
        item = ctx.content.items.get(row["item_id"])
        if item is not None and item.kind == "equipment":
            stack(item.id, 0)["bag"] += int(row["quantity"])
    for row in ctx.repo.conn.execute(
        "SELECT item_id, enhancement, quantity FROM unequipped_equipment "
        "WHERE user_id=? AND quantity>0", (owner,),
    ):
        stack(row["item_id"], int(row["enhancement"]))["bag"] += int(row["quantity"])
    for row in ctx.repo.conn.execute(
        "SELECT e.item_id, e.enhancement, p.pet_id, p.name FROM equipment e "
        "JOIN pets p USING(pet_id) WHERE p.user_id=? ORDER BY p.pet_id, e.slot",
        (owner,),
    ):
        entry = stack(row["item_id"], int(row["enhancement"]))
        entry["pets"].append((int(row["pet_id"]), row["name"]))
    return stacks


def objective_line(ctx: Context, user_id: str) -> str:
    """Summarize usable word stacks without creating or changing state."""
    if ctx.repo.player(user_id) is None:
        return "灵器词条：尚未结契"
    stacks = _owned_stacks(ctx, user_id)
    if not stacks:
        return "灵器词条：暂无灵器 · 先打造或获得装备"
    eligible = []
    for entry in stacks.values():
        current = rows(ctx, entry["item_id"], entry["enhancement"], user_id)
        if any(word_id in ctx.content.gear_words for word_id, _ in current):
            eligible.append((entry, current))
    if not eligible:
        return f"灵器词条：暂无可定向淬词 · 已有 {len(stacks)} 个灵器栈尚无可用词条"
    word_count = sum(
        sum(1 for word_id, _ in current if word_id in ctx.content.gear_words)
        for _, current in eligible
    )
    copies = sum(entry["bag"] + len(entry["pets"]) for entry, _ in eligible)
    return f"灵器词条：可定向淬词 {len(eligible)} 栈 · {word_count} 条词条 · 覆盖 {copies} 件装备"


def _stack(ctx: Context, item_name: str, level_text: str, stacks: dict | None = None) -> tuple[object, int, dict]:
    item = named(ctx.content.items, item_name)
    if item.kind != "equipment" or item.equipment_id not in ctx.content.equipment:
        raise GameError("词条重铸只接受装备名称，请检查装备图鉴。")
    if not level_text.startswith("+"):
        raise GameError("强化等级须写成 +0 至 +10。")
    digits = level_text[1:]
    if digits == "0":
        level = 0
    else:
        try:
            level = quantity(digits, max(ctx.content.forge_levels))
        except GameError:
            raise GameError(f"强化等级须为 +0 至 +{max(ctx.content.forge_levels)}。") from None
    available = (stacks if stacks is not None else _owned_stacks(ctx)).get((item.id, level))
    if available is None:
        raise GameError(f"未持有或穿戴{item.name} +{level}，未进行词条操作。")
    return item, level, available


def _stack_label(ctx: Context, stack: dict) -> str:
    item = ctx.content.items[stack["item_id"]]
    return f"{item.name} +{stack['enhancement']}"


def _ownership_text(stack: dict) -> str:
    equipped = stack["pets"]
    owners = "、".join(f"{name}（编号 {pet_id}）" for pet_id, name in equipped)
    parts = [f"背包 {stack['bag']} 件"]
    if equipped:
        parts.append(f"穿戴 {len(equipped)} 件：{owners}")
    return "、".join(parts)


def _catalog(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply("灵器词条", (
            "尚未结契，先领养伙伴；装备词条将在打造、购买或获得新装备后显示。",
        ), ("灵宠帮助",))
    if arg and not arg.isdecimal():
        raise GameError("格式：灵宠词条重铸 [页码]。")
    stacks = sorted(
        _owned_stacks(ctx).values(),
        key=lambda entry: (ctx.content.items[entry["item_id"]].name, entry["enhancement"]),
    )
    pages = max(1, (len(stacks) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = quantity(arg or "1", 999)
    if page > pages:
        raise GameError(f"灵器词条共 {pages} 页。")
    selected = stacks[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = [f"灵器词条 {page}/{pages} · 每次改写作用于同一装备与强化级的全部副本。"]
    links = []
    if not selected:
        lines.append("乾坤袋与已穿戴装备中还没有灵器。")
    for entry in selected:
        label = _stack_label(ctx, entry)
        current = rows(ctx, entry["item_id"], entry["enhancement"])
        summary = "、".join(
            f"{ctx.content.gear_words[word_id].name} +{value}"
            for word_id, value in current if word_id in ctx.content.gear_words
        ) or "尚无词条"
        lines.append(f"{label} · {_ownership_text(entry)} · {summary}")
        links.append(InlineCommand(len(lines) - 1, "查看词条", f"灵宠词条重铸 查看 {ctx.content.items[entry['item_id']].name} +{entry['enhancement']}"))
    commands = []
    if page > 1:
        commands.append(f"灵宠词条重铸 {page - 1}")
    if page < pages:
        commands.append(f"灵宠词条重铸 {page + 1}")
    commands.extend(("灵宠装备", "灵宠背包", "灵宠帮助 灵物与灵术"))
    return Reply("灵器词条", tuple(lines), tuple(commands[:4]), tuple(links))


def _detail(ctx: Context, item, level: int, stack: dict) -> Reply:
    current = rows(ctx, item.id, level)
    lines = [
        f"{item.name} +{level} · {_ownership_text(stack)}。",
        "改写同一装备与强化级会同步影响背包和已穿戴的全部副本。",
    ]
    links = []
    if not current:
        lines.append("该装备栈尚无词条，不能重铸；单件打造会生成词条。")
    for index, (word_id, value) in enumerate(current, 1):
        definition = ctx.content.gear_words.get(word_id)
        if definition is None:
            lines.append(f"词条 {index} 的旧内容定义暂不可用，不能安全改写。")
            continue
        lines.append(f"词条 {index}：{definition.name} +{value} · {STATS[definition.stat]}")
        links.append(InlineCommand(
            len(lines) - 1, "选择目标四维",
            f"灵宠词条重铸 选择 {item.name} +{level} {index}",
        ))
    lines.append(f"定向改写每个词条位消耗灵石 {SELECTIVE_STONES}、灵粮 {SELECTIVE_GRAIN}；其余词条不变。")
    return Reply("灵器词条详情", tuple(lines), ("灵宠词条重铸", "灵宠装备", "灵宠背包"), tuple(links))


def _parse_slot(ctx: Context, value: str, count: int) -> int:
    try:
        index = quantity(value, MAX_WORDS)
    except GameError:
        raise GameError(f"词条序号须为 1-{MAX_WORDS} 的整数。") from None
    if index > count:
        raise GameError(f"该装备只有 {count} 条词条，不能选择第 {index} 条。")
    return index - 1


def _choose(ctx: Context, item_name: str, level_text: str, slot_text: str) -> Reply:
    item, level, stack = _stack(ctx, item_name, level_text)
    current = rows(ctx, item.id, level)
    if not current:
        raise GameError(f"{item.name} +{level} 尚无词条，不能选择词条位。")
    index = _parse_slot(ctx, slot_text, len(current))
    word_id, value = current[index]
    definition = ctx.content.gear_words.get(word_id)
    if definition is None:
        raise GameError("该词条引用的内容暂不可用，未进行重铸。")
    lines = [
        f"{item.name} +{level} · 选择重洗词条 {index + 1}：{definition.name} +{value}（{STATS[definition.stat]}）。",
        f"覆盖范围：{_ownership_text(stack)}。",
        f"新词条会从所选四维的内容定义范围内产生，消耗灵石 {SELECTIVE_STONES}、灵粮 {SELECTIVE_GRAIN}。",
    ]
    commands = tuple(
        f"灵宠词条重铸 定向 {item.name} +{level} {index + 1} {stat}"
        for stat in STATS
    )
    return Reply("定向淬词", tuple(lines), commands)


def _selective(ctx: Context, item_name: str, level_text: str, slot_text: str, target_text: str) -> Reply:
    item, level, stack = _stack(ctx, item_name, level_text)
    player = ctx.player()
    current = rows(ctx, item.id, level)
    if not current:
        raise GameError(f"{item.name} +{level} 尚无词条，未进行重铸。")
    index = _parse_slot(ctx, slot_text, len(current))
    target = STAT_INPUTS.get(target_text)
    if target is None:
        raise GameError("目标四维须为气血、攻击、防御或速度。")
    old_word_id, old_value = current[index]
    old_word = ctx.content.gear_words.get(old_word_id)
    if old_word is None:
        raise GameError("该词条引用的内容暂不可用，未进行重铸。")
    choices = [
        (word, value)
        for word in ctx.content.gear_words.values() if word.stat == target
        for value in range(word.low, word.high + 1)
        if (word.id, value) != (old_word_id, old_value)
    ]
    if not choices:
        raise GameError(f"当前没有可用的{STATS[target]}词条结果，未扣除资源。")
    if player.stones < SELECTIVE_STONES:
        raise GameError(f"定向淬词需要 {SELECTIVE_STONES} 灵石，当前 {player.stones}。")
    inventory = ctx.repo.inventory(ctx.user_id)
    if inventory.get("spirit_food", 0) < SELECTIVE_GRAIN:
        raise GameError(f"定向淬词需要灵粮 {SELECTIVE_GRAIN}，当前 {inventory.get('spirit_food', 0)}。")

    word, value = choices[ctx.rng.randint(0, len(choices) - 1)]
    player.stones -= SELECTIVE_STONES
    ctx.repo.consume_item(ctx.user_id, "spirit_food", SELECTIVE_GRAIN)
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (ctx.user_id, stack_key(item.id, level, index, old_word_id)),
    )
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (ctx.user_id, stack_key(item.id, level, index, word.id), value),
    )
    if stack["pets"]:
        ctx.repo.invalidate_ready(ctx.user_id)
    after = rows(ctx, item.id, level)
    lines = [
        f"{item.name} +{level} 词条 {index + 1}：{old_word.name} +{old_value} → {word.name} +{value}（{STATS[target]}）。",
        f"已消耗灵石 {SELECTIVE_STONES}、灵粮 {SELECTIVE_GRAIN}；其余 {len(after) - 1} 条词条保持不变。",
        f"已更新该栈全部副本：{_ownership_text(stack)}。",
        f"新词条值 {value} 位于内容定义范围 {word.low}-{word.high}，装备战斗属性立即重算。",
    ]
    return Reply("定向淬词完成", tuple(lines), (
        f"灵宠词条重铸 查看 {item.name} +{level}", "灵宠装备", "灵宠背包",
    ), (InlineCommand(3, "重新查看词条", f"灵宠词条重铸 查看 {item.name} +{level}"),))


def roll(ctx: Context, item_id: str, enhancement: int) -> int:
    """Generate words for a fresh stack; returns the number of words rolled."""
    count = min(MAX_WORDS, 1 + enhancement // 4)
    for index in range(count):
        word = ctx.content.gear_words[list(ctx.content.gear_words)[
            ctx.rng.randint(0, len(ctx.content.gear_words) - 1)
        ]]
        value = ctx.rng.randint(word.low, word.high)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=1",
            (ctx.user_id, stack_key(item_id, enhancement, index, word.id), value),
        )
    return count


def reroll(ctx: Context, item_id: str, enhancement: int) -> None:
    """Reroll a stack's words in place, never reducing the count."""
    words = rows(ctx, item_id, enhancement)
    current = len(words)
    _clear(ctx, item_id, enhancement)
    count = max(current, min(MAX_WORDS, 1 + enhancement // 4))
    for index in range(count):
        word = ctx.content.gear_words[list(ctx.content.gear_words)[
            ctx.rng.randint(0, len(ctx.content.gear_words) - 1)
        ]]
        value = ctx.rng.randint(word.low, word.high)
        ctx.repo.conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
            (ctx.user_id, stack_key(item_id, enhancement, index, word.id), value),
        )


def word_reforge(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if not parts or (len(parts) == 1 and parts[0].isdecimal()):
        return _catalog(ctx, parts[0] if parts else "")
    if parts[0] == "查看":
        if len(parts) != 3:
            raise GameError("格式：灵宠词条重铸 查看 装备名 +强化等级。")
        item, level, stack = _stack(ctx, parts[1], parts[2])
        return _detail(ctx, item, level, stack)
    if parts[0] == "选择":
        if len(parts) != 4:
            raise GameError("格式：灵宠词条重铸 选择 装备名 +强化等级 词条序号。")
        return _choose(ctx, *parts[1:])
    if parts[0] == "定向":
        if len(parts) != 5:
            raise GameError("格式：灵宠词条重铸 定向 装备名 +强化等级 词条序号 目标四维。")
        return _selective(ctx, *parts[1:])

    if len(parts) != 1:
        raise GameError(
            "格式：灵宠词条重铸 [页码|查看 装备名 +等级|选择 装备名 +等级 序号|"
            "定向 装备名 +等级 序号 四维]。仅填装备名保留整件随机重铸。"
        )
    item = named(ctx.content.items, parts[0])
    gear = ctx.content.equipment.get(item.id) if item.kind == "equipment" else None
    if gear is None:
        raise GameError("未找到该装备，请检查名称。")
    player = ctx.player()
    stacks = _owned_stacks(ctx)
    owned_levels = [level for (item_id, level) in stacks if item_id == item.id]
    if not owned_levels:
        raise GameError(f"未持有或穿戴{item.name}，不能重铸词条。")
    enhancement = max(owned_levels)
    current = len(rows(ctx, item.id, enhancement))
    if current == 0:
        raise GameError(f"{item.name} +{enhancement} 还没有词条，先打造或获得带词条的装备。")
    if player.stones < REFORGE_STONES:
        raise GameError(f"词条重铸需要 {REFORGE_STONES} 灵石，当前不足。")
    grain = ctx.repo.conn.execute(
        "SELECT quantity FROM inventory WHERE user_id=? AND item_id='spirit_food'",
        (player.user_id,),
    ).fetchone()
    if grain is None or grain["quantity"] < REFORGE_GRAIN:
        raise GameError(f"词条重铸需要 {REFORGE_GRAIN} 份灵粮，当前不足。")
    player.stones -= REFORGE_STONES
    ctx.repo.conn.execute(
        "UPDATE inventory SET quantity=quantity-? WHERE user_id=? AND item_id='spirit_food'",
        (REFORGE_GRAIN, player.user_id),
    )
    before = rows(ctx, item.id, enhancement)
    reroll(ctx, item.id, enhancement)
    if stacks[(item.id, enhancement)]["pets"]:
        ctx.repo.invalidate_ready(ctx.user_id)
    return Reply("词条重铸", (
        f"{item.name} +{enhancement} 的词条已重铸。",
        "改写：" + "、".join(
            f"{STATS[ctx.content.gear_words[old].stat]} {ctx.content.gear_words[old].name} +{value} → "
            f"{ctx.content.gear_words[new].name} +{new_value}"
            for (old, value), (new, new_value) in zip(before, rows(ctx, item.id, enhancement))
        ),
        describe(ctx, item.id, enhancement),
        f"花费灵石 {REFORGE_STONES}、灵粮 {REFORGE_GRAIN}。",
    ), ("灵宠词条重铸", "灵宠背包", "灵宠装备", "灵宠工坊"))
