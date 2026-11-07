"""灵宠斗法: exchange-by-exchange duels, weekly payout and QQ payload shape."""

import itertools
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import DuelRule, DuelStance, Rules
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import duel
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def ladder(game):
    return duel.opponents(game[0])


def first(game):
    return ladder(game)[0]


def boost(game, realm=0, user="u1"):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, affinity=100, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def set_energy(game, amount, user="u1"):
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id=?", (amount, NOW, user))


def state_rows(game, user="u1"):
    rows = sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id GLOB 'duel_*' ORDER BY quest_id",
        (user,),
    )
    return [row for row in rows if not row["quest_id"].startswith("duel_week_")]


def marker(game, opponent, user="u1", now=NOW):
    return sql(
        game[1],
        "SELECT claimed FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"duel_week_{beijing_week(now)[0]}_{opponent.id}"),
    )


def stub(hp=0, enemy_hp=0, winner=-1, rounds=1):
    def fake(left, right, rng, elements=None, *, max_rounds=None):
        left[0].hp -= hp
        right[0].hp -= enemy_hp
        return SimpleNamespace(winner=winner, rounds=rounds, lines=["这一回合交手。"], history=[], skill_uses=[{}, {}])

    return fake


def test_content_ladder_is_ordered_and_valid(game):
    entries = ladder(game)
    assert len(entries) == 7
    assert [entry.realm for entry in entries] == [
        "qiling", "ningqi", "zhuji", "jindan", "yuanying", "huashen", "dujie",
    ]
    assert all(entry.stats.hp > 0 and entry.reward.items for entry in entries)
    rule = game[0].content.rules.duel
    assert rule.energy == 3 and rule.exchanges == 12
    assert {stance.name for stance in rule.stances.values()} == {"抢攻", "稳守", "游斗"}


def test_rules_reject_stances_without_a_tradeoff_or_one_sided_sets():
    base = {"energy": 3, "exchanges": 6, "stances": {"assault": {"name": "抢攻", "dealt": 1.3, "taken": 1.2}}}
    with pytest.raises(ValidationError, match="at least two stances"):
        DuelRule.model_validate(base)
    single_sided = {
        "energy": 3,
        "exchanges": 6,
        "stances": {
            "quiet": {"name": "静守", "dealt": 0.9, "taken": 0.9},
            "slow": {"name": "缓攻", "dealt": 0.8, "taken": 0.8},
        },
    }
    with pytest.raises(ValidationError, match="aggressive and a defensive"):
        DuelRule.model_validate(single_sided)
    with pytest.raises(ValidationError, match="same way"):
        DuelStance.model_validate({"name": "怪招", "dealt": 1.2, "taken": 0.9})


def test_unknown_realm_or_missing_item_is_refused_by_the_catalog(game, tmp_path):
    import shutil

    source = game[0].content
    from nonebot_plugin_spirit_pet.content.catalog import Catalog

    data = tmp_path / "data"
    shutil.copytree(source.source_dir if hasattr(source, "source_dir") else "src/plugins/nonebot_plugin_spirit_pet/data", data)
    duels = data / "duels.json"
    broken = duels.read_text().replace('"realm": "qiling"', '"realm": "nowhere"', 1)
    duels.write_text(broken)
    with pytest.raises(ValueError, match="unknown realm"):
        Catalog.load(data)


def test_page_without_a_pet_is_read_only(game, play):
    page = play("duel", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert state_rows(game, "ghost") == []


def test_page_lists_every_guardian_and_only_links_the_reachable_one(game, play):
    play("adopt", "青鸾")
    page = play("duel")
    assert "松风道人（启灵）" in page.text()
    assert "无相居士（元婴）" in page.text()
    assert {link.label for link in page.inline_commands} == {"挑战"}
    assert page.inline_commands[0].command == "灵宠斗法 松风道人"


def test_start_refuses_realm_energy_expedition_and_unknown_names(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="境界"):
        play("duel", "石泉客")
    with pytest.raises(GameError, match="未找到该内容"):
        play("duel", "无名氏")
    set_energy(game, 2)
    with pytest.raises(GameError, match="精力不足"):
        play("duel", "松风道人")
    set_energy(game, 100)
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("duel", "松风道人")
    assert state_rows(game) == []


def test_start_writes_the_four_rows_and_a_repeat_is_refused(game, play):
    play("adopt", "青鸾")
    reply = play("duel", "松风道人")
    assert reply.title == "斗法开局"
    assert "第 1/12 回合" in reply.text()
    rows = {row["quest_id"]: row["progress"] for row in state_rows(game)}
    assert rows["duel_target"] == 1 and rows["duel_round"] == 1
    assert rows["duel_hp"] == 120 and rows["duel_enemy_hp"] == 150
    with pytest.raises(GameError, match="尚未结束"):
        play("duel", "松风道人")


def test_each_exchange_costs_energy_and_carries_health(game, play):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    play("duel", "抢攻")
    assert pet(game[1])["energy"] == 97
    rows = {row["quest_id"]: row["progress"] for row in state_rows(game)}
    assert rows["duel_round"] == 2
    assert 0 < rows["duel_hp"] < 120
    assert 0 < rows["duel_enemy_hp"] < 150
    page = play("duel")
    assert f"第 2 回合" in page.text()
    assert {link.label for link in page.inline_commands} == {"抢攻", "稳守", "游斗", "认输"}


def test_a_win_pays_once_marks_the_week_and_clears_the_bout(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))
    before = player(game[1])["stones"]
    reply = play("duel", "抢攻")
    assert reply.title == "斗法得胜"
    assert "本周奖励" in reply.text()
    assert player(game[1])["stones"] == before + 50
    assert items(game[1])["forge_ore"] >= 1
    assert marker(game, first(game))[0]["claimed"] == 1
    assert state_rows(game) == []
    with pytest.raises(GameError, match="本周已胜过"):
        play("duel", "松风道人")


