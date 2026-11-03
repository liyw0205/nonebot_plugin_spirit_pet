"""灵宠分享: revocable, expiring share codes for a permanent battle report."""

import json
import re
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import shares
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema23, legacy_schema24

from .support import sql

NOW = 1_800_000_000
DAY = 86400
SHARE_RE = re.compile(rf"[{shares.ALPHABET}]{{{shares.CODE_LENGTH}}}")


def account(game, play, user, species="青鸾"):
    play("adopt", species, user=user)


def seed_report(game, owner="u1", *, side=0, title="试炼", played_at=NOW, pet="青鸾", foe="木灵"):
    """Insert one minimal report the owner participated in; returns its battle_id."""
    snapshot = json.dumps({
        "version": 2,
        "teams": [
            {"side": 0, "members": [{"pet_name": pet}]},
            {"side": 1, "members": [{"pet_name": foe}]},
        ],
    })
    log = json.dumps(["第一回合：青鸾出手", "第二回合：木灵倒下"])
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, title, winner_side, rounds,"
            " played_at, reply, snapshot, battle_log) VALUES (?, ?, 'pve', ?, 0, 3, ?, '{}', ?, ?)",
            (f"seed-{owner}-{title}-{played_at}", owner, title, played_at, snapshot, log),
        )
        battle_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, ?, 'participant')",
            (battle_id, owner, side),
        )
        conn.commit()
    return battle_id


def rows(game):
    return sql(game[1], "SELECT * FROM battle_shares ORDER BY share_id")


def code_of(reply):
    match = SHARE_RE.search(reply.text())
    assert match is not None, reply.text()
    return match.group(0)


def share(play, battle_id, user="u1", op=None, now=NOW):
    return play("shares", str(battle_id), user=user, op=op, now=now)


def snapshot(game):
    """Everything a share action must not touch."""
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT battle_id, winner_side, rounds FROM battle_records ORDER BY battle_id"),
        sql(game[1], "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
    )


# ---------------------------------------------------------------- content

def test_share_rule_is_wired_and_bounded(game):
    rules = game[0].content.rules.share
    assert 1 <= rules.daily_limit <= 20
    assert 1 <= rules.code_days <= 30
    assert 1 <= rules.list_page_size <= 10


def test_rule_model_enforces_bounds():
    from nonebot_plugin_spirit_pet.domain.content import ShareRule

    with pytest.raises(ValidationError):
        ShareRule.model_validate({"daily_limit": 0, "code_days": 7, "list_page_size": 5})
    with pytest.raises(ValidationError):
        ShareRule.model_validate({"daily_limit": 5, "code_days": 0, "list_page_size": 5})
    with pytest.raises(ValidationError):
        ShareRule.model_validate({"daily_limit": 5, "code_days": 7, "list_page_size": 0})


def test_minting_is_random_and_uses_the_documented_alphabet():
    codes = {shares.mint_code() for _ in range(200)}
    assert len(codes) == 200, "codes must not repeat"
    for code in codes:
        assert SHARE_RE.fullmatch(code)
    assert not set("0OI1") & {char for code in codes for char in code}


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("shares", user="ghost")
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT * FROM battle_shares") == []


def test_a_fresh_player_sees_an_empty_share_page(game, play):
    account(game, play, "u1")
    page = play("shares")
    assert "有效期内的分享 0 条" in page.text()
    assert page.inline_commands == ()


# ---------------------------------------------------------------- create

def test_create_writes_one_active_code(game, play):
    account(game, play, "u1")
    battle_id = seed_report(game)
    reply = share(play, battle_id)
    assert reply.title == "战报已分享"
    stored = rows(game)
    assert len(stored) == 1
    row = stored[0]
    assert row["battle_id"] == battle_id
    assert row["owner_id"] == "u1"
    assert row["state"] == "active"
    assert row["views"] == 0
    assert row["expires_at"] == NOW + 7 * DAY
    assert row["closed_at"] is None
    assert code_of(reply) == row["share_id"]


