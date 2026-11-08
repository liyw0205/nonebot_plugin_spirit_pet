"""Attrition gauntlet: five rounds, carried hp, weekly rewards, gates and idempotency."""

import re
from contextlib import closing
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.gauntlet_content import Gauntlet, GauntletRound
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import gauntlet

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400
COOLDOWN = 700


def entry(game):
    return sorted(game[0].content.gauntlets.values(), key=lambda item: item.id)[0]


def markers(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    rows = sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
        (user, f"gauntlet_{beijing_week(now)[0]}_%"),
    )
    return sorted(row["quest_id"] for row in rows)



def ctx_for(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "gauntlet-ctx")


def week_start(game, now=NOW):
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    return beijing_week(now)[0]


def ready(game, play, *, energy=100):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id='u1'", (energy, NOW))


def scripted(plan, seen=None):
    """Replace fight(): record entry hp, apply attrition, return the scripted winners."""
    queue = list(plan)

    def fake(allies, enemies, rng, elements=None):
        if seen is not None:
            seen.append([unit.hp for unit in allies])
        if not queue:
            raise AssertionError("fight() called more times than scripted")
        winner = queue.pop(0)
        for unit in allies:
            unit.hp = max(1, unit.hp - 10)
        return SimpleNamespace(winner=winner, rounds=3, lines=["战斗线"], history=[], skill_uses=[{}, {}])

    return fake


def test_content_declares_five_escalating_rounds(game):
    config = entry(game)
    assert config.energy == 15
    assert len(config.rounds) == 5
    content = game[0].content
    assert all(round_.enemy in content.enemies for round_ in config.rounds)
    assert all(item in content.items for round_ in config.rounds for item in round_.reward.items)
    assert [round_.hp_scale for round_ in config.rounds] == [1.0, 1.1, 1.3, 1.5, 1.8]
    assert config.rounds[-1].attack_scale > config.rounds[0].attack_scale


def test_gauntlet_validation_rejects_broken_content():
    reward = {"exp": {"minimum": 1, "maximum": 1}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}
    row = {"enemy": "wood_guard", "hp_scale": 1.0, "attack_scale": 1.0,
           "defense_scale": 1.0, "speed_scale": 1.0, "reward": reward}
    base = {"id": "g", "name": "擂台", "description": "测试", "energy": 15,
            "bonus": reward, "rounds": [row]}
    assert Gauntlet.model_validate(base).rounds[0].hp_scale == 1.0
    with pytest.raises(ValidationError):
        GauntletRound.model_validate({**row, "hp_scale": 0})
    with pytest.raises(ValidationError):
        Gauntlet.model_validate({**base, "rounds": []})
    with pytest.raises(ValidationError, match="exceeds"):
        Gauntlet.model_validate({**base, "energy": 200})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("gauntlet", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_every_round_rewards_and_bonus(game, play):
    ready(game, play)
    page = play("gauntlet")
    config = entry(game)
    assert "擂台：本周已过 0/5 关" in page.text()
    assert "15 精力" in page.text()
    for number, round_ in enumerate(config.rounds, 1):
        enemy = game[0].content.enemies[round_.enemy]
        assert f"{number}. {enemy.name}" in page.text()
        assert "未通关" in page.text()
    assert "全清奖励" in page.text()
    assert [link.command for link in page.inline_commands] == ["灵宠擂台 挑战"]


def test_a_full_clear_pays_every_round_and_the_bonus_once(game, play, monkeypatch):
    ready(game, play)
    stones = player(game[1])["stones"]
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0]))
    reply = play("gauntlet", "挑战", op="full-clear")
    config = entry(game)
    assert reply.title == "擂台全清"
    assert "本次通过 5 关" in reply.text()
    assert markers(game) == [f"gauntlet_{markers(game)[0].split('_')[1]}_{number}" for number in range(1, 6)] + [
        f"gauntlet_{markers(game)[0].split('_')[1]}_all"
    ]
    expected = sum(round_.reward.stones.minimum for round_ in config.rounds) + config.bonus.stones.minimum
    assert player(game[1])["stones"] == stones + expected
    assert pet(game[1])["energy"] == 85


def test_hp_carries_over_between_rounds(game, play, monkeypatch):
    ready(game, play)
    seen = []
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0], seen))
    play("gauntlet", "挑战", op="carry")
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-hp")
        full = combatant(ctx, "u1", recover_energy=False, pet_id=pet(game[1])["pet_id"]).stats.hp
    assert len(seen) == 5
    assert seen[0][0] == full
    assert seen[1][0] < seen[0][0]
    assert seen[4][0] < seen[1][0]


