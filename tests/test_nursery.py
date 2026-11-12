import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from itertools import product
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.nursery_content import NurseryRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import loadout, nursery
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000
CHOICES = ("修行", "亲和", "默契")


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "players", "player_identity", "pets", "active_pet_slots", "inventory", "quest_progress",
        "duel_actions", "team_members", "battle_records",
    )}


def nest(store, user="u1"):
    return json.loads(sql(store, "SELECT snapshot FROM duel_actions WHERE user_id=? "
                         "AND json_extract(snapshot,'$.kind')='nursery' ORDER BY action_id DESC LIMIT 1",
                         (user,))[0]["snapshot"])


def grant(game, item, amount=1, user="u1"):
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,?,?) "
                "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item, amount))


def setup(game, play, egg="egg_qingluan", user="u1"):
    play("adopt", "青鸾", user=user)
    grant(game, egg, 2, user)
    grant(game, "spirit_food", 5, user)
    return pet(game[1], user)["pet_id"]


def start(game, play, egg="egg_qingluan", **kwargs):
    return play("nursery", f"入巢 {egg}", **kwargs)


def test_content_has_three_bounded_distinct_growth_choices(game):
    rule = game[0].content.nursery
    assert (rule.item_id, rule.energy, rule.interval, rule.lessons, rule.guardian_bond) == (
        "spirit_food", 6, 600, 2, 4)
    assert [(c.exp, c.affinity, c.bond) for c in rule.choices] == [(20, 0, 0), (0, 2, 0), (0, 0, 8)]
    assert {item.species_id for item in game[0].content.items.values() if item.kind == "pet_egg"} == set(game[0].content.species)


@pytest.mark.parametrize("field,value", [("energy", 0), ("energy", 11), ("interval", 0),
                                        ("lessons", 3), ("guardian_bond", 5), ("extra", 1)])
def test_invalid_rule_rejected_at_load(game, field, value):
    values = game[0].content.nursery.model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        NurseryRule.model_validate(values)


@pytest.mark.parametrize("bad", ["missing", "not_food", "duplicate", "same_growth"])
def test_catalog_rejects_broken_references_and_decisions(game, bad):
    rule = game[0].content.nursery.model_copy(deep=True)
    if bad == "missing":
        rule = rule.model_copy(update={"item_id": "does_not_exist"})
    elif bad == "not_food":
        rule = rule.model_copy(update={"item_id": "bloodline_essence"})
    elif bad == "duplicate":
        rule.choices[1] = rule.choices[0]
    else:
        rule.choices[1] = rule.choices[1].model_copy(update={"exp": 20, "affinity": 0})
    with pytest.raises(ValueError):
        replace(game[0].content, nursery=rule).validate()


def test_view_and_preview_do_not_register_or_restore_energy(game, play):
    before = snapshot(game[1])
    assert "尚未结契" in play("nursery").text()
    assert "尚未结契" in play("nursery", "预览 青鸾灵卵").text()
    assert snapshot(game[1]) == before
    guardian = setup(game, play)
    sql(game[1], "UPDATE pets SET energy=2,energy_updated=?", (NOW - 10000,))
    before = snapshot(game[1])
    for arg in ("", "预览 青鸾灵卵", f"预览 青鸾灵卵 伙伴 {guardian}", "记录"):
        play("nursery", arg)
    assert snapshot(game[1]) == before


def test_inventory_pages_and_preview_links_reach_real_start(game, play):
    setup(game, play)
    for egg in (item for item in game[0].content.items.values() if item.kind == "pet_egg"):
        grant(game, egg.id)
    first = play("nursery")
    last = play("nursery", "7")
    assert len(first.inline_commands) == 4 and len(last.inline_commands) == 3
    action, arg = handlers._parse(first.inline_commands[0].command)
    preview = play(action, arg)
    link = next(link for link in preview.inline_commands if link.label == "入巢护育")
    action, arg = handlers._parse(link.command)
    reply = play(action, arg, op="from-preview")
    assert "巢中" in reply.title
    assert nest(game[1])["egg_id"] in game[0].content.items


