"""灵宠信箱: escrowed cross-player mail, claim, recall, expiry and migration."""

import json
import shutil
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import mailbox
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_PATH, SCHEMA_VERSION, Store
from nonebot_plugin_spirit_pet.storage.registration import legacy_schema22

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


def account(game, play, user="u1", species="青鸾"):
    play("adopt", species, user=user)


def grant(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id)"
            " DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def set_stones(game, value, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (value, user))


def friend(game, play, first="u1", second="u2"):
    """Both players adopted, and a shared battle edge exists between them."""
    account(game, play, first)
    account(game, play, second)
    uid = sql(game[1], "SELECT id FROM player_identity WHERE user_id=?", (second,))[0]["id"] + 9999
    sql(
        game[1],
        "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title, winner_side,"
        " rounds, played_at, reply, snapshot, battle_log) VALUES (?, ?, 'spar', '', '切磋', 0, 3, ?, '{}', '{}', '[]')",
        (f"edge-{first}-{second}", first, NOW),
    )
    battle_id = sql(game[1], "SELECT MAX(battle_id) AS n FROM battle_records")[0]["n"]
    for side, owner in ((0, first), (1, second)):
        sql(
            game[1],
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) VALUES (?, ?, ?, 'participant')",
            (battle_id, owner, side),
        )
    return uid


def messages(game):
    return sql(game[1], "SELECT * FROM mail_messages ORDER BY message_id")


def snapshot(game):
    """Domain tables only; the operation cache moves on every call by design."""
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT message_id, state, stones, item_id, quantity FROM mail_messages ORDER BY message_id"),
    )


def send(play, uid, item, amount, body="拿去用", user="u1", op=None, now=NOW):
    return play("mail", f"邮寄 {uid} {item} {amount} {body}", user=user, op=op, now=now)


# ---------------------------------------------------------------- content

@pytest.fixture
def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit_rules(directory, change):
    path = directory / "rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_mail_rule_is_wired_and_bounded(game):
    rules = game[0].content.rules.mail
    assert rules.kinds == ["material", "consumable"]
    assert rules.days >= 1 and rules.daily_limit >= 1
    assert rules.max_stones >= 1 and rules.max_items >= 1 and rules.inbox_capacity >= 1


def test_rule_model_rejects_duplicate_kinds():
    from nonebot_plugin_spirit_pet.domain.content import MailRule

    with pytest.raises(ValidationError, match="kinds must be unique"):
        MailRule.model_validate({
            "days": 7, "daily_limit": 5, "max_stones": 100, "max_items": 5,
            "inbox_capacity": 5, "kinds": ["material", "material"],
        })


def test_a_kind_with_no_item_is_rejected(game):
    """Run the real validator against a catalog whose consumables were removed."""
    catalog = game[0].content
    bare = type(catalog)(**{
        **catalog.__dict__,
        "items": {key: item for key, item in catalog.items.items() if item.kind != "consumable"},
    })
    with pytest.raises(ValueError, match="mail has no consumable item to send"):
        Catalog._validate_mail(bare)


def test_an_unknown_kind_is_rejected_by_the_rule_model():
    from nonebot_plugin_spirit_pet.domain.content import MailRule

    with pytest.raises(ValidationError, match="literal_error"):
        MailRule.model_validate({
            "days": 7, "daily_limit": 5, "max_stones": 100, "max_items": 5,
            "inbox_capacity": 5, "kinds": ["equipment"],
        })


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("mail", user="ghost")
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT * FROM mail_messages") == []
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []


# ---------------------------------------------------------------- send

def test_sending_escrows_the_stack_and_shows_in_the_inbox(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 4})
    reply = send(play, uid, "锻灵矿", 3)
    assert reply.title == "信件已寄出"
    rows = messages(game)
    assert len(rows) == 1
    row = rows[0]
    assert (row["sender_id"], row["recipient_id"], row["kind"]) == ("u1", "u2", "item")
    assert (row["item_id"], row["quantity"], row["state"]) == ("forge_ore", 3, "active")
    assert row["expires_at"] == NOW + 7 * DAY
    assert "留言：拿去用" in reply.text()
    assert items(game[1])["forge_ore"] == 1

    inbox = play("mail", user="u2")
    assert "锻灵矿 ×3" in inbox.text()
    assert "留言：拿去用" in inbox.text()
    assert inbox.inline_commands[0].command == f"灵宠信箱 领取 {row['message_id']}"


