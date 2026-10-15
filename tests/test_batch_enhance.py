import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

WEAPON = "青岚翎"


def prepare(game, play, stones=1_000_000, ore=1000):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=1000000")
    play("buy", WEAPON)
    play("equipment", WEAPON)
    sql(game[1], "UPDATE players SET stones=?", (stones,))
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'forge_ore', ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=?",
        (ore, ore),
    )


def level(game):
    return sql(game[1], "SELECT enhancement FROM equipment WHERE slot='weapon'")[0]["enhancement"]


def stones(game):
    return sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]


def ore(game):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")
    return rows[0]["quantity"] if rows else 0


def test_batch_enhance_charges_the_whole_ladder(game, play):
    prepare(game, play)
    before = stones(game)
    reply = play("enhance", "灵器 5")
    assert reply.title == "灵物淬炼"
    assert reply.lines == (
        f"青鸾的{WEAPON}强化至 +5。",
        "消耗 1000 灵石、锻灵矿 15；装备属性倍率 2。",
    )
    assert reply.commands == ("灵宠装备", "灵宠背包")
    assert level(game) == 5
    assert stones(game) == before - 1000
    assert ore(game) == 1000 - 15


def test_single_step_is_unchanged(game, play):
    prepare(game, play)
    before = stones(game)
    reply = play("enhance", "灵器")
    assert reply.lines == (
        f"青鸾的{WEAPON}强化至 +1。",
        "消耗 80 灵石、锻灵矿 1；装备属性倍率 1.2。",
    )
    assert level(game) == 1
    assert stones(game) == before - 80
    assert ore(game) == 999


def test_batch_enhance_is_atomic_when_stones_are_short(game, play):
    prepare(game, play, stones=100)
    with pytest.raises(GameError, match="强化需要 5000 灵石、锻灵矿 55，灵石不足"):
        play("enhance", "灵器 10")
    assert level(game) == 0
    assert stones(game) == 100
    assert ore(game) == 1000


def test_batch_enhance_is_atomic_when_materials_are_short(game, play):
    prepare(game, play, ore=3)
    before = stones(game)
    with pytest.raises(GameError, match="道具数量不足"):
        play("enhance", "灵器 10")
    assert level(game) == 0
    assert stones(game) == before
    assert ore(game) == 3


def test_batch_enhance_rejects_a_target_not_above_the_current_level(game, play):
    prepare(game, play)
    play("enhance", "灵器 3")
    with pytest.raises(GameError, match=r"青岚翎当前 \+3，目标等级须更高"):
        play("enhance", "灵器 3")
    assert level(game) == 3


def test_batch_enhance_rejects_a_bad_target(game, play):
    prepare(game, play)
    for argument in ("灵器 0", "灵器 11", "灵器 abc"):
        with pytest.raises(GameError, match="目标等级须为 1-10 的整数"):
            play("enhance", argument)
    with pytest.raises(GameError, match="格式：灵宠强化 灵器"):
        play("enhance", "灵器 5 多余")
    assert level(game) == 0


def test_batch_enhance_rejects_an_empty_slot(game, play):
    prepare(game, play)
    with pytest.raises(GameError, match="该位置没有装备"):
        play("enhance", "护甲 5")
    assert level(game) == 0


def test_batch_enhance_rejects_a_full_ladder(game, play):
    prepare(game, play)
    sql(game[1], "UPDATE equipment SET enhancement=10")
    with pytest.raises(GameError, match="该装备已达最高强化等级"):
        play("enhance", "灵器")
    with pytest.raises(GameError, match=r"当前 \+10，目标等级须更高"):
        play("enhance", "灵器 10")


def test_batch_enhance_replays_one_operation_once(game, play):
    prepare(game, play)
    first = play("enhance", "灵器 3", op="batch-once")
    again = play("enhance", "灵器 3", op="batch-once")
    assert again.title == first.title and again.lines == first.lines
    assert level(game) == 3


def test_help_mentions_the_target_level(game, play):
    assert "目标等级" in play("help", "灵物与灵术").text()


def test_native_payload_keeps_buttons_without_links(game, play):
    prepare(game, play)
    reply = play("enhance", "灵器 2")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(reply.commands)
    assert reply.inline_commands == ()
