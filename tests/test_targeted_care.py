import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items, _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import pet, player, sql
from .test_commands import onebot_event, qq_event


NOW = 1_800_000_000


def add_pet(store, *, name="玄狐副宠", energy=50, user_id="u1"):
    sql(
        store,
        "INSERT INTO pets(user_id, species_id, name, energy, energy_updated) "
        "VALUES (?, 'xuanhu', ?, ?, ?)",
        (user_id, name, energy, NOW),
    )
    return sql(store, "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user_id,))[0]["pet_id"]


def snapshot(store):
    return {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "players", "pets", "inventory", "active_pet_slots", "quest_progress", "team_members",
    )}


def create_ready_team(play, store):
    active_id = pet(store)["pet_id"]
    play("team_create", now=NOW)
    play("team_ready", now=NOW)
    assert sql(store, "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]
    return active_id


def test_numbered_feed_only_changes_selected_pet_and_keeps_team_ready(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = create_ready_team(play, game[1])
    target_id = add_pet(game[1])

    reply = play("feed", str(target_id), now=NOW)

    assert "灵粮 -1，精力 +20，修为 +10，亲密 +5" in reply.text()
    assert sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE pet_id=?", (active_id,)) == [
        {"energy": 100, "exp": 0, "affinity": 0},
    ]
    assert sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"energy": 70, "exp": 10, "affinity": 5},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='spirit_food'") == [
        {"quantity": 2},
    ]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]


def test_numbered_feed_repeat_keeps_original_target_and_stops_when_food_runs_out(game, play):
    play("adopt", "青鸾")
    active_id = create_ready_team(play, game[1])
    target_id = add_pet(game[1])
    page = play("pet_prep", str(target_id))
    feed = next(link.command for link in page.inline_commands if link.command == f"灵宠喂养 {target_id}")
    reply = play(*handlers._parse(feed), op="feed-backup")
    assert feed in reply.commands
    assert "灵宠喂养" not in reply.commands
    assert "我的灵宠" not in reply.commands
    assert any(link.command == f"灵宠整备 {target_id}" for link in reply.inline_commands)
    assert f"玄狐副宠（编号 {target_id}）" in reply.text()
    assert "精力 70/100" in reply.text() and "修为 10" in reply.text() and "亲密 5/100" in reply.text()
    assert play(*handlers._parse(feed), op="feed-backup") == reply
    sql(game[1], "DELETE FROM active_pet_slots WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    for index in range(2):
        command = next(command for command in reply.commands if command == feed)
        reply = play(*handlers._parse(command), op=f"continue-feeding-{index}")
    assert not any(command.startswith("灵宠喂养") for command in reply.commands)
    assert sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE pet_id=?", (active_id,)) == [
        {"energy": 100, "exp": 0, "affinity": 0},
    ]
    assert sql(game[1], "SELECT energy, exp, affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"energy": 100, "exp": 30, "affinity": 15},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='spirit_food'") == [
        {"quantity": 0},
    ]
    assert player(game[1])["active_pet_id"] is None


@pytest.mark.parametrize("argument", ["", "1"])
def test_feed_unregistered_users_get_adoption_without_writes(game, play, argument):
    before = snapshot(game[1])
    with pytest.raises(GameError) as rejected:
        play("feed", argument)
    assert rejected.value.reply is not None
    assert rejected.value.reply.inline_commands[0].command == "灵宠领养 "
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("argument", ["0", "-1", "１２", "wrong", "1 2", "9" * 5000])
def test_feed_rejects_invalid_targets_without_cost(game, play, argument):
    play("adopt", "青鸾")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="有效编号"):
        play("feed", argument)
    assert snapshot(game[1]) == before


def test_feed_without_active_pet_recovers_or_accepts_an_explicit_target(game, play):
    play("adopt", "青鸾")
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    before = snapshot(game[1])
    with pytest.raises(GameError) as rejected:
        play("feed")
    assert rejected.value.reply is not None and rejected.value.reply.title == "选择伙伴"
    assert [link.command for link in rejected.value.reply.inline_commands] == ["灵宠列表", "灵宠出战 "]
    assert snapshot(game[1]) == before
    reply = play("feed", "1")
    assert "灵宠喂养 1" in reply.commands
    assert player(game[1])["active_pet_id"] is None


@pytest.mark.parametrize("blocked,reason", [("sealed", "已封存"), ("trip", "当前不能行动"),
                                            ("stock", "数量不足"), ("foreign", "没有属于你的")])
def test_stale_feed_actions_recheck_target_and_resources_atomically(game, play, blocked, reason):
    play("adopt", "青鸾")
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1])
    first = play("feed", str(target_id))
    command = next(command for command in first.commands if command == f"灵宠喂养 {target_id}")
    if blocked == "sealed":
        play("pet_archive", str(target_id))
    elif blocked == "trip":
        play("switch", str(target_id))
        play("expedition_start", "采灵药")
        play("switch", str(active_id))
    elif blocked == "foreign":
        play("adopt", "玄狐", user="other")
        sql(game[1], "UPDATE pets SET user_id='other' WHERE pet_id=?", (target_id,))
    else:
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id='spirit_food'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match=reason):
        play(*handlers._parse(command))
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("prefix", ["", "/", "!"])
@pytest.mark.parametrize("keyboard", [True, False])
def test_numbered_feed_qq_keeps_targeted_actions_unique_in_native_and_fallback(game, play, prefix, keyboard):
    play("adopt", "青鸾")
    target_id = add_pet(game[1])
    reply = play("feed", str(target_id))
    config = Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix)
    plain, native = _qq_segments(reply, config, allow_keyboard=keyboard)
    markdown = native["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    buttons = [button for segment in native["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons]
    payloads = [button.action.data for button in buttons]
    expected_links = {prefix + link.command for link in reply.inline_commands}
    expected_buttons = {prefix + command for _, command in _action_items(reply)}
    if keyboard:
        assert set(links) == expected_links
        assert set(payloads) == expected_buttons
    else:
        assert set(links) == expected_links | expected_buttons
        assert not payloads
    assert not set(links) & set(payloads)
    assert len(links + payloads) == len(set(links + payloads)) <= 4
    if keyboard:
        repeat = next(button for button in buttons if button.action.data == prefix + f"灵宠喂养 {target_id}")
        assert repeat.render_data.label == f"喂养编号 {target_id}"
        assert repeat.action.enter is True
    assert prefix + f"灵宠喂养 {target_id}" in plain
    assert "mqqapi://" not in plain


