"""Skill-preset contracts: save, apply, clear, limits and persistence."""

import sqlite3

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, sql

NOW = 1_800_000_000
SKILLS = ("wind_slash", "wood_heal", "vine_lash", "meditation", "pure_breath")


def account(play):
    play("adopt", "青鸾")


def add_skills(game, pet_id, skill_ids=SKILLS):
    for skill_id in skill_ids:
        sql(
            game[1],
            "INSERT INTO learned_skills(pet_id, skill_id, equipped) VALUES (?, ?, 0)",
            (pet_id, skill_id),
        )


def set_equipped(game, pet_id, skill_ids):
    sql(game[1], "UPDATE learned_skills SET equipped=0 WHERE pet_id=?", (pet_id,))
    for skill_id in skill_ids:
        sql(
            game[1],
            "UPDATE learned_skills SET equipped=1 WHERE pet_id=? AND skill_id=?",
            (pet_id, skill_id),
        )


def equipped(game, pet_id):
    return {
        row["skill_id"] for row in sql(
            game[1],
            "SELECT skill_id FROM learned_skills WHERE pet_id=? AND equipped=1",
            (pet_id,),
        )
    }


def preset_rows(game, pet_id):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress"
        " WHERE quest_id LIKE ? ORDER BY quest_id",
        (f"skill_preset_{pet_id}_%",),
    )


def saved_slot(game, play, pet_id, slot="1"):
    add_skills(game, pet_id)
    set_equipped(game, pet_id, ["wind_slash", "meditation"])
    return play("skill_presets", f"保存 {slot}")


def test_unregistered_preview_is_read_only(game, play):
    page = play("skill_presets", user="u9")
    assert page.title == "技能预设"
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert [link.command for link in page.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_page_lists_three_empty_slots_and_save_links(game, play):
    account(play)
    page = play("skill_presets")
    assert page.title == "技能预设 · 青鸾"
    assert "携带上限 2 门" in page.text()
    for slot in (1, 2, 3):
        assert f"方案 {slot} · 未保存" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠技能预设 保存 1",
        "灵宠技能预设 保存 2",
        "灵宠技能预设 保存 3",
    ]
    assert page.commands == ("灵宠技能", "灵宠技能图鉴", "灵宠商店")


