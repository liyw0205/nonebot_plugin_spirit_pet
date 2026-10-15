import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, sql

NOW = 1_800_000_000


def account(game, play, user="u1", stones=5000):
    play("adopt", "青鸾", user=user)
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (stones, user))


def stones_of(game, user="u1"):
    return sql(game[1], "SELECT stones FROM players WHERE user_id=?", (user,))[0]["stones"]


def give(game, item_id, quantity, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+?",
        (user, item_id, quantity, quantity),
    )


def test_content_recycle_rate_cannot_be_arbitraged(game):
    content = game[0].content
    percent = content.rules.recycle_percent
    assert 0 < percent < 100
    for item in content.items.values():
        if item.price is None or item.kind == "equipment":
            continue
        assert item.price * percent // 100 < item.price


def test_recycle_turns_items_into_stones(game, play):
    account(game, play)
    play("buy", "锻灵矿 5")
    before = stones_of(game)
    reply = play("recycle", "锻灵矿 2")
    assert reply.title == "灵坊回收"
    assert reply.lines == ("锻灵矿 -2，灵石 +64。", "回收价为售价的 40%；当前灵石 4664。")
    assert reply.commands == ("灵宠背包", "灵宠商店", "灵宠装备")
    assert reply.inline_commands == ()
    assert items(game[1])["forge_ore"] == 3
    assert stones_of(game) == before + 64


def test_recycle_scales_with_the_amount(game, play):
    account(game, play)
    give(game, "forge_ore", 3)
    before = stones_of(game)
    assert play("recycle", "锻灵矿 3").lines[0] == "锻灵矿 -3，灵石 +96。"
    assert stones_of(game) == before + 96


def test_recycle_rejects_items_without_a_price(game, play):
    account(game, play)
    give(game, "egg_tengling", 1)
    with pytest.raises(GameError, match="不在灵坊出售，无法回收"):
        play("recycle", "青藤灵卵 1")
    assert items(game[1])["egg_tengling"] == 1


def test_recycle_rejects_equipment(game, play):
    account(game, play)
    with pytest.raises(GameError, match="装备请用 灵宠分解 回收材料"):
        play("recycle", "青岚翎 1")


def test_recycle_rejects_a_short_bag(game, play):
    account(game, play)
    with pytest.raises(GameError, match="道具数量不足"):
        play("recycle", "锻灵矿 1")


def test_recycle_rejects_bad_arguments(game, play):
    account(game, play)
    for argument in ("", "锻灵矿 1 2"):
        with pytest.raises(GameError, match="格式：道具名称 数量"):
            play("recycle", argument)
    for argument in ("锻灵矿 0", "锻灵矿 100"):
        with pytest.raises(GameError, match="数量须为 1-99 的整数"):
            play("recycle", argument)
    with pytest.raises(GameError, match="未找到该内容"):
        play("recycle", "不存在的东西 1")


def test_recycle_needs_an_account(game, play):
    with pytest.raises(GameError, match="先完成领养"):
        play("recycle", "锻灵矿 1", user="u9")


def test_recycle_writes_no_records_and_keeps_pets(game, play):
    account(game, play)
    give(game, "forge_ore", 2)
    energy = pet(game[1])["energy"]
    play("recycle", "锻灵矿 1")
    assert sql(game[1], "SELECT battle_id FROM battle_records") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []
    assert pet(game[1])["energy"] == energy


def test_recycle_replays_one_operation_once(game, play):
    account(game, play)
    give(game, "forge_ore", 2)
    first = play("recycle", "锻灵矿 1", op="recycle-once")
    again = play("recycle", "锻灵矿 1", op="recycle-once")
    assert again.title == first.title and again.lines == first.lines
    assert items(game[1])["forge_ore"] == 1


def test_recycling_never_profits_from_buying(game, play):
    account(game, play)
    before = stones_of(game)
    play("buy", "灵粮 1")
    play("recycle", "灵粮 1")
    assert stones_of(game) == before - 12


def test_help_lists_the_recycle_entry(game, play):
    assert "灵宠回收" in play("help", "血脉与道具").text()


def test_native_payload_keeps_buttons_without_links(game, play):
    account(game, play)
    give(game, "forge_ore", 1)
    reply = play("recycle", "锻灵矿 1")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(reply.commands)
    assert reply.inline_commands == ()