def test_breeding_output_flows_through_nursery_to_new_growth(game, play):
    guardian = setup(game, play)
    play("use", "egg_qingluan")
    second = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>?", (guardian,))[0]["pet_id"]
    sql(game[1], "UPDATE pets SET affinity=100")
    sql(game[1], "UPDATE players SET stones=2000")
    before_eggs = items(game[1])["egg_qingluan"]
    breed = play("breeding", f"{guardian} {second}")
    assert items(game[1])["egg_qingluan"] == before_eggs + 1
    assert player(game[1])["stones"] == 1200
    link = next(link for link in breed.inline_commands if link.label == "护育预览")
    preview = play(*handlers._parse(link.command))
    play(*handlers._parse(next(link.command for link in preview.inline_commands if link.label == "入巢护育")))
    play("nursery", "照料 亲和", now=NOW + 600)
    play("nursery", "迎接", now=NOW + 1200)
    baby_id = nest(game[1])["baby_id"]
    baby = sql(game[1], "SELECT * FROM pets WHERE pet_id=?", (baby_id,))[0]
    assert baby["affinity"] == game[0].content.species["qingluan"].initial_affinity + 2
    assert items(game[1])["egg_qingluan"] == before_eggs


def test_all_species_can_be_nurtured_without_changing_species(game, play):
    # One finite content chain per species, rather than a simulation matrix.
    setup(game, play)
    for index, species in enumerate(game[0].content.species.values()):
        day = NOW + index * 86400
        grant(game, f"egg_{species.id}")
        start(game, play, f"egg_{species.id}", now=day)
        play("nursery", "迎接", now=day + 1200)
        baby = sql(game[1], "SELECT * FROM pets ORDER BY pet_id DESC LIMIT 1")[0]
        assert (baby["species_id"], baby["affinity"], baby["exp"]) == (species.id, species.initial_affinity, 0)
        assert baby["energy"] == 100
    assert len(sql(game[1], "SELECT * FROM pets")) == 28
    assert player(game[1])["active_pet_id"] == 1


@pytest.mark.parametrize("choices", list(product(CHOICES, repeat=2)) + [("修行",), ()])
def test_limited_choices_settle_real_growth_and_resources(game, play, choices):
    guardian = setup(game, play)
    before_food = items(game[1])["spirit_food"]
    start(game, play)
    for index, choice in enumerate(choices, start=1):
        play("nursery", "照料 " + choice, now=NOW + index * 600)
    reply = play("nursery", "迎接", now=NOW + 1200, op="hatch")
    baby = sql(game[1], "SELECT * FROM pets WHERE pet_id<>?", (guardian,))[0]
    assert baby["exp"] == choices.count("修行") * 20
    assert baby["affinity"] == game[0].content.species[baby["species_id"]].initial_affinity + choices.count("亲和") * 2
    bonds = {row["quest_id"]: row["progress"] for row in sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'bond_exp_*'")}
    assert bonds.get(f"bond_exp_{baby['pet_id']}", 0) == choices.count("默契") * 8
    assert bonds.get(f"bond_exp_{guardian}", 0) == (4 if choices else 0)
    assert items(game[1])["spirit_food"] == before_food - len(choices)
    assert pet(game[1])["energy"] == (100 if not choices else 94 - 4 * (len(choices) - 1))
    assert items(game[1])["egg_qingluan"] == 1
    assert nest(game[1])["status"] == "hatched"
    assert "破壳相见" in reply.title and player(game[1])["active_pet_id"] == guardian
    assert not sql(game[1], "SELECT * FROM battle_records")


def test_growth_is_consumed_by_breakthrough_and_real_fighter(game, play):
    guardian = setup(game, play)
    sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,46,0)", (f"bond_exp_{guardian}",))
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read")
        before = loadout.combatant(ctx, recover_energy=False).stats
    start(game, play)
    play("nursery", "照料 修行", now=NOW + 600)
    play("nursery", "照料 修行", now=NOW + 1200)
    play("nursery", "迎接", now=NOW + 1200)
    baby_id = nest(game[1])["baby_id"]
    assert "突破成功" in play("breakthrough", str(baby_id), now=NOW + 1200).title
    baby = sql(game[1], "SELECT * FROM pets WHERE pet_id=?", (baby_id,))[0]
    assert (baby["exp"], baby["layer"]) == (10, 2)
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW + 1200, "read")
        after = loadout.combatant(ctx, recover_energy=False).stats
        assert (after.hp - before.hp, after.attack - before.attack) == (30, 5)


