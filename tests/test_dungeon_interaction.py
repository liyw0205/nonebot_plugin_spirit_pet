import re
from urllib.parse import parse_qs, urlparse

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

from .test_pve_stages import account


def markdown_links(message):
    segment = message["markdown"][0].data["markdown"]
    markdown = segment.content if hasattr(segment, "content") else segment["content"]
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def keyboard_buttons(message):
    return [
        button
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def ordered_dungeons(game):
    content = game[0].content
    return sorted(content.dungeons.values(), key=lambda dungeon: (
        next(index for index, realm in enumerate(content.realms) if realm.id == dungeon.min_realm),
        dungeon.team, dungeon.id,
    ))


def test_every_listed_dungeon_links_its_own_detail_row(game, play):
    account(game, play, "u1")
    listing = play("dungeons")
    selected = ordered_dungeons(game)[:5]
    assert [(link.line, link.label, link.command) for link in listing.inline_commands] == [
        (index, "查看详情", f"灵宠秘境 {dungeon.name}")
        for index, dungeon in enumerate(selected)
    ]
    for link, dungeon in zip(listing.inline_commands, selected):
        assert link.line < len(listing.lines) and dungeon.name in listing.lines[link.line]
    # Row details leave the button set; only next-page navigation remains.
    assert listing.commands == ("灵宠秘境 2",)
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert button_commands == {"灵宠秘境 2"}
    assert markdown_links(message) == [
        ("查看详情", f"/灵宠秘境 {dungeon.name}") for dungeon in selected
    ]


def test_second_page_links_its_own_rows_and_keeps_pagination(game, play):
    account(game, play, "u1")
    listing = play("dungeons", "2")
    selected = ordered_dungeons(game)[5:10]
    assert len(listing.inline_commands) == len(selected)
    assert all(link.label == "查看详情" for link in listing.inline_commands)
    assert [link.command for link in listing.inline_commands] == [
        f"灵宠秘境 {dungeon.name}" for dungeon in selected
    ]
    assert listing.commands == ("灵宠秘境 1", "灵宠秘境 3")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert button_commands == {"灵宠秘境 1", "灵宠秘境 3"}
    linked = {command for _, command in markdown_links(message)}
    assert linked == {f"/灵宠秘境 {dungeon.name}" for dungeon in selected}
    assert not linked & button_commands


def test_detail_reply_still_offers_its_run_entry(game, play):
    account(game, play, "u1")
    dungeon = next(item for item in ordered_dungeons(game) if not item.team)
    detail = play("dungeons", dungeon.name)
    assert detail.title == dungeon.name
    assert detail.commands[0] == f"灵宠挑战 {dungeon.name}"
    assert not detail.inline_commands


def test_degraded_text_keeps_readable_detail_without_mqqapi(game, play):
    account(game, play, "u1")
    listing = play("dungeons")
    selected = ordered_dungeons(game)[:5]
    plain, message = _qq_segments(listing, Config())
    for dungeon in selected:
        assert f"灵宠秘境 {dungeon.name}" in plain
        assert f"查看详情（/灵宠秘境 {dungeon.name}）" in plain
    assert "mqqapi://" not in plain
    assert not any("mqqapi://" in str(segment) for segment in message)
