"""Second expedition line: schema 21, per-line scheduling and the one-off unlock."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import expeditions
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema20

from .support import player, sql

NOW = 1_800_000_000
COST = 3000


def add_pet(game, user="u1", species="qingluan"):
    with closing(game[1].connect()) as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, 100, ?)",
            (user, species, f"{species}二", NOW),
        ).lastrowid


def jobs(game, user="u1"):
    return sql(game[1], "SELECT * FROM expeditions WHERE user_id=? ORDER BY slot, job_id", (user,))


def unlock(game, play, *, stones=COST + 500):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=?", (stones,))
    return play("expedition_start", "开辟", op="unlock")


def test_fresh_schema_has_a_slot_column_and_per_line_index(tmp_path):
    store = Store(tmp_path / "fresh.db")
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(expeditions)")}
        assert "slot" in columns
        indexes = {row["name"]: row for row in conn.execute("PRAGMA index_list(expeditions)")}
        assert "expedition_running_player" not in indexes
        assert indexes["expedition_running_slot"]["unique"] == 1
        assert indexes["expedition_running_slot"]["partial"] == 1
        fields = [row["name"] for row in conn.execute("PRAGMA index_info(expedition_running_slot)")]
        assert fields == ["user_id", "slot"]


def test_schema_20_database_migrates_to_21_with_a_backup(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema20(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=20")
        conn.commit()
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 20

    Store(path).initialize()

    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(expeditions)")}
        assert "slot" in columns
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(expeditions)")}
        assert "expedition_running_slot" in indexes and "expedition_running_player" not in indexes
    backups = list(Path(tmp_path).glob("legacy.db.schema20-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 20


def test_existing_running_job_keeps_working_after_migration(tmp_path):
    path = tmp_path / "occupied.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema20(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=20")
        conn.execute("INSERT INTO players(user_id, stones) VALUES ('u1', 500)")
        conn.execute("INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES ('u1','qingluan','青鸾',?)", (NOW,))
        pet_id = conn.execute("SELECT pet_id FROM pets").fetchone()[0]
        conn.execute(
            "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
            " started_at, finishes_at, state, reward_snapshot)"
            " VALUES ('u1', ?, 'herb_gathering', '采灵药', 'legacy-op', ?, ?, 'running', '{}')",
            (pet_id, NOW, NOW + 3600),
        )
        conn.commit()

    Store(path).initialize()

    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT slot, state FROM expeditions").fetchone()
        assert row["slot"] == 0 and row["state"] == "running"


def test_second_line_is_locked_until_purchased(game, play):
    play("adopt", "青鸾")
    play("expedition_start", "采灵药", op="locked-first")
    second_pet = add_pet(game)
    play("switch", str(second_pet), op="locked-switch")
    with pytest.raises(GameError, match="已有外出委托"):
        play("expedition_start", "采灵药", op="locked-second")
    assert len(jobs(game)) == 1


def test_unlock_charges_the_documented_stones_once(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=5000")
    reply = play("expedition_start", "开辟", op="unlock-once")
    assert reply.title == "委托线开辟"
    assert player(game[1])["stones"] == 5000 - COST
    assert expeditions.unlocked_lines(_ctx(game)) == 2
    with pytest.raises(GameError, match="已经开辟"):
        play("expedition_start", "开辟", op="unlock-twice")
    assert player(game[1])["stones"] == 5000 - COST


def test_unlock_refuses_when_stones_are_short(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="灵石不足"):
        play("expedition_start", "开辟", op="unlock-poor")
    assert player(game[1])["stones"] == 100
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'expedition_lines_%'")
    assert rows == []


def _ctx(game, user="u1"):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, NOW, "read")


def test_two_pets_depart_on_separate_lines(game, play):
    unlock(game, play)
    first = play("expedition_start", "采灵药", op="line-one")
    assert "委托1" in first.text()
    second_pet = add_pet(game)
    play("switch", str(second_pet), op="switch-two")
    second = play("expedition_start", "采灵药", op="line-two")
    assert "委托2" in second.text()
    rows = jobs(game)
    assert [row["slot"] for row in rows] == [0, 1]


def test_a_third_departure_is_refused_when_both_lines_run(game, play):
    unlock(game, play)
    play("expedition_start", "采灵药", op="full-one")
    second_pet = add_pet(game)
    play("switch", str(second_pet), op="full-switch")
    play("expedition_start", "采灵药", op="full-two")
    third_pet = add_pet(game)
    play("switch", str(third_pet), op="full-switch-3")
    with pytest.raises(GameError, match="两条委托线都在外出"):
        play("expedition_start", "采灵药", op="full-three")
    assert len(jobs(game)) == 2


def test_the_same_pet_cannot_take_both_lines(game, play):
    unlock(game, play)
    play("expedition_start", "采灵药", op="dup-one")
    with pytest.raises(GameError, match="外出|委托"):
        play("expedition_start", "采灵药", op="dup-two")


def test_each_line_settles_and_claims_independently(game, play):
    unlock(game, play)
    play("expedition_start", "采灵药", op="claim-one", now=NOW)
    second_pet = add_pet(game)
    play("switch", str(second_pet), op="claim-switch")
    play("expedition_start", "采灵药", op="claim-two", now=NOW + 60)
    rows = {row["slot"]: row["job_id"] for row in jobs(game)}
    early = play("expedition_claim", str(rows[0]), now=NOW + 7200, op="claim-first")
    assert early.title == "委托归来"
    remaining = sql(game[1], "SELECT state FROM expeditions WHERE job_id=?", (rows[1],))
    assert remaining[0]["state"] == "running"
    later = play("expedition_claim", str(rows[1]), now=NOW + 8000, op="claim-second")
    assert later.title == "委托归来"


def test_status_overview_lists_both_lines_and_next_actions(game, play):
    unlock(game, play)
    play("expedition_start", "采灵药", op="status-one")
    second_pet = add_pet(game)
    play("switch", str(second_pet), op="status-switch")
    play("expedition_start", "采灵药", op="status-two")
    page = play("expedition_status", now=NOW + 60)
    assert "已开辟 2/2" in page.text()
    assert "委托1" in page.text() and "委托2" in page.text()
    assert all(link.command.startswith(("灵宠召回 ", "灵宠加急 ", "灵宠归来 ")) for link in page.inline_commands)


def test_status_overview_offers_the_unlock_before_it_is_bought(game, play):
    play("adopt", "青鸾")
    page = play("expedition_status")
    assert "已开辟 1/2" in page.text()
    assert any(link.command == "灵宠派遣 开辟" for link in page.inline_commands)


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    unlock(game, play)
    play("expedition_start", "采灵药", op="qq-one")
    page = play("expedition_status", now=NOW + 60)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4
