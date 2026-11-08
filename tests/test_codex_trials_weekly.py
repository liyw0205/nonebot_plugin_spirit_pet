"""Weekly codex trials: a rotating condition per slot, all-clear bonus, weekly reset."""

import json
import re
import shutil
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.codex_trial_content import CodexRotation, CodexTrial
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import codex_trials
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def trial(game):
    return sorted(game[0].content.codex_trials.values(), key=lambda entry: entry.id)[0]


def stub(winner, rounds=3):
    return SimpleNamespace(winner=winner, rounds=rounds, lines=["战斗线"], history=[], skill_uses=[{}, {}])


def week_start(now=NOW):
    return beijing_week(now)[0]


def marks(game, user="u1"):
    return {
        row["quest_id"]: row["progress"]
        for row in sql(
            game[1],
            "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE 'codex_week%'",
            (user,),
        )
    }


def add_pet(game, user, species, name, *, realm=5):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp, affinity,"
        " energy, energy_updated, archived) VALUES (?, ?, ?, ?, 10, 4, 0, 0, 100, ?, 0)",
        (user, species, name, realm, NOW),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def boost(game, user="u1"):
    sql(
        game[1],
        "UPDATE pets SET realm=5, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (NOW, user),
    )


def locked_element(game, text):
    """Which element the element_lock slot demands, as an id, or None."""
    match = re.search(r"需(\S+?)属性", text)
    if match is None:
        return None
    name = match.group(1)
    return next(key for key, element in game[0].content.elements.items() if element.name == name)


def species_with(game, element):
    return next(
        entry.id for entry in game[0].content.species.values() if element in entry.elements
    )


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT quest_id FROM quest_progress ORDER BY user_id, quest_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
    )


# ---------------------------------------------------------------- content

def test_content_declares_three_slots_and_a_bonus(game):
    entry = trial(game)
    assert entry.weekly_slots == 3
    assert len(entry.rotations) >= entry.weekly_slots
    assert entry.weekly_bonus is not None and entry.weekly_bonus.stones.minimum == 400
    kinds = {rotation.kind for rotation in entry.rotations}
    assert kinds == {"round_limit", "element_lock", "stat_scale"}


def test_every_rotation_reward_and_element_exists(game):
    content = game[0].content
    for rotation in trial(game).rotations:
        assert all(item in content.items for item in rotation.reward.items)
        assert all(key in content.elements for key in rotation.elements)
        assert rotation.energy <= 100


def rotation_payload(**overrides):
    base = {
        "id": "probe", "name": "试炼", "description": "说明", "kind": "round_limit",
        "rounds": 10, "energy": 10,
        "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 1, "maximum": 1}, "items": {}},
    }
    base.update(overrides)
    return base


def test_a_rotation_must_arm_exactly_its_own_condition():
    with pytest.raises(ValidationError, match="must set its own"):
        CodexRotation.model_validate(rotation_payload(kind="round_limit", rounds=None))
    with pytest.raises(ValidationError, match="must not set values for another kind"):
        CodexRotation.model_validate(rotation_payload(kind="stat_scale", scale=1.2, rounds=8))


def test_an_element_lock_needs_two_distinct_elements():
    with pytest.raises(ValidationError, match="at least two elements"):
        CodexRotation.model_validate(rotation_payload(kind="element_lock", rounds=None, elements=["fire"]))
    with pytest.raises(ValidationError, match="repeats an element"):
        CodexRotation.model_validate(
            rotation_payload(kind="element_lock", rounds=None, elements=["fire", "fire"])
        )


def test_weekly_slots_need_enough_rotations_and_a_bonus():
    base = {
        "id": "probe", "name": "试炼", "boost": 2.2, "energy": 10,
        "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 1, "maximum": 1}, "items": {}},
    }
    one = rotation_payload(id="a")
    two = rotation_payload(id="b")
    with pytest.raises(ValidationError, match="slots and bonus must be set together"):
        CodexTrial.model_validate({**base, "weekly_slots": 2, "rotations": [one, two]})
    with pytest.raises(ValidationError, match="at least weekly_slots"):
        CodexTrial.model_validate({**base, "weekly_slots": 3, "weekly_bonus": base["reward"],
                                   "rotations": [one, two]})
    with pytest.raises(ValidationError, match="repeats a rotation id"):
        CodexTrial.model_validate({**base, "weekly_slots": 2, "weekly_bonus": base["reward"],
                                   "rotations": [one, dict(one)]})