def test_the_weekly_marker_clears_next_week(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))
    play("duel", "抢攻")
    page = play("duel", now=NOW + WEEK)
    assert "松风道人（启灵）" in page.text() and "可挑战" in page.text()
    play("duel", "松风道人", now=NOW + WEEK)
    rows = {row["quest_id"]: row["progress"] for row in state_rows(game)}
    assert rows["duel_round"] == 1


def test_losing_and_drawing_clear_the_bout_without_paying(game, play, monkeypatch):
    play("adopt", "青鸾")
    before = player(game[1])["stones"]
    play("duel", "松风道人")
    monkeypatch.setattr(duel, "fight", stub(hp=999, winner=1))
    reply = play("duel", "抢攻")
    assert reply.title == "斗法败退"
    assert state_rows(game) == []
    assert player(game[1])["stones"] == before
    play("duel", "松风道人")
    sql(game[1], "UPDATE quest_progress SET progress=12 WHERE quest_id='duel_round'")
    monkeypatch.setattr(duel, "fight", stub(hp=1, enemy_hp=1))
    reply = play("duel", "稳守")
    assert reply.title == "斗法平局"
    assert state_rows(game) == []
    assert player(game[1])["stones"] == before


def test_forfeit_clears_the_bout_and_requires_one(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="没有进行中的斗法"):
        play("duel", "认输")
    play("duel", "松风道人")
    reply = play("duel", "认输")
    assert reply.title == "斗法中止"
    assert state_rows(game) == []
    assert marker(game, first(game)) == []


def test_an_expedition_pauses_the_bout_until_it_is_forfeited(game, play):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    play("duel", "游斗")
    play("expedition_start", "采灵药")
    page = play("duel")
    assert "外出派遣" in page.text() and "暂时无法继续" in page.text()
    assert {link.label for link in page.inline_commands} == {"认输"}
    with pytest.raises(GameError, match="外出派遣"):
        play("duel", "抢攻")
    reply = play("duel", "认输")
    assert reply.title == "斗法中止"
    assert state_rows(game) == []


def test_replaying_an_exchange_returns_the_same_reply_and_settles_once(game, play):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    first_reply = play("duel", "抢攻", op="duel-op")
    energy = pet(game[1])["energy"]
    again = play("duel", "抢攻", op="duel-op")
    assert again.text() == first_reply.text()
    assert pet(game[1])["energy"] == energy
    rows = {row["quest_id"]: row["progress"] for row in state_rows(game)}
    assert rows["duel_round"] == 2


def test_a_bout_survives_a_restart(game, play):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    play("duel", "游斗")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "duel", "", "restart-duel", NOW)
    assert "第 2 回合" in page.text()


def test_a_broken_state_row_is_treated_as_no_bout(game, play):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    sql(game[1], "DELETE FROM quest_progress WHERE quest_id='duel_hp'")
    page = play("duel")
    assert "进行中" not in page.text()
    play("duel", "松风道人")
    assert {row["quest_id"]: row["progress"] for row in state_rows(game)}["duel_round"] == 1


def test_duels_write_no_battle_record_and_advance_nothing(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))
    play("duel", "抢攻")
    assert sql(game[1], "SELECT * FROM battle_records") == []
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'stat_%'") == []
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []


def test_max_rounds_leaves_the_default_fight_untouched(game):
    """One exchange is exactly one round; an unlimited fight still runs to a winner."""
    from nonebot_plugin_spirit_pet.domain.content import Stats
    from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, fight

    def fresh():
        return (
            [Fighter.create("甲", Stats(hp=10_000, attack=10, defense=0, speed=10))],
            [Fighter.create("乙", Stats(hp=10_000, attack=10, defense=0, speed=5))],
        )

    left, right = fresh()
    battle = fight(left, right, game[0].rng, game[0].content.elements, max_rounds=1)
    assert battle.rounds == 1 and battle.winner == -1
    assert sum(unit.turns for unit in left + right) == 2
    left, right = fresh()
    battle = fight(left, right, game[0].rng, game[0].content.elements)
    assert battle.rounds > 1


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "秘境与关卡")
    assert "灵宠斗法" in guide.text() and "认输" in guide.text()
    objectives = play("objectives")
    total = len(duel.opponents(game[0]))
    assert f"斗法：本周已胜 0/{total} 位护法 · 未开局" in objectives.text()
    assert handlers._parse("灵宠斗法") == ("duel", "")
    assert handlers._parse("灵宠斗法 抢攻") == ("duel", "抢攻")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    page = play("duel")
    # OneBot/plain fallback still spells the command next to the label.
    assert "（灵宠斗法 抢攻）" in page.text()
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