@pytest.mark.parametrize("arg,reason", [("入巢 灵粮", "不是灵卵"), ("入巢 不存在", "未找到"),
                                       ("入巢 egg_qingluan 伙伴 999999", "没有属于"),
                                       ("入巢 egg_qingluan 伙伴 " + "9" * 5000, "有效编号"),
                                       ("照料", "格式"), ("迎接", "没有巢中"),
                                       ("记录 1", "额外参数")])
def test_invalid_entry_is_specific_and_zero_write(game, play, arg, reason):
    setup(game, play)
    before = snapshot(game[1])
    with pytest.raises(GameError, match=reason):
        play("nursery", arg)
    assert snapshot(game[1]) == before


def test_interval_quota_clock_and_eligibility_rejections_preserve_nest(game, play):
    guardian = setup(game, play)
    start(game, play)
    before = snapshot(game[1])
    for arg, now, reason in (("照料 修行", NOW + 599, "休息 1 秒"), ("迎接", NOW + 1199, "还需 1 秒"),
                             ("入巢 egg_qingluan", NOW, "已有灵卵"), ("撤回", NOW - 1, "时间早于")):
        with pytest.raises(GameError, match=reason):
            play("nursery", arg, now=now)
        assert snapshot(game[1]) == before
    sql(game[1], "UPDATE pets SET energy=0,energy_updated=? WHERE pet_id=?", (NOW + 600, guardian))
    before = snapshot(game[1])
    with pytest.raises(GameError, match="精力不足.*需要 6"):
        play("nursery", "照料 修行", now=NOW + 600)
    assert snapshot(game[1]) == before
    assert not any("照料" in link.label for link in play("nursery", now=NOW + 600).inline_commands)
    sql(game[1], "UPDATE pets SET energy=100")
    sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="灵粮不足"):
        play("nursery", "照料 修行", now=NOW + 600)
    assert snapshot(game[1]) == before
    grant(game, "spirit_food", 2)
    play("nursery", "照料 修行", now=NOW + 600)
    play("nursery", "照料 亲和", now=NOW + 1200)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="次数已用尽"):
        play("nursery", "照料 默契", now=NOW + 1800)
    assert snapshot(game[1]) == before


def test_original_guardian_survives_switch_and_capacity_recovery(game, play):
    guardian = setup(game, play)
    play("use", "egg_qingluan")
    other = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>?", (guardian,))[0]["pet_id"]
    grant(game, "egg_qingluan")
    start(game, play)
    play("switch", str(other))
    play("nursery", "照料 默契", now=NOW + 600)
    game[0].config.spirit_pet_max_pets = 2
    before = snapshot(game[1])
    with pytest.raises(GameError, match="容量不足.*保留"):
        play("nursery", "迎接", now=NOW + 1200)
    assert snapshot(game[1]) == before
    assert not any("迎接" in cmd for cmd in play("nursery", now=NOW + 1200).commands)
    play("pet_archive", str(guardian), now=NOW + 1200)
    with pytest.raises(GameError, match="已封存"):
        play("nursery", "迎接", now=NOW + 1200)
    play("pet_restore", str(guardian), now=NOW + 1200)
    play("switch", str(guardian), now=NOW + 1200)
    play("pet_archive", str(other), now=NOW + 1200)
    play("nursery", "迎接", now=NOW + 1200)
    assert nest(game[1])["guardian_id"] == guardian


