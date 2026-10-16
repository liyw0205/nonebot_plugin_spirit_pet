import sqlite3
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.bloodline_milestone_rewards import claim_id

from .support import items, pet, player, sql


def add_pet(game, *, user="u1", name="备用伙伴", bloodline=0, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, bloodline, archived, energy_updated) "
        "VALUES (?, 'qingluan', ?, ?, ?, 0)",
        (user, name, bloodline, archived),
    )
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? AND name=?", (user, name))[0]["pet_id"]


def test_routes_and_unregistered_browsing_are_read_only(game, play):
    assert COMMANDS["灵宠血脉赏"] == "bloodline_milestone_rewards"
    assert COMMANDS["灵宠血脉领奖"] == "bloodline_milestone_claim"
    assert handlers._parse("灵宠血脉领奖 17 仙血") == ("bloodline_milestone_claim", "17 仙血")

    listing = play("bloodline_milestone_rewards", user="u9")
    assert listing.title == "灵宠血脉赏 1/1"
    assert any("仙血 · 奖励：灵石 250、血脉精华 4" in line for line in listing.lines)
    assert listing.inline_commands[-1].command == "灵宠领养 "
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="先完成领养"):
        play("bloodline_milestone_claim", "1 灵血", user="u9")


def test_catalog_paginates_each_pet_and_links_only_reached_levels(game, play):
    play("adopt", "青鸾")
    first_id = pet(game[1])["pet_id"]
    second_id = add_pet(game, name="封存伙伴", bloodline=4, archived=1)
    sql(game[1], "UPDATE pets SET bloodline=2 WHERE pet_id=?", (first_id,))

    first = play("bloodline_milestone_rewards")
    assert first.title == "灵宠血脉赏 1/2"
    assert [link.command for link in first.inline_commands] == [
        f"灵宠血脉领奖 {first_id} 灵血",
        f"灵宠血脉领奖 {first_id} 玄血",
        f"灵宠血脉领奖 {second_id} 灵血",
    ]
    assert any("封存伙伴 · 已封存 · 当前仙血 · 灵血" in line for line in first.lines)
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert not buttons & {link.command for link in first.inline_commands}

    second = play("bloodline_milestone_rewards", "2")
    assert second.title == "灵宠血脉赏 2/2"
    assert [link.command for link in second.inline_commands] == [
        f"灵宠血脉领奖 {second_id} 玄血",
        f"灵宠血脉领奖 {second_id} 真血",
        f"灵宠血脉领奖 {second_id} 仙血",
    ]
    with pytest.raises(GameError, match="共 2 页"):
        play("bloodline_milestone_rewards", "3")


def test_claims_backfill_reached_levels_and_are_independent_per_pet(game, play):
    play("adopt", "青鸾")
    first_id = pet(game[1])["pet_id"]
    second_id = add_pet(game, name="第二只伙伴", bloodline=1)
    sql(game[1], "UPDATE pets SET bloodline=2 WHERE pet_id=?", (first_id,))
    before_stones = player(game[1])["stones"]
    before_essence = items(game[1]).get("bloodline_essence", 0)

    first = play("bloodline_milestone_claim", f"{first_id} 灵血", op="bloodline-first")
    assert first.title == "血脉进阶奖励"
    assert player(game[1])["stones"] == before_stones + 50
    assert items(game[1])["bloodline_essence"] == before_essence + 1
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(first_id, 1),),
    ) == [{"progress": 2, "claimed": 1}]
    assert play("bloodline_milestone_claim", "ignored args", op="bloodline-first") == first
    with pytest.raises(GameError, match="已领取"):
        play("bloodline_milestone_claim", f"{first_id} 灵血")

    second = play("bloodline_milestone_claim", f"{second_id} 灵血")
    assert "灵石 +50" in second.text()
    assert items(game[1])["bloodline_essence"] == before_essence + 2


