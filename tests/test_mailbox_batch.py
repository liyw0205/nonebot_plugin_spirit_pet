"""Batch claiming from the mailbox."""

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000
DAY = 86_400


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def seed(game, kind="stones", *, recipient="u1", sender="u2", created=NOW, state="active"):
    stones, item_id, quantity = (30, None, 0) if kind == "stones" else (0, "forge_ore", 2)
    closed = claimed = created + 1 if state == "claimed" else None
    sql(
        game[1],
        "INSERT INTO mail_messages(sender_id, recipient_id, kind, stones, item_id, quantity, "
        "body, created_at, expires_at, state, closed_at, claimed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, '批量', ?, ?, ?, ?, ?)",
        (sender, recipient, kind, stones, item_id, quantity, created,
         created + DAY, state, closed, claimed),
    )


def state(store):
    return {
        "players": sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        "inventory": sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        "mail": sql(store, "SELECT message_id, state, stones, item_id, quantity FROM mail_messages ORDER BY 1"),
    }


def test_claim_all_pays_every_active_mail_once(game, play):
    account(game, play)
    account(game, play, "u2")
    before = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    seed(game, "stones")
    seed(game, "item")
    page = play("mail", "一键领取", now=NOW)
    assert page.title == "信件已领取"
    assert "已领取 2 封" in page.text()
    assert "灵石 +30" in page.text()
    assert "物品 2 件" in page.text()
    rows = sql(game[1], "SELECT state, claimed_at FROM mail_messages ORDER BY message_id")
    assert [row["state"] for row in rows] == ["claimed", "claimed"]
    assert all(row["claimed_at"] == NOW for row in rows)
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before + 30
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")[0][
        "quantity"
    ] == 2


def test_empty_and_repeated_claim_do_not_write(game, play):
    account(game, play)
    account(game, play, "u2")
    before = state(game[1])
    page = play("mail", "一键领取", now=NOW)
    assert "没有可领取" in page.text()
    assert state(game[1]) == before
    seed(game)
    play("mail", "一键领取", now=NOW)
    before = state(game[1])
    page = play("mail", "一键领取", now=NOW)
    assert "没有可领取" in page.text()
    assert state(game[1]) == before


def test_expired_mail_returns_to_sender_and_is_not_claimed(game, play):
    account(game, play)
    account(game, play, "u2")
    seed(game, "item", created=NOW - 2 * DAY)
    sql(game[1], "UPDATE mail_messages SET expires_at=?", (NOW - DAY,))
    page = play("mail", "一键领取", now=NOW)
    assert "本次已将 1 封" in page.text()
    row = sql(game[1], "SELECT state FROM mail_messages")[0]
    assert row["state"] == "returned"
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u2' AND item_id='forge_ore'")[0][
        "quantity"
    ] == 2
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'") == []


def test_argument_and_unregistered_are_rejected_without_writes(game, play):
    account(game, play)
    before = state(game[1])
    with pytest.raises(GameError, match="格式"):
        play("mail", "一键领取 1", now=NOW)
    assert state(game[1]) == before
    page = play("mail", "一键领取", user="ghost", now=NOW)
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == [{"user_id": "u1"}]


def test_page_help_parser_and_native_payload(game, play):
    account(game, play)
    account(game, play, "u2")
    seed(game)
    page = play("mail", now=NOW)
    assert any(link.command == "灵宠信箱 一键领取" for link in page.inline_commands)
    assert _parse("灵宠信箱 一键领取") == ("mail", "一键领取")
    assert "灵宠信箱 一键领取" in play("help", "秘境与关卡", now=NOW).text()
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


def test_page_is_read_only_when_nothing_expired(game, play):
    account(game, play)
    account(game, play, "u2")
    seed(game)
    before = state(game[1])
    play("mail", now=NOW)
    assert state(game[1]) == before
