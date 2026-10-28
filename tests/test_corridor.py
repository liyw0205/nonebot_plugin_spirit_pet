"""Endless corridor: scaling, run state, cash-out, defeat settlement and records."""

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
from nonebot_plugin_spirit_pet.gameplay import corridor
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def entry(game):
    return sorted(game[0].content.corridor.values(), key=lambda item: item.id)[0]


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def set_energy(game, amount, user="u1", now=NOW):
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id=?", (amount, now, user))


def floor_row(game, user="u1"):
    return sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, "corridor_floor"),
    )


def best_row(game, user="u1", now=NOW):
    return sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"corridor_best_{beijing_week(now)[0]}"),
    )


def seed_floor(game, value, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, 'corridor_floor', ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, value),
    )


def stub(winner, rounds=3):
    return SimpleNamespace(winner=winner, rounds=rounds, lines=["战斗线"], history=[], skill_uses=[{}, {}])


def test_content_defines_the_scaling_corridor(game):
    content = entry(game)
    assert content.id == "corridor" and content.max_floor == 30 and content.energy == 6
    assert content.base_enemy in game[0].content.enemies
    assert content.stones_at(1) == 10 and content.stones_at(10) == 64
    assert content.exp_at(1) == 8 and content.exp_at(10) == 44
    assert [milestone.floor for milestone in content.milestones] == [5, 10, 15, 20, 25, 30]
    assert all(item in game[0].content.items for milestone in content.milestones for item in milestone.items)


def test_content_validation_rejects_broken_corridors():
    from nonebot_plugin_spirit_pet.domain.corridor_content import Corridor

    base = {
        "id": "corridor",
        "name": "无尽回廊",
        "description": "测试",
        "energy": 6,
        "max_floor": 30,
        "base_enemy": "wood_guard",
        "scaling": {"hp": 0.18},
        "stones_per_floor": {"base": 10, "growth": 6},
        "exp_per_floor": {"base": 8, "growth": 4},
        "milestones": [{"floor": 5, "items": {"forge_ore": 1}}],
    }
    assert Corridor.model_validate(base).max_floor == 30
    beyond = {**base, "milestones": [{"floor": 31, "items": {"forge_ore": 1}}]}
    with pytest.raises(ValidationError, match="beyond the last floor"):
        Corridor.model_validate(beyond)
    descending = {**base, "milestones": [{"floor": 10}, {"floor": 5}]}
    with pytest.raises(ValidationError, match="ascending"):
        Corridor.model_validate(descending)
    flat = {**base, "scaling": {"hp": 0, "attack": 0, "defense": 0, "speed": 0}}
    with pytest.raises(ValidationError, match="does not scale"):
        Corridor.model_validate(flat)


