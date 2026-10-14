import re
from urllib.parse import parse_qs, urlparse

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config


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


def register(play, user, uid):
    reply = play("adopt", user=user)
    assert f"UID：{uid}" in reply.text()


def seed_inbox(game, play, count):
    """Register a leader plus `count` candidates who applied to the leader's team."""
    game[0].config.spirit_pet_team_request_limit = max(50, count + 1)
    register(play, "leader", "10000")
    play("team_create", user="leader")
    for index in range(count):
        user = f"member-{index}"
        register(play, user, str(10001 + index))
        play("team_join", "UID 10000", user=user)


def row_uid(line):
    return re.search(r"UID \d+", line).group(0)


def test_full_page_links_each_row_and_keeps_only_pagination(game, play):
    seed_inbox(game, play, 9)
    listing = play("team_requests", user="leader")
    assert listing.title == "待处理队务 1/3"
    assert len(listing.lines) == 4
    assert [(link.line, link.label) for link in listing.inline_commands] == [
        (index, "查看详情") for index in range(4)
    ]
    for link in listing.inline_commands:
        assert link.command == f"灵宠队务 {row_uid(listing.lines[link.line])}"
    # Row details leave the button set; a full page keeps only next-page navigation.
    assert listing.commands == ("灵宠队务 分页 2",)
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert button_commands == {"灵宠队务 分页 2"}
    assert markdown_links(message) == [
        ("查看详情", f"/{link.command}") for link in listing.inline_commands
    ]


def test_second_page_links_its_rows_and_keeps_both_pagination_buttons(game, play):
    seed_inbox(game, play, 9)
    listing = play("team_requests", "分页 2", user="leader")
    assert listing.title == "待处理队务 2/3"
    assert len(listing.inline_commands) == len(listing.lines) == 4
    for link in listing.inline_commands:
        assert link.command == f"灵宠队务 {row_uid(listing.lines[link.line])}"
    assert listing.commands == ("灵宠队务 分页 1", "灵宠队务 分页 3")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    button_commands = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert button_commands == {"灵宠队务 分页 1", "灵宠队务 分页 3"}
    linked = {command for _, command in markdown_links(message)}
    assert linked == {f"/{link.command}" for link in listing.inline_commands}
    assert not linked & button_commands


def test_empty_inbox_keeps_its_fallback_entry_and_no_row_links(game, play):
    seed_inbox(game, play, 0)
    listing = play("team_requests", user="leader")
    assert listing.title == "待处理队务 1/1"
    assert listing.inline_commands == ()
    assert listing.commands == ("灵宠队伍",)
    register(play, "solo", "10001")
    solo = play("team_requests", user="solo")
    assert solo.inline_commands == ()
    assert solo.commands == ("灵宠组队",)


def test_detail_reply_keeps_direction_specific_actions(game, play):
    seed_inbox(game, play, 1)
    leader_detail = play("team_requests", "UID 10001", user="leader")
    assert leader_detail.title == "队务详情"
    assert "灵宠队伍同意 UID 10001" in leader_detail.commands
    assert "灵宠队伍拒绝 UID 10001" in leader_detail.commands
    assert not leader_detail.inline_commands
    candidate_detail = play("team_requests", "UID 10000", user="member-0")
    assert "灵宠队伍撤回 UID 10000" in candidate_detail.commands
    assert not candidate_detail.inline_commands


def test_degraded_text_keeps_readable_row_command_without_mqqapi(game, play):
    seed_inbox(game, play, 9)
    listing = play("team_requests", user="leader")
    plain, message = _qq_segments(listing, Config())
    for link in listing.inline_commands:
        assert f"查看详情（/{link.command}）" in plain
    assert "mqqapi://" not in plain
    assert not any("mqqapi://" in str(segment) for segment in message)
