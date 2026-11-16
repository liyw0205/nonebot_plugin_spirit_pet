import asyncio
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.adapters import handlers

from .support import sql
from .test_commands import onebot_event


def _links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def _buttons(message):
    return [
        button.action.data
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def _distinct_roster(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000")
    play("summon", "3")
    pets = sql(game[1], "SELECT pet_id FROM pets ORDER BY pet_id")
    for row, species in zip(pets, ("qingluan", "xuanhu", "baize", "jiaolong")):
        sql(game[1], "UPDATE pets SET species_id=? WHERE pet_id=?", (species, row["pet_id"]))
    ids = [row["pet_id"] for row in pets]
    play("lineup", " ".join(str(pet_id) for pet_id in ids[:3]))
    return ids


def test_pet_list_links_non_lead_to_switch_without_dropping_the_roster(game, play):
    ids = _distinct_roster(game, play)

    listing = play("pet_list")
    link = next(link for link in listing.inline_commands if link.command == f"灵宠切换 {ids[3]}")
    assert link.label == "切换领队"
    assert f"编号 {ids[3]}" in listing.lines[link.line]

    switched = play("switch", str(ids[3]))
    assert "阵容共 3 只" in switched.text()
    assert [row["pet_id"] for row in sql(
        game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot",
    )] == [ids[3], ids[1], ids[2]]


def test_lineup_page_links_each_member_to_read_only_preparation(game, play):
    ids = _distinct_roster(game, play)
    page = play("lineup", "")

    assert [link.command for link in page.inline_commands] == [
        f"灵宠整备 {pet_id}" for pet_id in ids[:3]
    ]
    assert [link.line for link in page.inline_commands] == [0, 1, 2]
    before = sql(game[1], "SELECT pet_id, slot FROM active_pet_slots ORDER BY slot")
    prep = play("pet_prep", str(ids[1]))
    assert "整备只读" in prep.text()
    assert sql(game[1], "SELECT pet_id, slot FROM active_pet_slots ORDER BY slot") == before


def test_identity_links_account_state_without_duplicate_qq_actions(game, play):
    play("adopt", "青鸾")
    info = play("identity")
    assert [link.command for link in info.inline_commands] == ["灵宠列表", "灵宠出战"]
    assert info.commands == ("灵宠列表", "灵宠背包", "灵宠帮助 身份与收集")

    _, message = _qq_segments(info, Config(spirit_pet_qq_mode="native"))
    linked = {command for _, command in _links(message)}
    buttons = set(_buttons(message))
    assert linked == {"/灵宠列表", "/灵宠出战"}
    assert buttons == {"/灵宠背包", "/灵宠帮助 身份与收集"}
    assert not linked & buttons


def test_onebot_identity_keeps_row_actions_readable_and_no_qq_protocol(game, monkeypatch):
    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 1), "!灵宠领养 青鸾")
        await handlers._run(bot, onebot_event("!我的信息", 2), "!我的信息")

    asyncio.run(run())
    text = bot.send.call_args.args[1]
    assert "查看灵宠名册（!灵宠列表）" in text
    assert "查看出战阵容（!灵宠出战）" in text
    assert "mqqapi://" not in text
    assert sql(store, "SELECT COUNT(*) AS count FROM players WHERE user_id='12345'") == [{"count": 1}]


def test_identity_without_active_roster_guides_back_to_the_list(game, play):
    play("adopt", "青鸾")
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")

    info = play("identity")
    assert info.inline_commands[-1].command == "灵宠列表"
    assert "出战伙伴：0 只" in info.text()
    assert all(link.command != "灵宠出战" for link in info.inline_commands)