def test_create_refuses_a_report_the_player_did_not_fight(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    battle_id = seed_report(game, owner="u1")
    before = snapshot(game)
    for arg in (str(battle_id), "999999"):
        with pytest.raises(GameError, match="只能分享自己参与过的战报"):
            share(play, arg, user="u2")
    with pytest.raises(GameError, match="格式：灵宠分享"):
        share(play, "abc")
    assert play("shares", "", user="u2").title == "灵宠分享"   # the bare page is not a share
    assert snapshot(game) == before
    assert rows(game) == []


def test_create_refuses_a_defender_only_row_for_an_outsider(game, play):
    """A `defender` participant row still authorizes only that player."""
    account(game, play, "u1")
    account(game, play, "u2")
    snapshot_data = json.dumps({"teams": [{"side": 0, "members": [{"pet_name": "A"}]},
                                          {"side": 1, "members": [{"pet_name": "B"}]}]})
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, title, winner_side, rounds,"
            " played_at, reply, snapshot, battle_log) VALUES ('def','u2','spar','切磋',1,2,?,'{}',?,'[]')",
            (NOW, snapshot_data),
        )
        battle_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, 'u2', 1, 'defender')",
            (battle_id,),
        )
        conn.commit()
    with pytest.raises(GameError, match="只能分享自己参与过的战报"):
        share(play, battle_id, user="u1")
    assert share(play, battle_id, user="u2").title == "战报已分享"


def test_daily_limit_refuses_the_next_share_with_zero_writes(game, play):
    account(game, play, "u1")
    game[0].content = __import__("dataclasses").replace(
        game[0].content,
        rules=game[0].content.rules.model_copy(
            update={"share": game[0].content.rules.share.model_copy(update={"daily_limit": 2})},
        ),
    )
    battle_id = seed_report(game)
    share(play, battle_id)
    share(play, battle_id)
    before = rows(game)
    with pytest.raises(GameError, match="今日分享已达 2 次"):
        share(play, battle_id)
    assert rows(game) == before
    # tomorrow the allowance is back
    assert share(play, battle_id, now=NOW + DAY).title == "战报已分享"


# ---------------------------------------------------------------- view

