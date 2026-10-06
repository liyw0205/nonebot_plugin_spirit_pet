import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from .catalog import ADVENTURES, REALMS, SPECIES, breakthrough_cost
from .config import Config
from .models import GameError, Reply
from .storage import Store

HELP = Reply(
    "灵宠仙途",
    (
        "灵宠领养 青鸾 / 玄狐 / 白泽 / 蛟龙",
        "我的灵宠 / 灵宠签到 / 灵宠喂养",
        "灵宠修炼 / 灵宠突破 / 灵宠历练",
        "灵宠背包 / 灵宠商店 / 灵宠购买 灵粮 3",
        "灵宠改名 名字 / 灵宠排行 / 灵宠图鉴",
        "灵宠身份：查看当前玩家 ID。不同 ID 是不同玩家。",
    ),
    ("灵宠领养 青鸾", "灵宠图鉴", "我的灵宠", "灵宠签到"),
)
COMMANDS = {
    "灵宠帮助": "help",
    "灵宠": "help",
    "灵宠领养": "adopt",
    "我的灵宠": "status",
    "灵宠签到": "sign",
    "灵宠喂养": "feed",
    "灵宠修炼": "train",
    "灵宠突破": "breakthrough",
    "灵宠历练": "explore",
    "灵宠背包": "bag",
    "灵宠商店": "shop",
    "灵宠购买": "buy",
    "灵宠改名": "rename",
    "灵宠排行": "rank",
    "灵宠图鉴": "catalog",
    "灵宠身份": "identity",
}