@pytest.mark.parametrize("adapter", ["OneBot V11", "QQ"])
def test_public_feed_repeat_keeps_target_and_replays_duplicate_messages(game, play, monkeypatch, adapter):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    play("adopt", "青鸾", user="12345")
    target_id = add_pet(game[1], user_id="12345")
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())

    def send(text, message_id):
        event = (qq_event(text=text, message_id=str(message_id)) if adapter == "QQ"
                 else onebot_event(text, message_id))
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
        return bot.send.call_args.args[1]

    first = send(f"!灵宠喂养 {target_id}", 401)
    before = snapshot(game[1])
    assert send(f"!灵宠喂养 {target_id}", 401) == first
    assert snapshot(game[1]) == before
    if adapter == "QQ":
        repeat = next(button.action.data for segment in first["keyboard"]
                      for row in segment.data["keyboard"].content.rows for button in row.buttons
                      if button.action.data.startswith("!灵宠喂养"))
    else:
        repeat = f"!灵宠喂养 {target_id}"
        assert f"喂养编号 {target_id}（{repeat}）" in first
        assert f"查看整备（!灵宠整备 {target_id}）" in first
        assert "mqqapi://" not in first
    send(repeat, 402)
    assert bot.send.await_count == 3
    assert sql(game[1], "SELECT exp, affinity FROM pets WHERE user_id='12345' ORDER BY pet_id") == [
        {"exp": 0, "affinity": 0}, {"exp": 20, "affinity": 10},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE user_id='12345' AND item_id='spirit_food'") == [
        {"quantity": 1},
    ]


@pytest.mark.parametrize("adapter", ["OneBot V11", "QQ"])
@pytest.mark.parametrize("state,argument,reason,recovery", [
    ("unregistered", "1", "还没有灵宠伙伴", ("灵宠领养 ", "灵宠帮助")),
    ("inactive", "", "尚未选择出战灵宠", ("灵宠列表", "灵宠出战 ")),
    ("invalid", "wrong", "有效编号", ()),
    ("sealed", "2", "已封存", ()),
    ("stock", "1", "数量不足", ()),
])
def test_public_feed_errors_preserve_state_and_render_recovery(
    game, play, monkeypatch, adapter, state, argument, reason, recovery,
):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!", spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    if state != "unregistered":
        play("adopt", "青鸾", user="12345")
    if state == "inactive":
        sql(game[1], "DELETE FROM active_pet_slots")
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    elif state == "sealed":
        target_id = add_pet(game[1], user_id="12345")
        assert str(target_id) == argument
        play("pet_archive", str(target_id), user="12345")
    elif state == "stock":
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id='spirit_food'")
    before = snapshot(game[1])
    text = f"!灵宠喂养 {argument}".rstrip()
    event = qq_event(text=text) if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    for _ in range(2):
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
        assert snapshot(game[1]) == before
    reply = bot.send.call_args.args[1]
    if adapter == "QQ" and recovery:
        markdown = reply["markdown"][0].data["markdown"].content
        assert reason in markdown
        links = [parse_qs(urlparse(url).query)["command"][0]
                 for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
        payloads = [button.action.data for segment in reply["keyboard"]
                    for row in segment.data["keyboard"].content.rows for button in row.buttons]
        assert set(links + payloads) == {"!" + command for command in recovery}
        assert len(links + payloads) == len(set(links + payloads))
    else:
        assert reason in reply
        assert "mqqapi://" not in reply
        for command in recovery:
            assert f"（!{command.rstrip()}）" in reply
    assert bot.send.await_count == 2


def test_numbered_bond_uses_player_daily_limit_and_preserves_active_readiness(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = create_ready_team(play, game[1])
    target_id = add_pet(game[1])

    reply = play("bond", str(target_id), now=NOW)

    assert "亲密 +2（2/100）" in reply.text()
    assert pet(game[1])["affinity"] == 0
    assert sql(game[1], "SELECT affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"affinity": 2},
    ]
    assert player(game[1])["last_bond_day"] == beijing_day(NOW)
    assert player(game[1])["current_bond_streak"] == 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_once'") == [
        {"progress": 1},
    ]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]
    with pytest.raises(GameError, match="今日已与灵宠相伴"):
        play("bond", now=NOW)


def test_numbered_bond_rejects_target_on_expedition_without_using_daily_interaction(game, play):
    play("adopt", "青鸾", now=NOW)
    active_id = pet(game[1])["pet_id"]
    target_id = add_pet(game[1])
    play("switch", str(target_id), now=NOW)
    play("expedition_start", "采灵药", now=NOW)
    play("switch", str(active_id), now=NOW)

    with pytest.raises(GameError, match="当前不能行动"):
        play("bond", str(target_id), now=NOW)
    assert player(game[1])["last_bond_day"] == ""
    assert sql(game[1], "SELECT affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"affinity": 0},
    ]
