import sqlite3

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.equipment_set_rewards import SET_REWARDS, claim_id

from .support import items, player, sql


def account(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")


def equip_wind_set(play):
    play("buy", "青岚翎")
    play("equipment", "青岚翎", op="equip-wind-feather")
    play("buy", "灵心铃")
    play("equipment", "灵心铃", op="equip-spirit-bell")


def test_reward_definitions_cover_every_builtin_set(game):
    assert set(SET_REWARDS) == set(game[0].content.equipment_sets)
    assert all(
        item_id in game[0].content.items
        for _, reward_items in SET_REWARDS.values()
        for item_id in reward_items
    )
    assert COMMANDS["灵宠套装领奖"] == "equipment_set_claim"
    assert handlers._parse("灵宠套装领奖 青岚风铃") == ("equipment_set_claim", "青岚风铃")


def test_set_catalog_previews_without_an_account(game, play):
    page = play("equipment_sets", user="u9")
    assert page.title == "装备套装 1/1"
    assert all(line.endswith("尚未结契") for line in page.lines)
    assert sql(game[1], "SELECT user_id FROM players") == []
    with pytest.raises(GameError):
        play("equipment_set_claim", "青岚风铃", user="u9")


def test_partial_set_and_stale_claim_are_rejected_without_consuming_items(game, play):
    account(game, play)
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    partial = play("equipment_sets", "青岚风铃")
    assert partial.lines[-1].endswith("未完成。")
    assert not any(link.command.startswith("灵宠套装穿戴") for link in partial.inline_commands)
    assert not any(link.command.startswith("灵宠套装领奖") for link in partial.inline_commands)
    with pytest.raises(GameError, match="须由同一只出战灵宠"):
        play("equipment_set_claim", "青岚风铃")
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE ?", (claim_id("%"),)) == []

    play("buy", "灵心铃")
    play("equipment", "灵心铃")
    stale_link = next(
        link for link in play("equipment_sets", "青岚风铃").inline_commands
        if link.command.startswith("灵宠套装领奖")
    )
    assert stale_link.command == "灵宠套装领奖 青岚风铃"
    play("unequip", "饰品")
    stale_action, stale_argument = handlers._parse(stale_link.command)
    with pytest.raises(GameError, match="须由同一只出战灵宠"):
        play(stale_action, stale_argument)
    assert items(game[1])["spirit_bell"] == 1
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id=?", (claim_id("sky_wind"),)) == []


def test_complete_set_claim_is_durable_one_time_and_replay_safe(game, play):
    account(game, play)
    equip_wind_set(play)
    stones_before = player(game[1])["stones"]
    food_before = items(game[1])["spirit_food"]

    detail = play("equipment_sets", "青岚风铃")
    assert detail.lines[-1] == "首次完成奖励：灵石 180，灵粮 1 · 可领取。"
    assert [link.command for link in detail.inline_commands if link.command.startswith("灵宠套装领奖")] == [
        "灵宠套装领奖 青岚风铃",
    ]

    first = play("equipment_set_claim", "青岚风铃", op="wind-set-reward")
    assert first.title == "套装完成奖励"
    assert player(game[1])["stones"] == stones_before + 180
    assert items(game[1])["spirit_food"] == food_before + 1
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
               (claim_id("sky_wind"),)) == [{"progress": 1, "claimed": 1}]
    assert play("equipment_set_claim", "青岚风铃", op="wind-set-reward") == first
    with pytest.raises(GameError, match="已领取"):
        play("equipment_set_claim", "青岚风铃")

    play("unequip", "饰品")
    assert play("equipment_sets", "青岚风铃").lines[-1].endswith("已领取。")
    assert not any(
        link.command.startswith("灵宠套装领奖")
        for link in play("equipment_sets", "青岚风铃").inline_commands
    )
    assert player(game[1])["stones"] == stones_before + 180


@pytest.mark.parametrize(("set_id", "species_id"), [
    ("sky_wind", "qingluan"),
    ("stone_guard", "shiou"),
    ("venom_edge", "duman"),
    ("root_silk", "tengling"),
])
def test_every_builtin_set_reward_can_be_earned_and_claimed(game, play, set_id, species_id):
    account(game, play)
    sql(game[1], "UPDATE pets SET species_id=? WHERE user_id='u1'", (species_id,))
    equipment_set = game[0].content.equipment_sets[set_id]
    for equipment_id in equipment_set.items:
        name = game[0].content.items[equipment_id].name
        play("buy", name)
        play("equipment", name)

    stones, reward_items = SET_REWARDS[set_id]
    before_stones = player(game[1])["stones"]
    before_items = items(game[1])
    reply = play("equipment_set_claim", equipment_set.name)

    assert reply.title == "套装完成奖励"
    assert player(game[1])["stones"] == before_stones + stones
    for item_id, amount in reward_items.items():
        assert items(game[1]).get(item_id, 0) == before_items.get(item_id, 0) + amount
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(set_id),),
    ) == [{"progress": 1, "claimed": 1}]


def test_late_claim_persistence_failure_rolls_back_reward_and_allows_retry(game, play):
    account(game, play)
    equip_wind_set(play)
    before_player, before_items = player(game[1]), items(game[1])
    sql(game[1],
        "CREATE TRIGGER reject_equipment_set_claim BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{claim_id('sky_wind')}' "
        "BEGIN SELECT RAISE(ABORT, 'injected set reward failure'); END")

    with pytest.raises(sqlite3.IntegrityError, match="injected set reward failure"):
        play("equipment_set_claim", "青岚风铃", op="rollback-set-reward")

    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (claim_id("sky_wind"),)) == []
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items

    sql(game[1], "DROP TRIGGER reject_equipment_set_claim")
    retry = play("equipment_set_claim", "青岚风铃", op="rollback-set-reward")
    assert retry.title == "套装完成奖励"
    assert player(game[1])["stones"] == before_player["stones"] + SET_REWARDS["sky_wind"][0]


def test_set_list_has_claim_link_separate_from_native_buttons(game, play):
    account(game, play)
    equip_wind_set(play)
    reply = play("equipment_sets")
    assert [link.command for link in reply.inline_commands] == ["灵宠套装领奖 青岚风铃"]
    _, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert "灵宠套装领奖 青岚风铃" not in buttons
    assert "灵宠套装 青岚风铃" in buttons


def test_help_and_objectives_expose_set_rewards(game, play):
    assert "灵宠套装领奖 套装名：" in play("help", "灵物与灵术").text()
    assert "灵宠套装穿戴 宠物编号 套装名：" in play("help", "灵物与灵术").text()
    account(game, play)
    equip_wind_set(play)
    hub = play("objectives")
    assert "套装完成奖励：可领 1 套（青岚风铃）· 共 4 套" in hub.text()
    assert [link.command for link in hub.inline_commands[-4:]] == [
        "灵宠套装", "灵宠灵术赏", "灵宠亲密赏", "灵宠境界赏",
    ]
