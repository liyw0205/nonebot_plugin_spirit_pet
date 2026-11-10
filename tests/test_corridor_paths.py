"""Corridor choices affect real battles and settle exactly the earned reward."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import random

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.corridor_content import Corridor
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import corridor

from .support import items, pet, player, sql
from .test_corridor import NOW, boost, entry, seed_floor, set_energy, stub


def snapshot(store):
    with closing(store.connect()) as conn:
        return tuple(conn.iterdump())


def prepare(game, play):
    play("adopt", "青鸾")
    boost(game)


def test_choices_are_content_validated(game):
    content = entry(game)
    assert [path.name for path in content.paths] == ["疾行道", "护灵道", "寻宝道"]
    assert len(content.paths) == 3
    for field, value in (("energy", 0), ("energy", 101), ("reward_percent", 300), ("hp_percent", 0)):
        data = content.model_dump()
        data["paths"][0][field] = value
        with pytest.raises(ValidationError):
            Corridor.model_validate(data)
    for field in ("id", "name"):
        data = content.model_dump()
        data["paths"][1][field] = data["paths"][0][field]
        with pytest.raises(ValidationError, match="unique"):
            Corridor.model_validate(data)
    data = content.model_dump()
    data["paths"][0]["id"] = "common"
    with pytest.raises(ValidationError, match="reserved"):
        Corridor.model_validate(data)


def test_route_page_and_choice_do_not_restore_energy_or_change_the_party(game, play):
    prepare(game, play)
    set_energy(game, 50, now=NOW - 3600)
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    page = play("corridor")
    sql(game[1], "DELETE FROM operations")
    assert snapshot(game[1]) == before
    links = [link for link in page.inline_commands if link.label == "择路"]
    assert len(links) == 3
    for link in links:
        assert handlers._parse(link.command) == ("corridor", link.command.removeprefix("灵宠回廊 "))
        assert link.command not in page.commands
    resources = pet(game[1]), player(game[1]), items(game[1])
    chosen = play("corridor", "择路 1 疾行道")
    assert (pet(game[1]), player(game[1]), items(game[1])) == resources
    assert "本段 1-5 层：疾行道" in chosen.text()
    assert "尚未入廊 · 已择疾行道" in play("objectives").text()
    assert not any(link.label == "择路" for link in chosen.inline_commands)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='corridor_floor'") == []
    assert sql(game[1], "SELECT * FROM battle_records") == []


@pytest.mark.parametrize(("name", "energy", "stats", "reward"), [
    ("疾行道", 4, {"hp": 85, "attack": 17, "defense": 5, "speed": 15}, (10, 8)),
    ("护灵道", 8, {"hp": 85, "attack": 14, "defense": 5, "speed": 12}, (10, 8)),
    ("寻宝道", 6, {"hp": 102, "attack": 20, "defense": 5, "speed": 12}, (13, 10)),
])
def test_routes_change_real_battle_snapshots_energy_and_payout(game, play, name, energy, stats, reward):
    prepare(game, play)
    play("corridor", f"择路 1 {name}")
    reply = play("corridor", "挑战")
    assert reply.title == "回廊深入"
    assert pet(game[1])["energy"] == 100 - energy
    record = sql(game[1], "SELECT snapshot FROM battle_records")[0]
    assert json.loads(record["snapshot"])["teams"][1]["members"][0]["stats"] == stats
    assert f"待领 灵石 {reward[0]} · 修为 {reward[1]}" in play("corridor").text()
    stones, exp = player(game[1])["stones"], pet(game[1])["exp"]
    play("corridor", "收手")
    assert player(game[1])["stones"] == stones + reward[0]
    assert pet(game[1])["exp"] == exp + reward[1]
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'corridor_path_%'") == []


def test_new_segment_choice_never_reprices_earlier_wins(game, play):
    prepare(game, play)
    play("corridor", "择路 1 寻宝道")
    for _ in range(5):
        play("corridor", "挑战")
    # Per-floor rounding: 13+20+28+36+44, 10+15+20+26+31.
    page = play("corridor")
    assert "待领 灵石 141 · 修为 102" in page.text()
    assert "本段 6-10 层：常道" in page.text()
    assert {link.command for link in page.inline_commands if link.label == "择路"} == {
        f"灵宠回廊 择路 6 {name}" for name in ("疾行道", "护灵道", "寻宝道")
    }
    play("corridor", "择路 6 疾行道")
    play("corridor", "挑战")
    assert "待领 灵石 181 · 修为 130" in play("corridor").text()
    assert pet(game[1])["energy"] == 66
    before = player(game[1])["stones"], pet(game[1])["exp"]
    play("corridor", "收手")
    assert player(game[1])["stones"] == before[0] + 181
    assert pet(game[1])["exp"] == before[1] + 130
    assert items(game[1])["forge_ore"] == 2


@pytest.mark.parametrize("outcome", [1, -1])
def test_loss_and_draw_halve_the_earned_route_total(game, play, monkeypatch, outcome):
    prepare(game, play)
    play("corridor", "择路 1 寻宝道")
    for _ in range(5):
        play("corridor", "挑战")
    monkeypatch.setattr(corridor, "fight", lambda *a, **kw: stub(outcome))
    before = player(game[1])["stones"], pet(game[1])["exp"]
    play("corridor", "挑战")
    assert player(game[1])["stones"] == before[0] + 70
    assert pet(game[1])["exp"] == before[1] + 51
    assert items(game[1]).get("forge_ore", 0) == 0
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='corridor_pending_stones'") == []


def test_legacy_run_reads_without_writes_and_can_add_a_route(game, play):
    prepare(game, play)
    seed_floor(game, 6)
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    assert "待领 灵石 110 · 修为 80" in play("corridor").text()
    sql(game[1], "DELETE FROM operations")
    assert snapshot(game[1]) == before
    play("corridor", "择路 6 寻宝道")
    play("corridor", "挑战")
    assert "待领 灵石 162 · 修为 116" in play("corridor").text()


def test_route_and_rewards_survive_restart_and_content_changes(game, play):
    prepare(game, play)
    play("corridor", "择路 1 寻宝道")
    play("corridor", "挑战")
    content = entry(game)
    game[0].content.corridor[content.id] = content.model_copy(update={
        "paths": [path.model_copy(update={"energy": 99, "reward_percent": 200}) for path in content.paths],
    })
    restarted = Game(game[1], game[0].config, game[0].rng, game[0].content)
    page = restarted.execute("u1", "corridor", "", "reopened-page", NOW)
    assert "待领 灵石 13 · 修为 10" in page.text()
    assert "每宠精力 6" in page.text() and "灵石与修为 130%" in page.text()
    restarted.execute("u1", "corridor", "挑战", "reopened-fight", NOW)
    assert pet(game[1])["energy"] == 88
    assert "待领 灵石 33 · 修为 25" in play("corridor").text()


@pytest.mark.parametrize("argument", ["择路", "择路 1", "择路 x 疾行道", "择路 １ 疾行道", "择路 1 未知", "择路 6 疾行道", "择路 0 疾行道", "择路 1 疾行道 多余", f"择路 {'9' * 5000} 疾行道"])
def test_invalid_choices_have_zero_writes(game, play, argument):
    prepare(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("corridor", argument)
    assert snapshot(game[1]) == before


def test_locked_and_expired_choices_have_zero_writes(game, play):
    prepare(game, play)
    play("corridor", "择路 1 疾行道")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已经择路"):
        play("corridor", "择路 1 护灵道")
    assert snapshot(game[1]) == before
    play("corridor", "挑战")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已过期"):
        play("corridor", "择路 1 护灵道")
    assert snapshot(game[1]) == before


def test_choice_receipt_survives_cache_eviction_and_new_run(game, play):
    prepare(game, play)
    first = play("corridor", "择路 1 疾行道", op="choose-once")
    before = snapshot(game[1])
    assert play("corridor", "择路 1 疾行道", op="choose-once").text() == first.text()
    assert snapshot(game[1]) == before
    play("corridor", "挑战")
    play("corridor", "收手")
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已处理"):
        play("corridor", "择路 1 疾行道", op="choose-once")
    assert snapshot(game[1]) == before


def test_unregistered_or_busy_roster_cannot_choose(game, play):
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("corridor", "择路 1 疾行道", user="ghost")
    assert snapshot(game[1]) == before
    prepare(game, play)
    play("expedition_start", "采灵药")
    assert not play("corridor").inline_commands
    before = snapshot(game[1])
    with pytest.raises(GameError, match="外出派遣"):
        play("corridor", "择路 1 疾行道")
    assert snapshot(game[1]) == before


def test_multi_pet_route_cost_and_readiness_are_atomic(game, play):
    prepare(game, play)
    lead = pet(game[1])["pet_id"]
    sql(game[1], "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES ('u1', 'xuanhu', '玄狐', ?)", (NOW,))
    second = sql(game[1], "SELECT MAX(pet_id) AS id FROM pets")[0]["id"]
    play("lineup", f"{lead} {second}")
    play("team_create")
    play("team_ready")
    ready = sql(game[1], "SELECT * FROM team_members")
    play("corridor", "择路 1 疾行道")
    assert sql(game[1], "SELECT * FROM team_members") == ready
    sql(game[1], "UPDATE pets SET energy=3 WHERE pet_id=?", (second,))
    before = snapshot(game[1])
    with pytest.raises(GameError, match="精力不足"):
        play("corridor", "挑战")
    assert snapshot(game[1]) == before
    sql(game[1], "UPDATE pets SET energy=100")
    play("corridor", "挑战")
    assert [row["energy"] for row in sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")] == [96, 96]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None


def test_concurrent_cash_out_pays_the_run_once(game, play):
    prepare(game, play)
    play("corridor", "择路 1 寻宝道")
    play("corridor", "挑战")
    before_stones = player(game[1])["stones"]

    def claim(index):
        try:
            return game[0].execute("u1", "corridor", "收手", f"race-cash-{index}", NOW).title
        except GameError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sorted(results) == ["refused", "灵宠回廊"]
    assert player(game[1])["stones"] == before_stones + 13
    assert len(sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'corridor_receipt_%'")) == 2


def test_choice_can_make_a_low_energy_entry_playable(game, play):
    prepare(game, play)
    set_energy(game, 4)
    page = play("corridor")
    assert not any(link.label == "挑战" for link in page.inline_commands)
    page = play("corridor", "择路 1 疾行道")
    assert any(link.label == "挑战" for link in page.inline_commands)
    play("corridor", "挑战")
    assert pet(game[1])["energy"] == 0


def test_insufficient_route_energy_rejects_without_writes(game, play):
    prepare(game, play)
    play("corridor", "择路 1 护灵道")
    set_energy(game, 7)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="需要 8"):
        play("corridor", "挑战")
    assert snapshot(game[1]) == before


def test_failed_cash_out_rolls_back_and_can_retry_same_message(game, play, monkeypatch):
    prepare(game, play)
    play("corridor", "择路 1 寻宝道")
    play("corridor", "挑战")
    original = corridor.grant

    def fail_after_grant(*args, **kwargs):
        original(*args, **kwargs)
        raise GameError("模拟发奖失败")

    monkeypatch.setattr(corridor, "grant", fail_after_grant)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="模拟发奖失败"):
        play("corridor", "收手", op="retry-cash")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(corridor, "grant", original)
    before_stones = player(game[1])["stones"]
    play("corridor", "收手", op="retry-cash")
    assert player(game[1])["stones"] == before_stones + 13


def test_terminal_victory_includes_route_bonus_then_clears_state(game, play, monkeypatch):
    prepare(game, play)
    seed_floor(game, 26)
    play("corridor", "择路 26 寻宝道")
    monkeypatch.setattr(corridor, "fight", lambda *a, **kw: stub(0))
    for _ in range(4):
        play("corridor", "挑战")
    before_stones, before_exp = player(game[1])["stones"], pet(game[1])["exp"]
    assert play("corridor", "挑战").title == "回廊通关"
    assert player(game[1])["stones"] - before_stones == 2050 + 208 + 215 + 223 + 231 + 239
    assert pet(game[1])["exp"] - before_exp == 1400 + 140 + 145 + 150 + 156 + 161
    assert items(game[1])["exp_pill"] == 7
    assert "待领 灵石 0 · 修为 0" in play("corridor").text()


def test_terminal_reward_failure_rolls_back_the_whole_battle(game, play, monkeypatch):
    prepare(game, play)
    seed_floor(game, 30)
    monkeypatch.setattr(corridor, "fight", lambda *a, **kw: stub(0))
    original = corridor.grant

    def broken_grant(*args, **kwargs):
        original(*args, **kwargs)
        raise GameError("模拟终层发奖失败")

    monkeypatch.setattr(corridor, "grant", broken_grant)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="终层发奖失败"):
        play("corridor", "挑战", op="last-floor")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(corridor, "grant", original)
    reply = play("corridor", "挑战", op="last-floor")
    assert reply.title == "回廊通关"
    sql(game[1], "DELETE FROM operations")
    seed_floor(game, 2)
    before = snapshot(game[1])
    assert play("corridor", "挑战", op="last-floor").text() == reply.text()
    # A permanent battle reply may repopulate only the generic operation cache.
    sql(game[1], "DELETE FROM operations")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("seed", [7, 29, 83])
@pytest.mark.parametrize("floor", [1, 11, 26])
@pytest.mark.parametrize("route", ["疾行道", "护灵道", "寻宝道"])
def test_fixed_seed_routes_resolve_through_shared_engine(game, play, seed, floor, route):
    prepare(game, play)
    if floor > 1:
        seed_floor(game, floor)
    game[0].rng = random.Random(seed)
    play("corridor", f"择路 {floor} {route}")
    page = play("corridor")
    before = pet(game[1])["energy"]
    reply = play("corridor", "挑战")
    record = sql(game[1], "SELECT * FROM battle_records")[0]
    assert 1 <= record["rounds"] <= 40
    assert record["winner_side"] in (-1, 0, 1)
    assert record["battle_key"] == f"corridor_{floor}"
    expected_cost = {"疾行道": 4, "护灵道": 8, "寻宝道": 6}[route]
    assert pet(game[1])["energy"] == before - expected_cost
    assert route in reply.text() and route in page.text()


def test_expired_cash_out_cannot_settle_a_later_run(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("corridor", "挑战")
    play("corridor", "收手", op="old-cash-out")
    sql(game[1], "DELETE FROM operations")
    play("corridor", "挑战")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已处理"):
        play("corridor", "收手", op="old-cash-out")
    assert snapshot(game[1]) == before