def test_original_guardian_expedition_rejection_and_recall_restore(game, play):
    setup(game, play)
    start(game, play)
    play("expedition_start", "采灵药")
    before = snapshot(game[1])
    for arg in ("照料 修行", "迎接"):
        with pytest.raises(GameError, match="正在外出派遣"):
            play("nursery", arg, now=NOW + 1200)
    page = play("nursery", now=NOW + 1200)
    assert "灵宠行程" in {link.command for link in page.inline_commands}
    assert not any("照料" in link.label for link in page.inline_commands)
    assert snapshot(game[1]) == before
    job = sql(game[1], "SELECT job_id FROM expeditions WHERE state='running'")[0]["job_id"]
    play("expedition_cancel", str(job), now=NOW + 1200)
    play("nursery", "照料 修行", now=NOW + 1200)
    assert "破壳相见" in play("nursery", "迎接", now=NOW + 1200).title


def test_pet_specific_readiness_only_changes_when_guardian_participates(game, play):
    guardian = setup(game, play)
    play("use", "egg_qingluan")
    other = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>?", (guardian,))[0]["pet_id"]
    start(game, play)
    play("team_create")
    play("team_ready")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": guardian}]
    play("nursery", "照料 修行", now=NOW + 600)
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": None}]
    play("switch", str(other), now=NOW + 600)
    play("team_ready", now=NOW + 600)
    play("nursery", "照料 修行", now=NOW + 1200)
    play("nursery", "迎接", now=NOW + 1200)
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": other}]


def test_missing_guardian_can_withdraw_without_growth_or_double_refund(game, play):
    guardian = setup(game, play)
    start(game, play)
    play("nursery", "照料 默契", now=NOW + 600)
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    sql(game[1], "DELETE FROM pets WHERE pet_id=?", (guardian,))
    before = snapshot(game[1])
    with pytest.raises(GameError, match="原护育伙伴不存在"):
        play("nursery", "迎接", now=NOW + 1200)
    assert snapshot(game[1]) == before
    reply = play("nursery", "撤回", now=NOW + 1200, op="refund")
    assert items(game[1])["egg_qingluan"] == 2
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id GLOB 'bond_exp_*'")
    with pytest.raises(GameError, match="没有巢中"):
        play("nursery", "撤回", now=NOW + 1200)
    with pytest.raises(GameError, match="今日已经入巢"):
        start(game, play, now=NOW + 1200)
    assert play("nursery", "撤回", op="refund", now=NOW + 86400 * 8) == reply
    assert items(game[1])["egg_qingluan"] == 2


def test_real_released_guardian_is_not_misreported_as_recoverable_archive(game, play):
    guardian = setup(game, play)
    play("use", "egg_qingluan")
    other = sql(game[1], "SELECT pet_id FROM pets WHERE pet_id<>?", (guardian,))[0]["pet_id"]
    start(game, play)
    play("nursery", "照料 默契", now=NOW + 600)
    play("switch", str(other), now=NOW + 600)
    play("pet_release", f"确认 {guardian}", now=NOW + 600)
    before_eggs = items(game[1])["egg_qingluan"]
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已归灵，请撤回"):
        play("nursery", "迎接", now=NOW + 1200)
    page = play("nursery", now=NOW + 1200)
    assert "已归灵" in page.text() and "已封存" not in page.text()
    assert not any(link.command.startswith("灵宠复原") for link in page.inline_commands)
    assert snapshot(game[1]) == before
    play("nursery", "撤回", now=NOW + 1200)
    assert items(game[1])["egg_qingluan"] == before_eggs + 1


