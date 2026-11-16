import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql
from .test_commands import onebot_event, qq_event
from .test_targeted_care import NOW, add_pet, create_ready_team, snapshot


def test_numbered_interaction_continues_with_same_partner_and_claims_streak_reward(game, play):
    play("adopt", "青鸾")
    active_id = create_ready_team(play, game[1])
    target_id = add_pet(game[1])
    prep = play("pet_prep", str(target_id))
    command = next(link.command for link in prep.inline_commands if link.command == f"灵宠互动 {target_id}")
    reply = play(*handlers._parse(command), op="targeted-bond-first")
    assert any(link.command == f"灵宠整备 {target_id}" for link in reply.inline_commands)
    assert f"编号 {target_id}" in reply.text()
    assert "亲密 +2（2/100）" in reply.text()
    assert reply.commands == ("灵宠任务", "灵宠陪伴奖励")
    before = snapshot(game[1])
    assert play(*handlers._parse(command), op="targeted-bond-first") == reply
    with pytest.raises(GameError, match="今日已与灵宠相伴"):
        play("bond")
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT ready_pet_id FROM team_members WHERE user_id='u1'") == [
        {"ready_pet_id": active_id},
    ]

    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    feed = next(link.command for link in reply.inline_commands if link.command.startswith("灵宠喂养"))
    assert feed == f"灵宠喂养 {target_id}"
    fed = play(*handlers._parse(feed))
    assert any(link.command == f"灵宠整备 {target_id}" for link in fed.inline_commands)
    for day in (1, 2):
        play(*handlers._parse(command), now=NOW + day * 86400)
    rewards = play(*handlers._parse("灵宠陪伴奖励"), now=NOW + 2 * 86400)
    claim = next(link.command for link in rewards.inline_commands if link.command == "灵宠陪伴领奖 3")
    stones = player(game[1])["stones"]
    claimed = play(*handlers._parse(claim), now=NOW + 2 * 86400, op="targeted-streak-reward")
    assert "3 天里程碑「初识相伴」已领取" in claimed.text()
    assert play(*handlers._parse(claim), now=NOW + 2 * 86400, op="targeted-streak-reward") == claimed
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已领取"):
        play(*handlers._parse(claim), now=NOW + 2 * 86400)
    assert snapshot(game[1]) == before
    assert player(game[1])["stones"] == stones + 80
    assert player(game[1])["active_pet_id"] is None
    assert sql(game[1], "SELECT exp, affinity FROM pets ORDER BY pet_id") == [
        {"exp": 0, "affinity": 0}, {"exp": 10, "affinity": 11},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_food'") == [{"quantity": 3}]


@pytest.mark.parametrize("food", [0, 1])
@pytest.mark.parametrize("affinity", [0, 100])
def test_numbered_interaction_only_offers_usable_food_without_blocking_full_affinity(game, play, food, affinity):
    play("adopt", "青鸾")
    target_id = add_pet(game[1])
    sql(game[1], "UPDATE pets SET affinity=? WHERE pet_id=?", (affinity, target_id))
    sql(game[1], "UPDATE inventory SET quantity=? WHERE item_id='spirit_food'", (food,))
    reply = play("bond", str(target_id))
    assert (f"灵宠喂养 {target_id}" in [link.command for link in reply.inline_commands]) is bool(food)
    assert not {"灵宠喂养", "我的灵宠", "灵宠互动"} & set(reply.commands)
    assert sql(game[1], "SELECT affinity FROM pets WHERE pet_id=?", (target_id,)) == [
        {"affinity": min(100, affinity + 2)},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_food'") == [{"quantity": food}]
    assert player(game[1])["current_bond_streak"] == 1


@pytest.mark.parametrize("prefix", ["", "/", "!"])
@pytest.mark.parametrize("keyboard", [True, False])
def test_numbered_interaction_qq_actions_keep_target_without_duplicates(game, play, prefix, keyboard):
    play("adopt", "青鸾")
    target_id = add_pet(game[1])
    reply = play("bond", str(target_id))
    plain, native = _qq_segments(
        reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix), allow_keyboard=keyboard,
    )
    markdown = native["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    payloads = [button.action.data for segment in native["keyboard"]
                for row in segment.data["keyboard"].content.rows for button in row.buttons]
    target_actions = {prefix + f"灵宠整备 {target_id}", prefix + f"灵宠喂养 {target_id}"}
    navigation = {prefix + "灵宠任务", prefix + "灵宠陪伴奖励"}
    if keyboard:
        assert set(links) == target_actions
        assert set(payloads) == navigation
    else:
        assert set(links) == target_actions | navigation
        assert not payloads
    assert len(links + payloads) == len(set(links + payloads)) == 4
    assert "mqqapi://" not in plain
    assert f"喂养这位伙伴（{prefix}灵宠喂养 {target_id}）" in plain


@pytest.mark.parametrize("adapter", ["OneBot V11", "QQ"])
def test_public_numbered_interaction_replays_and_feeds_same_partner_without_active_pet(game, play, monkeypatch, adapter):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    play("adopt", "青鸾", user="12345")
    target_id = add_pet(game[1], user_id="12345", name="青鸾")
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())

    def send(command, message_id):
        event = (qq_event(text=command, message_id=str(message_id)) if adapter == "QQ"
                 else onebot_event(command, message_id))
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
        return bot.send.call_args.args[1]

    reply = send(f"!灵宠互动 {target_id}", 501)
    before = snapshot(game[1])
    assert send(f"!灵宠互动 {target_id}", 501) == reply
    assert snapshot(game[1]) == before
    assert "今日已与灵宠相伴" in send(f"!灵宠互动 {target_id}", 502)
    assert snapshot(game[1]) == before
    if adapter == "QQ":
        markdown = reply["markdown"][0].data["markdown"].content
        commands = [parse_qs(urlparse(url).query)["command"][0]
                    for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
        feed = next(command for command in commands if command.startswith("!灵宠喂养"))
    else:
        assert f"青鸾（编号 {target_id}）" in reply
        assert f"查看整备（!灵宠整备 {target_id}）" in reply
        assert "mqqapi://" not in reply
        feed = re.search(r"喂养这位伙伴（([^）]+)）", reply).group(1)
    assert feed == f"!灵宠喂养 {target_id}"
    send(feed, 503)
    assert sql(game[1], "SELECT exp, affinity FROM pets ORDER BY pet_id") == [
        {"exp": 0, "affinity": 0}, {"exp": 10, "affinity": 7},
    ]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_food'") == [{"quantity": 2}]
    assert sql(game[1], "SELECT active_pet_id FROM players") == [{"active_pet_id": None}]
    assert bot.send.await_count == 4


@pytest.mark.parametrize("adapter", ["OneBot V11", "QQ"])
@pytest.mark.parametrize("state,argument,reason,recovery", [
    ("unregistered", "1", "还没有灵宠伙伴", ("灵宠领养 ", "灵宠帮助")),
    ("inactive", "", "尚未选择出战灵宠", ("灵宠列表", "灵宠出战 ")),
    ("invalid", "1 2", "有效编号", ()),
    ("sealed", "2", "已封存", ()),
    ("trip", "2", "当前不能行动", ()),
])
def test_public_interaction_errors_do_not_consume_daily_care(
    game, play, monkeypatch, adapter, state, argument, reason, recovery,
):
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    if state != "unregistered":
        play("adopt", "青鸾", user="12345")
    if state == "inactive":
        sql(game[1], "DELETE FROM active_pet_slots")
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    elif state in {"sealed", "trip"}:
        target_id = add_pet(game[1], user_id="12345")
        assert str(target_id) == argument
        if state == "sealed":
            play("pet_archive", str(target_id), user="12345")
        else:
            play("switch", str(target_id), user="12345")
            play("expedition_start", "采灵药", user="12345")
            play("switch", "1", user="12345")
    before = snapshot(game[1])
    command = f"!灵宠互动 {argument}".rstrip()
    event = qq_event(text=command) if adapter == "QQ" else onebot_event(command)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
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
    assert snapshot(game[1]) == before
    assert bot.send.await_count == 1