def test_save_stores_the_current_set_and_page_marks_it_applied(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    reply = saved_slot(game, play, target)
    assert reply.title == "技能预设"
    assert "方案 1 已保存" in reply.text()
    rows = preset_rows(game, target)
    marker = next(row for row in rows if row["quest_id"] == f"skill_preset_{target}_1")
    assert marker["progress"] == 2
    assert {row["quest_id"] for row in rows} == {
        f"skill_preset_{target}_1",
        f"skill_preset_{target}_1_meditation",
        f"skill_preset_{target}_1_wind_slash",
    }
    page = play("skill_presets")
    assert "方案 1 · 已应用 · 凝神术、风刃术" in page.text()
    assert [link.label for link in page.inline_commands[:3]] == ["保存当前", "应用", "清除"]
    assert [link.command for link in page.inline_commands[:3]] == [
        "灵宠技能预设 保存 1", "灵宠技能预设 应用 1", "灵宠技能预设 清除 1",
    ]


def test_apply_restores_the_saved_set_and_reports_no_change(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    set_equipped(game, target, ["wood_heal", "vine_lash"])
    reply = play("skill_presets", "应用 1")
    assert "已应用方案 1" in reply.text()
    assert "当前携带 2/2 门" in reply.text()
    assert equipped(game, target) == {"wind_slash", "meditation"}
    again = play("skill_presets", "应用 1")
    assert "已是当前配置" in again.text()


def test_empty_preset_can_be_saved_and_applied(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    add_skills(game, target)
    assert "空方案" in play("skill_presets", "保存 1").text()
    set_equipped(game, target, ["wind_slash"])
    assert "全部卸下" in play("skill_presets", "应用 1").text()
    assert equipped(game, target) == set()
    assert "方案 1 · 已应用 · 空方案" in play("skill_presets").text()


def test_overwrite_replaces_old_skill_rows(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    add_skills(game, target)
    set_equipped(game, target, ["wind_slash"])
    play("skill_presets", "保存 1")
    set_equipped(game, target, ["meditation"])
    play("skill_presets", "保存 1")
    rows = preset_rows(game, target)
    assert {row["quest_id"] for row in rows} == {
        f"skill_preset_{target}_1",
        f"skill_preset_{target}_1_meditation",
    }
    assert next(row for row in rows if row["quest_id"].endswith("_1"))["progress"] == 1


def test_normal_pet_rejects_three_skills_on_save_and_apply(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    add_skills(game, target)
    set_equipped(game, target, ["wind_slash", "meditation", "wood_heal"])
    with pytest.raises(GameError, match="超过上限 2 门"):
        play("skill_presets", "保存 1")
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 3, 1)",
        (f"skill_preset_{target}_1",),
    )
    for skill_id in ("wind_slash", "meditation", "wood_heal"):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
            (f"skill_preset_{target}_1_{skill_id}",),
        )
    with pytest.raises(GameError, match="超过当前携带上限 2 门"):
        play("skill_presets", "应用 1")


def test_ascended_pet_can_save_and_apply_five_skills(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
        (f"ascended_{target}",),
    )
    add_skills(game, target)
    set_equipped(game, target, list(SKILLS))
    assert "携带上限 5 门" in play("skill_presets").text()
    assert "已保存" in play("skill_presets", "保存 1").text()
    set_equipped(game, target, ["wind_slash"])
    assert "当前携带 5/5 门" in play("skill_presets", "应用 1").text()
    assert equipped(game, target) == set(SKILLS)


def test_unlearned_skill_rejects_the_whole_apply(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    sql(
        game[1],
        "DELETE FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'",
        (target,),
    )
    with pytest.raises(GameError, match="尚未学会的灵术：风刃术"):
        play("skill_presets", "应用 1")
    assert equipped(game, target) == {"meditation"}


def test_requirement_failure_rejects_the_whole_apply(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    add_skills(game, target, ("thunder_roar", "meditation"))
    set_equipped(game, target, ["thunder_roar"])
    play("skill_presets", "保存 1")
    with pytest.raises(GameError, match="类别不兼容"):
        play("skill_presets", "应用 1")
    assert equipped(game, target) == {"thunder_roar"}


def test_unknown_skill_row_is_rejected(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    add_skills(game, target)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
        (f"skill_preset_{target}_1",),
    )
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
        (f"skill_preset_{target}_1_unknown_skill",),
    )
    with pytest.raises(GameError, match="已不存在的灵术"):
        play("skill_presets", "应用 1")


def test_failed_apply_rolls_back_every_equipped_row(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    set_equipped(game, target, ["wood_heal", "vine_lash"])
    sql(
        game[1],
        "CREATE TRIGGER reject_skill_preset BEFORE UPDATE ON learned_skills "
        "BEGIN SELECT RAISE(ABORT, 'injected preset failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected preset failure"):
        play("skill_presets", "应用 1")
    assert equipped(game, target) == {"wood_heal", "vine_lash"}
    sql(game[1], "DROP TRIGGER reject_skill_preset")


def test_clear_removes_slots_without_changing_the_loadout(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    assert "方案 1 已清除" in play("skill_presets", "清除 1").text()
    assert preset_rows(game, target) == []
    assert equipped(game, target) == {"wind_slash", "meditation"}
    assert "方案 1 本来就是空的" in play("skill_presets", "清除 1").text()


def test_state_persists_across_restart(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "skill_presets", "", "restart-preset", NOW)
    assert "方案 1 · 已应用 · 凝神术、风刃术" in page.text()


def test_same_operation_replays_without_rewriting(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    set_equipped(game, target, ["wood_heal"])
    first = play("skill_presets", "应用 1", op="preset-once")
    again = play("skill_presets", "应用 1", op="preset-once")
    assert again.title == first.title and again.lines == first.lines
    assert equipped(game, target) == {"wind_slash", "meditation"}


def test_busy_pet_cannot_apply_but_can_save(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot) VALUES ('u1', ?, 't', '采灵药',"
        " 'preset-exp', ?, ?, 'running', '{}')",
        (target, NOW - 10, NOW + 1000),
    )
    assert play("skill_presets", "保存 2").title == "技能预设"
    with pytest.raises(GameError, match="正在外出派遣"):
        play("skill_presets", "应用 1")


def test_slot_and_format_errors_are_rejected(game, play):
    account(play)
    for value in ("0", "4", "x", ""):
        with pytest.raises(GameError, match="方案编号是 1-3|格式"):
            play("skill_presets", f"保存 {value}")
    with pytest.raises(GameError, match="格式"):
        play("skill_presets", "保存")
    with pytest.raises(GameError, match="格式"):
        play("skill_presets", "未知 1")


def test_native_payload_keeps_buttons_and_links_separate(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    saved_slot(game, play, target)
    page = play("skill_presets")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in page.inline_commands}
    assert buttons == set(page.commands)
    assert buttons & links == set()
    assert f"灵宠技能预设 应用 1" in links


def test_help_and_parse_contract(game, play):
    assert "灵宠技能预设" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠技能预设 保存 1") == ("skill_presets", "保存 1")
    assert handlers._parse("灵宠技能预设") == ("skill_presets", "")
