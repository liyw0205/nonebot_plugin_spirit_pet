"""Gear sockets: one gem per pet slot, consumed on set, returned on removal."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import loadout, sockets
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql

NOW = 1_800_000_000


def ctx_of(game, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, NOW, "read")


def owned(game, item_id, user="u1"):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id=? AND item_id=?", (user, item_id))
    return rows[0]["quantity"] if rows else 0


def gem_of(game, name):
    return next(entry for entry in game[0].content.gems.values() if entry.name == name)


def ready(game, play):
    """Adopt, then put one piece of gear in every slot of the active pet."""
    play("adopt", "青鸾")
    ctx = ctx_of(game)
    pet = ctx.pet()
    for slot, item_id in (("weapon", "wind_feather"), ("armor", None), ("charm", None)):
        if item_id is None:
            continue
        rows = sql(game[1], "SELECT item_id FROM equipment WHERE pet_id=?", (pet.pet_id,))
        if rows:
            continue
        ctx.repo.conn.execute(
            "INSERT INTO equipment(pet_id, slot, item_id, enhancement) VALUES (?, ?, ?, 0)",
            (pet.pet_id, slot, item_id),
        )
    for entry in game[0].content.gems.values():
        ctx.repo.add_item("u1", entry.item_id, 2)
    return pet


def test_content_declares_four_gems_on_distinct_stats(game):
    rows = list(game[0].content.gems.values())
    assert len(rows) == 4
    assert len({row.stat for row in rows}) == 4
    for row in rows:
        assert 0.01 <= row.rate <= 0.25
        assert game[0].content.items[row.item_id].kind == "material"


def test_page_without_a_pet_is_read_only(game, play):
    page = play("socket", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_slots_gear_and_gems(game, play):
    ready(game, play)
    page = play("socket")
    assert "兵刃" in page.text() and "护甲" in page.text() and "灵饰" in page.text()
    assert "未镶嵌" in page.text()
    assert any(link.command.startswith("灵宠镶嵌 兵刃 ") for link in page.inline_commands)


def test_socketing_consumes_one_gem_and_raises_the_stat(game, play):
    pet = ready(game, play)
    target = gem_of(game, "赤炎石")
    before = loadout.combatant(ctx_of(game)).stats.attack
    before_gems = owned(game, target.item_id)
    reply = play("socket", "兵刃 赤炎石", op="set-flame")
    assert reply.title == "镶嵌完成"
    assert owned(game, target.item_id) == before_gems - 1
    after = loadout.combatant(ctx_of(game)).stats.attack
    assert after > before
    assert sockets.socketed(ctx_of(game), pet.pet_id, "weapon").id == target.id


def test_socket_uses_the_documented_rate(game, play):
    pet = ready(game, play)
    target = gem_of(game, "赤炎石")
    plain = loadout.combatant(ctx_of(game)).stats.attack
    play("socket", "兵刃 赤炎石", op="rate")
    assert sockets.rates(ctx_of(game), pet.pet_id) == {"attack": target.rate}
    boosted = loadout.combatant(ctx_of(game)).stats.attack
    assert boosted >= int(plain * (1 + target.rate))


def test_empty_slot_is_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="尚未装备"):
        play("socket", "护甲 赤炎石")
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'socket_%'") == []


def test_occupied_slot_must_be_cleared_first(game, play):
    ready(game, play)
    play("socket", "兵刃 赤炎石", op="first")
    with pytest.raises(GameError, match="已有宝石"):
        play("socket", "兵刃 风灵石", op="second")


def test_gem_must_be_owned(game, play):
    pet = ready(game, play)
    ctx = ctx_of(game)
    for entry in game[0].content.gems.values():
        ctx.repo.consume_item("u1", entry.item_id, owned(game, entry.item_id))
    with pytest.raises(GameError, match="背包里没有"):
        play("socket", "兵刃 赤炎石")
    assert sockets.socketed(ctx_of(game), pet.pet_id, "weapon") is None


def test_unknown_slot_and_gem_are_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="未知槽位"):
        play("socket", "头盔 赤炎石")
    with pytest.raises(GameError, match="未找到该内容"):
        play("socket", "兵刃 不存在的宝石")
    with pytest.raises(GameError, match="格式"):
        play("socket", "兵刃")


def test_removing_returns_the_gem_and_clears_the_socket(game, play):
    pet = ready(game, play)
    target = gem_of(game, "赤炎石")
    play("socket", "兵刃 赤炎石", op="set")
    after_set = owned(game, target.item_id)
    reply = play("socket", "卸下 兵刃", op="unset")
    assert reply.title == "已卸下宝石"
    assert owned(game, target.item_id) == after_set + 1
    assert sockets.socketed(ctx_of(game), pet.pet_id, "weapon") is None


def test_removing_an_empty_socket_is_refused(game, play):
    ready(game, play)
    with pytest.raises(GameError, match="没有宝石"):
        play("socket", "卸下 兵刃")


def test_socket_survives_a_gear_swap_in_the_same_slot(game, play):
    pet = ready(game, play)
    play("socket", "兵刃 赤炎石", op="swap")
    ctx_of(game).repo.conn.execute(
        "UPDATE equipment SET item_id='fire_fang' WHERE pet_id=? AND slot='weapon'", (pet.pet_id,)
    )
    assert sockets.socketed(ctx_of(game), pet.pet_id, "weapon") is not None


def test_socket_survives_a_restart(game, play):
    pet = ready(game, play)
    play("socket", "兵刃 玄岩壁", op="persist")
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'socket_%'")
    assert len(rows) == 1 and "defense" not in rows[0]["quest_id"]
    assert sockets.socketed(ctx_of(game), pet.pet_id, "weapon").name == "玄岩壁"


def test_replaying_a_socket_never_consumes_a_second_gem(game, play):
    ready(game, play)
    target = gem_of(game, "赤炎石")
    first = play("socket", "兵刃 赤炎石", op="replay")
    count = owned(game, target.item_id)
    again = play("socket", "兵刃 赤炎石", op="replay")
    assert again.text() == first.text()
    assert owned(game, target.item_id) == count
    # A genuinely new request against the now-occupied slot is refused instead of charging again.
    with pytest.raises(GameError, match="已有宝石"):
        play("socket", "兵刃 赤炎石", op="replay-2")
    assert owned(game, target.item_id) == count


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "镶嵌：0/3" in play("objectives").text()
    play("socket", "兵刃 赤炎石", op="obj")
    assert "镶嵌：1/3" in play("objectives").text()
    assert "灵宠镶嵌" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠镶嵌") == ("socket", "")
    assert handlers._parse("灵宠镶嵌 兵刃 赤炎石") == ("socket", "兵刃 赤炎石")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("socket")
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