class Game:
    def __init__(self, store: Store, config: Config, rng=None):
        self.store = store
        self.config = config
        self.rng = rng or random.SystemRandom()

    def execute(
        self, user_id: str, action: str, argument: str, operation_id: str, now: int | None = None
    ) -> Reply:
        if not user_id or not operation_id:
            raise ValueError("user ID and operation ID are required")
        if action not in COMMANDS.values():
            raise GameError("未知指令，请发送 /灵宠帮助。")
        timestamp = int(time.time()) if now is None else now
        return self.store.transact(
            user_id,
            operation_id,
            timestamp,
            lambda conn: self._apply(conn, user_id, action, argument.strip(), timestamp),
        )

    def _apply(
        self, conn: sqlite3.Connection, user_id: str, action: str, arg: str, now: int
    ) -> Reply:
        if action not in {"adopt", "buy", "rename"} and arg:
            raise GameError("该指令不接受参数，请发送 /灵宠帮助。")
        if action == "help":
            return HELP
        if action == "identity":
            return Reply("灵契身份", (f"玩家 ID：{user_id}", "同 ID 共用存档，不同 ID 各自成长。"))
        if action == "catalog":
            return Reply("万灵图鉴", tuple(f"{name}：{desc}" for name, desc in SPECIES.items()))
        if action == "shop":
            return Reply("山海灵坊", ("灵粮：20 灵石 / 份", "购买：灵宠购买 灵粮 数量（1-99）"))
        if action == "rank":
            rows = conn.execute(
                "SELECT pet_name, species, realm, exp FROM players "
                "ORDER BY realm DESC, exp DESC, user_id LIMIT 10"
            ).fetchall()
            return Reply(
                "万灵榜",
                tuple(
                    f"{i}. {row['pet_name']}（{row['species']}）"
                    f" · {REALMS[row['realm']]} · 修为 {row['exp']}"
                    for i, row in enumerate(rows, 1)
                ) or ("尚无灵宠入榜。",),
            )
        row = conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
        if action == "adopt":
            if row:
                raise GameError("你已与灵宠结契，请发送 /我的灵宠。")
            species = arg or self.rng.choice(tuple(SPECIES))
            if species not in SPECIES:
                raise GameError("可领养：青鸾、玄狐、白泽、蛟龙。示例：灵宠领养 青鸾")
            conn.execute(
                "INSERT INTO players (user_id, pet_name, species, energy_updated) VALUES (?, ?, ?, ?)",
                (user_id, species, species, now),
            )
            return Reply("灵契初成", (f"你与{species}缔结了灵契。", "获赠 100 灵石、3 份灵粮。"))
        if not row:
            raise GameError("尚未结契，请先发送 /灵宠领养 青鸾。")
        pet = dict(row)
        self._restore_energy(pet, now)
        reply = self._play(pet, action, arg, now)
        conn.execute(
            "UPDATE players SET pet_name=:pet_name, realm=:realm, exp=:exp, stones=:stones, "
            "food=:food, affinity=:affinity, energy=:energy, energy_updated=:energy_updated, "
            "sign_day=:sign_day, last_train=:last_train, last_explore=:last_explore "
            "WHERE user_id=:user_id",
            pet,
        )
        return reply

    def _restore_energy(self, pet: dict, now: int) -> None:
        interval = self.config.spirit_pet_energy_interval
        restored = max(0, now - pet["energy_updated"]) // interval
        pet["energy"] = min(100, pet["energy"] + restored)
        if pet["energy"] == 100:
            pet["energy_updated"] = max(now, pet["energy_updated"])
        else:
            pet["energy_updated"] += restored * interval

    def _play(self, pet: dict, action: str, arg: str, now: int) -> Reply:
        name = pet["pet_name"]
        if action == "status":
            exp_cost, stone_cost = breakthrough_cost(pet["realm"])
            next_realm = (
                "已达当前最高境界。" if pet["realm"] == len(REALMS) - 1
                else f"突破所需：{exp_cost} 修为、{stone_cost} 灵石"
            )
            return Reply(
                name,
                (
                    f"种族：{pet['species']} · 境界：{REALMS[pet['realm']]}",
                    f"修为：{pet['exp']} · 灵石：{pet['stones']}",
                    f"精力：{pet['energy']}/100 · 亲密：{pet['affinity']}/100",
                    f"灵粮：{pet['food']} 份",
                    next_realm,
                ),
            )
        if action == "bag":
            return Reply("乾坤袋", (f"灵石：{pet['stones']}", f"灵粮：{pet['food']} 份"))
        if action == "sign":
            day = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date().isoformat()
            if pet["sign_day"] >= day:
                raise GameError("今日已领取仙缘，明日再来。（每日北京时间 00:00 刷新）")
            pet["sign_day"] = day
            pet["stones"] += 200
            pet["food"] += 3
            return Reply("今日仙缘", ("灵石 +200，灵粮 +3。", f"{name}与你共沐晨光。"))
        if action == "feed":
            if pet["food"] < 1:
                raise GameError("灵粮不足，可签到领取或在灵宠商店购买。")
            pet["food"] -= 1
            restored = min(20, 100 - pet["energy"])
            pet["energy"] += restored
            if pet["energy"] == 100:
                pet["energy_updated"] = max(now, pet["energy_updated"])
            pet["exp"] += 10
            affinity = min(5, 100 - pet["affinity"])
            pet["affinity"] += affinity
            return Reply("灵粮温养", (f"{name}享用了灵粮。", f"精力 +{restored}，修为 +10，亲密 +{affinity}。"))
        if action in {"train", "explore"}:
            cost = 15 if action == "train" else 25
            cooldown = (
                self.config.spirit_pet_train_cooldown if action == "train"
                else self.config.spirit_pet_explore_cooldown
            )
            previous = pet[f"last_{action}"]
            if previous is not None and now < previous + cooldown:
                raise GameError(f"尚需调息 {previous + cooldown - now} 秒。")
            if pet["energy"] < cost:
                raise GameError(f"精力不足，需要 {cost} 点；可喂养或等待自然恢复。")
            pet["energy"] -= cost
            pet[f"last_{action}"] = now
            if action == "train":
                gained = self.rng.randint(30, 50)
                pet["exp"] += gained
                return Reply("吐纳修炼", (f"{name}吸纳天地灵气。", f"修为 +{gained}，精力 -15。"))
            exp, stones, food = self.rng.randint(15, 40), self.rng.randint(30, 90), self.rng.randint(0, 2)
            pet["exp"] += exp
            pet["stones"] += stones
            pet["food"] += food
            return Reply(
                "山海历练",
                (self.rng.choice(ADVENTURES), f"修为 +{exp}，灵石 +{stones}，灵粮 +{food}，精力 -25。"),
            )
        if action == "breakthrough":
            if pet["realm"] >= len(REALMS) - 1:
                raise GameError("已达当前最高境界，静候新的仙途。")
            exp_cost, stone_cost = breakthrough_cost(pet["realm"])
            if pet["exp"] < exp_cost or pet["stones"] < stone_cost:
                raise GameError(f"突破需要 {exp_cost} 修为和 {stone_cost} 灵石。")
            chance = min(0.98, max(0.45, 0.90 - pet["realm"] * 0.08) + pet["affinity"] / 1000)
            pet["stones"] -= stone_cost
            if self.rng.random() < chance:
                pet["exp"] -= exp_cost
                pet["realm"] += 1
                return Reply("破境成功", (f"{name}踏入{REALMS[pet['realm']]}境！", f"修为 -{exp_cost}，灵石 -{stone_cost}。"))
            lost = exp_cost // 4
            pet["exp"] -= lost
            return Reply("破境未成", ("灵息稍乱，境界不变。", f"损失 {lost} 修为、{stone_cost} 灵石。"))
        if action == "buy":
            match = re.fullmatch(r"灵粮\s+([0-9]{1,2})", arg)
            if not match or not 1 <= int(match[1]) <= 99:
                raise GameError("格式：灵宠购买 灵粮 3，数量须为 1-99 的整数。")
            amount = int(match[1])
            if pet["stones"] < amount * 20:
                raise GameError("灵石不足。")
            pet["stones"] -= amount * 20
            pet["food"] += amount
            return Reply("灵坊购得", (f"灵粮 +{amount}，灵石 -{amount * 20}。",))
        if action == "rename":
            if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{1,12}", arg):
                raise GameError("名字限 1-12 个汉字、英文字母或数字。")
            pet["pet_name"] = arg
            return Reply("赐名结缘", (f"灵宠从此名为：{arg}。",))
        raise GameError("未知指令，请发送 /灵宠帮助。")
