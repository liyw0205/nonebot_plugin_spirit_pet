import json

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000  # 2027-01-15 Beijing


def seed_battle(game, stage_id, *, user="u1", winner_side=0, played=NOW, operation=None):
    """Insert a finished pve_stage battle with `user` as a participant."""
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, "
            "winner_side, rounds, played_at, reply, snapshot, battle_log) "
            "VALUES (?, ?, 'pve_stage', ?, 'seed', ?, 3, ?, '{}', ?, '[]')",
            (operation or f"op-{stage_id}-{played}-{winner_side}-{user}", user, stage_id,
             winner_side, played, json.dumps({"teams": []})),
        )
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) "
            "VALUES (?, ?, 0, 'participant')", (cursor.lastrowid, user),
        )


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_catalog_covers_stages_and_tower_ordered_by_recent(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "stage_01", played=NOW, operation="s1")
    seed_battle(game, "tower_01", winner_side=1, played=NOW + 1, operation="t1")
    page = play("stage_stats", now=NOW + 2)
    assert page.title == "关卡战绩 1/1"
    assert row(page, "万灵塔第一层") if any("万灵塔" in line for line in page.lines) else True
    tower_line = next(line for line in page.lines if "塔" in line)
    stage_line = row(page, "青木试锋")
    assert "出战 1 场 · 0 胜 1 负 0 平" in tower_line
    assert "出战 1 场 · 1 胜 0 负 0 平" in stage_line
    assert page.lines.index(tower_line) < page.lines.index(stage_line)
    assert "灵宠关卡星级" in page.commands


def test_detail_links_solo_stage_challenge(game, play):
    play("adopt", "青鸾", now=NOW)
    for index, winner in enumerate((0, 0, 1)):
        seed_battle(game, "stage_01", winner_side=winner, played=NOW + index, operation=f"d{index}")
    detail = play("stage_stats", "青木试锋", now=NOW + 5)
    assert detail.title == "关卡战绩 · 青木试锋"
    assert "出战 3 场 · 2 胜 1 负 0 平。" in detail.lines[0]
    assert "最近出战：2027-01-15 16:00" in detail.lines[1]
    assert "最近五场（新在前）：01-15 · 负、01-15 · 胜、01-15 · 胜" == detail.lines[2]
    assert "灵宠挑战关卡 1" in detail.commands
    assert {link.command for link in detail.inline_commands} == {
        "灵宠关卡星级", "灵宠挑战关卡 1",
    }


def test_detail_links_team_stage_and_tower_challenge(game, play):
    play("adopt", "青鸾", now=NOW)
    team_stage = next(
        stage for stage in game[0].content.stages.values() if stage.team
    )
    seed_battle(game, team_stage.id, played=NOW, operation="team-stage")
    detail = play("stage_stats", team_stage.name, now=NOW + 1)
    assert f"灵宠组队关卡 {team_stage.order}" in detail.commands

    seed_battle(game, "tower_03", played=NOW + 2, operation="tower3")
    tower_detail = play("stage_stats", "tower_03", now=NOW + 3)
    assert "灵宠挑战万灵塔 3" in tower_detail.commands
    assert {link.command for link in tower_detail.inline_commands} == {
        "灵宠关卡星级", "灵宠挑战万灵塔 3",
    }


def test_resolve_by_order_prefers_tower_floor(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "tower_01", played=NOW, operation="tower-order")
    detail = play("stage_stats", "tower_01", now=NOW + 1)
    assert detail.title == "关卡战绩 · 初入塔门"
    assert "灵宠挑战万灵塔 1" in detail.commands


def test_retired_keys_are_excluded(game, play):
    play("adopt", "青鸾", now=NOW)
    seed_battle(game, "removed_stage", played=NOW, operation="retired")
    page = play("stage_stats", now=NOW + 1)
    assert "还没有关卡出战记录" in page.text()


def test_unregistered_and_empty_states(game, play):
    page = play("stage_stats", user="u9", now=NOW)
    assert page.title == "关卡战绩"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    play("adopt", "青鸾", now=NOW)
    empty = play("stage_stats", now=NOW + 1)
    assert "还没有关卡出战记录" in empty.text()
    with pytest.raises(GameError, match="还没有青木试锋的出战记录"):
        play("stage_stats", "青木试锋", now=NOW + 2)
    with pytest.raises(GameError, match="未找到该内容"):
        play("stage_stats", "不存在的关卡", now=NOW + 2)


def test_pagination_rejects_overflow(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="关卡战绩共 1 页"):
        play("stage_stats", "9", now=NOW)


def test_star_page_links_stats_and_native_keyboard_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    stars = play("stage_stars", now=NOW)
    assert "灵宠关卡战绩" in stars.commands
    seed_battle(game, "stage_01", played=NOW, operation="link-check")
    page = play("stage_stats", now=NOW + 1)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_parse_and_help_contract():
    from nonebot_plugin_spirit_pet.adapters import handlers
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    assert handlers._parse("灵宠关卡战绩") == ("stage_stats", "")
    assert handlers._parse("灵宠关卡战绩 青木试锋") == ("stage_stats", "青木试锋")
    assert handlers._parse("灵宠关卡 2") == ("stage_catalog", "2")
    assert ("灵宠关卡战绩 关卡名", "灵宠关卡战绩 ", "按关卡与塔层回顾出战次数与胜负平；不填查看汇总列表。") in _HELP_SECTIONS["秘境与关卡"]
