import json
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
            data = dict(row)
            data["archived"] = bool(data["archived"])
            self.pets[pet_id] = Pet(**data)
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

    def active_pets(self, user_id: str) -> list[Pet]:
        """Return the persisted battle roster, with a safe legacy fallback."""
        player = self.player(user_id)
        rows = self.conn.execute(
            "SELECT pet_id FROM active_pet_slots WHERE user_id=? ORDER BY slot", (user_id,),
        ).fetchall()
        if rows and player is not None and player.active_pet_id == rows[0]["pet_id"]:
            return [self.pet(row["pet_id"]) for row in rows]
        if player is None or player.active_pet_id is None:
            return []
        return [self.pet(player.active_pet_id)]

    def set_active_pets(self, user_id: str, pet_ids: list[int]) -> None:
        if not 1 <= len(pet_ids) <= 3:
            raise GameError("出战阵容需要 1-3 只灵宠。")
        if len(set(pet_ids)) != len(pet_ids):
            raise GameError("同一只灵宠不能重复出战。")
        placeholders = ",".join("?" for _ in pet_ids)
        rows = self.conn.execute(
            f"SELECT pet_id, species_id, archived FROM pets WHERE user_id=? AND pet_id IN ({placeholders})",
            (user_id, *pet_ids),
        ).fetchall()
        by_id = {int(row["pet_id"]): row for row in rows}
        if len(by_id) != len(pet_ids):
            raise GameError("只能选择属于你的灵宠出战。")
        if any(row["archived"] for row in by_id.values()):
            raise GameError("封存灵宠不能出战，请先复原。")
        if len({row["species_id"] for row in by_id.values()}) != len(pet_ids):
            raise GameError("同一出战阵容不能包含重复宠物种类。")
        self.conn.execute("DELETE FROM active_pet_slots WHERE user_id=?", (user_id,))
        self.conn.executemany(
            "INSERT INTO active_pet_slots(user_id, slot, pet_id) VALUES (?, ?, ?)",
            [(user_id, slot, pet_id) for slot, pet_id in enumerate(pet_ids, 1)],
        )
        player = self.player(user_id)
        if player is not None:
            player.active_pet_id = pet_ids[0]

    def owned_pets(self, user_id: str) -> list[Pet]:
        ids = self.conn.execute(
            "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id", (user_id,),
        )
        return [self.pet(row["pet_id"]) for row in ids]

    def archived_pets(self, user_id: str, *, limit: int, offset: int) -> list[Pet]:
        ids = self.conn.execute(
            "SELECT pet_id FROM pets WHERE user_id=? AND archived=1 ORDER BY pet_id LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        return [self.pet(row["pet_id"]) for row in ids]

    def archived_pet_count(self, user_id: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM pets WHERE user_id=? AND archived=1", (user_id,),
        ).fetchone()[0])

    def inventory(self, user_id: str) -> dict[str, int]:
        return dict(self.conn.execute(
            "SELECT item_id, quantity FROM inventory WHERE user_id=? AND quantity>0 ORDER BY item_id",
            (user_id,),
        ))

    def player_resonance(self, user_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT resonance_id, activated_at FROM player_resonance WHERE user_id=?", (user_id,),
        ).fetchone()

    def set_player_resonance(self, user_id: str, resonance_id: str, activated_at: int) -> None:
        self.conn.execute(
            "INSERT INTO player_resonance(user_id, resonance_id, activated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET resonance_id=excluded.resonance_id, "
            "activated_at=excluded.activated_at",
            (user_id, resonance_id, activated_at),
        )

    def clear_player_resonance(self, user_id: str) -> None:
        self.conn.execute("DELETE FROM player_resonance WHERE user_id=?", (user_id,))

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
        self.conn.execute(
            "UPDATE team_members SET ready_pet_id=NULL, ready_pet_ids='' WHERE user_id=?", (user_id,),
        )

    def invalidate_pet_ready(self, user_id: str, pet_id: int) -> None:
        member = self.conn.execute(
            "SELECT t.leader_id FROM team_members m JOIN teams t USING(team_id) "
            "WHERE m.user_id=? AND m.ready_pet_id IS NOT NULL", (user_id,),
        ).fetchone()
        if member is None:
            return
        pets = self.active_pets(user_id)
        participants = pets if member["leader_id"] == user_id else pets[:1]
        if any(pet.pet_id == pet_id for pet in participants):
            self.invalidate_ready(user_id)

    def invalidate_team_ready(self, team_id: int) -> None:
        self.conn.execute(
            "UPDATE team_members SET ready_pet_id=NULL, ready_pet_ids='' WHERE team_id=?", (team_id,),
        )

    def record_battle(
        self, *, operation_id: str, initiator_id: str, kind: str, battle_key: str, title: str,
        winner_side: int, rounds: int, played_at: int, reply: dict,
        snapshot: dict, battle_log: tuple[str, ...], participants: list[dict],
    ) -> int:
        """Persist one immutable battle and its user visibility rows.

        The operation ID makes retries idempotent even after the short-lived
        operations reply cache has expired.  Snapshot and log are JSON values,
        so later pet/dao-name changes cannot alter a historical report.
        """
        existing = self.conn.execute(
            "SELECT battle_id FROM battle_records WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if existing is not None:
            return int(existing["battle_id"])
        cursor = self.conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, winner_side, rounds, played_at, "
            "reply, snapshot, battle_log) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                operation_id, initiator_id, kind, battle_key, title, winner_side, rounds, played_at,
                json.dumps(reply, ensure_ascii=False, separators=(",", ":")),
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                json.dumps(list(battle_log), ensure_ascii=False, separators=(",", ":")),
            ),
        )
        battle_id = int(cursor.lastrowid)
        for participant in participants:
            self.conn.execute(
                "INSERT INTO battle_participants(battle_id, user_id, side, permission) VALUES (?, ?, ?, ?)",
                (battle_id, participant["user_id"], participant["side"], participant["permission"]),
            )
        return battle_id

    def battle_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT initiator_id, reply FROM battle_records WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["initiator_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def battle_history(self, user_id: str, *, limit: int = 5, offset: int = 0) -> list[sqlite3.Row]:
        if type(limit) is not int or limit < 1 or limit > 100:
            raise ValueError("battle history limit must be between 1 and 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("battle history offset must be nonnegative")
        return self.conn.execute(
            "SELECT b.*, p.side, p.permission FROM battle_records b "
            "JOIN battle_participants p ON p.battle_id=b.battle_id "
            "WHERE p.user_id=? ORDER BY b.played_at DESC, b.battle_id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()

    def battle_history_count(self, user_id: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM battle_participants WHERE user_id=?", (user_id,),
        ).fetchone()[0])

    def battle_report(self, user_id: str, battle_id: int) -> sqlite3.Row | None:
        """Return a report only when the requesting user participated in it."""
        return self.conn.execute(
            "SELECT b.*, p.side, p.permission FROM battle_records b "
            "JOIN battle_participants p ON p.battle_id=b.battle_id "
            "WHERE b.battle_id=? AND p.user_id=?", (battle_id, user_id),
        ).fetchone()

    def battle_participants(self, battle_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT user_id, side, permission FROM battle_participants "
            "WHERE battle_id=? ORDER BY side, user_id", (battle_id,),
        ).fetchall()

    def achievement_claim_by_operation(self, operation_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM achievement_claims WHERE operation_id=?", (operation_id,),
        ).fetchone()

    def achievement_claim(self, user_id: str, achievement_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM achievement_claims WHERE user_id=? AND achievement_id=?",
            (user_id, achievement_id),
        ).fetchone()

    def record_achievement_claim(
        self, *, user_id: str, achievement_id: str, operation_id: str,
        claimed_at: int, reward_snapshot: str, reply: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, reward_snapshot, reply) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, achievement_id, operation_id, claimed_at, reward_snapshot, reply),
        )

    def save(self) -> None:
        for pet in self.pets.values():
            self.conn.execute(
                "UPDATE pets SET name=:name, realm=:realm, layer=:layer, bloodline=:bloodline, lineage_id=:lineage_id, "
                "archived=:archived, exp=:exp, affinity=:affinity, "
                "major_breakthrough_failures=:major_breakthrough_failures, "
                "energy=:energy, energy_updated=:energy_updated "
                "WHERE pet_id=:pet_id AND user_id=:user_id", asdict(pet),
            )
        for player in self.players.values():
            self.conn.execute(
                "UPDATE players SET dao_name=:dao_name, stones=:stones, active_pet_id=:active_pet_id, sign_day=:sign_day, "
                "last_bond_day=:last_bond_day, current_bond_streak=:current_bond_streak, "
                "best_bond_streak=:best_bond_streak, "
                "quest_day=:quest_day, last_train=:last_train, last_explore=:last_explore, "
                "last_pve=:last_pve, last_pvp=:last_pvp WHERE user_id=:user_id",
                asdict(player),
            )
