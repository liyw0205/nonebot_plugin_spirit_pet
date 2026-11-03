"""灵宠好友: the request handshake, the normalized friend list, and the widened edge."""

import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import friends
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema22, legacy_schema23

from .support import player_uid, sql

NOW = 1_800_000_000
DAY = 86400


def account(game, play, user, species="青鸾"):
    play("adopt", species, user=user)


def set_stones(game, value, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (value, user))


def two(game, play):
    """Two adopted players; returns their public UIDs."""
    account(game, play, "u1")
    account(game, play, "u2")
    return player_uid(game[1], "u1"), player_uid(game[1], "u2")


def links(game):
    return sql(game[1], "SELECT * FROM friend_links ORDER BY user_low, user_high")


def requests(game):
    return sql(game[1], "SELECT * FROM friend_requests ORDER BY from_id, to_id")


def befriend(game, play, first="u1", second="u2"):
    """Full handshake: first requests, second agrees. Returns the second UID."""
    uid_first = player_uid(game[1], first)
    uid_second = player_uid(game[1], second)
    play("friends", f"添加 {uid_second}", user=first)
    play("friends", f"同意 {uid_first}", user=second)
    return uid_second


def empty_snapshot(game):
    """Everything a friend action must not touch."""
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT * FROM battle_records"),
        sql(game[1], "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
    )


# ---------------------------------------------------------------- content

def test_friend_rule_is_wired_and_bounded(game):
    rules = game[0].content.rules.friend
    assert rules.max_friends >= 2
    assert 1 <= rules.request_hours <= 72


def test_rule_model_enforces_bounds():
    from nonebot_plugin_spirit_pet.domain.content import FriendRule

    with pytest.raises(ValidationError):
        FriendRule.model_validate({"max_friends": 0, "request_hours": 24})
    with pytest.raises(ValidationError):
        FriendRule.model_validate({"max_friends": 50, "request_hours": 0})
    with pytest.raises(ValidationError):
        FriendRule.model_validate({"max_friends": 500, "request_hours": 24})


def test_catalog_rejects_a_roster_that_cannot_hold_two(game):
    catalog = game[0].content
    bare = type(catalog)(**{**catalog.__dict__, "rules": catalog.rules.model_copy(
        update={"friend": catalog.rules.friend.model_copy(update={"max_friends": 1})},
    )})
    with pytest.raises(ValueError, match="friend roster must hold at least two friends"):
        Catalog._validate_friend(bare)


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("friends", user="ghost")
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert links(game) == [] and requests(game) == []


def test_a_fresh_player_sees_an_empty_roster_and_no_links(game, play):
    account(game, play, "u1")
    page = play("friends")
    assert "好友 0/50 位" in page.text()
    assert "暂时还没有好友" in page.text()
    assert page.inline_commands == ()


# ---------------------------------------------------------------- request

def test_add_writes_one_request_and_no_link(game, play):
    _, uid2 = two(game, play)
    reply = play("friends", f"添加 {uid2}")
    assert reply.title == "结交申请已发出"
    assert links(game) == []
    rows = requests(game)
    assert len(rows) == 1
    assert (rows[0]["from_id"], rows[0]["to_id"]) == ("u1", "u2")
    assert rows[0]["expires_at"] == NOW + 24 * 3600

    mine = play("friends", "申请")
    assert "等待 UID 10001 回应" in mine.text()
    assert mine.inline_commands[0].command == "灵宠好友 撤回 10001"

    theirs = play("friends", "申请", user="u2")
    assert "UID 10000 想与你结交" in theirs.text()
    assert [link.label for link in theirs.inline_commands] == ["同意", "拒绝"]