def test_cross_day_rule_snapshot_and_permanent_replay_survive_restart(game, play):
    setup(game, play)
    first = start(game, play, op="start")
    rule = game[0].content.nursery.model_copy(deep=True, update={"energy": 10})
    rule.choices[0] = rule.choices[0].model_copy(update={"exp": 1})
    game[0].content = replace(game[0].content, nursery=rule)
    care = play("nursery", "照料 修行", now=NOW + 86400, op="care")
    assert nest(game[1])["growth"]["exp"] == 20
    done = play("nursery", "迎接", now=NOW + 86400, op="done")
    before = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    fresh = Game(game[1], game[0].config, game[0].rng, game[0].content)
    game[1].initialize()
    for op, expected in (("start", first), ("care", care), ("done", done)):
        assert fresh.execute("u1", "nursery", "", op, NOW + 86400 * 8) == expected
    assert snapshot(game[1]) == before
    with pytest.raises(GameError, match="different user"):
        fresh.execute("u2", "nursery", "", "done", NOW + 86400 * 8)


def test_old_step_old_nest_and_huge_guard_do_not_touch_current_nest(game, play):
    setup(game, play)
    start(game, play)
    page = play("nursery", now=NOW + 600)
    link = next(link for link in page.inline_commands if "修行" in link.label)
    action, arg = handlers._parse(link.command)
    play(action, arg, now=NOW + 600)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="这一步照料已经执行"):
        play(action, arg, now=NOW + 1200)
    with pytest.raises(GameError, match="整数"):
        play(action, arg.rsplit(" ", 1)[0] + " " + "9" * 5000, now=NOW + 1200)
    assert snapshot(game[1]) == before
    play("nursery", "撤回", now=NOW + 1200)
    start(game, play, now=NOW + 86400)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="另一枚灵卵"):
        play(action, arg, now=NOW + 86400 + 600)
    assert snapshot(game[1]) == before


def test_active_nest_recovers_after_restart_and_old_cached_start_cannot_reset_it(game, play):
    setup(game, play)
    original = start(game, play, op="initial-nest")
    play("nursery", "照料 修行", now=NOW + 600)
    before = snapshot(game[1])
    sql(game[1], "DELETE FROM operations")
    fresh = Game(game[1], game[0].config, game[0].rng, game[0].content)
    assert fresh.execute("u1", "nursery", "入巢 egg_qingluan", "initial-nest", NOW + 86400 * 8) == original
    assert snapshot(game[1]) == before
    page = fresh.execute("u1", "nursery", "", "view-after-restart", NOW + 86400 * 8)
    assert "已照料 1/2" in page.text() and "修为 +20" in page.text()
    fresh.execute("u1", "nursery", "照料 默契", "resume-care", NOW + 86400 * 8)
    fresh.execute("u1", "nursery", "迎接", "resume-hatch", NOW + 86400 * 8)
    saved = nest(game[1])
    assert saved["history"] == ["修行", "默契"] and saved["growth"] == {"exp": 20, "affinity": 0, "bond": 8}
    assert items(game[1])["egg_qingluan"] == 1


def test_concurrent_old_step_only_spends_one_lesson(game, play):
    setup(game, play)
    start(game, play)
    before_food = items(game[1])["spirit_food"]
    page = play("nursery", now=NOW + 600)
    actions = [handlers._parse(link.command) for link in page.inline_commands if link.label.startswith("照料")][:2]

    def execute(action):
        try:
            return play(*action, now=NOW + 600)
        except GameError as exc:
            assert "这一步照料已经执行" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(execute, actions))
    assert sum(reply is not None for reply in replies) == 1
    assert len(nest(game[1])["history"]) == 1
    assert items(game[1])["spirit_food"] == before_food - 1


@pytest.mark.parametrize("phase,method", [("start", "consume_item"), ("start", "record_nursery_action"),
                                         ("care", "consume_item"), ("care", "record_nursery_action"),
                                         ("finish", "create_pet"), ("finish", "record_nursery_action"),
                                         ("withdraw", "add_item"), ("withdraw", "record_nursery_action")])