def test_a_loss_ends_the_run_and_pays_only_cleared_rounds(game, play, monkeypatch):
    ready(game, play)
    seen = []
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 1], seen))
    reply = play("gauntlet", "挑战", op="stop-2")
    assert reply.title == "擂台止步"
    assert len(seen) == 2
    week = markers(game)[0].split("_")[1]
    assert markers(game) == [f"gauntlet_{week}_1"]
    assert "本周最深 1/5 关" in reply.text()


def test_a_first_round_loss_pays_nothing(game, play, monkeypatch):
    ready(game, play)
    stones = player(game[1])["stones"]
    monkeypatch.setattr(gauntlet, "fight", scripted([1]))
    reply = play("gauntlet", "挑战", op="stop-1")
    assert reply.title == "擂台首关失守"
    assert markers(game) == []
    assert player(game[1])["stones"] == stones
    assert pet(game[1])["energy"] == 85


def test_cleared_rounds_are_not_paid_twice(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
    play("gauntlet", "挑战", op="first-run")
    stones = player(game[1])["stones"]
    play("gauntlet", "挑战", op="second-run", now=NOW + COOLDOWN)
    assert player(game[1])["stones"] == stones
    assert markers(game) == sorted(markers(game))
    assert len(markers(game)) == 6


def test_next_week_resets_progress_and_rewards(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
    play("gauntlet", "挑战", op="week-1")
    assert len(markers(game)) == 6
    later = NOW + WEEK
    assert markers(game, now=later) == []
    sql(game[1], "UPDATE pets SET energy=100, energy_updated=? WHERE user_id='u1'", (later,))
    stones = player(game[1])["stones"]
    reply = play("gauntlet", "挑战", op="week-2", now=later)
    assert reply.title == "擂台全清"
    assert len(markers(game, now=later)) == 6
    assert player(game[1])["stones"] > stones


def test_energy_is_charged_once_per_pet_for_the_whole_run(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0]))
    play("gauntlet", "挑战", op="energy-once")
    assert pet(game[1])["energy"] == 85


def test_insufficient_energy_refuses_before_any_write(game, play, monkeypatch):
    ready(game, play, energy=10)
    monkeypatch.setattr(gauntlet, "fight", scripted([0]))
    with pytest.raises(GameError, match="精力不足"):
        play("gauntlet", "挑战")
    assert markers(game) == []
    assert pet(game[1])["energy"] == 10


def test_an_expedition_pet_refuses_the_run(game, play, monkeypatch):
    ready(game, play)
    play("expedition_start", "采灵药", op="trip")
    monkeypatch.setattr(gauntlet, "fight", scripted([0]))
    with pytest.raises(GameError, match="派遣|行程"):
        play("gauntlet", "挑战")
    assert markers(game) == []


def test_the_shared_pve_cooldown_blocks_a_second_run(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0, 0]))
    play("gauntlet", "挑战", op="cd-1")
    with pytest.raises(GameError, match="调息"):
        play("gauntlet", "挑战", op="cd-2", now=NOW + 5)


def test_battle_records_use_the_gauntlet_key_and_never_touch_stage_progress(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 1]))
    play("gauntlet", "挑战", op="records")
    records = sql(game[1], "SELECT kind, battle_key FROM battle_records ORDER BY battle_id")
    # battle_records is unique per operation, so a run stores exactly one report: the deciding fight
    assert len(records) == 1
    assert records[0]["kind"] == "pve_stage"
    assert records[0]["battle_key"].endswith("_2")
    assert records[0]["battle_key"].startswith("gauntlet_")
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "擂台：本周尚未挑战" in play("objectives").text()
    assert "灵宠擂台" in play("help", "秘境与关卡").text()
    assert handlers._parse("灵宠擂台") == ("gauntlet", "")
    assert handlers._parse("灵宠擂台 挑战") == ("gauntlet", "挑战")
    with pytest.raises(GameError, match="格式"):
        play("gauntlet", "额外")


def test_same_operation_replays_identically(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0]))
    first = play("gauntlet", "挑战", op="replay")
    stones = player(game[1])["stones"]
    again = play("gauntlet", "挑战", op="replay")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones


