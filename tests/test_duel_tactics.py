"""Observe -> choose -> settle -> review, with durable and atomic turns."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.duel_content import DuelOpponent
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import duel
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, player, sql
from .test_duel import NOW, WEEK, stub


def snapshot(store, *, cache=True):
    with closing(store.connect()) as conn:
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                 if cache or row[0] != "operations"]
        return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                for name in names if not name.startswith("sqlite_")}


def latest(game):
    return json.loads(sql(game[1], "SELECT snapshot FROM duel_actions ORDER BY action_id DESC LIMIT 1")[0]["snapshot"])


@pytest.mark.parametrize("intents", [[], ["assault"], ["guard", "guard"], ["unknown", "assault"], ["guard", "feint"] * 4])
def test_invalid_cycles_rejected(game, intents):
    data = game[0].content.duels["songfeng"].model_dump()
    data["intents"] = intents
    with pytest.raises(ValidationError):
        DuelOpponent.model_validate(data)


def test_each_guardian_has_its_own_observable_cycle(game, play):
    entries = game[0].content.duels.values()
    assert len({tuple(entry.intents) for entry in entries}) == 7
    for entry in entries:
        page = play("duel", f"详情 {entry.name}", user="new")
        assert "招式循环" in page.text() and "开始领养" in page.text()
    assert sql(game[1], "SELECT * FROM players") == []


@pytest.mark.parametrize("round_no,stance,outcome,dealt,taken", [
    (1, "抢攻", "平招", 1.30, 1.20), (1, "稳守", "破招", .85 * 1.15, .70 * .85),
    (1, "游斗", "受制", 1.12 * .85, 1.06 * 1.15),
    (2, "抢攻", "受制", 1.30 * .85, 1.20 * 1.15), (2, "稳守", "平招", .85, .70),
    (2, "游斗", "破招", 1.12 * 1.15, 1.06 * .85),
    (3, "抢攻", "破招", 1.30 * 1.15, 1.20 * .85), (3, "稳守", "受制", .85 * .85, .70 * 1.15),
    (3, "游斗", "平招", 1.12, 1.06),
])
def test_preview_and_real_combat_apply_all_nine_responses(game, play, monkeypatch, round_no, stance, outcome, dealt, taken):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    sql(game[1], "UPDATE quest_progress SET progress=? WHERE quest_id='duel_round'", (round_no,))
    page = play("duel")
    expected_move = ("抢攻", "稳守", "游斗")[round_no - 1]
    assert f"护法将出：{expected_move}" in page.text()
    assert f"{stance}：{outcome}" in page.text()
    original = duel.fight
    observed = {}

    def actual(left, right, *args, **kwargs):
        assert left[0].dealt == pytest.approx(dealt)
        assert left[0].taken == pytest.approx(taken)
        result = original(left, right, *args, **kwargs)
        observed.update(hp=left[0].hp, enemy_hp=right[0].hp)
        return result

    monkeypatch.setattr(duel, "fight", actual)
    result = play("duel", stance)
    assert f"护法出手：{expected_move} · {outcome}" in result.text()
    entry = latest(game)
    assert entry["outcome"] == outcome and entry["round"] == round_no
    assert entry["hp"] == observed["hp"] < 120
    assert entry["enemy_hp"] == observed["enemy_hp"] < 150
    assert pet(game[1])["energy"] == 97


def test_cycle_wraps_and_opening_rules_survive_content_changes(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    monkeypatch.setattr(duel, "fight", stub(hp=1, enemy_hp=1))
    game[0].content.duels.clear()
    game[0].content = replace(game[0].content, rules=game[0].content.rules.model_copy(update={
        "duel": game[0].content.rules.duel.model_copy(update={"energy": 99}),
    }))
    for expected in ("抢攻", "稳守", "游斗", "抢攻"):
        assert "护法将出：" + expected in play("duel").text()
        assert "护法出手：" + expected in play("duel", "稳守").text()
    assert pet(game[1])["energy"] == 88


@pytest.mark.parametrize("argument", ["", "详情 松风道人", "回顾", "战历"])
def test_queries_do_not_recover_energy_or_write_business_rows(game, play, argument):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET energy=50,energy_updated=?", (NOW - 3600,))
    before = snapshot(game[1], cache=False)
    play("duel", argument)
    assert snapshot(game[1], cache=False) == before


@pytest.mark.parametrize("problem,pattern", [("energy", "精力不足"), ("switch", "原伙伴"),
    ("archived", "封存"), ("missing", "出战"), ("expedition", "外出派遣"), ("pending", "奖励待领取")])
def test_blocked_turns_hide_actions_and_leave_every_row_unchanged(game, play, problem, pattern):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    if problem == "energy":
        sql(game[1], "UPDATE pets SET energy=2")
    elif problem == "switch":
        with closing(game[1].connect()) as conn:
            repo = Repository(conn)
            other = repo.create_pet("u1", "qingluan", "另一伙伴", 0, NOW)
            conn.execute("UPDATE players SET active_pet_id=?", (other.pet_id,))
    elif problem == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    elif problem == "missing":
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    else:
        play("expedition_start", "采灵药")
        if problem == "pending":
            sql(game[1], "UPDATE expeditions SET started_at=?,finishes_at=?", (NOW-100, NOW))
    before = snapshot(game[1])
    with pytest.raises(GameError, match=pattern):
        play("duel", "稳守")
    assert snapshot(game[1]) == before
    page = play("duel")
    assert pattern in page.text()
    assert {link.label for link in page.inline_commands} == {"认输"}
    play("duel", "认输")
    assert latest(game)["status"] == "forfeit"


@pytest.mark.parametrize("argument", ["详情 不存在", "回顾 2", "回顾 查看 99999", "回顾 查看 1 extra", "稳守 extra", "未知招式"])
def test_invalid_arguments_zero_writes(game, play, argument):
    play("adopt", "青鸾")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("duel", argument)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("action", ["start", "turn", "win", "forfeit"])
def test_ledger_failure_rolls_back_entire_action(game, play, monkeypatch, action):
    play("adopt", "青鸾")
    if action != "start":
        play("duel", "松风道人")
    play("team_create")
    play("team_ready")
    if action == "win":
        monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))
    before = snapshot(game[1])
    original = Repository.record_duel_action

    def fail(self, *args):
        original(self, *args)
        raise RuntimeError("injected duel receipt")

    monkeypatch.setattr(Repository, "record_duel_action", fail)
    with pytest.raises(RuntimeError, match="injected duel receipt"):
        play("duel", {"start": "松风道人", "forfeit": "认输"}.get(action, "稳守"))
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("target", ["reward", "state", "save"])
def test_mid_transaction_failure_restores_health_energy_reward_and_readiness(game, play, monkeypatch, target):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    play("team_create")
    play("team_ready")
    before = snapshot(game[1])
    if target == "reward":
        monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))
        original = duel.grant
        def fail(*args):
            original(*args)
            raise RuntimeError("injected partial reward")
        monkeypatch.setattr(duel, "grant", fail)
    elif target == "state":
        original = duel._write
        def fail(*args):
            original(*args)
            raise RuntimeError("injected state write")
        monkeypatch.setattr(duel, "_write", fail)
    else:
        original = Repository.save
        def fail(self):
            original(self)
            raise RuntimeError("injected save")
        monkeypatch.setattr(Repository, "save", fail)
    with pytest.raises(RuntimeError, match="injected"):
        play("duel", "稳守")
    assert snapshot(game[1]) == before


def test_expired_cache_restart_cross_action_and_owner_replay(game, play, monkeypatch):
    play("adopt", "青鸾")
    opening = play("duel", "松风道人", op="open")
    turn = play("duel", "稳守", op="turn")
    closing_reply = play("duel", "认输", op="close")
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[1], game[0].config, game[0].rng, content=game[0].content)
    before = snapshot(game[1], cache=False)
    for op, expected in (("open", opening), ("turn", turn), ("close", closing_reply)):
        actual = restarted.execute("u1", "train", "", op, NOW+WEEK*2)
        assert actual == expected
    assert snapshot(game[1], cache=False) == before
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="different user"):
        restarted.execute("other", "duel", "", "turn", NOW+WEEK*2)
    assert snapshot(game[1]) == before


def test_simultaneous_same_message_and_independent_turns(game, play, monkeypatch):
    play("adopt", "青鸾")
    play("duel", "松风道人")
    monkeypatch.setattr(duel, "fight", stub(hp=1, enemy_hp=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: game[0].execute("u1", "duel", "稳守", "same", NOW), range(2)))
    assert replies[0] == replies[1]
    assert pet(game[1])["energy"] == 97
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda op: game[0].execute("u1", "duel", "稳守", op, NOW), ("a", "b")))
    assert pet(game[1])["energy"] == 91
    assert latest(game)["round"] == 3


def test_legacy_bout_continues_neutral_and_binds_without_inventing_history(game, play, monkeypatch):
    play("adopt", "青鸾")
    for key, value in (("duel_target", 1), ("duel_round", 4), ("duel_hp", 80), ("duel_enemy_hp", 75)):
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1',?,?,0)", (key, value))
    assert "旧局" in play("duel").text()
    assert sql(game[1], "SELECT * FROM duel_actions") == []
    monkeypatch.setattr(duel, "fight", stub(hp=1, enemy_hp=1))
    play("duel", "稳守")
    saved = latest(game)
    assert saved["bout"]["legacy"] and saved["bout"]["pet_id"] == pet(game[1])["pet_id"]
    assert saved["hp"] == 79 and saved["enemy_hp"] == 74 and saved["intent"] is None
    assert len(sql(game[1], "SELECT * FROM duel_actions")) == 1


def test_full_loop_review_ownership_and_growth_feedback(game, play, monkeypatch):
    play("adopt", "青鸾")
    detail = play("duel", "详情 松风道人")
    assert any(link.command == "灵宠斗法 松风道人" for link in detail.inline_commands)
    play("duel", "松风道人")
    assert "将出抢攻" in play("objectives").text()
    monkeypatch.setattr(duel, "fight", stub(hp=1, enemy_hp=1))
    for _ in range(5):
        play("duel", "稳守")
    monkeypatch.setattr(duel, "fight", stub(enemy_hp=999))
    won = play("duel", "游斗", op="winning")
    assert won.title == "斗法得胜" and "灵宠突破" in won.commands
    assert pet(game[1])["exp"] == 40 and player(game[1])["stones"] >= 50
    assert "本周已胜 1/7" in play("objectives").text()
    records = play("duel", "回顾")
    assert len(records.inline_commands) == 5 and "灵宠斗法 回顾 2" in records.commands
    assert len(play("duel", "回顾 2").inline_commands) == 2
    last_id = sql(game[1], "SELECT MAX(action_id) AS id FROM duel_actions")[0]["id"]
    review = play("duel", f"回顾 查看 {last_id}")
    assert review.lines == won.lines and review.inline_commands == ()
    with pytest.raises(GameError, match="本人"):
        play("duel", f"回顾 查看 {last_id}", user="stranger")
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1], cache=False)
    assert play("duel", "稳守", op="winning", now=NOW+WEEK) == won
    assert snapshot(game[1], cache=False) == before
    guide = play("help", "秘境与关卡")
    assert "灵宠斗法 详情" in guide.text() and "灵宠斗法 回顾" in guide.text()
