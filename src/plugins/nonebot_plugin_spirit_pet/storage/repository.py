import json
import re
import sqlite3
from dataclasses import asdict

from ..domain.models import GameError, Reply
from ..domain.state import ASCENDED_PREFIX, Pet, Player


_SPECIAL_REPLAY_PRIORITIES = {
    "cuisine_order": 1,
    "weekly_reward": 2,
    "pill_furnace": 3,
    "angling": 4,
    "adventure_travel": 5,
    "farm_care": 6,
    "convoy": 7,
    "training": 8,
    "play_course": 9,
    "nursery": 10,
    "herbalism": 11,
    "tracking": 12,
    "cooking": 13,
    "vein_expedition": 14,
    "ruin_expedition": 15,
    "cave_coop": 16,
    "stage_tactic": 15,
    "farm_contract": 6,
    "item_trade": 16,
    "cuisine_coop": 16,
    "friend_relay": 15,
    "wild_survey_claim": 17,
    "pedigree": 18,
    "family_trial": 15,
}


class Repository:
    """One identity map per transaction; never opens a second connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.players: dict[str, Player] = {}
        self.pets: dict[int, Pet] = {}

    def player(self, user_id: str) -> Player | None:
        if user_id not in self.players:
            row = self.conn.execute(
                "SELECT p.*, identity.id AS internal_id FROM players p "
                "JOIN player_identity identity USING(user_id) WHERE p.user_id=?", (user_id,),
            ).fetchone()
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
            pet = Pet(**data)
            pet.ascended = bool(self.conn.execute(
                "SELECT 1 FROM quest_progress WHERE user_id=? AND quest_id=? AND claimed=1",
                (pet.user_id, f"{ASCENDED_PREFIX}{pet.pet_id}"),
            ).fetchone())
            self.pets[pet_id] = pet
        return self.pets[pet_id]

    def _pet_from_row(self, row: sqlite3.Row) -> Pet:
        pet_id = int(row["pet_id"])
        cached = self.pets.get(pet_id)
        if cached is not None:
            return cached
        data = dict(row)
        data["archived"] = bool(data["archived"])
        data["ascended"] = bool(data.get("ascended", 0))
        pet = Pet(**data)
        self.pets[pet_id] = pet
        return pet

    def active_expedition(self, pet_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM expeditions WHERE pet_id=? AND state='running'", (pet_id,),
        ).fetchone()

    def active_expeditions(self, pet_ids: list[int]) -> dict[int, sqlite3.Row]:
        """Load running expeditions for a rendered pet page in one round trip."""
        if not pet_ids:
            return {}
        placeholders = ",".join("?" for _ in pet_ids)
        rows = self.conn.execute(
            f"SELECT * FROM expeditions WHERE state='running' AND pet_id IN ({placeholders})",
            tuple(pet_ids),
        )
        return {int(row["pet_id"]): row for row in rows}

    def player_by_uid(self, value: str | int) -> Player | None:
        text = str(value).strip()
        match = re.fullmatch(r"(?:UID\s*)?([0-9]+)", text, re.IGNORECASE)
        if match is None:
            return None
        uid = int(match.group(1))
        if not 10000 <= uid <= 9_223_372_036_854_785_806:
            return None
        row = self.conn.execute(
            "SELECT user_id FROM player_identity WHERE id=?", (uid - 9999,),
        ).fetchone()
        return self.player(row["user_id"]) if row else None

    def create_player(self, user_id: str, stones: int, now: int) -> Player:
        self.conn.execute(
            "INSERT INTO players(user_id, stones, registered_at) VALUES (?, ?, ?)",
            (user_id, stones, now),
        )
        cursor = self.conn.execute("INSERT INTO player_identity(user_id) VALUES (?)", (user_id,))
        player = Player(user_id, cursor.lastrowid, stones, None, registered_at=now)
        self.players[user_id] = player
        return player

    def create_pet(self, user_id: str, species_id: str, name: str, affinity: int, now: int) -> Pet:
        cursor = self.conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated) VALUES (?, ?, ?, ?, ?)",
            (user_id, species_id, name, affinity, now),
        )
        return self.pet(cursor.lastrowid)

    def record_pedigree_operation(
        self, operation_id: str, user_id: str, kind: str, created_at: int,
        snapshot: dict, reply: Reply,
    ) -> None:
        if kind not in {"breed", "hatch", "milestone_claim"}:
            raise ValueError("invalid pedigree operation kind")
        self.conn.execute(
            "INSERT INTO pet_pedigree_operations(operation_id,user_id,kind,created_at,snapshot,reply) "
            "VALUES (?,?,?,?,?,?)",
            (operation_id, user_id, kind, created_at, json.dumps(snapshot, ensure_ascii=False),
             json.dumps(asdict(reply), ensure_ascii=False)),
        )

    def record_lineage_egg(
        self, *, user_id: str, item_id: str, species_id: str, parent_a_id: int,
        parent_a_name: str, parent_b_id: int, parent_b_name: str, operation_id: str,
        created_at: int,
    ) -> int:
        parents = self.conn.execute(
            "SELECT pet_id,user_id,species_id FROM pets WHERE pet_id IN (?,?)",
            (parent_a_id, parent_b_id),
        ).fetchall()
        if len(parents) != 2 or any(
            row["user_id"] != user_id or row["species_id"] != species_id for row in parents
        ):
            raise GameError("灵卵亲本凭证与当前灵宠不一致。")
        cursor = self.conn.execute(
            "INSERT INTO pet_lineage_eggs(user_id,item_id,species_id,parent_a_id,parent_a_name,"
            "parent_a_species_id,parent_b_id,parent_b_name,parent_b_species_id,operation_id,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'available',?)",
            (user_id, item_id, species_id, parent_a_id, parent_a_name, species_id,
             parent_b_id, parent_b_name, species_id, operation_id, created_at),
        )
        return int(cursor.lastrowid)

    def _pet_egg_quantity(self, user_id: str, item_id: str) -> int:
        row = self.conn.execute(
            "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user_id, item_id),
        ).fetchone()
        return int(row["quantity"]) if row else 0

    def consume_pet_eggs(self, user_id: str, item_id: str, amount: int, now: int) -> list[int | None]:
        """Consume unknown-source eggs first, then known lineage eggs in FIFO order."""
        if amount <= 0:
            raise ValueError("pet egg amount must be positive")
        quantity = self._pet_egg_quantity(user_id, item_id)
        if quantity < amount:
            raise GameError("道具数量不足。")
        available = self.conn.execute(
            "SELECT egg_record_id FROM pet_lineage_eggs "
            "WHERE user_id=? AND item_id=? AND status='available' ORDER BY egg_record_id",
            (user_id, item_id),
        ).fetchall()
        unknown = quantity - len(available)
        if unknown < 0:
            raise RuntimeError("available lineage eggs exceed inventory quantity")
        unknown_to_consume = min(amount, unknown)
        known_to_consume = amount - unknown_to_consume
        selected = [int(row["egg_record_id"]) for row in available[:known_to_consume]]
        if len(selected) != known_to_consume:
            raise RuntimeError("lineage egg inventory is inconsistent")
        self.consume_item(user_id, item_id, amount)
        if selected:
            updated = self.conn.execute(
                "UPDATE pet_lineage_eggs SET status='consumed',finished_at=? "
                "WHERE status='available' AND egg_record_id IN ("
                + ",".join("?" for _ in selected) + ")",
                (now, *selected),
            )
            if updated.rowcount != len(selected):
                raise RuntimeError("lineage egg inventory changed during consumption")
        return [None] * unknown_to_consume + selected

    def reserve_pet_egg(self, user_id: str, item_id: str, reservation_id: str, now: int) -> int | None:
        selected = self.consume_pet_eggs(user_id, item_id, 1, now)[0]
        if selected is None:
            return None
        updated = self.conn.execute(
            "UPDATE pet_lineage_eggs SET status='reserved',reservation_id=?,finished_at=NULL "
            "WHERE egg_record_id=? AND user_id=? AND status='consumed'",
            (reservation_id, selected, user_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError("could not reserve lineage egg")
        return selected

    def return_reserved_pet_egg(self, user_id: str, egg_record_id: int) -> None:
        updated = self.conn.execute(
            "UPDATE pet_lineage_eggs SET status='available',reservation_id=NULL "
            "WHERE egg_record_id=? AND user_id=? AND status='reserved'",
            (egg_record_id, user_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError("could not return reserved lineage egg")

    def hatch_lineage_egg(
        self, user_id: str, egg_record_id: int, child_pet_id: int, child_name: str,
        finished_at: int, *, reservation_id: str | None = None,
    ) -> None:
        egg = self.conn.execute(
            "SELECT species_id FROM pet_lineage_eggs WHERE egg_record_id=? AND user_id=?",
            (egg_record_id, user_id),
        ).fetchone()
        child = self.conn.execute(
            "SELECT user_id,species_id FROM pets WHERE pet_id=?", (child_pet_id,),
        ).fetchone()
        if egg is None or child is None or child["user_id"] != user_id or child["species_id"] != egg["species_id"]:
            raise RuntimeError("lineage egg and child ownership or species mismatch")
        if reservation_id is None:
            updated = self.conn.execute(
                "UPDATE pet_lineage_eggs SET status='hatched',child_pet_id=?,child_name=?,finished_at=? "
                "WHERE egg_record_id=? AND user_id=? AND status='consumed'",
                (child_pet_id, child_name, finished_at, egg_record_id, user_id),
            )
        else:
            updated = self.conn.execute(
                "UPDATE pet_lineage_eggs SET status='hatched',reservation_id=NULL,child_pet_id=?,"
                "child_name=?,finished_at=? WHERE egg_record_id=? AND user_id=? AND status='reserved' "
                "AND reservation_id=?",
                (child_pet_id, child_name, finished_at, egg_record_id, user_id, reservation_id),
            )
        if updated.rowcount != 1:
            raise RuntimeError("could not hatch lineage egg")

    def egg_source_counts(self, user_id: str, item_id: str) -> tuple[int, int]:
        quantity = self._pet_egg_quantity(user_id, item_id)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM pet_lineage_eggs "
            "WHERE user_id=? AND item_id=? AND status='available'",
            (user_id, item_id),
        ).fetchone()
        known = int(row[0])
        if known > quantity:
            raise RuntimeError("available lineage eggs exceed inventory quantity")
        return quantity - known, known

    def lineage_eggs(self, user_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pet_lineage_eggs WHERE user_id=? AND status='hatched' "
            "ORDER BY child_pet_id",
            (user_id,),
        ).fetchall()

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

    def active_pet_ids(self, user_id: str) -> set[int]:
        """Return roster IDs without materializing pets for list rendering."""
        player = self.player(user_id)
        rows = self.conn.execute(
            "SELECT pet_id FROM active_pet_slots WHERE user_id=? ORDER BY slot", (user_id,),
        ).fetchall()
        if rows and player is not None and player.active_pet_id == rows[0]["pet_id"]:
            return {int(row["pet_id"]) for row in rows}
        if player is None or player.active_pet_id is None:
            return set()
        return {int(player.active_pet_id)}

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

    def owned_pets(self, user_id: str, *, limit: int | None = None, offset: int = 0) -> list[Pet]:
        query = "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id"
        args: tuple = (user_id,)
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            args += (limit, offset)
        ids = self.conn.execute(query, args)
        return [self.pet(row["pet_id"]) for row in ids]

    def owned_pets_page(self, user_id: str, *, limit: int, offset: int) -> list[Pet]:
        query = (
            "SELECT p.*, EXISTS("
            "SELECT 1 FROM quest_progress q "
            "WHERE q.user_id=p.user_id AND q.quest_id=? || CAST(p.pet_id AS TEXT) AND q.claimed=1"
            ") AS ascended FROM pets p WHERE p.user_id=? AND p.archived=0 ORDER BY p.pet_id"
        )
        args: tuple = (ASCENDED_PREFIX, user_id)
        query += " LIMIT ? OFFSET ?"
        args += (limit, offset)
        return [self._pet_from_row(row) for row in self.conn.execute(query, args)]

    def owned_pet_count(self, user_id: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM pets WHERE user_id=? AND archived=0", (user_id,),
        ).fetchone()[0])

    def pet_counts(self, user_id: str) -> tuple[int, int]:
        """Return active and archived counts with one indexed aggregate scan."""
        row = self.conn.execute(
            "SELECT SUM(archived=0), SUM(archived=1) FROM pets WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def co_training_candidates(self, user_id: str, species_id: str, exclude_pet_id: int) -> list[Pet]:
        rows = self.conn.execute(
            "SELECT * FROM pets WHERE user_id=? AND archived=0 AND species_id=? AND pet_id!=? "
            "ORDER BY pet_id",
            (user_id, species_id, exclude_pet_id),
        )
        return [self._pet_from_row(row) for row in rows]

    def cuisine_progress(self, user_id: str) -> dict[str, tuple[int, int]]:
        """Read cuisine portions and mastery receipts in one covering-index scan."""
        rows = self.conn.execute(
            "SELECT quest_id, progress, claimed FROM quest_progress "
            "WHERE user_id=? AND quest_id LIKE 'cuisine_%'",
            (user_id,),
        )
        return {
            str(row["quest_id"]): (int(row["progress"]), int(row["claimed"]))
            for row in rows
        }

    def archived_pets(self, user_id: str, *, limit: int, offset: int) -> list[Pet]:
        rows = self.conn.execute(
            "SELECT p.*, EXISTS("
            "SELECT 1 FROM quest_progress q "
            "WHERE q.user_id=p.user_id AND q.quest_id=? || CAST(p.pet_id AS TEXT) AND q.claimed=1"
            ") AS ascended FROM pets p "
            "WHERE p.user_id=? AND p.archived=1 ORDER BY p.pet_id LIMIT ? OFFSET ?",
            (ASCENDED_PREFIX, user_id, limit, offset),
        )
        return [self._pet_from_row(row) for row in rows]

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

    def special_operation(self, operation_id: str) -> tuple[str, str, dict] | None:
        """Find a durable replay in one indexed round trip.

        Durable special receipts live in four tables and were checked one by
        one by ``Game.execute``. Keep that lookup order, including
        collisions across tables, while fetching at most one row per table.
        ``operation_id`` is unique in each table, so the candidate set is
        bounded to four rows.
        """
        rows = self.conn.execute(
            "SELECT /* special-replay */ source, user_id, snapshot, reply FROM ("
            "SELECT 'duel' AS source, user_id, snapshot, reply FROM duel_actions WHERE operation_id=? "
            "UNION ALL "
            "SELECT 'battle' AS source, initiator_id AS user_id, NULL AS snapshot, reply "
            "FROM battle_records WHERE operation_id=? "
            "UNION ALL "
            "SELECT 'fishing' AS source, user_id, snapshot, reply "
            "FROM fishing_casts WHERE operation_id=? "
            "UNION ALL "
            "SELECT 'pedigree' AS source, user_id, snapshot, reply "
            "FROM pet_pedigree_operations WHERE operation_id=?"
            ")",
            (operation_id, operation_id, operation_id, operation_id),
        ).fetchall()
        if not rows:
            return None

        candidates: list[tuple[int, str, str, dict]] = []
        for row in rows:
            source = str(row["source"])
            if source == "battle":
                kind = "battle"
                priority = 16
            elif source == "fishing":
                kind = "fishing"
                priority = 17
            elif source == "pedigree":
                kind = "pedigree"
                priority = _SPECIAL_REPLAY_PRIORITIES[kind]
            else:
                snapshot = json.loads(row["snapshot"])
                kind = snapshot.get("kind")
                priority = _SPECIAL_REPLAY_PRIORITIES.get(kind, 14)
                if kind not in _SPECIAL_REPLAY_PRIORITIES:
                    kind = "duel"
            candidates.append((priority, kind, str(row["user_id"]), json.loads(row["reply"])))

        _, kind, owner, reply = min(candidates, key=lambda candidate: candidate[0])
        return kind, owner, reply

    def fishing_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id, reply FROM fishing_casts WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def duel_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id, snapshot, reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if json.loads(row["snapshot"]).get("kind") is not None:
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def stage_tactic_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id, snapshot, reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "stage_tactic":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_duel_action(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT snapshot FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind') IS NULL "
            "ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return json.loads(row["snapshot"]) if row else None

    def record_stage_tactic_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.conn.execute(
            "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
            (operation_id, user_id, created_at,
             json.dumps({"kind": "stage_tactic", **snapshot}, ensure_ascii=False),
             json.dumps(asdict(reply), ensure_ascii=False)),
        )

    def record_duel_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.conn.execute(
            "INSERT INTO duel_actions(operation_id,user_id,created_at,snapshot,reply) VALUES (?,?,?,?,?)",
            (operation_id, user_id, created_at, json.dumps(snapshot, ensure_ascii=False),
             json.dumps(asdict(reply), ensure_ascii=False)),
        )

    def weekly_reward_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "weekly_reward":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def cuisine_order_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "cuisine_order":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def cooking_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "cooking":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def furnace_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "pill_furnace":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_furnace_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='pill_furnace'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_furnace_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "pill_furnace"}, reply)

    def angling_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "angling":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_angling_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='angling'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_angling_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "angling"}, reply)

    def latest_cooking_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='cooking'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])}

    def record_cooking_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "cooking"}, reply)

    def tracking_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "tracking":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_tracking_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='tracking'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])}

    def record_tracking_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "tracking"}, reply)

    def herbalism_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "herbalism":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_herbalism_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='herbalism'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_herbalism_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "herbalism"}, reply)

    def nursery_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "nursery":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_nursery_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='nursery'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_nursery_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "nursery"}, reply)

    def play_course_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "play_course":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_play_course_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='play_course'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_play_course_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "play_course"}, reply)

    def adventure_travel_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "adventure_travel":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_adventure_travel_action(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='adventure_travel' ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_adventure_travel_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(
            operation_id, user_id, created_at, {**snapshot, "kind": "adventure_travel"}, reply,
        )

    def vein_expedition_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "vein_expedition":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_vein_expedition_action(self, user_id: str, active_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status')='active'" if active_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='vein_expedition'" + status +
            " ORDER BY action_id DESC LIMIT 1", (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def vein_expedition_history(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='vein_expedition' "
            "AND json_extract(snapshot,'$.status')!='active' ORDER BY action_id DESC", (user_id,),
        )
        return [{"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} for row in rows]

    def record_vein_expedition_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(
            operation_id, user_id, created_at, {**snapshot, "kind": "vein_expedition"}, reply,
        )

    def latest_ruin_expedition_action(self, user_id: str, active_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status')='active'" if active_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='ruin_expedition'" + status +
            " ORDER BY action_id DESC LIMIT 1", (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def ruin_expedition_history(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='ruin_expedition' "
            "AND json_extract(snapshot,'$.status')!='active' ORDER BY action_id DESC", (user_id,),
        )
        return [{"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} for row in rows]

    def record_ruin_expedition_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(
            operation_id, user_id, created_at, {**snapshot, "kind": "ruin_expedition"}, reply,
        )

    def latest_cave_coop_action(self, user_id: str, active_only: bool = False) -> dict | None:
        status = " AND json_extract(current.snapshot,'$.status') IN ('pending','ready')" if active_only else ""
        row = self.conn.execute(
            "SELECT current.snapshot,current.reply FROM duel_actions AS current "
            "WHERE json_extract(current.snapshot,'$.kind')='cave_coop' "
            "AND (json_extract(current.snapshot,'$.owner_id')=? OR json_extract(current.snapshot,'$.helper_id')=?)" + status +
            " AND NOT EXISTS (SELECT 1 FROM duel_actions AS newer "
            "WHERE json_extract(newer.snapshot,'$.kind')='cave_coop' "
            "AND json_extract(newer.snapshot,'$.project_id')=json_extract(current.snapshot,'$.project_id') "
            "AND newer.action_id>current.action_id)" +
            " ORDER BY action_id DESC LIMIT 1", (user_id, user_id),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def cave_coop_history(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE json_extract(snapshot,'$.kind')='cave_coop' "
            "AND (user_id=? OR json_extract(snapshot,'$.owner_id')=? OR json_extract(snapshot,'$.helper_id')=?) "
            "AND json_extract(snapshot,'$.status') NOT IN ('pending','ready') ORDER BY action_id DESC",
            (user_id, user_id, user_id),
        )
        return [{"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} for row in rows]

    def record_cave_coop_action(
        self, operation_id: str, actor_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, actor_id, created_at, {**snapshot, "kind": "cave_coop"}, reply)

    def item_trade(self, user_id: str, trade_id: int | None = None) -> dict | None:
        by_id = " AND json_extract(snapshot,'$.trade_id')=?" if trade_id is not None else ""
        params = (user_id, user_id, trade_id) if trade_id is not None else (user_id, user_id)
        row = self.conn.execute(
            "SELECT snapshot FROM duel_actions WHERE json_extract(snapshot,'$.kind')='item_trade' "
            "AND (json_extract(snapshot,'$.owner_id')=? OR json_extract(snapshot,'$.target_id')=?)"
            + by_id + " ORDER BY action_id DESC LIMIT 1", params,
        ).fetchone()
        return json.loads(row["snapshot"]) if row else None

    def item_trade_history(self, user_id: str, page: int, size: int) -> tuple[int, list[dict]]:
        where = (
            " FROM duel_actions WHERE json_extract(snapshot,'$.kind')='item_trade' "
            "AND json_extract(snapshot,'$.status')!='pending' "
            "AND (json_extract(snapshot,'$.owner_id')=? OR json_extract(snapshot,'$.target_id')=?)"
        )
        count = int(self.conn.execute("SELECT COUNT(*)" + where, (user_id, user_id)).fetchone()[0])
        rows = self.conn.execute(
            "SELECT snapshot" + where + " ORDER BY action_id DESC LIMIT ? OFFSET ?",
            (user_id, user_id, size, (page - 1) * size),
        )
        return count, [json.loads(row["snapshot"]) for row in rows]

    def record_item_trade(self, operation_id: str, actor_id: str, now: int, snapshot: dict, reply: Reply) -> None:
        self.record_duel_action(operation_id, actor_id, now, snapshot, reply)

    def latest_cuisine_coop_action(self, user_id: str, active_only: bool = False) -> dict | None:
        status = " AND json_extract(current.snapshot,'$.status') IN ('pending','ready')" if active_only else ""
        row = self.conn.execute(
            "SELECT current.snapshot,current.reply FROM duel_actions AS current "
            "WHERE json_extract(current.snapshot,'$.kind')='cuisine_coop' "
            "AND (json_extract(current.snapshot,'$.owner_id')=? OR json_extract(current.snapshot,'$.helper_id')=?)" + status +
            " AND NOT EXISTS (SELECT 1 FROM duel_actions AS newer "
            "WHERE json_extract(newer.snapshot,'$.kind')='cuisine_coop' "
            "AND json_extract(newer.snapshot,'$.project_id')=json_extract(current.snapshot,'$.project_id') "
            "AND newer.action_id>current.action_id) ORDER BY current.action_id DESC LIMIT 1",
            (user_id, user_id),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def cuisine_coop_project(self, user_id: str, project_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT current.snapshot,current.reply FROM duel_actions AS current "
            "WHERE json_extract(current.snapshot,'$.kind')='cuisine_coop' "
            "AND json_extract(current.snapshot,'$.project_id')=? "
            "AND (json_extract(current.snapshot,'$.owner_id')=? OR json_extract(current.snapshot,'$.helper_id')=?) "
            "AND NOT EXISTS (SELECT 1 FROM duel_actions AS newer "
            "WHERE json_extract(newer.snapshot,'$.kind')='cuisine_coop' "
            "AND json_extract(newer.snapshot,'$.project_id')=json_extract(current.snapshot,'$.project_id') "
            "AND json_extract(newer.snapshot,'$.owner_id')=json_extract(current.snapshot,'$.owner_id') "
            "AND json_extract(newer.snapshot,'$.helper_id')=json_extract(current.snapshot,'$.helper_id') "
            "AND newer.action_id>current.action_id) ORDER BY current.action_id DESC LIMIT 1",
            (project_id, user_id, user_id),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def cuisine_coop_history(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT current.snapshot,current.reply FROM duel_actions AS current "
            "WHERE json_extract(current.snapshot,'$.kind')='cuisine_coop' "
            "AND (json_extract(current.snapshot,'$.owner_id')=? OR json_extract(current.snapshot,'$.helper_id')=?) "
            "AND json_extract(current.snapshot,'$.status') NOT IN ('pending','ready') "
            "AND NOT EXISTS (SELECT 1 FROM duel_actions AS newer "
            "WHERE json_extract(newer.snapshot,'$.kind')='cuisine_coop' "
            "AND json_extract(newer.snapshot,'$.project_id')=json_extract(current.snapshot,'$.project_id') "
            "AND newer.action_id>current.action_id) ORDER BY current.action_id DESC",
            (user_id, user_id),
        )
        return [{"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} for row in rows]

    def record_cuisine_coop_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(
            operation_id, user_id, created_at, {**snapshot, "kind": "cuisine_coop"}, reply,
        )

    def friend_relay_runs(self, user_id: str, *, run_id: int | None = None, active_only: bool = False) -> list[dict]:
        filters = ""
        params: list = [user_id, user_id]
        if run_id is not None:
            filters += " AND json_extract(current.snapshot,'$.run_id')=?"
            params.append(run_id)
        if active_only:
            filters += " AND json_extract(current.snapshot,'$.status') IN ('pending','first','second')"
        rows = self.conn.execute(
            "SELECT current.snapshot FROM duel_actions AS current "
            "WHERE json_extract(current.snapshot,'$.kind')='friend_relay' "
            "AND (json_extract(current.snapshot,'$.owner_id')=? OR json_extract(current.snapshot,'$.helper_id')=?)"
            + filters +
            " AND NOT EXISTS (SELECT 1 FROM duel_actions AS newer "
            "WHERE json_extract(newer.snapshot,'$.kind')='friend_relay' "
            "AND json_extract(newer.snapshot,'$.run_id')=json_extract(current.snapshot,'$.run_id') "
            "AND newer.action_id>current.action_id) ORDER BY current.action_id DESC", params,
        )
        return [json.loads(row['snapshot']) for row in rows]

    def adventure_travel_choice(self, user_id: str, encounter_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT snapshot FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='adventure_travel' "
            "AND EXISTS (SELECT 1 FROM json_each(snapshot,'$.history') "
            "WHERE json_extract(value,'$.encounter_id')=?) ORDER BY action_id DESC LIMIT 1",
            (user_id, encounter_id),
        ).fetchone()
        if row is None:
            return None
        run = json.loads(row["snapshot"])
        selected = next(entry["option_id"] for entry in run["history"] if entry["encounter_id"] == encounter_id)
        scene = next(entry for entry in run["scenes"] if entry["id"] == encounter_id)
        return next(entry for entry in scene["options"] if entry["id"] == selected)

    def convoy_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "convoy":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def farm_care_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "farm_care":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_farm_contract(self, user_id: str) -> dict | None:
        rows = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? AND ("
            "json_extract(snapshot,'$.kind')='farm_contract' OR "
            "(json_extract(snapshot,'$.kind')='farm_care' AND "
            "json_type(snapshot,'$.contract')='object')) ORDER BY action_id DESC",
            (user_id,),
        )
        row = next(iter(rows), None)
        if row is None:
            return None
        snapshot = json.loads(row["snapshot"])
        contract = snapshot.get("contract")
        if contract is None:
            contract = {key: value for key, value in snapshot.items() if key != "kind"}
        return {"snapshot": contract, "reply": json.loads(row["reply"])}

    def farm_contract_history(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? AND ("
            "json_extract(snapshot,'$.kind')='farm_contract' OR "
            "(json_extract(snapshot,'$.kind')='farm_care' AND "
            "json_type(snapshot,'$.contract')='object')) ORDER BY action_id DESC",
            (user_id,),
        )
        latest: dict[int, dict] = {}
        for row in rows:
            snapshot = json.loads(row["snapshot"])
            contract = snapshot.get("contract")
            if contract is None:
                contract = {key: value for key, value in snapshot.items() if key != "kind"}
            contract_id = int(contract["contract_id"])
            latest.setdefault(contract_id, {"snapshot": contract, "reply": json.loads(row["reply"])})
        return list(latest.values())

    def record_farm_contract_action(
        self, operation_id: str, user_id: str, created_at: int, contract: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(
            operation_id, user_id, created_at, {"kind": "farm_contract", "contract": contract}, reply,
        )

    def latest_convoy_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='convoy'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_convoy_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "convoy"}, reply)

    def training_operation(self, operation_id: str, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id,snapshot,reply FROM duel_actions WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if row is None or json.loads(row["snapshot"]).get("kind") != "training":
            return None
        if row["user_id"] != user_id:
            raise GameError("operation ID reused by a different user")
        return json.loads(row["reply"])

    def latest_training_action(self, user_id: str, finished_only: bool = False) -> dict | None:
        status = " AND json_extract(snapshot,'$.status') != 'active'" if finished_only else ""
        row = self.conn.execute(
            "SELECT snapshot,reply FROM duel_actions WHERE user_id=? "
            "AND json_extract(snapshot,'$.kind')='training'" + status + " ORDER BY action_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return {"snapshot": json.loads(row["snapshot"]), "reply": json.loads(row["reply"])} if row else None

    def record_training_action(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.record_duel_action(operation_id, user_id, created_at, {**snapshot, "kind": "training"}, reply)

    def record_fishing_cast(
        self, operation_id: str, user_id: str, created_at: int, snapshot: dict, reply: Reply,
    ) -> None:
        self.conn.execute(
            "INSERT INTO fishing_casts(operation_id,user_id,created_at,snapshot,reply)"
            " VALUES (?,?,?,?,?)",
            (operation_id, user_id, created_at, json.dumps(snapshot, ensure_ascii=False),
             json.dumps(asdict(reply), ensure_ascii=False)),
        )

    def battle_history(
        self, user_id: str, *, limit: int = 5, offset: int = 0, kind: str | None = None,
    ) -> list[sqlite3.Row]:
        if type(limit) is not int or limit < 1 or limit > 100:
            raise ValueError("battle history limit must be between 1 and 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("battle history offset must be nonnegative")
        query = (
            "SELECT b.*, p.side, p.permission FROM battle_records b "
            "JOIN battle_participants p ON p.battle_id=b.battle_id "
            "WHERE p.user_id=?"
        )
        params: list = [user_id]
        if kind is not None:
            query += " AND b.kind=?"
            params.append(kind)
        query += " ORDER BY b.played_at DESC, b.battle_id DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        return self.conn.execute(query, params).fetchall()

    def battle_history_count(self, user_id: str, *, kind: str | None = None) -> int:
        if kind is None:
            return int(self.conn.execute(
                "SELECT COUNT(*) FROM battle_participants WHERE user_id=?", (user_id,),
            ).fetchone()[0])
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM battle_participants p "
            "JOIN battle_records b ON b.battle_id=p.battle_id "
            "WHERE p.user_id=? AND b.kind=?",
            (user_id, kind),
        ).fetchone()[0])

    def battle_report(self, user_id: str, battle_id: int) -> sqlite3.Row | None:
        """Return a report only when the requesting user participated in it."""
        return self.conn.execute(
            "SELECT b.*, p.side, p.permission FROM battle_records b "
            "JOIN battle_participants p ON p.battle_id=b.battle_id "
            "WHERE b.battle_id=? AND p.user_id=?", (battle_id, user_id),
        ).fetchone()

    def previous_comparable_battle(
        self, user_id: str, *, before_played_at: int, before_battle_id: int,
        kind: str, battle_key: str,
    ) -> sqlite3.Row | None:
        """The most recent earlier battle of this same player, kind and key.

        Ordering mirrors ``battle_history`` (played_at, battle_id), so the row is
        the one immediately before ``before_*`` in the player's timeline. Used
        by the read-only review comparison; no writes.
        """
        return self.conn.execute(
            "SELECT b.*, p.side, p.permission FROM battle_records b "
            "JOIN battle_participants p ON p.battle_id=b.battle_id "
            "WHERE p.user_id=? AND b.kind=? AND b.battle_key=? "
            "AND (b.played_at < ? OR (b.played_at = ? AND b.battle_id < ?)) "
            "ORDER BY b.played_at DESC, b.battle_id DESC LIMIT 1",
            (user_id, kind, battle_key, before_played_at, before_played_at, before_battle_id),
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

    def add_sect_week_contribution(
        self, *, week_start: int, sect_id: str, user_id: str, amount: int,
    ) -> None:
        if amount <= 0:
            raise ValueError("sect contribution increment must be positive")
        self.conn.execute(
            "INSERT INTO sect_week_contributions(week_start, sect_id, user_id, contribution) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(week_start, sect_id, user_id) DO UPDATE "
            "SET contribution=sect_week_contributions.contribution + excluded.contribution",
            (week_start, sect_id, user_id, amount),
        )

    def sect_week_contribution(
        self, *, week_start: int, sect_id: str, user_id: str,
    ) -> int:
        row = self.conn.execute(
            "SELECT contribution FROM sect_week_contributions "
            "WHERE week_start=? AND sect_id=? AND user_id=?",
            (week_start, sect_id, user_id),
        ).fetchone()
        return int(row["contribution"]) if row else 0

    def sect_week_total(self, *, week_start: int, sect_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(contribution), 0) AS total "
            "FROM sect_week_contributions WHERE week_start=? AND sect_id=?",
            (week_start, sect_id),
        ).fetchone()
        return int(row["total"])

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
            values = asdict(player)
            values.pop("internal_id")
            self.conn.execute(
                "UPDATE players SET stones=:stones, active_pet_id=:active_pet_id, sign_day=:sign_day, "
                "last_bond_day=:last_bond_day, current_bond_streak=:current_bond_streak, "
                "best_bond_streak=:best_bond_streak, "
                "quest_day=:quest_day, last_train=:last_train, last_explore=:last_explore, "
                "last_pve=:last_pve, last_pvp=:last_pvp WHERE user_id=:user_id",
                values,
            )