def test_accept_creates_one_normalized_link_for_both(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    reply = play("friends", "同意 10000", user="u2")
    assert reply.title == "已是好友"
    rows = links(game)
    assert len(rows) == 1
    assert (rows[0]["user_low"], rows[0]["user_high"]) == ("u1", "u2")
    assert rows[0]["created_at"] == NOW
    assert requests(game) == []
    assert "UID 10001" in play("friends").text()
    assert "UID 10000" in play("friends", user="u2").text()


def test_accept_normalizes_regardless_of_who_asked(game, play):
    """u2 asks, u1 accepts: the stored row is still (u1, u2)."""
    _, uid2 = two(game, play)
    play("friends", f"添加 10000", user="u2")
    play("friends", f"同意 {uid2}")
    assert (links(game)[0]["user_low"], links(game)[0]["user_high"]) == ("u1", "u2")


def test_reject_and_withdraw_delete_the_request_without_a_link(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    assert play("friends", "撤回 10001").title == "申请已撤回"
    assert requests(game) == [] and links(game) == []

    play("friends", f"添加 {uid2}")
    assert play("friends", "拒绝 10000", user="u2").title == "已拒绝结交"
    assert requests(game) == [] and links(game) == []


def test_remove_drops_the_link_for_either_side(game, play):
    _, uid2 = two(game, play)
    befriend(game, play)
    assert play("friends", "解除 10000", user="u2").title == "已解除好友"
    assert links(game) == []
    assert "暂时还没有好友" in play("friends").text()
    assert "暂时还没有好友" in play("friends", user="u2").text()


# ---------------------------------------------------------------- refusals

def test_add_refuses_self_unknown_and_extra_arguments(game, play):
    two(game, play)
    with pytest.raises(GameError, match="不能把自己加为好友"):
        play("friends", "添加 10000")
    with pytest.raises(GameError, match="未找到该 UID"):
        play("friends", "添加 999999")
    with pytest.raises(GameError, match="请只填写一个 UID"):
        play("friends", "添加 10000 10001")
    with pytest.raises(GameError, match="请填写对方的 UID"):
        play("friends", "添加")
    assert requests(game) == [] and links(game) == []


def test_add_refuses_an_existing_friend_and_a_pending_request(game, play):
    _, uid2 = two(game, play)
    befriend(game, play)
    with pytest.raises(GameError, match="已经是你的好友"):
        play("friends", f"添加 {uid2}")

    account(game, play, "u3")
    uid3 = player_uid(game[1], "u3")
    play("friends", f"添加 {uid3}")           # u1 -> u3 pending
    with pytest.raises(GameError, match="已有一条等待对方回应"):
        play("friends", f"添加 {uid3}")       # the same direction again
    with pytest.raises(GameError, match="已经向你发起结交"):
        play("friends", "添加 10000", user="u3")  # the reverse direction
    assert len(links(game)) == 1 and len(requests(game)) == 1


def test_refusals_leave_the_database_untouched(game, play):
    _, uid2 = two(game, play)
    before = empty_snapshot(game)
    for action, arg, user in (
        ("friends", "添加 999999", "u1"),
        ("friends", "添加 10000", "u1"),
        ("friends", "同意 10001", "u1"),
        ("friends", "撤回 10001", "u2"),
        ("friends", "拒绝 10001", "u1"),
        ("friends", "解除 10001", "u1"),
    ):
        with pytest.raises(GameError):
            play(action, arg, user=user)
    assert empty_snapshot(game) == before
    assert requests(game) == [] and links(game) == []


def test_accept_is_refused_for_the_wrong_party_and_a_missing_request(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    with pytest.raises(GameError, match="没有来自该道友的结交申请"):
        play("friends", "同意 10001", user="u1")     # the initiator cannot accept
    with pytest.raises(GameError, match="没有来自该道友的结交申请"):
        play("friends", "拒绝 10001", user="u1")     # nor reject
    account(game, play, "u3")
    with pytest.raises(GameError, match="没有来自该道友的结交申请"):
        play("friends", "同意 10000", user="u3")     # no such request exists
    with pytest.raises(GameError, match="没有发给该道友的待回应申请"):
        play("friends", f"撤回 {player_uid(game[1], 'u3')}", user="u1")  # nothing sent there
    assert links(game) == [] and len(requests(game)) == 1


def test_remove_refuses_a_stranger(game, play):
    two(game, play)
    with pytest.raises(GameError, match="你们还不是好友"):
        play("friends", "解除 10001")
    assert links(game) == []


def test_roster_cap_refuses_a_fresh_request(game, play):
    game[0].content = replace(
        game[0].content,
        rules=game[0].content.rules.model_copy(
            update={"friend": game[0].content.rules.friend.model_copy(update={"max_friends": 2})},
        ),
    )
    account(game, play, "u1")
    uid1 = player_uid(game[1], "u1")
    peers = []
    for index in range(3):
        user = f"p{index}"
        account(game, play, user)
        peers.append((user, player_uid(game[1], user)))
    for user, uid in peers[:2]:
        play("friends", f"添加 {uid}")
        play("friends", f"同意 {uid1}", user=user)
    assert len(links(game)) == 2
    with pytest.raises(GameError, match="好友已达 2 位上限"):
        play("friends", f"添加 {peers[2][1]}")
    assert requests(game) == []


def test_target_cap_refuses_before_the_request_exists(game, play):
    game[0].content = replace(
        game[0].content,
        rules=game[0].content.rules.model_copy(
            update={"friend": game[0].content.rules.friend.model_copy(update={"max_friends": 1})},
        ),
    )
    two(game, play)
    account(game, play, "u3")
    uid1, uid2, uid3 = (player_uid(game[1], u) for u in ("u1", "u2", "u3"))
    # u2 fills up on u3, so u1 must not be able to befriend u2.
    play("friends", f"添加 {uid3}", user="u2")
    play("friends", f"同意 {uid2}", user="u3")
    assert len(links(game)) == 1
    with pytest.raises(GameError, match="的好友已满"):
        play("friends", f"添加 {uid2}")
    assert requests(game) == []


def test_malformed_subcommands_are_refused(game, play):
    two(game, play)
    with pytest.raises(GameError, match="格式：灵宠好友"):
        play("friends", "好友")
    with pytest.raises(GameError, match="请只填写一个 UID"):
        play("friends", "添加 10000 10001 10002")
    with pytest.raises(GameError, match="未找到该 UID"):
        play("friends", "同意 不是uid")


# ---------------------------------------------------------------- expiry

def test_expiry_is_lazy_and_frees_the_pair(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    late = NOW + 25 * 3600
    assert "没有待处理的结交申请" in play("friends", "申请", now=late).text()
    assert requests(game) == []
    assert play("friends", f"添加 {uid2}", now=late).title == "结交申请已发出"


def test_an_expired_request_cannot_be_accepted(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    with pytest.raises(GameError, match="没有来自该道友的结交申请"):
        play("friends", "同意 10000", user="u2", now=NOW + 25 * 3600)
    assert links(game) == []


# ---------------------------------------------------------------- the edge

def test_an_accepted_friend_unlocks_gift_mail_and_foster(game, play):
    """Two players with no shared battle or team can now exchange things."""
    _, uid2 = two(game, play)
    set_stones(game, 3000)
    with pytest.raises(GameError, match="可用 灵宠好友 结交"):
        play("gift", f"{uid2} 灵石 10")
    befriend(game, play)
    assert play("gift", f"{uid2} 灵石 10").title == "灵宠赠送"
    assert play("mail", f"邮寄 {uid2} 灵石 100 拿去用").title == "信件已寄出"
    assert player_uid(game[1], "u2") is not None


def test_the_derived_battle_edge_still_works(game, play):
    """An old save with arena history must keep working without any handshake."""
    _, uid2 = two(game, play)
    set_stones(game, 3000)
    sql(
        game[1],
        "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, winner_side,"
        " rounds, played_at, reply, snapshot, battle_log) VALUES ('legacy', 'u1', 'spar', '', '切磋',"
        " 0, 3, ?, '{}', '{}', '[]')",
        (NOW,),
    )
    battle_id = sql(game[1], "SELECT MAX(battle_id) AS n FROM battle_records")[0]["n"]
    for side, owner in ((0, "u1"), (1, "u2")):
        sql(
            game[1],
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, ?, 'participant')",
            (battle_id, owner, side),
        )
    assert links(game) == []
    assert play("gift", f"{uid2} 灵石 10").title == "灵宠赠送"


def test_breaking_the_friendship_closes_the_edge_again(game, play):
    _, uid2 = two(game, play)
    set_stones(game, 3000)
    befriend(game, play)
    assert play("gift", f"{uid2} 灵石 10").title == "灵宠赠送"
    play("friends", f"解除 {uid2}")
    with pytest.raises(GameError, match="可用 灵宠好友 结交"):
        play("gift", f"{uid2} 灵石 10")


def test_linked_is_symmetric_and_false_for_self(game, play):
    two(game, play)
    befriend(game, play)
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    context = Context(Repository(game[1].connect()), game[0].content, Config(), None, "u1", NOW, "probe")
    assert friends.linked(context, "u1", "u2") is True
    assert friends.linked(context, "u2", "u1") is True
    assert friends.linked(context, "u1", "u1") is False
    assert friends.linked(context, "u1", "u3") is False


# ---------------------------------------------------------------- state

def test_friend_state_survives_a_restart(game, play):
    _, uid2 = two(game, play)
    befriend(game, play)
    store = game[1]
    restarted = Game(store, Config(), game[0].rng)
    reply = restarted.execute("u1", "friends", "", "restart", NOW)
    assert "UID 10001" in reply.text()
    assert "好友 1/50 位" in reply.text()


def test_replaying_one_operation_settles_once(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}", op="once")
    play("friends", f"添加 {uid2}", op="once")
    assert len(requests(game)) == 1
    play("friends", "同意 10000", user="u2", op="accept")
    play("friends", "同意 10000", user="u2", op="accept")
    assert len(links(game)) == 1


def test_objectives_row_reports_the_friend_list(game, play):
    two(game, play)
    line = next(line for line in play("objectives").lines if line.startswith("好友："))
    assert line == "好友：0/50 位 · 待处理 0 条"
    play("friends", "添加 10001")
    line = next(line for line in play("objectives", user="u2").lines if line.startswith("好友："))
    assert line == "好友：0/50 位 · 待处理 1 条"


def test_friend_actions_do_not_move_resources_or_write_battles(game, play):
    _, uid2 = two(game, play)
    before = empty_snapshot(game)
    play("friends", f"添加 {uid2}")
    play("friends", "同意 10000", user="u2")
    play("friends", f"解除 {uid2}")
    after = empty_snapshot(game)
    assert after == before


# ---------------------------------------------------------------- surfaces

def test_help_and_parser_cover_the_friend_list(game, play):
    two(game, play)
    assert _parse("灵宠好友") == ("friends", "")
    assert _parse("灵宠好友 申请") == ("friends", "申请")
    assert _parse("灵宠好友 添加 UID 10001") == ("friends", "添加 UID 10001")
    assert _parse("灵宠好友 同意 10001") == ("friends", "同意 10001")
    assert _parse("灵宠好友 解除 10001") == ("friends", "解除 10001")
    assert _parse("灵宠好友之后聊天") is None
    assert _parse("灵宠好友 申请 2") == ("friends", "申请 2")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["秘境与关卡"]}
    assert "灵宠好友" in rows and "灵宠好友 申请" in rows
    assert "灵宠好友 添加 UID" in rows and "灵宠好友 解除 UID" in rows


def test_rendered_rows_only_offer_executable_links(game, play):
    for index in range(5):
        account(game, play, f"q{index}")
    account(game, play, "u1")
    for index in range(5):
        play("friends", f"添加 {player_uid(game[1], f'q{index}')}")
    page = play("friends", "申请")
    assert page.inline_commands
    for link in page.inline_commands:
        assert link.line < len(page.lines)
        assert _parse(link.command) is not None
    page2 = play("friends", "申请 2")
    assert page2.inline_commands
    for link in page2.inline_commands:
        assert _parse(link.command) is not None


def test_qq_payload_keeps_buttons_and_links_disjoint(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    page = play("friends", "申请")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in __import__("re").findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_onebot_text_spells_the_friend_commands(game, play):
    _, uid2 = two(game, play)
    play("friends", f"添加 {uid2}")
    page = play("friends", "申请", user="u2")
    rendered = _qq_segments(page, Config(spirit_pet_qq_mode="text"))[0]
    assert "（/灵宠好友 同意 10000）" in rendered
    assert "（/灵宠好友 拒绝 10000）" in rendered


# ---------------------------------------------------------------- storage

def test_fresh_install_carries_the_friend_tables(game):
    connection = game[1].connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        )
    }
    assert {"friend_links", "friend_requests", "friend_link_low", "friend_link_high",
            "friend_request_inbox", "friend_request_outbox"} <= names
    connection.close()


def test_the_link_table_rejects_an_unordered_or_duplicated_pair(game):
    with closing(game[1].connect()) as conn:
        for user in ("a", "b"):
            conn.execute(
                "INSERT INTO players(user_id, stones, active_pet_id) VALUES (?, 0, NULL)", (user,),
            )
        conn.execute("INSERT INTO friend_links VALUES ('a', 'b', 1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO friend_links VALUES ('a', 'b', 2)")   # duplicate pair
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO friend_links VALUES ('b', 'a', 2)")   # wrong order
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO friend_links VALUES ('a', 'a', 2)")   # self link
        conn.rollback()


def test_three_link_columns_are_all_counted_towards_the_cap(game, play):
    """A player who is always the high id still counts every friend."""
    game[0].content = replace(
        game[0].content,
        rules=game[0].content.rules.model_copy(
            update={"friend": game[0].content.rules.friend.model_copy(update={"max_friends": 2})},
        ),
    )
    account(game, play, "u1")
    uid1 = player_uid(game[1], "u1")
    peers = []
    for index in range(3):
        account(game, play, f"z{index}")
        peers.append(player_uid(game[1], f"z{index}"))
    for index in range(2):
        play("friends", f"添加 {peers[index]}")
        play("friends", "同意 10000", user=f"z{index}")
    assert len(links(game)) == 2
    with pytest.raises(GameError, match="好友已达 2 位上限"):
        play("friends", f"添加 {peers[2]}")


# ---------------------------------------------------------------- migration

def test_schema22_database_migrates_and_keeps_its_rows(tmp_path):
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    path = tmp_path / "old22.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema22(schema))
        conn.execute("PRAGMA user_version=22")
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('u9', 42, NULL)")
        conn.commit()
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"friend_links", "friend_requests", "mail_messages"} <= names
        assert conn.execute("SELECT stones FROM players WHERE user_id='u9'").fetchone()[0] == 42
    assert list(tmp_path.glob("*schema22-backup*")), "the pre-migration database must be kept"


def test_schema23_database_migrates_and_keeps_its_rows(tmp_path):
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    path = tmp_path / "old23.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema23(schema))
        conn.execute("PRAGMA user_version=23")
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('u9', 77, NULL)")
        conn.commit()
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT stones FROM players WHERE user_id='u9'").fetchone()[0] == 77
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"friend_links", "friend_requests"} <= names
    assert list(tmp_path.glob("*schema23-backup*"))
