"""Cross-player gifting and foster care.

Gifts are strictly one-way (item/material stacks or raw stones) with a daily
limit; foster care transfers temporary caretaking of an idle pet to a teammate
without changing ownership. Anti-abuse rules:

- both actions require a friendship edge (arena history or team history);
- gifts cannot be reversed and never exceed 2000 stones per gift;
- fostering moves no resources: feeding uses the caretaker's own food and the
  pet keeps its owner;
- the daily cross-player operation log lives in `quest_progress`
  (`gift_log_<day>_<ordinal>` rows) for limit checks.

Schema 20 stays untouched.
"""

from datetime import date

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from ..utils.arguments import item_amount, quantity
from ..utils.time import beijing_day
from .economy import _use_consumable
from .rewards import grant

GIFT_LOG_PREFIX = "gift_log_"
FOSTER_PREFIX = "foster_"
GIFTS_PER_DAY = 3
MAX_STONES_PER_GIFT = 2000
MAX_MATERIAL_PER_GIFT = 20
GIFTABLE_KINDS = {"material", "consumable"}


def _today(ctx: Context) -> str:
    return beijing_day(ctx.now)


def gift_log_count(ctx: Context, day: str) -> int:
    prefix = f"{GIFT_LOG_PREFIX}{day}_"
    row = ctx.repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id=? AND substr(quest_id, 1, ?)=?",
        (ctx.user_id, len(prefix), prefix),
    ).fetchone()
    return row["n"]


def _log_gift(ctx: Context, day: str, ordinal: int) -> None:
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        (ctx.user_id, f"{GIFT_LOG_PREFIX}{day}_{ordinal}"),
    )


def are_friends(ctx: Context, sender: str, target: str) -> bool:
    """One shared battle or team edge is enough (mirrors 论剑/同队 history)."""
    arena = ctx.repo.conn.execute(
        "SELECT 1 FROM battle_participants a JOIN battle_participants b USING(battle_id) "
        "WHERE a.user_id=? AND b.user_id=? LIMIT 1",
        (sender, target),
    ).fetchone()
    if arena:
        return True
    team_ids = {
        row["team_id"] for row in ctx.repo.conn.execute(
            "SELECT t.team_id FROM team_members mine JOIN team_members t USING(team_id) "
            "WHERE mine.user_id=? AND t.user_id=?",
            (sender, target),
        )
    }
    return bool(team_ids)


def foster_row(ctx: Context, pet_id: int):
    return ctx.repo.conn.execute(
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
        (ctx.user_id, f"{FOSTER_PREFIX}{pet_id}"),
    ).fetchone()


def _fostered_by(ctx: Context, pet_id: int) -> str | None:
    row = ctx.repo.conn.execute(
        "SELECT p.user_id AS owner_id, f.progress AS caretaker_uid FROM quest_progress f "
        "JOIN pets p ON p.pet_id=? WHERE f.user_id=p.user_id AND f.quest_id=? AND f.claimed=1",
        (pet_id, f"{FOSTER_PREFIX}{pet_id}"),
    ).fetchone()
    if row is None:
        return None
    player = ctx.repo.player_by_uid(row["caretaker_uid"])
    return player.user_id if player else None