def test_state_survives_a_restart(game, play, monkeypatch):
    ready(game, play)
    monkeypatch.setattr(gauntlet, "fight", scripted([0, 0, 0, 0, 0]))
    play("gauntlet", "挑战", op="persist")
    assert "擂台：本周已过 5/5 关" in play("objectives").text()
    assert "已领" in play("gauntlet").text()


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("gauntlet")
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

def seed_week(game, round_number, now=NOW, ladder_id=None, user="u1"):
    """Write one round marker the way the module names it."""
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    prefix = "gauntlet_" if ladder_id is None else f"gauntlet_{ladder_id}_"
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
        " ON CONFLICT(user_id, quest_id) DO NOTHING",
        (user, f"{prefix}{beijing_week(now)[0]}_{round_number}"),
    )


def test_history_lists_past_weeks_newest_first(game, play):
    ready(game, play)
    this = week_start(game)
    last = this - WEEK
    seed_week(game, 1)
    seed_week(game, 2)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"gauntlet_{last}_1",),
    )
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"gauntlet_{last}_2",),
    )
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"gauntlet_{last}_3",),
    )
    page = play("gauntlet", "战历")
    assert page.title == "擂台战历"
    assert "共 2 条周记录" in page.text()
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    assert f"{beijing_day(this)} 起那一周 · 灵宠擂台 · 通过 2 关" in page.text()
    assert f"{beijing_day(last)} 起那一周 · 灵宠擂台 · 通过 3 关" in page.text()


def test_history_shows_both_ladders_and_a_retired_one(game, play):
    ready(game, play)
    seed_week(game, 1)
    seed_week(game, 1, ladder_id="high_gauntlet")
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
        (f"gauntlet_old_ladder_{week_start(game)}_1",),
    )
    page = play("gauntlet", "战历")
    assert "灵宠擂台 · 通过 1 关" in page.text()
    assert "问天擂台 · 通过 1 关" in page.text()
    assert "old_ladder（已下线） · 通过 0 关" in page.text()


def test_history_is_empty_before_any_run(game, play):
    ready(game, play)
    page = play("gauntlet", "战历")
    assert "还没有擂台记录" in page.text()
    assert page.inline_commands == ()


def test_history_without_a_pet_is_read_only(game, play):
    page = play("gauntlet", "战历", user="ghost")
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "


def test_history_never_writes(game, play):
    ready(game, play)
    seed_week(game, 1)
    before = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    stones = player(game[1])["stones"]
    play("gauntlet", "战历")
    after = sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY quest_id")
    assert after == before
    assert player(game[1])["stones"] == stones


def test_history_pages_and_refuses_beyond_the_end(game, play):
    ready(game, play)
    this = week_start(game)
    total = gauntlet.HISTORY_PAGE_SIZE + 1
    for index in range(total):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
            (f"gauntlet_{this - index * WEEK}_1",),
        )
    first = play("gauntlet", "战历")
    assert f"共 {total} 条周记录 · 第 1/2 页" in first.text()
    assert "第 2/2 页" in play("gauntlet", "战历 2").text()
    with pytest.raises(GameError, match="共 2 页"):
        play("gauntlet", "战历 3")


def test_the_second_ladder_is_independent_and_named(game, play):
    ready(game, play)
    high = gauntlet.ladder(ctx_for(game), "high_gauntlet")
    assert high.id != gauntlet.config(ctx_for(game)).id
    assert len(gauntlet.ladders(ctx_for(game))) == 2
    page = play("gauntlet", "名单")
    assert page.title == "擂台名单"
    assert high.name in page.text()
    assert f"灵宠擂台 挑战 {high.id}" in {link.command for link in page.inline_commands}


def test_challenging_the_second_ladder_marks_only_its_own_keys(game, play, monkeypatch):
    ready(game, play)
    high = gauntlet.ladder(ctx_for(game), "high_gauntlet")
    monkeypatch.setattr(gauntlet, "fight", scripted([0] * len(high.rounds)))
    reply = play("gauntlet", f"挑战 {high.id}", op="high-run")
    assert reply.title == "擂台全清"
    week = week_start(game)
    keys = {row["quest_id"] for row in sql(game[1], "SELECT quest_id FROM quest_progress")}
    assert f"gauntlet_high_gauntlet_{week}_all" in keys
    # The default ladder's keys stay untouched.
    assert not any(key.startswith(f"gauntlet_{week}_") for key in keys)
    # And the default ladder still reads as untouched.
    assert gauntlet.deepest(ctx_for(game)) == 0
    assert gauntlet.deepest(ctx_for(game), None, high.id) == len(high.rounds)
