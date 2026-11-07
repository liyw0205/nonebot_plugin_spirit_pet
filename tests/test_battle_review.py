"""战报复盘: stored battles turned into diagnosis and priced next steps."""

import json

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000


def seed_record(store, user="u1", winner=1, snapshot=None, *, kind="pve", battle_key="forest", played=NOW, operation=None):
    sql(
        store,
        "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title,"
        " winner_side, rounds, played_at, reply, snapshot, battle_log)"
        " VALUES (?, ?, ?, ?, '青岚林', ?, 3, ?, '战报', ?, '[]')",
        (
            operation or f"record-{user}-{winner}-{played}-{battle_key}", user, kind, battle_key,
            winner, played, json.dumps(snapshot or default_snapshot(), ensure_ascii=False),
        ),
    )
    battle_id = sql(store, "SELECT MAX(battle_id) AS id FROM battle_records")[0]["id"]
    sql(
        store,
        "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
        " VALUES (?, ?, 0, 'participant')",
        (battle_id, user),
    )
    return battle_id


def default_snapshot(affinity=40):
    mine = {
        "pet_name": "青鸾", "primary_element": "wind", "affinity": affinity,
        "stats": {"hp": 100, "attack": 20, "defense": 10, "speed": 15},
        "skills": [], "equipment": [],
    }
    theirs = {
        "pet_name": "影狼", "primary_element": "earth", "affinity": 0,
        "stats": {"hp": 120, "attack": 22, "defense": 12, "speed": 14},
        "skills": [], "equipment": [],
    }
    return {"version": 1, "teams": [
        {"side": 0, "members": [mine]},
        {"side": 1, "members": [theirs]},
    ]}


def stats_snapshot(mine_stats, theirs_stats):
    """A minimal snapshot with explicit four-stat totals for delta assertions."""
    return {"version": 1, "teams": [
        {"side": 0, "members": [{"pet_name": "青鸾", "stats": mine_stats, "skills": [], "equipment": []}]},
        {"side": 1, "members": [{"pet_name": "影狼", "stats": theirs_stats, "skills": [], "equipment": []}]},
    ]}


def snapshot_tables(store):
    return (
        sql(store, "SELECT user_id, stones, active_pet_id FROM players"),
        sql(store, "SELECT * FROM equipment ORDER BY pet_id, slot"),
        sql(store, "SELECT * FROM learned_skills ORDER BY pet_id, skill_id"),
        sql(store, "SELECT user_id, quest_id, progress, claimed FROM quest_progress ORDER BY quest_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY item_id"),
    )


def test_participant_reads_a_full_review(game, play):
    play("adopt", "青鸾", now=NOW)
    battle_id = seed_record(game[1])
    reply = play("battle_reports", f"复盘 {battle_id}", now=NOW)
    assert f"战报 #{battle_id} 复盘" in reply.title
    text = reply.text()
    assert "败北" in text
    assert "我方四维" in text and "对方四维" in text
    assert "元素：" in text and "×" in text
    assert "下一步：" in text
    assert "复盘只读" in text


