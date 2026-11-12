"""Pet escort: graded payout, escort survival, carried hp, gates and idempotency."""

import re
from contextlib import closing
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.escort_content import EscortMission, EscortRewards
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import escort

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400
COOLDOWN = 700


def missions(game):
    return sorted(game[0].content.escorts.values(), key=lambda mission: mission.energy)


def grade_row(game, mission_id, now=NOW, user="u1"):
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"escort_{beijing_week(now)[0]}_{mission_id}"),
    )
    return rows[0]["progress"] if rows else 0


def ready(game, play, *, energy=100):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id='u1'", (energy, NOW))


def scripted(plan, seen=None):
    """Replace fight(): record the escort's hp, drain it by the scripted amount, return winners."""
    queue = list(plan)

    def fake(team, enemies, rng, elements=None):
        winner, drain = queue.pop(0)
        target = team[-1]  # the escort is appended last on the player's side
        if seen is not None:
            seen.append(target.hp)
        target.hp = max(0, target.hp - drain)
        return SimpleNamespace(winner=winner, rounds=4, lines=["战斗线"], history=[], skill_uses=[{}, {}])

    return fake


def test_content_declares_the_graded_missions(game):
    rows = missions(game)
    assert [row.id for row in rows] == [
        "medicine_run", "frost_escort", "dragon_road", "frost_caravan", "heaven_relay",
    ]
    # Energy is the ordering key, so it must stay strictly increasing.
    energies = [row.energy for row in rows]
    assert energies == sorted(energies) and len(set(energies)) == len(energies)
    assert [len(row.waves) for row in rows] == [2, 2, 3, 2, 3]
    content = game[0].content
    for row in rows:
        assert all(enemy in content.enemies for wave in row.waves for enemy in wave)
        assert row.rewards.full.stones.minimum >= row.rewards.partial.stones.minimum


def test_escort_validation_rejects_inverted_payouts():
    reward = {"exp": {"minimum": 10, "maximum": 10}, "stones": {"minimum": 10, "maximum": 10}, "items": {}}
    better = {"exp": {"minimum": 20, "maximum": 20}, "stones": {"minimum": 20, "maximum": 20}, "items": {}}
    assert EscortRewards.model_validate({"full": better, "partial": reward}).full.stones.minimum == 20
    with pytest.raises(ValidationError, match="must not be smaller"):
        EscortRewards.model_validate({"full": reward, "partial": better})
    base = {
        "id": "x", "name": "护送", "description": "测试", "energy": 15,
        "npc": {"name": "目标", "hp": 100, "attack": 5, "defense": 5, "speed": 5},
        "waves": [["wood_guard"]],
        "rewards": {"full": better, "partial": reward},
    }
    assert EscortMission.model_validate(base).energy == 15
    with pytest.raises(ValidationError):
        EscortMission.model_validate({**base, "energy": 200})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("escort", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_missions_payouts_and_state(game, play):
    ready(game, play)
    page = play("escort")
    first = missions(game)[0]
    assert "护送目标会加入我方参战" in page.text()
    assert f"{first.name} · 目标 {first.npc.name}" in page.text()
    assert "满评" in page.text() and "部分" in page.text()
    assert "未通关" in page.text()
    assert [link.command for link in page.inline_commands] == [
        *(f"灵宠护送 出发 {mission.name}" for mission in missions(game)), "灵宠护航",
    ]
    assert page.inline_commands[-1].line == len(page.lines) - 1


def test_a_clean_clear_pays_the_full_reward(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    stones = player(game[1])["stones"]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10)]))
    reply = play("escort", f"出发 {first.name}", op="clean")
    assert reply.title == "护送满评"
    assert grade_row(game, first.id) == 2
    assert player(game[1])["stones"] == stones + first.rewards.full.stones.minimum
    assert pet(game[1])["energy"] == 100 - first.energy


