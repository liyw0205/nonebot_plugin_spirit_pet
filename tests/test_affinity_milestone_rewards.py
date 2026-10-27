import sqlite3
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.affinity_milestone_rewards import claim_id

from .support import items, pet, player, sql


def add_pet(game, *, user="u1", name="备用伙伴", affinity=0, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, affinity, archived, energy_updated) "
        "VALUES (?, 'qingluan', ?, ?, ?, 0)",
        (user, name, affinity, archived),
    )
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? AND name=?", (user, name))[0]["pet_id"]


def test_routes_and_unregistered_browsing_are_read_only(game, play):
    assert COMMANDS["灵宠亲密赏"] == "affinity_milestone_rewards"
    assert COMMANDS["灵宠亲密领奖"] == "affinity_milestone_claim"
    assert handlers._parse("灵宠亲密领奖 17 50") == ("affinity_milestone_claim", "17 50")

    listing = play("affinity_milestone_rewards", user="u9")
    assert listing.title == "灵宠亲密赏 1/1"
    assert any("同心丹 1" in line for line in listing.lines)
    assert listing.inline_commands[-1].command == "灵宠领养 "
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="先完成领养"):
        play("affinity_milestone_claim", "1 25", user="u9")


def test_catalog_paginates_each_pet_and_only_links_reached_milestones(game, play):
    play("adopt", "青鸾")
    first_id = pet(game[1])["pet_id"]
    second_id = add_pet(game, name="封存伙伴", affinity=100, archived=1)
    sql(game[1], "UPDATE pets SET affinity=75 WHERE pet_id=?", (first_id,))

    first = play("affinity_milestone_rewards")
    assert first.title == "灵宠亲密赏 1/2"
    assert len(first.inline_commands) == 4
    assert [link.command for link in first.inline_commands] == [
        f"灵宠亲密领奖 {first_id} 25",
        f"灵宠亲密领奖 {first_id} 50",
        f"灵宠亲密领奖 {first_id} 75",
        f"灵宠亲密领奖 {second_id} 25",
    ]
    assert any("封存伙伴 · 已封存 · 亲密 100/100 · 初识 25" in line for line in first.lines)
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert not buttons & {link.command for link in first.inline_commands}

    second = play("affinity_milestone_rewards", "2")
    assert second.title == "灵宠亲密赏 2/2"
    assert [link.command for link in second.inline_commands] == [
        f"灵宠亲密领奖 {second_id} 50",
        f"灵宠亲密领奖 {second_id} 75",
        f"灵宠亲密领奖 {second_id} 100",
    ]
    with pytest.raises(GameError, match="共 2 页"):
        play("affinity_milestone_rewards", "3")


def test_existing_feed_progress_unlocks_milestone_and_claim_is_per_pet(game, play):
    play("adopt", "青鸾")
    first_id = pet(game[1])["pet_id"]
    second_id = add_pet(game, name="第二只伙伴", affinity=50)
    sql(game[1], "UPDATE pets SET affinity=20 WHERE pet_id=?", (first_id,))
    sql(
        game[1],
        "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','spirit_food',1) "
        "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=inventory.quantity+excluded.quantity",
    )

    play("feed", str(first_id))
    assert pet(game[1])["affinity"] == 25
    listing = play("affinity_milestone_rewards")
    assert f"灵宠亲密领奖 {first_id} 25" in [link.command for link in listing.inline_commands]
    assert "亲密里程碑奖励：可领 3 项 · 已达成 3 项" in play("objectives").text()

    before_stones = player(game[1])["stones"]
    before_items = items(game[1])
    reward = play("affinity_milestone_claim", f"{first_id} 25", op="affinity-first")
    assert reward.title == "亲密成长奖励"
    assert player(game[1])["stones"] == before_stones + 20
    assert items(game[1])["spirit_food"] == before_items["spirit_food"] + 1
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(first_id, 25),),
    ) == [{"progress": 25, "claimed": 1}]
    assert play("affinity_milestone_claim", "ignored args", op="affinity-first") == reward
    with pytest.raises(GameError, match="已领取"):
        play("affinity_milestone_claim", f"{first_id} 25")

    second_reward = play("affinity_milestone_claim", f"{second_id} 50")
    assert "同心丹 +1" in second_reward.text()
    assert items(game[1])["affinity_pill"] == before_items.get("affinity_pill", 0) + 1