def test_a_stranger_cannot_review_the_record(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    battle_id = seed_record(game[1])
    with pytest.raises(GameError, match="战报不存在"):
        play("battle_reports", f"复盘 {battle_id}", user="u2", now=NOW)


def test_an_unknown_record_is_refused(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="战报不存在"):
        play("battle_reports", "复盘 9999", now=NOW)
    with pytest.raises(GameError, match="格式"):
        play("battle_reports", "复盘", now=NOW)


def test_the_review_is_read_only(game, play):
    play("adopt", "青鸾", now=NOW)
    battle_id = seed_record(game[1])
    before = snapshot_tables(game[1])
    play("battle_reports", f"复盘 {battle_id}", now=NOW)
    assert snapshot_tables(game[1]) == before


def test_an_empty_gear_slot_becomes_a_next_step(game, play):
    play("adopt", "青鸾", now=NOW)
    battle_id = seed_record(game[1])
    reply = play("battle_reports", f"复盘 {battle_id}", now=NOW)
    assert "位还空着" in reply.text()
    pet_line = next(line for line in reply.lines if "灵器位还空着" in line)
    index = reply.lines.index(pet_line)
    assert any(link.line == index and link.command.startswith("灵宠整备 ") for link in reply.inline_commands)


def test_the_cheapest_enhancement_is_priced_with_its_real_cost(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'spirit_bell', 1)")
    play("equipment", "灵心铃", now=NOW)
    battle_id = seed_record(game[1])
    free = game[0].content.forge_levels[0]
    reply = play("battle_reports", f"复盘 {battle_id}", now=NOW)
    assert "可强化" in reply.text()
    assert f"{free.upgrade_stones} 灵石" in reply.text()
    assert any(link.command == "灵宠强化 饰品 伙伴 1" for link in reply.inline_commands)


def test_low_affinity_is_called_out(game, play):
    play("adopt", "青鸾", now=NOW)
    battle_id = seed_record(game[1], snapshot=default_snapshot(affinity=40))
    reply = play("battle_reports", f"复盘 {battle_id}", now=NOW)
    assert "心契护佑" in reply.text()


# ------------------------------------------------------------- comparison
def test_the_first_battle_of_a_kind_has_no_comparison(game, play):
    play("adopt", "青鸾", now=NOW)
    battle_id = seed_record(game[1])
    reply = play("battle_reports", f"复盘 {battle_id}", now=NOW)
    assert "对比上一场" not in reply.text()
    assert not any(link.label == "再战" for link in reply.inline_commands)


def test_a_previous_comparable_battle_shows_exact_deltas_and_outcome(game, play):
    play("adopt", "青鸾", now=NOW)
    older = stats_snapshot(
        {"hp": 100, "attack": 20, "defense": 10, "speed": 15},
        {"hp": 120, "attack": 22, "defense": 12, "speed": 14},
    )
    newer = stats_snapshot(
        {"hp": 140, "attack": 30, "defense": 8, "speed": 15},
        {"hp": 100, "attack": 22, "defense": 18, "speed": 10},
    )
    first_id = seed_record(game[1], winner=1, snapshot=older, played=NOW - 100, operation="older")
    second_id = seed_record(game[1], winner=0, snapshot=newer, played=NOW, operation="newer")
    reply = play("battle_reports", f"复盘 {second_id}", now=NOW)
    text = reply.text()
    assert f"对比上一场同类战斗（战报 #{first_id}）" in text
    # mine: +40 / +10 / −2 / +0 ; theirs: −20 / +0 / +6 / −4
    assert "我方四维变化 气血 +40 攻击 +10 防御 -2 速度 +0" in text
    assert "对方四维变化 气血 -20 攻击 +0 防御 +6 速度 -4" in text
    assert "结果 败北 → 胜利" in text


def test_the_rematch_link_points_at_a_real_dungeon_command(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_record(game[1], winner=1, played=NOW - 100, operation="older")
    second_id = seed_record(game[1], winner=1, played=NOW, operation="newer")
    reply = play("battle_reports", f"复盘 {second_id}", now=NOW)
    rematch = [link for link in reply.inline_commands if link.label == "再战"]
    assert len(rematch) == 1
    assert rematch[0].command == "灵宠挑战 青岚林"
    assert reply.lines[rematch[0].line] == "还想再试一次？"
    assert _parse(rematch[0].command) == ("challenge", "青岚林")


def test_a_kind_without_an_owning_command_gets_no_rematch_link(game, play):
    play("adopt", "青鸾", now=NOW)
    # spar has no dungeon/stage owning command; comparison still renders.
    seed_record(game[1], winner=1, played=NOW - 100, operation="older", kind="spar", battle_key="")
    second_id = seed_record(game[1], winner=1, played=NOW, operation="newer", kind="spar", battle_key="")
    reply = play("battle_reports", f"复盘 {second_id}", now=NOW)
    assert "对比上一场" in reply.text()
    assert not any(link.label == "再战" for link in reply.inline_commands)


def test_a_stage_battle_links_its_stage_challenge_command(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_record(game[1], winner=1, played=NOW - 100, operation="older", kind="pve_stage", battle_key="stage_01")
    second_id = seed_record(game[1], winner=1, played=NOW, operation="newer", kind="pve_stage", battle_key="stage_01")
    reply = play("battle_reports", f"复盘 {second_id}", now=NOW)
    rematch = [link for link in reply.inline_commands if link.label == "再战"]
    assert len(rematch) == 1
    assert rematch[0].command == "灵宠挑战关卡 青木试锋"


def test_comparison_ignores_other_players_kinds_and_keys(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    # Different participant, different kind, different key, and a battle AFTER this one.
    seed_record(game[1], winner=1, played=NOW - 100, operation="other-user", user="u2")
    seed_record(game[1], winner=1, played=NOW - 100, operation="other-kind", kind="spar", battle_key="")
    seed_record(game[1], winner=1, played=NOW - 100, operation="other-key", battle_key="moon")
    second_id = seed_record(game[1], winner=1, played=NOW, operation="newer")
    reply = play("battle_reports", f"复盘 {second_id}", now=NOW)
    # No earlier row shares (u1, pve, forest), so no comparison.
    assert "对比上一场" not in reply.text()


def test_the_comparison_is_read_only_and_participant_gated(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    seed_record(game[1], winner=1, played=NOW - 100, operation="older")
    second_id = seed_record(game[1], winner=1, played=NOW, operation="newer")
    before = snapshot_tables(game[1])
    reply = play("battle_reports", f"复盘 {second_id}", now=NOW)
    assert "对比上一场" in reply.text()
    assert snapshot_tables(game[1]) == before
    with pytest.raises(GameError, match="战报不存在"):
        play("battle_reports", f"复盘 {second_id}", user="u2", now=NOW)