def test_escort_hp_carries_over_between_waves(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    seen = []
    monkeypatch.setattr(escort, "fight", scripted([(0, 20), (0, 20)], seen))
    play("escort", f"出发 {first.name}", op="carry")
    assert len(seen) == 2
    assert seen[0] == first.npc.hp
    assert seen[1] == first.npc.hp - 20


def test_a_damaged_escort_earns_the_partial_payout(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    stones = player(game[1])["stones"]
    drain = first.npc.hp // 2 + 1
    monkeypatch.setattr(escort, "fight", scripted([(0, drain), (0, 0)]))
    reply = play("escort", f"出发 {first.name}", op="partial")
    assert reply.title == "护送达成"
    assert grade_row(game, first.id) == 1
    assert player(game[1])["stones"] == stones + first.rewards.partial.stones.minimum


def test_a_later_full_clear_pays_only_the_difference(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    drain = first.npc.hp // 2 + 1
    monkeypatch.setattr(escort, "fight", scripted([(0, drain), (0, 0), (0, 0), (0, 0)]))
    play("escort", f"出发 {first.name}", op="p1")
    stones = player(game[1])["stones"]
    play("escort", f"出发 {first.name}", op="p2", now=NOW + COOLDOWN)
    assert grade_row(game, first.id) == 2
    assert player(game[1])["stones"] == stones + (
        first.rewards.full.stones.minimum - first.rewards.partial.stones.minimum
    )


def test_a_dead_escort_fails_the_run(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    stones = player(game[1])["stones"]
    monkeypatch.setattr(escort, "fight", scripted([(0, first.npc.hp + 10), (0, 0)]))
    reply = play("escort", f"出发 {first.name}", op="dead")
    assert reply.title == "护送失败"
    assert "倒下" in reply.text()
    assert grade_row(game, first.id) == 0
    assert player(game[1])["stones"] == stones


def test_a_lost_wave_ends_the_run_early(game, play, monkeypatch):
    ready(game, play)
    third = missions(game)[2]
    seen = []
    monkeypatch.setattr(escort, "fight", scripted([(0, 5), (1, 0)], seen))
    reply = play("escort", f"出发 {third.name}", op="lost")
    assert reply.title == "护送失败"
    assert len(seen) == 2
    assert grade_row(game, third.id) == 0


def test_a_full_clear_is_not_paid_again(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10), (0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="dup-1")
    stones = player(game[1])["stones"]
    reply = play("escort", f"出发 {first.name}", op="dup-2", now=NOW + COOLDOWN)
    assert "不再重复发奖" in reply.text()
    assert player(game[1])["stones"] == stones


def test_next_week_resets_the_grade(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10), (0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="w1")
    assert grade_row(game, first.id) == 2
    later = NOW + WEEK
    assert grade_row(game, first.id, later) == 0
    sql(game[1], "UPDATE pets SET energy=100, energy_updated=? WHERE user_id='u1'", (later,))
    reply = play("escort", f"出发 {first.name}", op="w2", now=later)
    assert reply.title == "护送满评"
    assert grade_row(game, first.id, later) == 2


def test_energy_shortage_refuses_before_any_write(game, play, monkeypatch):
    ready(game, play, energy=5)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 0)]))
    with pytest.raises(GameError, match="精力不足"):
        play("escort", f"出发 {first.name}")
    assert grade_row(game, first.id) == 0
    assert pet(game[1])["energy"] == 5


def test_expedition_and_cooldown_refuse(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10), (0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="cd-1")
    with pytest.raises(GameError, match="调息"):
        play("escort", f"出发 {first.name}", op="cd-2", now=NOW + 5)
    play("expedition_start", "采灵药", op="trip", now=NOW + COOLDOWN)
    with pytest.raises(GameError, match="派遣|行程"):
        play("escort", f"出发 {first.name}", op="cd-3", now=NOW + COOLDOWN)