def test_archived_pet_can_claim_the_highest_bloodline_reward(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET bloodline=4, archived=1 WHERE pet_id=?", (pet_id,))

    listing = play("bloodline_milestone_rewards")
    assert any("已封存 · 当前仙血 · 仙血" in line for line in listing.lines)
    assert f"灵宠血脉领奖 {pet_id} 仙血" in [link.command for link in listing.inline_commands]
    result = play("bloodline_milestone_claim", f"{pet_id} 仙血")
    assert "血脉精华 +4" in result.text()


def test_foreign_unreached_invalid_and_corrupt_bloodlines_are_rejected(game, play):
    play("adopt", "青鸾")
    owner_pet = pet(game[1])["pet_id"]
    play("adopt", "玄狐", user="u2")
    foreign_pet = pet(game[1], "u2")["pet_id"]

    with pytest.raises(GameError, match="尚未达到灵血"):
        play("bloodline_milestone_claim", f"{owner_pet} 灵血")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("bloodline_milestone_claim", f"{foreign_pet} 灵血")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("bloodline_milestone_claim", "999999 灵血")
    with pytest.raises(GameError, match="未找到可领奖"):
        play("bloodline_milestone_claim", f"{owner_pet} 凡血")
    with pytest.raises(GameError, match="未找到可领奖"):
        play("bloodline_milestone_claim", f"{owner_pet} 未知血脉")
    with pytest.raises(GameError, match="格式"):
        play("bloodline_milestone_claim", f"{owner_pet} 灵血 extra")

    sql(game[1], "UPDATE pets SET bloodline=9 WHERE pet_id=?", (owner_pet,))
    listing = play("bloodline_milestone_rewards")
    assert "血脉数据异常" in listing.text()
    assert not listing.inline_commands
    with pytest.raises(GameError, match="血脉记录异常"):
        play("bloodline_milestone_claim", f"{owner_pet} 灵血")


def test_missing_or_wrong_essence_definition_hides_links_and_rejects_claim(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET bloodline=1 WHERE pet_id=?", (pet_id,))
    original = game[0].content
    before_player, before_items = player(game[1]), items(game[1])

    missing = dict(original.items)
    missing.pop("bloodline_essence")
    game[0].content = replace(original, items=missing)
    listing = play("bloodline_milestone_rewards")
    assert "奖励待修复" in listing.text()
    assert listing.inline_commands == ()
    with pytest.raises(GameError, match="定义缺失或类型错误"):
        play("bloodline_milestone_claim", f"{pet_id} 灵血")
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (claim_id(pet_id, 1),)) == []

    wrong_kind = dict(original.items)
    wrong_kind["bloodline_essence"] = original.items["bloodline_essence"].model_copy(
        update={"kind": "consumable"},
    )
    game[0].content = replace(original, items=wrong_kind)
    with pytest.raises(GameError, match="定义缺失或类型错误"):
        play("bloodline_milestone_claim", f"{pet_id} 灵血")
    game[0].content = original


def test_claim_persistence_failure_rolls_back_and_allows_retry(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET bloodline=2 WHERE pet_id=?", (pet_id,))
    before_player, before_items = player(game[1]), items(game[1])
    marker = claim_id(pet_id, 2)
    sql(
        game[1],
        "CREATE TRIGGER reject_bloodline_reward BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{marker}' BEGIN SELECT RAISE(ABORT, 'injected bloodline reward failure'); END",
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected bloodline reward failure"):
        play("bloodline_milestone_claim", f"{pet_id} 玄血", op="bloodline-retry")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (marker,)) == []
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items

    sql(game[1], "DROP TRIGGER reject_bloodline_reward")
    result = play("bloodline_milestone_claim", f"{pet_id} 玄血", op="bloodline-retry")
    assert result.title == "血脉进阶奖励"
    assert player(game[1])["stones"] == before_player["stones"] + 100


def test_help_objectives_and_native_commands_expose_bloodline_rewards(game, play):
    help_page = play("help", "成长")
    assert "灵宠血脉赏 页码" in help_page.text()
    assert "灵宠血脉领奖 宠物编号 血脉名" in help_page.text()
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET bloodline=1 WHERE pet_id=?", (pet_id,))

    hub = play("objectives")
    assert "血脉进阶奖励：可领 1 项 · 已达成 1 项" in hub.text()
    assert "灵宠血脉赏" in [link.command for link in hub.inline_commands]
    listing = play("bloodline_milestone_rewards")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    assert not buttons & {link.command for link in listing.inline_commands}