def test_sending_stones_moves_them_out_of_the_sender(game, play):
    uid = friend(game, play)
    set_stones(game, 3000)
    reply = send(play, uid, "灵石", 800)
    assert "灵石 800" in reply.text()
    assert player(game[1])["stones"] == 2200
    row = messages(game)[0]
    assert (row["kind"], row["stones"], row["item_id"], row["quantity"]) == ("stones", 800, None, 0)
    before = player(game[1], "u2")["stones"]
    play("mail", f"领取 {row['message_id']}", user="u2")
    assert player(game[1], "u2")["stones"] == before + 800


def test_claim_moves_the_attachment_once(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    message_id = messages(game)[0]["message_id"]
    before = items(game[1], "u2").get("forge_ore", 0)
    reply = play("mail", f"领取 {message_id}", user="u2")
    assert reply.title == "信件已领取"
    assert items(game[1], "u2")["forge_ore"] == before + 3
    assert messages(game)[0]["state"] == "claimed"
    assert messages(game)[0]["claimed_at"] == NOW
    assert play("mail", user="u2").inline_commands == ()
    with pytest.raises(GameError, match="没有可领取的信件"):
        play("mail", f"领取 {message_id}", user="u2")


def test_recall_returns_the_stack_while_unclaimed(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    message_id = messages(game)[0]["message_id"]
    outbox = play("mail", "寄件")
    assert f"#{message_id}" in outbox.text()
    reply = play("mail", f"收回 {message_id}")
    assert reply.title == "信件已收回"
    assert items(game[1])["forge_ore"] == 3
    assert messages(game)[0]["state"] == "recalled"
    assert play("mail", user="u2").inline_commands == ()


def test_expiry_returns_the_stack_lazily_and_once(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    message_id = messages(game)[0]["message_id"]
    later = NOW + 8 * DAY
    inbox = play("mail", user="u2", now=later)
    assert inbox.inline_commands == ()
    assert messages(game)[0]["state"] == "returned"
    assert items(game[1])["forge_ore"] == 3
    # A second sweep must not pay the same row again.
    again = play("mail", now=later + DAY)
    assert "暂时没有未领取的信件" in again.text()
    assert messages(game)[0]["state"] == "returned"
    assert items(game[1])["forge_ore"] == 3
    with pytest.raises(GameError, match="没有可领取的信件"):
        play("mail", f"领取 {message_id}", user="u2", now=later)
    with pytest.raises(GameError, match="没有可收回的信件"):
        play("mail", f"收回 {message_id}", now=later)


def test_daily_limit_counts_only_today(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 40})
    limit = game[0].content.rules.mail.daily_limit
    for index in range(limit):
        send(play, uid, "锻灵矿", 1, op=f"mail-{index}")
    with pytest.raises(GameError, match="今日寄信已达"):
        send(play, uid, "锻灵矿", 1, op="mail-over")
    assert len(messages(game)) == limit
    next_day = send(play, uid, "锻灵矿", 1, now=NOW + DAY, op="mail-next-day")
    assert next_day.title == "信件已寄出"
    assert len(messages(game)) == limit + 1


def test_inbox_capacity_refuses_without_escrowing(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 40})
    capacity = game[0].content.rules.mail.inbox_capacity
    # Seed the inbox directly: the daily send limit is lower than the inbox cap, so
    # the fills must also be dated before today (they are still unclaimed at NOW).
    for index in range(capacity):
        sql(
            game[1],
            "INSERT INTO mail_messages(sender_id, recipient_id, kind, stones, item_id, quantity,"
            " body, created_at, expires_at, state) VALUES ('u1', 'u2', 'item', 0, 'forge_ore', 1,"
            " 'x', ?, ?, 'active')",
            (NOW - 2 * DAY, NOW + DAY + index),
        )
    before = snapshot(game)
    with pytest.raises(GameError, match="对方信箱已满"):
        send(play, uid, "锻灵矿", 1, op="cap-over")
    assert snapshot(game) == before


@pytest.mark.parametrize(
    "argument, message",
    [
        ("邮寄 10001 锻灵矿", "格式：灵宠信箱 邮寄"),
        ("邮寄 10001 锻灵矿 2", "格式：灵宠信箱 邮寄"),
        ("邮寄 10001 不存在的东西 2 你好", "未找到该物品"),
        ("邮寄 10001 破境丹 2 你好", "只能寄送材料与消耗品"),
        ("邮寄 10001 风刃术诀 2 你好", "只能寄送材料与消耗品"),
    ],
)
def test_send_refusals_write_nothing(game, play, argument, message):
    friend(game, play)
    set_stones(game, 5000)
    grant(game, {"forge_ore": 5, "breakthrough_pill": 1})
    before = snapshot(game)
    with pytest.raises(GameError, match=message):
        play("mail", argument)
    assert snapshot(game) == before


def test_a_body_longer_than_sixty_characters_is_refused(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 2})
    before = snapshot(game)
    with pytest.raises(GameError, match="留言最多 60 个字"):
        send(play, uid, "锻灵矿", 1, body="字" * 61)
    assert snapshot(game) == before


