"""Focused contracts for team-arena matchmaking (灵宠组队匹配)."""

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql
from .team_support import NOW, USERS, create_players, create_team

U1_UID = "10000"
U2_UID = "10001"
U3_UID = "10002"
U4_UID = "10003"


def prepare_all(play, users):
    for user in users:
        play("team_ready", user=user)


def two_teams(play, *, ready=True):
    """Two 2-person teams: team A (users 0,1) and team B (users 2,3)."""
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    if ready:
        prepare_all(play, USERS[:2])
        prepare_all(play, USERS[2:4])


def set_rating(game, user, value):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, 'team_rating_', ?) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, value),
    )


def test_matchmaking_finds_the_other_team(game, play):
    two_teams(play)
    reply = play("team_arena_match", user=USERS[0], op="match-found")
    assert "组队论剑候选" in reply.title
    assert U3_UID in reply.text()
    assert any(link.command == f"灵宠组队论剑 {U3_UID}" for link in reply.inline_commands)


def test_matchmaking_excludes_own_team(game, play):
    two_teams(play)
    reply = play("team_arena_match", user=USERS[0], op="match-own")
    assert U1_UID not in reply.text()
    assert all(U1_UID not in link.command for link in reply.inline_commands)


def test_matchmaking_requires_captain(game, play):
    two_teams(play)
    with pytest.raises(GameError, match="只有队长"):
        play("team_arena_match", user=USERS[1], op="match-member")


def test_matchmaking_requires_full_preparation(game, play):
    two_teams(play, ready=False)
    with pytest.raises(GameError, match="全员准备"):
        play("team_arena_match", user=USERS[0], op="match-unready")


def test_matchmaking_hides_unready_or_undersized_opponents(game, play):
    create_players(play, 4)
    create_team(play, leader=0, members=(1,))
    create_team(play, leader=2, members=(3,))
    prepare_all(play, USERS[:2])
    # Opposing team is the right size but not prepared.
    reply = play("team_arena_match", user=USERS[0], op="match-opponent-unready")
    assert "暂无符合条件的候选队伍" in reply.text()
    assert reply.inline_commands == ()
    # Once ready it appears, proving the filter was the preparation gate.
    prepare_all(play, USERS[2:4])
    again = play("team_arena_match", user=USERS[0], op="match-opponent-ready")
    assert U3_UID in again.text()


def test_matchmaking_requires_two_member_team(game, play):
    create_players(play, 3)
    create_team(play, leader=0)
    with pytest.raises(GameError, match="至少两名"):
        play("team_arena_match", user=USERS[0], op="match-solo-team")


def test_matchmaking_requires_a_team(game, play):
    create_players(play, 2)
    with pytest.raises(GameError, match="还没有队伍"):
        play("team_arena_match", user=USERS[0], op="match-no-team")


def test_matchmaking_is_read_only(game, play):
    two_teams(play)
    before_battles = sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")
    before_rows = sql(game[1], "SELECT * FROM quest_progress ORDER BY user_id, quest_id")
    play("team_arena_match", user=USERS[0], op="match-readonly")
    play("team_arena_match", user=USERS[0], op="match-readonly")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records") == before_battles
    assert sql(game[1], "SELECT * FROM quest_progress ORDER BY user_id, quest_id") == before_rows


def test_matchmaking_rejects_bad_pages(game, play):
    two_teams(play)
    with pytest.raises(GameError, match="整数"):
        play("team_arena_match", "abc", user=USERS[0], op="match-bad")
    with pytest.raises(GameError, match="暂无候选队伍"):
        play("team_arena_match", "2", user=USERS[0], op="match-page-2")


def test_matchmaking_native_keeps_links_out_of_buttons(game, play):
    two_teams(play)
    reply = play("team_arena_match", user=USERS[0], op="match-native")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in reply.inline_commands}
    assert len(buttons) <= 4
    assert buttons & links == set()


def test_matchmaking_parse_contract():
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠组队匹配") == ("team_arena_match", "")
    assert handlers._parse("灵宠组队匹配 2") == ("team_arena_match", "2")


def test_matchmaking_help_entry():
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    entries = dict((row[0], row) for section in _HELP_SECTIONS.values() for row in section)
    assert entries["灵宠组队匹配 页码"][2].startswith("队长按积分与队伍规模")
