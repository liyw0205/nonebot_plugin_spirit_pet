"""Tribulation contracts: weekly rotation, modifiers, round limits and weekly rewards."""

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.tribulation_content import Tribulation
from nonebot_plugin_spirit_pet.gameplay import tribulations
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400
COOLDOWN = 700


def config(game):
    return sorted(game[0].content.tribulations.values(), key=lambda entry: entry.id)[0]


def contracts_at(game, now):
    entry = config(game)
    dungeons = sorted(game[0].content.dungeons.values(), key=lambda dungeon: dungeon.id)
    start = beijing_week(now)[0]
    return [
        (slot + 1, dungeons[(start // 86400 + slot * 7) % len(dungeons)],
         entry.modifiers[(start // 86400 + slot * 2) % len(entry.modifiers)])
        for slot in range(entry.slots)
    ]


def week_with(game, modifier_id):
    for step in range(120):
        now = NOW + step * WEEK
        for number, _, modifier in contracts_at(game, now):
            if modifier.id == modifier_id:
                return now, number
    raise AssertionError(f"no week maps to {modifier_id}")


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def set_energy(game, amount, user="u1", now=NOW):
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id=?", (amount, now, user))


def marker(game, slot, now=NOW, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"trib_{beijing_week(now)[0]}_{slot}"),
    )
    return rows[0]["progress"] if rows else None


def all_marker(game, now=NOW, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"trib_{beijing_week(now)[0]}_all"),
    )
    return rows[0]["progress"] if rows else None


def stub(winner, rounds=3):
    return SimpleNamespace(winner=winner, rounds=rounds, lines=["战斗线"], history=[], skill_uses=[{}, {}])


def test_content_defines_three_slots_and_six_modifiers(game):
    entry = config(game)
    assert (entry.slots, entry.energy) == (3, 15)
    assert [modifier.id for modifier in entry.modifiers] == [
        "blood_tide", "blade_wind", "iron_wall", "swift_shadow", "hourglass", "thin_air",
    ]
    assert entry.modifiers[4].round_limit == 12
    assert entry.modifiers[5].energy_multiplier == 1.5
    assert all(item in game[0].content.items for modifier in entry.modifiers for item in modifier.reward.items)


def test_content_validation_rejects_broken_tribulations():
    base = {
        "id": "t", "name": "劫境", "description": "测试", "energy": 15, "slots": 3,
        "bonus": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}},
        "modifiers": [
            {"id": "a", "name": "甲", "description": "甲", "hp": 1.0, "attack": 1.0, "defense": 1.0, "speed": 1.0,
             "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
            {"id": "b", "name": "乙", "description": "乙", "hp": 1.0, "attack": 1.0, "defense": 1.0, "speed": 1.0,
             "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
            {"id": "c", "name": "丙", "description": "丙", "hp": 1.0, "attack": 1.0, "defense": 1.0, "speed": 1.0,
             "reward": {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}},
        ],
    }
    assert Tribulation.model_validate(base).slots == 3
    with pytest.raises(ValidationError, match="round limit"):
        Tribulation.model_validate({**base, "modifiers": [
            {**base["modifiers"][0], "round_limit": 2}, *base["modifiers"][1:],
        ]})
    with pytest.raises(ValidationError, match="duplicate"):
        Tribulation.model_validate({**base, "modifiers": [
            base["modifiers"][0], {**base["modifiers"][1], "id": "a"}, base["modifiers"][2],
        ]})


def test_contracts_are_stable_in_a_week_and_rotate_next_week(game):
    first = [(slot, dungeon.id, modifier.id) for slot, dungeon, modifier in contracts_at(game, NOW)]
    again = [(slot, dungeon.id, modifier.id) for slot, dungeon, modifier in contracts_at(game, NOW + 3600)]
    assert first == again and len(first) == 3
    later = [(slot, dungeon.id, modifier.id) for slot, dungeon, modifier in contracts_at(game, NOW + WEEK)]
    assert later != first


def test_page_without_a_pet_is_read_only(game, play):
    page = play("tribulations", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_lists_three_contracts_with_links(game, play):
    play("adopt", "青鸾")
    page = play("tribulations")
    assert "本周已清 0/3 份契约" in page.text()
    for slot, dungeon, modifier in contracts_at(game, NOW):
        assert f"{slot}. {dungeon.name} · {modifier.name}" in page.text()
    assert {link.command for link in page.inline_commands} == {
        "灵宠劫境 挑战 1", "灵宠劫境 挑战 2", "灵宠劫境 挑战 3",
    }


def test_first_clear_pays_the_modifier_reward_and_marks_the_slot(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    stones = player(game[1])["stones"]
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    reply = play("tribulations", "挑战 1")
    modifier = contracts_at(game, NOW)[0][2]
    assert reply.title == "劫境契约达成"
    assert f"第 1 份契约首通" in reply.text()
    assert player(game[1])["stones"] == stones + modifier.reward.stones.minimum
    assert marker(game, 1) == 1
    record = sql(game[1], "SELECT kind, battle_key FROM battle_records")
    assert record[0]["kind"] == "pve_stage" and record[0]["battle_key"].startswith("trib_")
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_a_repeat_clear_is_refused_and_pays_nothing(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    play("tribulations", "挑战 1")
    stones = player(game[1])["stones"]
    with pytest.raises(GameError, match="本周已通关"):
        play("tribulations", "挑战 1", now=NOW + COOLDOWN)
    assert player(game[1])["stones"] == stones


def test_a_loss_pays_nothing_but_spends_energy(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(1))
    reply = play("tribulations", "挑战 1")
    assert reply.title == "劫境败退"
    assert marker(game, 1) is None
    assert pet(game[1])["energy"] == 100 - 15


def test_an_overtime_win_pays_nothing(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    now, slot = week_with(game, "hourglass")
    modifier = next(item for number, _, item in contracts_at(game, now) if number == slot)
    assert modifier.round_limit == 12
    set_energy(game, 100, now=now)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0, 20))
    reply = play("tribulations", f"挑战 {slot}", now=now)
    assert reply.title == "劫境超时"
    assert "回合上限" in reply.text()
    assert marker(game, slot, now) is None


def test_the_energy_multiplier_raises_the_cost(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    now, slot = week_with(game, "thin_air")
    modifier = next(item for number, _, item in contracts_at(game, now) if number == slot)
    set_energy(game, 100, now=now)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    play("tribulations", f"挑战 {slot}", now=now)
    assert pet(game[1])["energy"] == 100 - 23


def test_clearing_all_three_pays_the_bonus_once(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    stones = player(game[1])["stones"]
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    play("tribulations", "挑战 1")
    play("tribulations", "挑战 2", now=NOW + COOLDOWN)
    set_energy(game, 100, now=NOW + 2 * COOLDOWN)
    reply = play("tribulations", "挑战 3", now=NOW + 2 * COOLDOWN)
    assert "三份契约全清" in reply.text()
    assert all_marker(game) == 1
    expected = sum(modifier.reward.stones.minimum for _, _, modifier in contracts_at(game, NOW))
    assert player(game[1])["stones"] == stones + expected + config(game).bonus.stones.minimum


def test_energy_shortage_is_refused_before_the_fight(game, play):
    play("adopt", "青鸾")
    boost(game)
    set_energy(game, 10)
    with pytest.raises(GameError, match="精力不足"):
        play("tribulations", "挑战 1")
    assert marker(game, 1) is None
    assert pet(game[1])["energy"] == 10


def test_invalid_slots_and_text_are_refused(game, play):
    play("adopt", "青鸾")
    boost(game)
    with pytest.raises(GameError, match="只有 3 份"):
        play("tribulations", "挑战 4")
    with pytest.raises(GameError, match="格式"):
        play("tribulations", "挑战 一")
    with pytest.raises(GameError, match="格式"):
        play("tribulations", "挑战")


def test_next_week_resets_the_slots(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    play("tribulations", "挑战 1")
    assert marker(game, 1) == 1
    later = NOW + WEEK
    set_energy(game, 100, now=later)
    reply = play("tribulations", "挑战 1", now=later)
    assert reply.title == "劫境契约达成"
    assert marker(game, 1, later) == 1


def test_state_survives_a_restart(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    play("tribulations", "挑战 1")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "tribulations", "", "restart-trib", NOW)
    assert "本周已清 1/3 份契约" in page.text()


def test_same_operation_replays_identically(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(tribulations, "fight", lambda *args, **kwargs: stub(0))
    first = play("tribulations", "挑战 1", op="trib-op")
    again = play("tribulations", "挑战 1", op="trib-op")
    assert again.text() == first.text()
    assert marker(game, 1) == 1


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "秘境与关卡")
    assert "灵宠劫境" in guide.text()
    assert "劫境：本周 0/3 已清" in play("objectives").text()
    assert handlers._parse("灵宠劫境") == ("tribulations", "")
    assert handlers._parse("灵宠劫境 挑战 2") == ("tribulations", "挑战 2")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("tribulations")
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
