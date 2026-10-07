import sqlite3
from dataclasses import asdict

from ..domain.models import GameError
from ..domain.state import Pet, Player


class Repository:
    """One identity map per transaction; never opens a second connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.players: dict[str, Player] = {}
        self.pets: dict[int, Pet] = {}

    def player(self, user_id: str) -> Player | None:
        if user_id not in self.players:
            row = self.conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
            if row is None:
                return None
            self.players[user_id] = Player(**dict(row))
        return self.players[user_id]

    def pet(self, pet_id: int) -> Pet:
        if pet_id not in self.pets:
            row = self.conn.execute("SELECT * FROM pets WHERE pet_id=?", (pet_id,)).fetchone()
            if row is None:
                raise GameError("灵宠不存在。")
            self.pets[pet_id] = Pet(**dict(row))
        return self.pets[pet_id]

    def active_expedition(self, pet_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM expeditions WHERE pet_id=? AND state='running'", (pet_id,),
        ).fetchone()

    def player_by_name(self, dao_name: str) -> Player | None:
        row = self.conn.execute("SELECT user_id FROM players WHERE dao_name=? COLLATE NOCASE", (dao_name,)).fetchone()
        return self.player(row["user_id"]) if row else None

    def create_player(self, user_id: str, dao_name: str, stones: int) -> Player:
        self.conn.execute("INSERT INTO players(user_id, dao_name, stones) VALUES (?, ?, ?)", (user_id, dao_name, stones))
        player = Player(user_id, dao_name, stones, None)
        self.players[user_id] = player
        return player

    def create_pet(self, user_id: str, species_id: str, name: str, affinity: int, now: int) -> Pet:
        cursor = self.conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated) VALUES (?, ?, ?, ?, ?)",
            (user_id, species_id, name, affinity, now),
        )
        return self.pet(cursor.lastrowid)

    def owned_pets(self, user_id: str) -> list[Pet]:
        ids = self.conn.execute("SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (user_id,))
        return [self.pet(row["pet_id"]) for row in ids]

    def inventory(self, user_id: str) -> dict[str, int]:
        return dict(self.conn.execute(
            "SELECT item_id, quantity FROM inventory WHERE user_id=? AND quantity>0 ORDER BY item_id",
            (user_id,),
        ))

    def add_item(self, user_id: str, item_id: str, amount: int) -> None:
        if amount < 0:
            raise ValueError("item amount cannot be negative")
        if amount:
            self.conn.execute(
                "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id) "
                "DO UPDATE SET quantity=quantity+excluded.quantity",
                (user_id, item_id, amount),
            )

    def consume_item(self, user_id: str, item_id: str, amount: int) -> None:
        if amount <= 0:
            raise ValueError("item amount must be positive")
        updated = self.conn.execute(
            "UPDATE inventory SET quantity=quantity-? WHERE user_id=? AND item_id=? AND quantity>=?",
            (amount, user_id, item_id, amount),
        )
        if updated.rowcount != 1:
            raise GameError("道具数量不足。")

    def invalidate_ready(self, user_id: str) -> None:
        self.conn.execute("UPDATE team_members SET ready_pet_id=NULL WHERE user_id=?", (user_id,))

    def save(self) -> None:
        for pet in self.pets.values():
            self.conn.execute(
                "UPDATE pets SET name=:name, realm=:realm, layer=:layer, bloodline=:bloodline, lineage_id=:lineage_id, "
                "exp=:exp, affinity=:affinity, energy=:energy, energy_updated=:energy_updated "
                "WHERE pet_id=:pet_id AND user_id=:user_id", asdict(pet),
            )
        for player in self.players.values():
            self.conn.execute(
                "UPDATE players SET dao_name=:dao_name, stones=:stones, active_pet_id=:active_pet_id, sign_day=:sign_day, "
                "quest_day=:quest_day, last_train=:last_train, last_explore=:last_explore, "
                "last_pve=:last_pve, last_pvp=:last_pvp, rating=:rating WHERE user_id=:user_id",
                asdict(player),
            )