def gift(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 3:
        raise GameError("格式：灵宠赠送 <UID> <物品名|灵石> <数量>。")
    uid_text, name, amount_text = parts
    player = ctx.player()
    target = ctx.repo.player_by_uid(quantity(uid_text, 9_223_372_036_854_775_807))
    if target is None or target.user_id == player.user_id:
        raise GameError("请填写其他玩家的 UID。")
    if not are_friends(ctx, player.user_id, target.user_id):
        raise GameError("只能向论剑或同队出现过的玩家赠送。")
    day = _today(ctx)
    ordinal = gift_log_count(ctx, day)
    if ordinal >= GIFTS_PER_DAY:
        raise GameError(f"今日赠送已达 {GIFTS_PER_DAY} 次，明日 00:00（北京时间）再送。")
    amount = quantity(amount_text, 99999)
    if name == "灵石":
        if amount > MAX_STONES_PER_GIFT:
            raise GameError(f"单次赠送灵石最多 {MAX_STONES_PER_GIFT}。")
        if player.stones < amount:
            raise GameError("灵石不足。")
        player.stones -= amount
        target_row = ctx.repo.player(target.user_id)
        target_row.stones += amount
        _log_gift(ctx, day, ordinal + 1)
        return Reply("灵宠赠送", (
            f"已向 UID {target.uid} 赠送灵石 {amount}。",
            f"今日已赠送 {ordinal + 1}/{GIFTS_PER_DAY} 次。",
        ), ("我的信息", "灵宠帮助"))
    item = next(
        (entry for entry in ctx.content.items.values() if entry.name == name), None,
    )
    if item is None or item.kind not in GIFTABLE_KINDS:
        raise GameError("只能赠送灵石、消耗品或材料；装备、灵卵与秘笈不可赠送。")
    if amount > MAX_MATERIAL_PER_GIFT:
        raise GameError(f"单次赠送道具最多 {MAX_MATERIAL_PER_GIFT} 件。")
    ctx.repo.consume_item(player.user_id, item.id, amount)
    ctx.repo.add_item(target.user_id, item.id, amount)
    _log_gift(ctx, day, ordinal + 1)
    return Reply("灵宠赠送", (
        f"已向 UID {target.uid} 赠送 {item.name} {amount}。",
        f"今日已赠送 {ordinal + 1}/{GIFTS_PER_DAY} 次。",
    ), ("我的信息", "灵宠帮助"))


def foster(ctx: Context, arg: str) -> Reply:
    parts = arg.split()
    if len(parts) != 2:
        raise GameError("格式：灵宠寄养 <UID> <宠物编号>。")
    uid_text, pet_text = parts
    player = ctx.player()
    target = ctx.repo.player_by_uid(quantity(uid_text, 9_223_372_036_854_775_807))
    if target is None or target.user_id == player.user_id:
        raise GameError("请填写其他玩家的 UID。")
    if not are_friends(ctx, player.user_id, target.user_id):
        raise GameError("只能把灵宠寄养给论剑或同队出现过的玩家。")
    pet_id = quantity(pet_text, 9_223_372_036_854_775_807)
    pet = ctx.repo.pet(pet_id)
    if pet is None or pet.user_id != player.user_id:
        raise GameError("没有属于你的这只灵宠。")
    if pet.archived:
        raise GameError("封存灵宠不能寄养，请先复原。")
    if _fostered_by(ctx, pet.pet_id) is not None:
        raise GameError(f"{pet.name}已在寄养中，先归还再重新寄养。")
    if player.active_pet_id == pet.pet_id:
        raise GameError("出战灵宠不能寄养，请先切换其他灵宠出战。")
    ctx.require_idle_pet(pet)
    caretaker = ctx.repo.player(target.user_id)
    if caretaker is None:
        raise GameError("对方存档异常，暂不能寄养。")
    ctx.repo.conn.execute(
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (player.user_id, f"{FOSTER_PREFIX}{pet.pet_id}", caretaker.uid),
    )
    return Reply("灵宠寄养", (
        f"{pet.name}已寄养给 UID {target.uid}，由对方代管喂食；归属不变。",
        "发送 灵宠归还 <宠物编号> 可随时取回。",
    ), (f"灵宠归还 {pet.pet_id}", "灵宠列表"))


def foster_feed(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet_id = quantity(arg.strip(), 9_223_372_036_854_775_807)
    pet = ctx.repo.pet(pet_id)
    owner_id = _fostered_by(ctx, pet.pet_id) if pet else None
    if pet is None or owner_id is None or owner_id != player.user_id:
        raise GameError("只有代管方可以喂食寄养中的灵宠。")
    owner = ctx.repo.player(owner_id)
    if owner is None:
        raise GameError("原主人存档异常，暂不能喂食。")
    item = ctx.content.items["spirit_food"]
    return _use_consumable(ctx, item, 1, pet)


def foster_return(ctx: Context, arg: str) -> Reply:
    player = ctx.player()
    pet_id = quantity(arg.strip(), 9_223_372_036_854_775_807)
    pet = ctx.repo.pet(pet_id)
    caretaker = _fostered_by(ctx, pet.pet_id) if pet else None
    if pet is None or caretaker is None:
        raise GameError("这只灵宠没有在寄养中。")
    if player.user_id not in {pet.user_id, caretaker}:
        raise GameError("只有原主人或代管方可以归还寄养灵宠。")
    owner = ctx.repo.player(pet.user_id)
    owner_uid = owner.uid if owner else 0
    ctx.repo.conn.execute(
        "DELETE FROM quest_progress WHERE user_id=? AND quest_id=?",
        (pet.user_id, f"{FOSTER_PREFIX}{pet.pet_id}"),
    )
    return Reply("灵宠归还", (
        f"{pet.name}已归还给原主人（UID {owner_uid}）。",
    ), ("灵宠列表", "灵宠帮助"))