def test_a_different_player_can_read_the_shared_report(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    battle_id = seed_report(game, pet="青鸾", foe="木灵")
    code = code_of(share(play, battle_id))

    reply = play("shares", f"查看 {code}", user="u2")
    assert "由 UID 10000 分享" in reply.text()
    assert code in reply.text()
    assert "以分享者视角" in reply.text()
    assert "青鸾" in reply.text() and "木灵" in reply.text()
    assert "第一回合：青鸾出手" in reply.text()
    assert "第二回合：木灵倒下" in reply.text()
    assert rows(game)[0]["views"] == 1


def test_the_replay_uses_the_stored_snapshot_not_live_content(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    battle_id = seed_report(game, title="旧标题")
    code = code_of(share(play, battle_id))
    # The owner renames their pet and the report title; the replay must not follow.
    sql(game[1], "UPDATE pets SET name='改名后' WHERE user_id='u1'")
    reply = play("shares", f"查看 {code}", user="u2")
    assert "旧标题" in reply.text()
    assert "改名后" not in reply.text()


def test_views_count_once_per_successful_read(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    for expected in (1, 2, 3):
        play("shares", f"查看 {code}", user="u2")
        assert rows(game)[0]["views"] == expected


def test_view_refuses_bad_codes_without_counting_a_read(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    before = rows(game)[0]["views"]
    for bad in ("AAAAAAAAAAAA", "abc", "ABC", "ABCDEFGHJKLMNOP"):
        with pytest.raises(GameError):
            play("shares", f"查看 {bad}", user="u2")
    assert rows(game)[0]["views"] == before
    assert rows(game)[0]["state"] == "active"


def test_an_expired_code_cannot_be_opened(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    late = NOW + 8 * DAY
    with pytest.raises(GameError, match="分享码无效或已失效"):
        play("shares", f"查看 {code}", user="u2", now=late)
    # A refusal writes nothing, so the row is closed by the next page read instead.
    page = play("shares", "我的", now=late)
    assert "已过期" in page.text()
    assert page.inline_commands == ()
    assert rows(game)[0]["state"] == "revoked"
    assert rows(game)[0]["views"] == 0


def test_resharing_after_expiry_mints_a_new_working_code(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    battle_id = seed_report(game)
    first = code_of(share(play, battle_id))
    late = NOW + 8 * DAY
    second = code_of(share(play, battle_id, now=late))
    assert second != first
    assert play("shares", f"查看 {second}", user="u2", now=late).title.startswith("战报 #")
    with pytest.raises(GameError, match="分享码无效或已失效"):
        play("shares", f"查看 {first}", user="u2", now=late)


# ---------------------------------------------------------------- revoke

def test_revoke_closes_the_code_for_everyone(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    assert play("shares", f"撤回 {code}").title == "分享已撤回"
    row = rows(game)[0]
    assert row["state"] == "revoked" and row["closed_at"] == NOW
    with pytest.raises(GameError, match="分享码无效或已失效"):
        play("shares", f"查看 {code}", user="u2")
    with pytest.raises(GameError, match="没有可撤回的分享"):
        play("shares", f"撤回 {code}")


def test_revoke_is_refused_for_a_non_owner(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    code = code_of(share(play, seed_report(game)))
    with pytest.raises(GameError, match="没有可撤回的分享"):
        play("shares", f"撤回 {code}", user="u2")
    assert rows(game)[0]["state"] == "active"


def test_revoke_refuses_an_unknown_code(game, play):
    account(game, play, "u1")
    with pytest.raises(GameError, match="没有可撤回的分享"):
        play("shares", "撤回 AAAAAAAAAAAA")
    with pytest.raises(GameError, match="分享码为"):
        play("shares", "撤回 nope")


# ---------------------------------------------------------------- pages

def test_my_shares_lists_state_and_only_offers_live_actions(game, play):
    account(game, play, "u1")
    battle_id = seed_report(game)
    code = code_of(share(play, battle_id))
    page = play("shares", "我的")
    assert code in page.text() and "已读 0 次" in page.text()
    assert [link.label for link in page.inline_commands] == ["查看", "撤回"]

    play("shares", f"撤回 {code}")
    page = play("shares", "我的")
    assert "已撤回" in page.text()
    assert page.inline_commands == ()
    assert page.commands == ("灵宠战报", "灵宠目标")


def test_my_shares_paginates(game, play):
    account(game, play, "u1")
    game[0].content = __import__("dataclasses").replace(
        game[0].content,
        rules=game[0].content.rules.model_copy(
            update={"share": game[0].content.rules.share.model_copy(update={"daily_limit": 10})},
        ),
    )
    for index in range(7):
        battle_id = seed_report(game, title=f"战斗{index}")
        share(play, battle_id)
    first = play("shares", "我的")
    assert "第 1/2 页" in first.text()
    assert set(first.commands) & {"灵宠分享 我的 2"}
    second = play("shares", "我的 2")
    assert "第 2/2 页" in second.text()
    for link in (*first.inline_commands, *second.inline_commands):
        assert _parse(link.command) is not None


def test_objectives_row_reports_shares(game, play):
    account(game, play, "u1")
    line = next(line for line in play("objectives").lines if line.startswith("分享："))
    assert line == "分享：有效 0 条 · 今日 0/5 次"
    share(play, seed_report(game))
    line = next(line for line in play("objectives").lines if line.startswith("分享："))
    assert line == "分享：有效 1 条 · 今日 1/5 次"


def test_the_battle_detail_page_offers_sharing(game, play):
    account(game, play, "u1")
    battle_id = seed_report(game)
    reply = play("battle_reports", f"查看 {battle_id}")
    assert f"灵宠分享 {battle_id}" in reply.commands
    # An outsider still cannot read the report through the normal path.
    account(game, play, "u2")
    with pytest.raises(GameError, match="不是该场战斗的参与者"):
        play("battle_reports", f"查看 {battle_id}", user="u2")


# ---------------------------------------------------------------- state

def test_state_survives_a_restart(game, play):
    account(game, play, "u1")
    code = code_of(share(play, seed_report(game)))
    restarted = Game(game[1], Config(), game[0].rng)
    reply = restarted.execute("u1", "shares", "我的", "restart", NOW)
    assert code in reply.text()


def test_replaying_one_operation_mints_one_share(game, play):
    account(game, play, "u1")
    battle_id = seed_report(game)
    first = share(play, battle_id, op="once")
    second = share(play, battle_id, op="once")
    assert first.text() == second.text()
    assert len(rows(game)) == 1


def test_sharing_moves_nothing_and_does_not_write_a_battle(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    battle_id = seed_report(game)
    before = snapshot(game)
    code = code_of(share(play, battle_id))
    play("shares", f"查看 {code}", user="u2")
    play("shares", f"撤回 {code}")
    assert snapshot(game) == before


# ---------------------------------------------------------------- surfaces

def test_help_and_parser_cover_shares(game, play):
    account(game, play, "u1")
    assert _parse("灵宠分享") == ("shares", "")
    assert _parse("灵宠分享 12") == ("shares", "12")
    assert _parse("灵宠分享 查看 ABCDEFGHJKLM") == ("shares", "查看 ABCDEFGHJKLM")
    assert _parse("灵宠分享 撤回 ABCDEFGHJKLM") == ("shares", "撤回 ABCDEFGHJKLM")
    assert _parse("灵宠分享 我的 2") == ("shares", "我的 2")
    assert _parse("灵宠分享之后聊天") is None

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows_help = {row[0] for row in _HELP_SECTIONS["对战与赛季"]}
    assert "灵宠分享 战报编号" in rows_help
    assert "灵宠分享 查看 分享码" in rows_help and "灵宠分享 撤回 分享码" in rows_help


def test_qq_payload_keeps_buttons_and_links_disjoint(game, play):
    account(game, play, "u1")
    code = code_of(share(play, seed_report(game)))
    page = play("shares", "我的")
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
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert f"查看（/灵宠分享 查看 {code}）" in _qq_segments(
        page, Config(spirit_pet_qq_mode="text"),
    )[0]


# ---------------------------------------------------------------- storage

def test_fresh_install_carries_the_share_table(game):
    connection = game[1].connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        )
    }
    assert {"battle_shares", "battle_share_owner", "battle_share_battle"} <= names
    connection.close()


def test_the_share_table_rejects_a_half_closed_row(game):
    account = game[1]
    with closing(account.connect()) as conn:
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('x', 0, NULL)")
        conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, title, winner_side, rounds,"
            " played_at, reply, snapshot, battle_log) VALUES ('t','x','pve','t',0,1,1,'{}','{}','[]')",
        )
        battle_id = conn.execute("SELECT MAX(battle_id) AS n FROM battle_records").fetchone()["n"]
        with pytest.raises(sqlite3.IntegrityError):  # revoked without closed_at
            conn.execute(
                "INSERT INTO battle_shares VALUES ('ABCDEFGHJK', ?, 'x', 1, 2, 'revoked', NULL, 0)",
                (battle_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):  # active with closed_at
            conn.execute(
                "INSERT INTO battle_shares VALUES ('ABCDEFGHJK', ?, 'x', 1, 2, 'active', 3, 0)",
                (battle_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):  # code too short
            conn.execute(
                "INSERT INTO battle_shares VALUES ('ABC', ?, 'x', 1, 2, 'active', NULL, 0)",
                (battle_id,),
            )
        conn.rollback()


def test_schema23_database_walks_the_whole_chain(tmp_path):
    """Guard the two fall-through fixes: a 23 database must reach 25 in one call."""
    path = tmp_path / "old23.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema23(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=23")
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('u9', 55, NULL)")
        conn.commit()
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"friend_links", "friend_requests", "battle_shares"} <= names
        assert conn.execute("SELECT stones FROM players WHERE user_id='u9'").fetchone()[0] == 55
    assert list(tmp_path.glob("*schema23-backup*"))


def test_schema24_database_gains_the_share_table(tmp_path):
    path = tmp_path / "old24.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema24(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=24")
        conn.execute("INSERT INTO players(user_id, stones, active_pet_id) VALUES ('u9', 77, NULL)")
        conn.commit()
    store = Store(path)
    store.initialize()
    with closing(store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"battle_shares", "battle_share_owner", "battle_share_battle"} <= names
        assert conn.execute("SELECT stones FROM players WHERE user_id='u9'").fetchone()[0] == 77
    assert list(tmp_path.glob("*schema24-backup*"))
