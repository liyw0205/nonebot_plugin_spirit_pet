import itertools
import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import journey
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
COUNTER = itertools.count()


def stones(game):
    return player(game[1])["stones"]


def items(game, item_id):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id=?", (item_id,))
    return rows[0]["quantity"] if rows else 0


def value(game, user, chapter_id):
    out = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "journey")
        out.append(journey._value(ctx, user, game[0].content.journey[chapter_id].task))
        return Reply("journey", ())

    game[1].transact(user, f"journey-value-{user}-{next(COUNTER)}", NOW, run)
    return out[-1]


def entry(reply, name):
    return next(text for text in reply.lines if text.startswith(name + " ·"))


def test_page_previews_without_an_account(game, play):
    reply = play("journey", user="u9", now=NOW)
    assert reply.title == "山海行纪"
    assert "尚未结契" in reply.text()
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_page_lists_chapters_with_states_and_stories(game, play):
    play("adopt", "青鸾", now=NOW)
    total = len(game[0].content.journey)
    page = play("journey", now=NOW)
    assert page.title == "山海行纪 1/4"
    assert entry(page, "灵泉初醒") == "灵泉初醒 · 启灵 · 进行中（0/1）"
    assert entry(page, "灵泉寻踪") == "灵泉寻踪 · 启灵 · 未解锁"
    assert "青岚林的风声里" in page.text()
    assert page.lines[-1] == f"共 {total} 章，已完成 0 章，尚有 0 章可领取。"
    assert page.commands == ("灵宠行纪 2", "灵宠主线", "灵宠目标")
    assert page.inline_commands == ()
    assert play("journey", "3", now=NOW).title == "山海行纪 3/4"
    with pytest.raises(GameError, match="共 4 页"):
        play("journey", "5", now=NOW)


def test_first_chapter_waits_for_the_dungeon_win(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="本章尚未完成：通关青岚林（0/1）"):
        play("journey_claim", "灵泉初醒", now=NOW)
    play("challenge", "青岚林", now=NOW)
    page = play("journey", now=NOW)
    assert entry(page, "灵泉初醒") == "灵泉初醒 · 启灵 · 可领取"
    assert [link.command for link in page.inline_commands] == ["灵宠行纪领奖 灵泉初醒"]


def test_claim_grants_once_and_unlocks_the_next_chapter(game, play):
    play("adopt", "青鸾", now=NOW)
    play("challenge", "青岚林", now=NOW)
    before = stones(game), items(game, "spirit_food")
    reply = play("journey_claim", "灵泉初醒", now=NOW, op="journey-one")
    assert reply.title == "行纪奖励已领取"
    assert reply.lines[0].startswith("灵泉初醒 · 青岚林的风声里")
    assert (stones(game), items(game, "spirit_food")) == (before[0] + 120, before[1] + 2)
    assert reply.lines[-1] == "下一章「灵泉寻踪」已解锁。"
    assert entry(play("journey", now=NOW), "灵泉初醒") == "灵泉初醒 · 启灵 · 已完成"
    assert entry(play("journey", now=NOW), "灵泉寻踪") == "灵泉寻踪 · 启灵 · 进行中（0/1）"
    hub = next(text for text in play("objectives", now=NOW).lines if text.startswith("行纪："))
    assert hub == "行纪：暂无可领 · 已完成 1/16 章"


def test_locked_and_repeated_claims_are_refused(game, play):
    play("adopt", "青鸾", now=NOW)
    play("challenge", "青岚林", now=NOW)
    first = play("journey_claim", "灵泉初醒", now=NOW, op="journey-one")
    assert play("journey_claim", "灵泉初醒", now=NOW, op="journey-one").lines == first.lines
    with pytest.raises(GameError, match="已领取，不能重复领取"):
        play("journey_claim", "灵泉初醒", now=NOW)
    with pytest.raises(GameError, match="请先完成前置章节：灵泉寻踪"):
        play("journey_claim", "月影双行", now=NOW)


def test_every_task_kind_derives_its_progress(game, play):
    play("adopt", "青鸾", now=NOW)
    assert value(game, "u1", "journey_01") == 0
    play("challenge", "青岚林", now=NOW)
    assert value(game, "u1", "journey_01") == 1

    sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
        "VALUES ('u1','spring',?)", (NOW,))
    assert value(game, "u1", "journey_02") == 1

    sql(game[1], "UPDATE pets SET realm=3, layer=1")
    assert value(game, "u1", "journey_03") == 0
    play("challenge", "月影谷", now=NOW + 601)
    assert value(game, "u1", "journey_03") == 1
    play("challenge", "月影谷", now=NOW + 1202)
    assert value(game, "u1", "journey_03") == 2

    sql(game[1], "INSERT INTO player_resonance(user_id, resonance_id, activated_at) "
        "VALUES ('u1','wind_wings',?)", (NOW,))
    assert value(game, "u1", "journey_04") == 1

    sql(game[1], "INSERT INTO pets(user_id, species_id, name, energy_updated) "
        "VALUES ('u1','tielin','铁鳞二号',?)", (NOW,))
    assert value(game, "u1", "journey_08") == 1

    assert value(game, "u1", "journey_14") == 0
    sql(game[1], "UPDATE pets SET realm=6")
    assert value(game, "u1", "journey_14") == 1


def test_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾", now=NOW)
    play("challenge", "青岚林", now=NOW)
    reply = play("journey", now=NOW)
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for line in segment.data["keyboard"].content.rows
        for button in line.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()


def test_help_lists_both_entries(game, play):
    text = play("help", "秘境与关卡", now=NOW).text()
    assert "灵宠行纪" in text and "灵宠行纪领奖" in text


def edit_content(tmp_path, change):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "journey.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    change(entries)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return target


def test_broken_chain_is_rejected(tmp_path):
    target = edit_content(tmp_path, lambda entries: entries[1].update(previous_id=None))
    with pytest.raises(ValueError, match="exactly one first chapter"):
        Catalog.load(target)


def test_unreachable_target_is_rejected(tmp_path):
    def retarget(entries):
        entries[0]["task"] = {"kind": "clear_dungeon", "target": "tribulation_sky", "count": 1}
    target = edit_content(tmp_path, retarget)
    with pytest.raises(ValueError, match="unreachable dungeon"):
        Catalog.load(target)


def test_unknown_target_is_rejected(tmp_path):
    def retarget(entries):
        entries[0]["task"] = {"kind": "discover", "target": "no_such_encounter", "count": 1}
    target = edit_content(tmp_path, retarget)
    with pytest.raises(ValueError, match="unknown journey encounter"):
        Catalog.load(target)