def test_battle_records_use_the_escort_key_only(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="records")
    rows = sql(game[1], "SELECT kind, battle_key FROM battle_records")
    assert len(rows) == 1
    assert rows[0]["kind"] == "pve_stage"
    assert rows[0]["battle_key"].startswith("escort_")
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_the_escort_is_a_player_side_unit_in_the_snapshot(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="snapshot")
    row = sql(game[1], "SELECT snapshot FROM battle_records")[0]
    assert first.npc.name in row["snapshot"]


def test_objective_help_and_parse(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    assert "护送：本周尚未出发" in play("objectives").text()
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="obj")
    assert f"护送：本周已通关 1/{len(missions(game))}" in play("objectives").text()
    assert "灵宠护送" in play("help", "秘境与关卡").text()
    assert handlers._parse("灵宠护送") == ("escort", "")
    assert handlers._parse("灵宠护送 出发 药囊运送") == ("escort", "出发 药囊运送")
    with pytest.raises(GameError, match="格式"):
        play("escort", "额外")


def test_same_operation_replays_identically(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10)]))
    first_reply = play("escort", f"出发 {first.name}", op="replay")
    stones = player(game[1])["stones"]
    again = play("escort", f"出发 {first.name}", op="replay")
    assert again.text() == first_reply.text()
    assert player(game[1])["stones"] == stones


def test_state_survives_a_restart(game, play, monkeypatch):
    ready(game, play)
    first = missions(game)[0]
    monkeypatch.setattr(escort, "fight", scripted([(0, 10), (0, 10)]))
    play("escort", f"出发 {first.name}", op="persist")
    assert "满评" in play("escort").text()
    assert f"护送：本周已通关 1/{len(missions(game))}" in play("objectives").text()


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("escort")
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


# ---------------------------------------------------------------- history (战历)

def week_start(now=NOW):
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    return beijing_week(now)[0]


def seed_grade(game, week, mission_id, value, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"escort_{week}_{mission_id}", value),
    )


def test_history_summarises_each_week_newest_first(game, play):
    ready(game, play)
    this, last = week_start(), week_start() - WEEK
    seed_grade(game, this, "medicine_run", 2)
    seed_grade(game, this, "frost_escort", 1)
    seed_grade(game, last, "dragon_road", 2)
    page = play("escort", "战历")
    assert page.title == "护送战历"
    assert "共 2 周有记录" in page.text()
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    assert f"{beijing_day(this)} 起那一周 · 通关 2 条 · 满评 1 条" in page.text()
    assert f"{beijing_day(last)} 起那一周 · 通关 1 条 · 满评 1 条" in page.text()


def test_history_is_empty_before_any_run(game, play):
    ready(game, play)
    page = play("escort", "战历")
    assert "还没有护送记录" in page.text()
    assert page.inline_commands == ()


def test_history_without_a_pet_is_read_only(game, play):
    page = play("escort", "战历", user="ghost")
    assert "尚未结契" in page.text()


def test_history_never_writes(game, play):
    ready(game, play)
    seed_grade(game, week_start(), "medicine_run", 2)
    before = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    play("escort", "战历")
    after = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    assert after == before


def test_history_pages_and_refuses_beyond_the_end(game, play):
    ready(game, play)
    this = week_start()
    total = escort.HISTORY_PAGE_SIZE + 1
    for index in range(total):
        seed_grade(game, this - index * WEEK, "medicine_run", 2)
    first = play("escort", "战历")
    assert f"共 {total} 周有记录 · 第 1/2 页" in first.text()
    assert "第 2/2 页" in play("escort", "战历 2").text()
    with pytest.raises(GameError, match="共 2 页"):
        play("escort", "战历 3")


def test_history_counts_a_retired_mission_row(game, play):
    ready(game, play)
    seed_grade(game, week_start(), "retired_mission", 2)
    page = play("escort", "战历")
    assert "共 1 周有记录" in page.text()
    assert "通关 1 条 · 满评 1 条" in page.text()