def test_send_refuses_self_strangers_and_missing_funds(game, play):
    account(game, play)
    set_stones(game, 5000)
    grant(game, {"forge_ore": 5})
    own_uid = sql(game[1], "SELECT id FROM player_identity WHERE user_id='u1'")[0]["id"] + 9999
    account(game, play, "u3")
    stranger_uid = sql(game[1], "SELECT id FROM player_identity WHERE user_id='u3'")[0]["id"] + 9999
    before = snapshot(game)
    for argument, message in (
        (f"邮寄 {own_uid} 锻灵矿 1 你好", "请填写其他玩家的 UID"),
        (f"邮寄 {stranger_uid} 锻灵矿 1 你好", "只能寄给论剑或同队出现过的玩家"),
        ("邮寄 999999 锻灵矿 1 你好", "请填写其他玩家的 UID"),
        (f"邮寄 {own_uid} 锻灵矿 9 你好", "请填写其他玩家的 UID"),
    ):
        with pytest.raises(GameError, match=message):
            play("mail", argument)
    assert snapshot(game) == before


def test_send_refuses_over_caps_and_short_resources(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 5})
    set_stones(game, 50)
    rules = game[0].content.rules.mail
    before = snapshot(game)
    with pytest.raises(GameError, match="数量须为"):
        send(play, uid, "锻灵矿", rules.max_items + 1)
    with pytest.raises(GameError, match="道具数量不足"):
        send(play, uid, "锻灵矿", rules.max_items)
    with pytest.raises(GameError, match="数量须为"):
        send(play, uid, "灵石", rules.max_stones + 1)
    with pytest.raises(GameError, match="灵石不足"):
        send(play, uid, "灵石", 100)
    assert snapshot(game) == before


# ---------------------------------------------------------------- lifecycle

def test_replaying_one_operation_escrows_once(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 5})
    first = send(play, uid, "锻灵矿", 2, op="mail-once")
    second = send(play, uid, "锻灵矿", 2, op="mail-once")
    assert first.text() == second.text()
    assert len(messages(game)) == 1
    assert items(game[1])["forge_ore"] == 3