def test_an_unknown_element_is_rejected_at_load(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "codex_trials.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    lock = next(
        rotation for rotation in data[0]["rotations"] if rotation["kind"] == "element_lock"
    )
    lock["elements"] = [lock["elements"][0], "not_an_element"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="not_an_element"):
        Catalog.load(target)


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview(game, play):
    page = play("codex_trials", "每周", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert marks(game, "ghost") == {}


# ---------------------------------------------------------------- rotation

def test_the_week_is_deterministic_and_moves_on(game, play):
    play("adopt", "青鸾")
    first = play("codex_trials", "每周").lines
    again = play("codex_trials", "每周", op="again").lines
    assert first == again
    later = play("codex_trials", "每周", now=NOW + WEEK).lines
    assert later != first


def test_the_page_lists_three_slots_with_a_challenge_link(game, play):
    play("adopt", "青鸾")
    page = play("codex_trials", "每周")
    assert "本周 0/3 场已通关" in page.text()
    links = [link for link in page.inline_commands if link.label == "挑战"]
    assert [link.command for link in links] == [
        "灵宠图鉴试炼 每周 1", "灵宠图鉴试炼 每周 2", "灵宠图鉴试炼 每周 3",
    ]
    for link in page.inline_commands:
        assert link.line < len(page.lines)
        assert _parse(link.command) is not None


def test_the_three_slots_never_repeat_a_rotation(game, play):
    play("adopt", "青鸾")
    text = play("codex_trials", "每周").text()
    names = re.findall(r"^\d\. (\S+?) · ", text, re.M)
    assert len(names) == 3 and len(set(names)) == 3


# ---------------------------------------------------------------- fighting

def test_a_win_pays_the_rotation_reward_and_marks_the_slot(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    before = player(game[1])
    energy = pet(game[1])["energy"]
    reply = play("codex_trials", "每周 1")
    assert reply.title == "每周试炼通关"
    assert marks(game)[f"codex_week_{week_start()}_1"] == 3
    assert player(game[1])["stones"] == before["stones"] + 180
    assert pet(game[1])["energy"] == energy - 10
    assert "灵石 +180" in reply.text()


def test_a_cleared_slot_refuses_a_second_run_without_writing(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    play("codex_trials", "每周 2")
    state = snapshot(game)
    with pytest.raises(GameError, match="已经通关"):
        play("codex_trials", "每周 2")
    assert snapshot(game) == state


def test_an_out_of_range_slot_is_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="本周只有 3 场"):
        play("codex_trials", "每周 4")
    with pytest.raises(GameError, match="格式：灵宠图鉴试炼 每周"):
        play("codex_trials", "每周 一")


def test_a_round_limit_loss_is_not_a_clear(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(-1, rounds=12))
    reply = play("codex_trials", "每周 1")
    assert reply.title == "每周试炼超时"
    assert "未能在 12 回合内取胜" in reply.text()
    assert marks(game) == {}


def test_the_element_lock_refuses_a_mismatched_pet_before_spending_energy(game, play):
    play("adopt", "青鸾")
    boost(game)
    element = locked_element(game, play("codex_trials", "每周").text())
    if element is None:
        pytest.skip("this week has no element lock")
    species = next(
        entry for entry in game[0].content.species.values() if element not in entry.elements
    )
    sql(game[1], "UPDATE pets SET species_id=? WHERE user_id='u1'", (species.id,))
    state = snapshot(game)
    with pytest.raises(GameError, match="属性不匹配"):
        play("codex_trials", "每周 3")
    assert snapshot(game) == state


def test_the_element_lock_admits_a_matching_pet(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    element = locked_element(game, play("codex_trials", "每周").text())
    if element is None:
        pytest.skip("this week has no element lock")
    sql(game[1], "UPDATE pets SET species_id=? WHERE user_id='u1'", (species_with(game, element),))
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    assert play("codex_trials", "每周 3").title == "每周试炼通关"


def test_stat_scale_multiplies_the_mirror_on_top_of_the_boost(game):
    entry = trial(game)
    scaling = next(rotation for rotation in entry.rotations if rotation.kind == "stat_scale")
    species = next(iter(game[0].content.species.values()))
    ctx = SimpleNamespace(content=game[0].content)
    enemy = codex_trials.weekly_enemy(ctx, species, scaling)
    factor = entry.boost * scaling.scale
    assert enemy.stats.hp == max(1, round(species.stats.hp * factor))
    assert enemy.stats.attack == max(1, round(species.stats.attack * factor))


def test_the_mirror_keeps_the_species_elements(game):
    entry = trial(game)
    rotation = next(rotation for rotation in entry.rotations if rotation.kind == "round_limit")
    species = next(iter(game[0].content.species.values()))
    enemy = codex_trials.weekly_enemy(SimpleNamespace(content=game[0].content), species, rotation)
    assert enemy.elements == species.elements
    assert enemy.primary_element == species.primary_element


def test_clearing_all_three_slots_pays_the_weekly_bonus_once(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    element = locked_element(game, play("codex_trials", "每周").text())
    first = play("codex_trials", "每周 1", now=NOW)
    assert "本周三场全清" not in first.text()
    for index in (2, 3):
        sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
        if index == 3 and element is not None:
            sql(game[1], "UPDATE pets SET species_id=? WHERE user_id='u1'",
                (species_with(game, element),))
        reply = play("codex_trials", f"每周 {index}", now=NOW + 900 * index)
    assert "本周三场全清" in reply.text()
    assert f"codex_week_all_{week_start()}" in marks(game)
    assert len(marks(game)) == 4


def test_the_bonus_waits_for_the_third_clear(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    play("codex_trials", "每周 1", now=NOW)
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
    reply = play("codex_trials", "每周 2", now=NOW + 900)
    assert "本周三场全清" not in reply.text()
    assert f"codex_week_all_{week_start()}" not in marks(game)
    assert len(marks(game)) == 2


def test_last_weeks_marks_do_not_block_this_week(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    play("codex_trials", "每周 1")
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
    later = NOW + WEEK
    reply = play("codex_trials", "每周 1", now=later)
    assert reply.title == "每周试炼通关"
    assert f"codex_week_{week_start(later)}_1" in marks(game)


def test_a_weekly_clear_writes_a_battle_record_but_no_stage_progress(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(codex_trials, "fight", lambda *a, **k: stub(0))
    play("codex_trials", "每周 1")
    assert sql(game[1], "SELECT battle_id FROM battle_records") != []
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_the_objectives_line_reports_the_week(game, play):
    play("adopt", "青鸾")
    line = next(row for row in play("objectives").lines if row.startswith("图鉴试炼"))
    assert "本周 0/3" in line


def test_help_and_parser_cover_the_weekly_command(game, play):
    assert _parse("灵宠图鉴试炼 每周") == ("codex_trials", "每周")
    assert _parse("灵宠图鉴试炼 每周 2") == ("codex_trials", "每周 2")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["秘境与关卡"]}
    assert "灵宠图鉴试炼 每周" in rows
    assert "灵宠图鉴试炼 每周 序号" in rows


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("codex_trials", "每周")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


# ---------------------------------------------------------------- history (战历)


def ctx_for(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "codex-ctx")


def seed_week(game, week, slot, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
        " ON CONFLICT(user_id, quest_id) DO NOTHING",
        (user, f"codex_week_{week}_{slot}"),
    )


def test_history_lists_weeks_newest_first_with_the_week_bonus(game, play):
    play("adopt", "青鸾")
    this, last = week_start(), week_start() - WEEK
    for slot in (1, 2, 3):
        seed_week(game, this, slot)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
        (f"codex_week_all_{this}",),
    )
    seed_week(game, last, 1)
    page = play("codex_trials", "战历")
    assert page.title == "图鉴试炼战历"
    assert "共 2 周有记录" in page.text()
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    slots = len(codex_trials.weekly_slots(ctx_for(game)))
    assert f"{beijing_day(this)} 起那一周 · 通关 3/{slots} 场 · 周奖已领" in page.text()
    assert f"{beijing_day(last)} 起那一周 · 通关 1/{slots} 场" in page.text()


def test_history_is_empty_before_any_weekly_clear(game, play):
    play("adopt", "青鸾")
    page = play("codex_trials", "战历")
    assert "还没有每周试炼记录" in page.text()
    assert page.inline_commands == ()


def test_history_never_writes(game, play):
    play("adopt", "青鸾")
    seed_week(game, week_start(), 1)
    before = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    play("codex_trials", "战历")
    after = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    assert after == before


def test_history_pages_and_refuses_beyond_the_end(game, play):
    play("adopt", "青鸾")
    this = week_start()
    total = 7
    for index in range(total):
        seed_week(game, this - index * WEEK, 1)
    first = play("codex_trials", "战历")
    assert f"共 {total} 周有记录 · 第 1/2 页" in first.text()
    assert "第 2/2 页" in play("codex_trials", "战历 2").text()
    with pytest.raises(GameError, match="共 2 页"):
        play("codex_trials", "战历 3")
