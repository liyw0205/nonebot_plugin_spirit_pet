import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql
from .team_support import UIDS, USERS, create_players

TEAM_HELP = "灵宠帮助 组队与派遣"


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


def prepare(game, play, size=2):
    """Register `size` players, create the leader's team, and seat the rest directly."""
    create_players(play, count=size)
    play("team_create", user=USERS[0])
    team_id = sql(game[1], "SELECT team_id FROM teams WHERE leader_id=?", (USERS[0],))[0]["team_id"]
    for user in USERS[1:size]:
        sql(game[1], "INSERT INTO team_members(user_id, team_id) VALUES (?, ?)", (user, team_id))
    return team_id


def ready_all(game, team_id):
    sql(
        game[1],
        "UPDATE team_members SET ready_pet_id=(SELECT active_pet_id FROM players "
        "WHERE players.user_id=team_members.user_id) WHERE team_id=?",
        (team_id,),
    )


def assert_distinct_bounded_actions(reply):
    assert len(reply.commands) <= 4, reply.title
    assert len(set(reply.commands)) == len(reply.commands), reply.title
    assert not {link.command for link in reply.inline_commands} & set(reply.commands), reply.title


def test_roster_links_each_other_member_card_on_its_own_row(game, play):
    prepare(game, play, size=5)
    roster = play("team_status", user=USERS[0])
    member_lines = [index for index, line in enumerate(roster.lines) if line.startswith("队员")]
    assert len(member_lines) == 4 and roster.lines[1].startswith("队长")
    links = list(roster.inline_commands)
    assert [(link.line, link.label, link.command) for link in links[:1]] == [(0, "组队指南", TEAM_HELP)]
    assert [(link.line, link.label) for link in links[1:]] == [
        (index, "查看名帖") for index in member_lines
    ]
    for link in links[1:]:
        uid = re.search(r"UID \d+", roster.lines[link.line]).group(0)
        assert link.command == f"灵宠队伍 {uid}"
    # Row cards leave the button set, so every member stays reachable under the cap.
    assert not any(command.startswith("灵宠队伍 ") for command in roster.commands)
    assert not any(link.line == 1 for link in links)
    assert_distinct_bounded_actions(roster)


def test_team_pages_keep_bounded_distinct_actions_without_duplicating_row_links(game, play):
    prepare(game, play, size=3)
    replies = [
        play("team_status", user=USERS[0]),
        play("team_status", user=USERS[1]),
        play("team_status", UIDS[1], user=USERS[0]),
        play("team_status", UIDS[0], user=USERS[1]),
        play("team_ready", user=USERS[1]),
        play("team_unready", user=USERS[1]),
    ]
    for reply in replies:
        assert_distinct_bounded_actions(reply)


def test_team_run_entry_appears_exactly_when_the_whole_team_is_ready(game, play):
    team_id = prepare(game, play, size=3)
    assert "灵宠组队挑战 上古灵殿" not in play("team_status", user=USERS[0]).commands
    with pytest.raises(GameError, match="全体成员准备"):
        play("team_challenge", "上古灵殿", user=USERS[0])
    ready_all(game, team_id)
    roster = play("team_status", user=USERS[0])
    assert "灵宠组队挑战 上古灵殿" in roster.commands
    assert "已准备" in roster.text()
    assert_distinct_bounded_actions(roster)
    assert play("team_challenge", "上古灵殿", user=USERS[0]).title.startswith("秘境")


def test_ready_entry_is_hidden_while_the_roster_pet_is_away(game, play):
    prepare(game, play, size=2)
    play("expedition_start", "采灵药", user=USERS[1])
    roster = play("team_status", user=USERS[1])
    assert "灵宠准备" not in roster.commands and "灵宠队务" in roster.commands
    with pytest.raises(GameError):
        play("team_ready", user=USERS[1])
    card = play("team_status", UIDS[1], user=USERS[1])
    assert "灵宠准备" not in card.commands
    assert_distinct_bounded_actions(roster)
    assert_distinct_bounded_actions(card)


def test_member_card_keeps_leader_actions_and_links_the_guide(game, play):
    prepare(game, play, size=3)
    card = play("team_status", UIDS[1], user=USERS[0])
    assert f"灵宠踢人 {UIDS[1]}" in card.commands
    assert f"灵宠转让 {UIDS[1]}" in card.commands
    assert [(link.line, link.label, link.command) for link in card.inline_commands] == [
        (1, "组队指南", TEAM_HELP)
    ]
    assert_distinct_bounded_actions(card)
    own = play("team_status", UIDS[1], user=USERS[1])
    assert "灵宠准备" in own.commands
    assert not any(command.startswith(("灵宠踢人", "灵宠转让")) for command in own.commands)
    other = play("team_status", UIDS[2], user=USERS[1])
    assert not any(command.startswith(("灵宠踢人", "灵宠转让")) for command in other.commands)
    guide = play("help", "组队与派遣")
    assert guide.title == "帮助 · 组队与派遣"
    assert any("灵宠邀请" in line for line in guide.lines)


def test_invite_and_request_flow_replies_point_at_the_team_guide(game, play):
    create_players(play, count=5)
    replies = [
        play("team_create", user=USERS[0]),
        play("team_join", UIDS[0], user=USERS[1]),
        play("team_invite", UIDS[2], user=USERS[0]),
        play("team_accept", UIDS[1], user=USERS[0]),
        play("team_reject", UIDS[0], user=USERS[2]),
        play("team_join", UIDS[0], user=USERS[3]),
        play("team_withdraw", UIDS[0], user=USERS[3]),
        play("team_ready", user=USERS[1]),
        play("team_unready", user=USERS[1]),
        play("team_requests", user=USERS[0]),
        play("team_requests", user=USERS[4]),
    ]
    for reply in replies:
        assert TEAM_HELP in reply.commands, reply.title
        assert_distinct_bounded_actions(reply)


def test_roster_native_payload_links_cards_and_keeps_page_buttons(game, play):
    prepare(game, play, size=3)
    roster = play("team_status", user=USERS[0])
    _, message = _qq_segments(roster, Config(spirit_pet_qq_mode="native"))
    buttons = {button.action.data.removeprefix("/") for button in keyboard_buttons(message)}
    assert buttons == set(roster.commands)
    linked = {command for _, command in markdown_links(message)}
    assert linked == {f"/{link.command}" for link in roster.inline_commands}
    assert not linked & buttons