def test_claim_and_recall_are_guarded_by_the_recipient_and_sender(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    message_id = messages(game)[0]["message_id"]
    sender_before = snapshot(game)
    for argument, message in (
        (f"领取 {message_id}", "没有可领取的信件"),
        (f"领取 {message_id + 99}", "没有可领取的信件"),
        ("领取 abc", "格式：灵宠信箱 领取"),
    ):
        with pytest.raises(GameError, match=message):
            play("mail", argument)
    assert snapshot(game) == sender_before
    # The sender may not claim their own mail, and the recipient may not recall it.
    with pytest.raises(GameError, match="没有可领取的信件"):
        play("mail", f"领取 {message_id}", user="u1")
    with pytest.raises(GameError, match="没有可收回的信件"):
        play("mail", f"收回 {message_id}", user="u2")
    with pytest.raises(GameError, match="没有可收回的信件"):
        play("mail", f"收回 {message_id + 99}")
    with pytest.raises(GameError, match="格式：灵宠信箱 收回"):
        play("mail", "收回 abc")
    assert snapshot(game) == sender_before


def test_recall_after_claim_is_refused(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    message_id = messages(game)[0]["message_id"]
    play("mail", f"领取 {message_id}", user="u2")
    before = snapshot(game)
    with pytest.raises(GameError, match="没有可收回的信件"):
        play("mail", f"收回 {message_id}")
    assert snapshot(game) == before


def test_state_survives_a_restart(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    message_id = messages(game)[0]["message_id"]
    restarted = Game(game[1], Config())
    reply = restarted.execute("u2", "mail", f"领取 {message_id}", "restart-claim", NOW)
    assert reply.title == "信件已领取"
    assert items(game[1], "u2").get("forge_ore", 0) == 3


def test_mail_does_not_touch_battles_counters_or_progress(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    battles = sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"]
    send(play, uid, "锻灵矿", 3)
    play("mail", "寄件")
    play("mail", user="u2")
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"] == battles
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1'") == []


# ---------------------------------------------------------------- surfaces

def test_objectives_row_reports_the_mailbox(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    sender_hub = play("objectives")
    assert "信箱：待领 0 封 · 寄出未领 1 封" in sender_hub.lines
    recipient_hub = play("objectives", user="u2")
    assert "信箱：待领 1 封 · 寄出未领 0 封" in recipient_hub.lines


def test_outbox_lists_only_unclaimed_mail(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 4})
    send(play, uid, "锻灵矿", 1, op="outbox-1")
    send(play, uid, "锻灵矿", 1, op="outbox-2")
    first = messages(game)[0]["message_id"]
    play("mail", f"领取 {first}", user="u2")
    outbox = play("mail", "寄件")
    assert f"#{first}" not in outbox.text()
    assert f"#{messages(game)[1]['message_id']}" in outbox.text()
    assert outbox.inline_commands[0].command == f"灵宠信箱 收回 {messages(game)[1]['message_id']}"


def test_help_and_parser_cover_the_mailbox(game, play):
    assert _parse("灵宠信箱") == ("mail", "")
    assert _parse("灵宠信箱 寄件") == ("mail", "寄件")
    help_page = play("help", "秘境与关卡")
    assert "灵宠信箱" in help_page.text()


def test_qq_payload_keeps_buttons_and_links_disjoint(game, play):
    uid = friend(game, play)
    grant(game, {"forge_ore": 3})
    send(play, uid, "锻灵矿", 3)
    page = play("mail", user="u2")
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
    assert f"（灵宠信箱 领取 {messages(game)[0]['message_id']}）" in page.text()


# ---------------------------------------------------------------- migration

def test_fresh_install_carries_the_mailbox_tables(game):
    connection = game[1].connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {
        row["name"] for row in sql(
            game[1], "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "mail_messages" in names
    indexes = {
        row["name"] for row in sql(game[1], "SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert {"mail_inbox", "mail_outbox"}.issubset(indexes)
    connection.close()


def test_schema22_database_migrates_and_keeps_its_rows(tmp_path):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(legacy_schema22(SCHEMA_PATH.read_text(encoding="utf-8")))
        conn.execute("PRAGMA user_version=22")
        conn.execute("INSERT INTO players(user_id, stones, registered_at) VALUES ('keeper', 321, 1)")
        conn.commit()
    Store(path).initialize()
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT stones FROM players WHERE user_id='keeper'").fetchone()[0] == 321
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='mail_messages'"
        ).fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(tmp_path.glob("legacy.db.schema22-backup-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 22