def test_page_without_a_pet_is_read_only(game, play):
    page = play("corridor", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_fresh_page_offers_only_the_entry(game, play):
    play("adopt", "青鸾")
    page = play("corridor")
    assert "当前：第 1 层待战 · 已清 0 层 · 待领 灵石 0 · 修为 0" in page.text()
    assert "本周最深：0 层" in page.text()
    assert {link.label for link in page.inline_commands} == {"挑战"}


def test_the_page_hides_actions_the_player_cannot_take(game, play):
    play("adopt", "青鸾")
    boost(game)
    set_energy(game, 5)
    page = play("corridor")
    assert "精力不足" in page.text()
    assert page.inline_commands == ()
    set_energy(game, 100)
    page = play("corridor")
    assert {link.label for link in page.inline_commands} == {"挑战"}
    play("corridor", "挑战")
    page = play("corridor")
    assert {link.label for link in page.inline_commands} == {"挑战", "收手"}


def test_winning_a_floor_advances_the_run_and_counts_the_energy(game, play):
    play("adopt", "青鸾")
    boost(game)
    reply = play("corridor", "挑战")
    assert reply.title == "回廊深入"
    assert floor_row(game)[0]["progress"] == 2
    assert pet(game[1])["energy"] == 94
    assert "已清 1 层，待领 灵石 10 · 修为 8" in reply.text()
    record = sql(game[1], "SELECT kind, battle_key, title FROM battle_records")
    assert record == [{"kind": "pve_stage", "battle_key": "corridor_1", "title": "回廊深入"}]


def test_pending_rewards_sum_every_cleared_floor(game, play):
    play("adopt", "青鸾")
    boost(game)
    for _ in range(3):
        play("corridor", "挑战")
    assert floor_row(game)[0]["progress"] == 4
    page = play("corridor")
    assert "已清 3 层 · 待领 灵石 48 · 修为 36" in page.text()


def test_cash_out_pays_pending_rewards_and_closes_the_run(game, play):
    play("adopt", "青鸾")
    boost(game)
    for _ in range(5):
        play("corridor", "挑战")
    before = player(game[1])["stones"]
    exp_before = pet(game[1])["exp"]
    reply = play("corridor", "收手")
    assert "收手兑现：已清 5 层" in reply.text()
    assert "锻灵矿" in reply.text()
    assert player(game[1])["stones"] == before + 10 + 16 + 22 + 28 + 34
    assert pet(game[1])["exp"] == exp_before + 8 + 12 + 16 + 20 + 24
    assert items(game[1])["forge_ore"] == 2
    assert floor_row(game) == []
    assert best_row(game)[0]["progress"] == 5
    with pytest.raises(GameError, match="没有进行中的回廊"):
        play("corridor", "收手")


def test_cash_out_without_a_run_is_refused(game, play):
    play("adopt", "青鸾")
    boost(game)
    with pytest.raises(GameError, match="没有进行中的回廊"):
        play("corridor", "收手")


def test_a_defeat_halves_the_reward_and_drops_milestones(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    seed_floor(game, 6)  # cleared 5 floors, milestone at 5 reached
    before = player(game[1])["stones"]
    monkeypatch.setattr(corridor, "fight", lambda *args, **kwargs: stub(1))
    reply = play("corridor", "挑战")
    assert reply.title == "回廊败退"
    assert "只能取回一半" in reply.text()
    assert player(game[1])["stones"] == before + (10 + 16 + 22 + 28 + 34) // 2
    assert items(game[1]).get("forge_ore", 0) == 0
    assert floor_row(game) == []
    assert best_row(game)[0]["progress"] == 5


def test_reaching_the_last_floor_settles_in_full(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    seed_floor(game, 30)
    before = player(game[1])["stones"]
    monkeypatch.setattr(corridor, "fight", lambda *args, **kwargs: stub(0))
    reply = play("corridor", "挑战")
    assert reply.title == "回廊通关"
    assert "已打通回廊尽头" in reply.text()
    assert player(game[1])["stones"] > before
    assert items(game[1])["exp_pill"] >= 5
    assert floor_row(game) == []
    assert best_row(game)[0]["progress"] == 30


def test_energy_is_checked_before_the_floor(game, play):
    play("adopt", "青鸾")
    boost(game)
    set_energy(game, 5)
    with pytest.raises(GameError, match="精力不足"):
        play("corridor", "挑战")
    assert floor_row(game) == []


def test_an_expedition_pet_cannot_enter_the_corridor(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("corridor", "挑战")
    assert floor_row(game) == []


def test_scaling_compounds_from_the_base_enemy(game):
    play = None
    content = entry(game)
    base = game[0].content.enemies[content.base_enemy]

    class Ctx:
        content = game[0].content

    ctx = SimpleNamespace(content=game[0].content)
    scaled = corridor.scaled_enemy(ctx, 10)
    factor = (1 + content.scaling.hp) ** 9
    assert scaled.stats.hp == round(base.stats.hp * factor)
    assert scaled.stats.attack == round(base.stats.attack * (1 + content.scaling.attack) ** 9)
    assert scaled.name.endswith("10层")
    assert corridor.scaled_enemy(ctx, 1).stats == base.stats


def test_the_weekly_best_reads_zero_next_week(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("corridor", "挑战")
    assert best_row(game)[0]["progress"] == 1
    page = play("corridor", now=NOW + WEEK)
    assert "本周最深：0 层" in page.text()


def test_the_run_survives_a_restart(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("corridor", "挑战")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "corridor", "", "restart-corridor", NOW)
    assert "当前：第 2 层待战 · 已清 1 层" in page.text()


def test_cleared_floors_never_touch_stage_progress(game, play):
    play("adopt", "青鸾")
    boost(game)
    for _ in range(2):
        play("corridor", "挑战")
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    boost(game)
    first = play("corridor", "挑战", op="corridor-op")
    again = play("corridor", "挑战", op="corridor-op")
    assert again.text() == first.text()
    assert floor_row(game)[0]["progress"] == 2


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "秘境与关卡")
    assert "灵宠回廊" in guide.text() and "灵宠回廊 收手" in guide.text()
    objectives = play("objectives")
    assert "回廊：本周最深 0 层 · 尚未入廊" in objectives.text()
    assert handlers._parse("灵宠回廊") == ("corridor", "")
    assert handlers._parse("灵宠回廊 挑战") == ("corridor", "挑战")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    boost(game)
    for _ in range(2):
        play("corridor", "挑战")
    page = play("corridor")
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
