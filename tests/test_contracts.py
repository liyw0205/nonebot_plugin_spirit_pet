"""Dungeon contracts: optional constraints on an existing dungeon, paid only when they held."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.contract_content import Contract, ContractBonus
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import contracts
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def dungeon(game, team=False):
    return next(entry for entry in game[0].content.dungeons.values() if entry.team is team)


def add_pet(game, species_id, name, user="u1"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated) VALUES (?, ?, ?, 0, ?)",
        (user, species_id, name, NOW),
    )
    return max(row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets WHERE user_id=?", (user,)))


def ready(game, play, *, pets=1):
    """Adopt a starter strong enough for the easiest dungeon and top up resources."""
    play("adopt", "青鸾")
    ids = [row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")]
    extras = []
    for species, name in (("xuanhu", "玄狐甲"), ("baize", "白泽乙")):
        if len(ids) + len(extras) >= pets:
            break
        extras.append(add_pet(game, species, name))
    lineup = ids + extras
    sql(game[1], "UPDATE pets SET realm=4, layer=10, energy=100 WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='u1'")
    if len(lineup) > 1:
        play("lineup", " ".join(str(pet_id) for pet_id in lineup[:3]), op="lineup")
    return lineup


def test_content_declares_three_contracts(game):
    content = game[0].content
    kinds = sorted(entry.kind for entry in content.contracts.values())
    assert kinds == ["solo", "speed", "unhurt"]
    speed = next(entry for entry in content.contracts.values() if entry.kind == "speed")
    assert speed.rounds and speed.rounds >= 1
    for entry in content.contracts.values():
        assert entry.bonus.stones_percent or entry.bonus.exp_percent or entry.bonus.items


def test_contract_validation_rejects_mismatched_rounds_and_empty_bonus():
    bonus = {"stones_percent": 10, "exp_percent": 10, "items": {}}
    assert Contract.model_validate(
        {"id": "x", "name": "试", "description": "d", "kind": "speed", "rounds": 5, "bonus": bonus}
    ).rounds == 5
    with pytest.raises(ValidationError, match="round limit"):
        Contract.model_validate({"id": "x", "name": "试", "description": "d", "kind": "speed", "bonus": bonus})
    with pytest.raises(ValidationError, match="does not use a round limit"):
        Contract.model_validate(
            {"id": "x", "name": "试", "description": "d", "kind": "solo", "rounds": 5, "bonus": bonus}
        )
    with pytest.raises(ValidationError, match="pay something"):
        ContractBonus.model_validate({"stones_percent": 0, "exp_percent": 0, "items": {}})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("contracts", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_conditions_bonuses_and_targets(game, play):
    ready(game, play)
    page = play("contracts")
    assert "独行" in page.text() and "速战" in page.text() and "无伤" in page.text()
    assert "额外灵石" in page.text()
    assert all(link.command.startswith("灵宠契约 ") for link in page.inline_commands)
    names = {link.command for link in page.inline_commands}
    assert any("独行" in command for command in names)


def test_team_dungeons_are_excluded_from_the_page(game, play):
    ready(game, play)
    page = play("contracts")
    team = dungeon(game, team=True)
    assert f"灵宠契约 独行 {team.name}" not in {link.command for link in page.inline_commands}


def test_solo_refuses_before_spending_energy(game, play):
    ready(game, play, pets=2)
    first = dungeon(game)
    energy = sql(game[1], "SELECT SUM(energy) AS e FROM pets WHERE user_id='u1'")[0]["e"]
    with pytest.raises(GameError, match="只带一位伙伴"):
        play("contracts", f"独行 {first.name}", op="solo-refuse")
    assert sql(game[1], "SELECT SUM(energy) AS e FROM pets WHERE user_id='u1'")[0]["e"] == energy


def test_a_met_contract_pays_base_plus_bonus(game, play, monkeypatch):
    ready(game, play)
    first = dungeon(game)
    bst = game[0].content.contracts["solo"]
    stones = player(game[1])["stones"]
    play("contracts", f"独行 {first.name}", op="solo-ok")
    gained = player(game[1])["stones"] - stones
    base = first.reward.stones.minimum
    bonus = base * bst.bonus.stones_percent // 100
    assert gained >= base + bonus


def test_the_bonus_items_are_granted(game, play):
    ready(game, play)
    first = dungeon(game)
    before = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")
    play("contracts", f"独行 {first.name}", op="solo-items")
    after = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")
    before_qty = before[0]["quantity"] if before else 0
    # the dungeon itself may also drop forge_ore, so the contract only guarantees its own share
    assert (after[0]["quantity"] if after else 0) >= before_qty + 1


def test_a_broken_condition_pays_only_the_base_reward(game, play, monkeypatch):
    ready(game, play)
    first = dungeon(game)
    contract = game[0].content.contracts["speed"]
    monkeypatch.setattr(contracts, "satisfied", lambda *args, **kwargs: False)
    reply = play("contracts", f"速战 {first.name}", op="speed-miss")
    assert "未达成" in reply.text()
    assert "达成：" not in reply.text()


def test_a_lost_run_pays_no_bonus(game, play, monkeypatch):
    ready(game, play)
    first = dungeon(game)
    from types import SimpleNamespace

    def fake(*args, **kwargs):
        return SimpleNamespace(winner=1, rounds=3, lines=("败",), skill_uses=[{}, {}], history=())

    monkeypatch.setattr(contracts.adventure, "run_dungeon", lambda *a, **k: (
        SimpleNamespace(title="秘境败退", lines=("败",), commands=(), winner=1), fake(), []
    ))
    reply = play("contracts", f"独行 {first.name}", op="lost")
    assert "达成" not in reply.text()


def test_unknown_contract_and_dungeon_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("contracts", f"不存在的契约 {dungeon(game).name}")
    with pytest.raises(GameError, match="未找到该内容"):
        play("contracts", "独行 不存在的秘境")
    with pytest.raises(GameError, match="格式"):
        play("contracts", "独行")


def test_team_dungeon_refuses(game, play):
    ready(game, play)
    team = dungeon(game, team=True)
    with pytest.raises(GameError, match="组队秘境"):
        play("contracts", f"独行 {team.name}")


def test_bonus_math_is_deterministic(game):
    first = dungeon(game)
    ctx = ctx_of(game)
    contract = game[0].content.contracts["speed"]
    bonus = contracts.bonus_of(ctx, contract, first)
    assert bonus.stones.minimum == first.reward.stones.minimum * contract.bonus.stones_percent // 100
    assert bonus.exp.minimum == first.reward.exp.minimum * contract.bonus.exp_percent // 100


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "契约：" in play("objectives").text()
    assert "灵宠契约" in play("help", "秘境与关卡").text()
    assert handlers._parse("灵宠契约") == ("contracts", "")
    assert handlers._parse("灵宠契约 独行 森林") == ("contracts", "独行 森林")


def test_same_operation_replays_identically(game, play):
    ready(game, play)
    first = dungeon(game)
    original = play("contracts", f"独行 {first.name}", op="replay")
    stones = player(game[1])["stones"]
    again = play("contracts", f"独行 {first.name}", op="replay")
    assert again.text() == original.text()
    assert player(game[1])["stones"] == stones


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("contracts")
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