def test_archived_pet_can_claim_affinity_reward(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET affinity=100, archived=1 WHERE pet_id=?", (pet_id,))

    listing = play("affinity_milestone_rewards")
    assert any("已封存 · 亲密 100/100 · 初识 25" in line for line in listing.lines)
    assert f"灵宠亲密领奖 {pet_id} 100" in [link.command for link in listing.inline_commands]
    result = play("affinity_milestone_claim", f"{pet_id} 100")
    assert "血脉精华 +2" in result.text()


def test_foreign_unreached_invalid_and_duplicate_claims_are_rejected(game, play):
    play("adopt", "青鸾")
    owner_pet = pet(game[1])["pet_id"]
    play("adopt", "玄狐", user="u2")
    foreign_pet = pet(game[1], "u2")["pet_id"]

    with pytest.raises(GameError, match="尚未达成 25 点"):
        play("affinity_milestone_claim", f"{owner_pet} 25")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("affinity_milestone_claim", f"{foreign_pet} 25")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("affinity_milestone_claim", "999999 25")
    with pytest.raises(GameError, match="阈值须为"):
        play("affinity_milestone_claim", f"{owner_pet} 26")
    with pytest.raises(GameError, match="阈值须为"):
        play("affinity_milestone_claim", f"{owner_pet} 025")
    with pytest.raises(GameError, match="格式"):
        play("affinity_milestone_claim", f"{owner_pet} 25 extra")

    sql(game[1], "UPDATE pets SET affinity=100 WHERE pet_id=?", (owner_pet,))
    play("affinity_milestone_claim", f"{owner_pet} 25")
    sql(game[1], "UPDATE pets SET affinity=50.5 WHERE pet_id=?", (owner_pet,))
    listing = play("affinity_milestone_rewards")
    assert "亲密数据异常" in listing.text()
    assert not listing.inline_commands
    with pytest.raises(GameError, match="亲密记录异常"):
        play("affinity_milestone_claim", f"{owner_pet} 50")


def test_missing_or_wrong_reward_definition_hides_link_and_rejects_claim(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET affinity=25 WHERE pet_id=?", (pet_id,))
    original = game[0].content
    before_player, before_items = player(game[1]), items(game[1])

    missing = dict(original.items)
    missing.pop("spirit_food")
    game[0].content = replace(original, items=missing)
    listing = play("affinity_milestone_rewards")
    assert "奖励待修复" in listing.text()
    assert listing.inline_commands == ()
    with pytest.raises(GameError, match="物品定义缺失或类型错误"):
        play("affinity_milestone_claim", f"{pet_id} 25")
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (claim_id(pet_id, 25),)) == []

    wrong_kind = dict(original.items)
    wrong_kind["spirit_food"] = original.items["spirit_food"].model_copy(update={"kind": "material"})
    game[0].content = replace(original, items=wrong_kind)
    with pytest.raises(GameError, match="物品定义缺失或类型错误"):
        play("affinity_milestone_claim", f"{pet_id} 25")
    game[0].content = original


def test_claim_persistence_failure_rolls_back_and_allows_same_message_retry(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET affinity=50 WHERE pet_id=?", (pet_id,))
    before_player, before_items = player(game[1]), items(game[1])
    marker = claim_id(pet_id, 50)
    sql(
        game[1],
        "CREATE TRIGGER reject_affinity_reward BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{marker}' BEGIN SELECT RAISE(ABORT, 'injected affinity reward failure'); END",
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected affinity reward failure"):
        play("affinity_milestone_claim", f"{pet_id} 50", op="affinity-retry")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (marker,)) == []
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items

    sql(game[1], "DROP TRIGGER reject_affinity_reward")
    result = play("affinity_milestone_claim", f"{pet_id} 50", op="affinity-retry")
    assert result.title == "亲密成长奖励"
    assert player(game[1])["stones"] == before_player["stones"] + 40


def test_help_objectives_and_native_commands_expose_affinity_rewards(game, play):
    help_page = play("help", "成长")
    assert "灵宠亲密赏 页码" in help_page.text()
    assert "灵宠亲密领奖 宠物编号 阈值" in help_page.text()
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET affinity=50 WHERE pet_id=?", (pet_id,))

    hub = play("objectives")
    assert "亲密里程碑奖励：可领 2 项 · 已达成 2 项" in hub.text()
    assert hub.inline_commands[-3].command == "灵宠亲密赏"
    assert hub.inline_commands[-2].command == "灵宠境界赏"
    assert hub.inline_commands[-1].command == "灵宠飞升"
    listing = play("affinity_milestone_rewards")
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
