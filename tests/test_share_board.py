"""Share leaderboard: ranking, truncation, read-only page and wiring."""

from contextlib import closing

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import share_board
from nonebot_plugin_spirit_pet.gameplay.shares import READER_PREFIX

from .support import sql

NOW = 1_800_000_000


def account(game, play, user):
    play("adopt", "青鸾", user=user)


def add_readers(game, owner, count, prefix="r"):
    for index in range(count):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (owner, f"{READER_PREFIX}{prefix}{index}"),
        )


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def test_ranking_orders_by_distinct_readers_then_user_id(game, play):
    for user in ("u1", "u2", "u3"):
        account(game, play, user)
    add_readers(game, "u1", 3)
    add_readers(game, "u2", 1)
    add_readers(game, "u3", 1)
    rows = share_board.ranking(_ctx(game, "u1"))
    assert [row["user_id"] for row in rows] == ["u1", "u2", "u3"]
    assert [row["readers"] for row in rows] == [3, 1, 1]
    page = play("share_board", user="u1")
    assert page.title == "灵宠分享榜"
    assert page.lines[1:] == (
        "1. UID 10000 · 3 位读者", "2. UID 10001 · 1 位读者", "3. UID 10002 · 1 位读者",
    )


def test_ranking_ignores_other_progress_keys(game, play):
    account(game, play, "u1")
    add_readers(game, "u1", 2)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        ("u1", "share_read_reward_3"),
    )
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
        ("u1", "race_best_2026-11-02"),
    )
    assert share_board.ranking(_ctx(game, "u1"))[0]["readers"] == 2


def test_empty_board_is_honest(game, play):
    account(game, play, "u1")
    page = play("share_board")
    assert "还没有人分享过被阅读的战报。" in page.text()
    assert page.commands == ("灵宠分享", "灵宠分享奖励", "灵宠战报")


def test_unregistered_player_can_view_and_only_gets_adoption_link(game, play):
    page = play("share_board", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_top_ten_and_own_rank_outside_it(game, play):
    for index in range(1, 12):
        account(game, play, f"u{index}")
        add_readers(game, f"u{index}", 12 - index)
    page = play("share_board", user="u11")
    assert page.lines[1].endswith("· 11 位读者")
    assert len(page.lines) == 1 + 10 + 1
    assert "你的名次：第 11 名（共 11 位分享者）。" in page.text()
    assert "12 位读者" not in page.text()


def test_rank_shows_for_owner_inside_top_ten(game, play):
    account(game, play, "u1")
    add_readers(game, "u1", 2)
    page = play("share_board", user="u1")
    assert "第 11" not in page.text()
    assert "你还没有被阅读的分享" not in page.text()


def test_argument_rejection_writes_nothing(game, play):
    account(game, play, "u1")
    before = state(game[1])
    with pytest.raises(GameError, match="不接受参数"):
        play("share_board", "1")
    assert state(game[1]) == before


def test_board_is_read_only(game, play):
    account(game, play, "u1")
    add_readers(game, "u1", 3)
    before = state(game[1])
    play("share_board")
    play("share_board", user="u2")
    assert state(game[1]) == before


def test_help_parser_and_native_payload(game, play):
    account(game, play, "u1")
    assert _parse("灵宠分享榜") == ("share_board", "")
    assert "灵宠分享榜" in play("help", "对战与赛季").text()
    page = play("share_board")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons <= set(page.commands)
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in page.inline_commands}


def _ctx(game, user):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    conn = game[1].connect()
    return Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "read")