def test_write_failure_rolls_back_entire_action_and_retry(game, play, monkeypatch, phase, method):
    setup(game, play)
    if phase != "start":
        start(game, play)
    if phase in ("finish", "withdraw"):
        play("nursery", "照料 默契", now=NOW + 600)
    arg = {"start": "入巢 egg_qingluan", "care": "照料 修行", "finish": "迎接", "withdraw": "撤回"}[phase]
    before = snapshot(game[1])
    original = getattr(Repository, method)

    def broken(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("injected nursery write failure")

    monkeypatch.setattr(Repository, method, broken)
    with pytest.raises(RuntimeError, match="injected nursery"):
        play("nursery", arg, now=NOW + 1200, op="retry")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(Repository, method, original)
    reply = play("nursery", arg, now=NOW + 1200, op="retry")
    assert reply == play("nursery", arg, now=NOW + 1200, op="retry")


def test_growth_failure_rolls_back_baby_and_guardian_and_can_retry(game, play, monkeypatch):
    setup(game, play)
    start(game, play)
    play("nursery", "照料 默契", now=NOW + 600)
    before = snapshot(game[1])
    original = nursery.bond_levels.add_exp

    def broken(*args):
        original(*args)
        raise RuntimeError("injected growth failure")

    monkeypatch.setattr(nursery.bond_levels, "add_exp", broken)
    with pytest.raises(RuntimeError, match="injected growth failure"):
        play("nursery", "迎接", now=NOW + 1200, op="growth-retry")
    assert snapshot(game[1]) == before
    monkeypatch.setattr(nursery.bond_levels, "add_exp", original)
    play("nursery", "迎接", now=NOW + 1200, op="growth-retry")
    assert len(sql(game[1], "SELECT * FROM pets")) == 2


def test_same_operation_concurrent_start_only_reserves_one_egg(game, play):
    setup(game, play)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: start(game, play, op="same-start"), range(2)))
    assert replies[0] == replies[1]
    assert items(game[1])["egg_qingluan"] == 1
    assert len(sql(game[1], "SELECT * FROM duel_actions")) == 1


def test_two_users_and_concurrent_hatch_withdraw_settle_once(game, play):
    setup(game, play)
    setup(game, play, user="u2")
    start(game, play)
    start(game, play, user="u2")
    assert nest(game[1])["nest_id"] != nest(game[1], "u2")["nest_id"]
    u2_before = nest(game[1], "u2")

    def execute(arg):
        try:
            return play("nursery", arg, now=NOW + 1200)
        except GameError as exc:
            assert "没有巢中" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, ["迎接", "撤回"]))
    assert sum(reply is not None for reply in results) == 1
    assert nest(game[1], "u2") == u2_before
    count = len(sql(game[1], "SELECT * FROM pets WHERE user_id='u1'"))
    assert count + items(game[1])["egg_qingluan"] == 3


def test_daily_high_water_record_and_old_duel_consumers(game, play):
    setup(game, play)
    start(game, play, now=NOW + 86400)
    done = play("nursery", "撤回", now=NOW + 86400)
    with pytest.raises(GameError, match="时间早于"):
        start(game, play, now=NOW)
    record = play("nursery", "记录", now=NOW + 86400)
    assert record.lines == done.lines and not record.inline_commands
    before = snapshot(game[1])
    assert "护育" in play("objectives", now=NOW + 86400).text()
    with closing(game[1].connect()) as conn:
        repo = Repository(conn)
        assert repo.latest_duel_action("u1") is None
        assert repo.latest_cooking_action("u1") is None
        assert repo.latest_tracking_action("u1") is None
        assert repo.latest_herbalism_action("u1") is None
    assert "尚无回合记录" in play("duel", "回顾", now=NOW + 86400).text()
    assert snapshot(game[1])["duel_actions"] == before["duel_actions"]


