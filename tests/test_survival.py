"""Survival trial: guardian scaling, round scoring, milestones and records."""

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import survival
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql

NOW = 1_800_000_000
COOLDOWN = 700


def trial(game):
    return sorted(game[0].content.survival.values(), key=lambda entry: entry.id)[0]


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def best(game, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='survival_best'", (user,),
    )
    return rows[0]["progress"] if rows else 0


def milestone_rows(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE 'survival_milestone_%'"
        " ORDER BY quest_id",
        (user,),
    )


def stub(winner, rounds):
    return SimpleNamespace(winner=winner, rounds=rounds, lines=["战斗线"], history=[], skill_uses=[{}, {}])


def test_content_defines_the_guardian_and_ladder(game):
    entry = trial(game)
    assert entry.enemy in game[0].content.enemies
    assert (entry.hp_multiplier, entry.attack_multiplier, entry.energy) == (40.0, 0.6, 12)
    assert [milestone.rounds for milestone in entry.milestones] == [5, 10, 15, 20]
    assert entry.target == 20
    assert all(
        item in game[0].content.items
        for milestone in entry.milestones for item in milestone.reward.items
    )


def test_guardian_scales_only_the_configured_stats(game):
    play = None
    content = game[0].content
    base = content.enemies[trial(game).enemy]

    class Ctx:
        pass

    ctx = SimpleNamespace(content=content)
    boss = survival.guardian(ctx)
    assert boss.stats.hp == round(base.stats.hp * 40.0)
    assert boss.stats.attack == round(base.stats.attack * 0.6)
    assert boss.stats.defense == base.stats.defense
    assert boss.stats.speed == base.stats.speed
    assert boss.name.endswith("守关")


def test_page_without_a_pet_is_read_only(game, play):
    page = play("survival", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_shows_guardian_best_and_milestones(game, play):
    play("adopt", "青鸾")
    page = play("survival")
    assert "目标 20 回合" in page.text() and "每场精力 12" in page.text()
    assert "历史最深：0 回合" in page.text()
    assert "5 回合 · 修为 120 · 灵石 300 · 锻灵矿 2 · 未达" in page.text()
    assert {link.command for link in page.inline_commands} == {"灵宠守关 挑战"}


def test_a_defeat_records_the_survived_rounds(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 8))
    reply = play("survival", "挑战")
    assert reply.title == "守关结束"
    assert "守关 · 撑过 8 回合" in reply.text()
    assert best(game) == 8
    record = sql(game[1], "SELECT kind, battle_key FROM battle_records")
    assert record == [{"kind": "pve_stage", "battle_key": "survival"}]
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_a_win_counts_as_the_full_target(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(0, 3))
    play("survival", "挑战")
    assert best(game) == 20


def test_milestones_pay_once_and_only_when_crossed(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    stones = player(game[1])["stones"]
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 6))
    reply = play("survival", "挑战")
    assert "5 回合里程碑" in reply.text()

    assert player(game[1])["stones"] == stones + 300
    assert items(game[1])["forge_ore"] == 2
    assert [row["quest_id"] for row in milestone_rows(game)] == ["survival_milestone_5"]

    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 7))
    again = play("survival", "挑战", now=NOW + COOLDOWN)
    assert "里程碑" not in again.text()
    assert player(game[1])["stones"] == stones + 300


def test_a_jump_pays_every_crossed_milestone(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 12))
    reply = play("survival", "挑战")
    assert "5 回合里程碑" in reply.text() and "10 回合里程碑" in reply.text()
    assert [row["quest_id"] for row in milestone_rows(game)] == [
        "survival_milestone_10", "survival_milestone_5",
    ]


def test_a_worse_run_never_lowers_the_best_or_repays(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 12))
    play("survival", "挑战")
    stones = player(game[1])["stones"]
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 4))
    reply = play("survival", "挑战", now=NOW + COOLDOWN)
    assert "未刷新历史最深（12 回合）" in reply.text()
    assert best(game) == 12
    assert player(game[1])["stones"] == stones


def test_energy_is_checked_before_the_fight(game, play):
    play("adopt", "青鸾")
    boost(game)
    sql(game[1], "UPDATE pets SET energy=11 WHERE user_id='u1'")
    with pytest.raises(GameError, match="精力不足"):
        play("survival", "挑战")
    assert best(game) == 0


def test_an_expedition_pet_cannot_hold_the_line(game, play):
    play("adopt", "青鸾")
    boost(game)
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("survival", "挑战")


def test_the_page_switches_to_rematch_at_the_target(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(0, 30))
    play("survival", "挑战")
    page = play("survival")
    assert "已达最终目标" in page.text()
    assert {link.label for link in page.inline_commands} == {"再战"}


def test_state_survives_a_restart(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 9))
    play("survival", "挑战")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "survival", "", "restart-survival", NOW)
    assert "历史最深：9 回合" in page.text()


def test_same_operation_replays_identically(game, play, monkeypatch):
    play("adopt", "青鸾")
    boost(game)
    monkeypatch.setattr(survival, "fight", lambda *args, **kwargs: stub(1, 7))
    first = play("survival", "挑战", op="survival-op")
    again = play("survival", "挑战", op="survival-op")
    assert again.text() == first.text()
    assert best(game) == 7


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "秘境与关卡")
    assert "灵宠守关" in guide.text()
    assert "守关：尚未挑战" in play("objectives").text()
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', 'survival_best', 9, 1)",
    )
    assert "守关：最深 9 回合" in play("objectives").text()
    assert handlers._parse("灵宠守关") == ("survival", "")
    assert handlers._parse("灵宠守关 挑战") == ("survival", "挑战")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    page = play("survival")
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