def test_qq_native_and_fallback_short_contract(game, play):
    setup(game, play)
    replies = [play("nursery"), play("nursery", "预览 egg_qingluan"), start(game, play),
               play("nursery", now=NOW + 1200)]
    for reply in replies:
        assert len(reply.commands) <= 4
        assert all(not re.search(r"[0-9a-f]{16}", label) for label, _ in _action_items(reply))
        _, parts = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        body = parts["markdown"][0].data["markdown"].content
        links = {parse_qs(urlparse(url).query)["command"][0] for url in re.findall(r"\]\((mqqapi://[^)]+)\)", body)}
        buttons = {button.action.data for segment in parts["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert buttons == {"!" + command for command in reply.commands}
        assert links == {"!" + link.command for link in reply.inline_commands}
        assert not links & buttons
        _, text = _qq_segments(reply, Config(spirit_pet_qq_mode="text", spirit_pet_command_prefix="!"))
        assert all("!" + link.command in str(text) for link in reply.inline_commands)


def test_onebot_handler_full_chain_and_qq_entry_only(game, monkeypatch):
    import nonebot
    from nonebot.adapters.qq import Adapter, Bot
    from nonebot.adapters.qq.config import BotInfo

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    clock = [NOW]
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: clock[0])
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())

    async def run():
        for index, (command, timestamp) in enumerate((
            ("!灵宠领养 青鸾", NOW), ("!灵宠护育 预览 青鸾灵卵", NOW),
            ("!灵宠护育 入巢 青鸾灵卵", NOW), ("!灵宠护育 照料 修行", NOW + 600),
            ("!灵宠护育 照料 修行", NOW + 1200), ("!灵宠护育 迎接", NOW + 1200),
            ("!灵宠突破 2", NOW + 1200))):
            clock[0] = timestamp
            event = onebot_event(command, index + 1)
            await handlers.handle_command(bot, event, event.get_message())
            if index == 0:
                grant(game, "egg_qingluan", user="12345")
                grant(game, "spirit_food", 3, user="12345")

    asyncio.run(run())
    sent = [call.args[1] for call in bot.send.call_args_list]
    assert "10000" in sent[0] and "破壳相见" in sent[-2] and "突破成功" in sent[-1]
    assert sql(game[1], "SELECT exp,layer FROM pets WHERE pet_id=2") == [{"exp": 10, "layer": 2}]
    event = qq_event(user_id="qq-nursery", text="!灵宠护育", message_id="qq-nursery-entry")
    assert handlers._parse(event.get_plaintext()) == ("nursery", "")
    qq_bot = Bot(Adapter(nonebot.get_driver()), "test-app", BotInfo(id="test-app", secret="test-only", token="test-only"))
    qq_bot.post_group_messages = AsyncMock(return_value={})
    asyncio.run(handlers.handle_command(qq_bot, event, event.get_message()))
    assert qq_bot.post_group_messages.await_count == 1


@pytest.mark.parametrize("phase", ["execute", "send"])
def test_handler_real_exceptions_keep_command_context_and_propagate(game, monkeypatch, phase):
    monkeypatch.setattr(handlers, "game", game[0])
    logger = SimpleNamespace(exception=Mock())
    monkeypatch.setattr(handlers, "logger", logger)
    error = RuntimeError("injected nursery handler error")
    if phase == "execute":
        monkeypatch.setattr(game[0], "execute", Mock(side_effect=error))
    else:
        monkeypatch.setattr(handlers, "send_reply", AsyncMock(side_effect=error))
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    event = onebot_event("灵宠护育 预览 青鸾灵卵")
    with pytest.raises(RuntimeError, match="nursery handler"):
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert "action='nursery'" in logger.exception.call_args.args[0]
    assert "预览 青鸾灵卵" in logger.exception.call_args.args[0]


@pytest.mark.parametrize("phase", ["execute", "send"])
def test_normal_finish_is_not_logged_as_failure(game, monkeypatch, phase):
    from nonebot.exception import FinishedException

    monkeypatch.setattr(handlers, "game", game[0])
    logger = SimpleNamespace(exception=Mock())
    monkeypatch.setattr(handlers, "logger", logger)
    if phase == "execute":
        monkeypatch.setattr(game[0], "execute", Mock(side_effect=FinishedException))
    else:
        monkeypatch.setattr(handlers, "send_reply", AsyncMock(side_effect=FinishedException))
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock())
    event = onebot_event("灵宠护育")
    with pytest.raises(FinishedException):
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    logger.exception.assert_not_called()
