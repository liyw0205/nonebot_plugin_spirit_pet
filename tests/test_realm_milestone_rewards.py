import sqlite3
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.realm_milestone_rewards import claim_id

from .support import items, pet, player, sql


def add_pet(game, user="u1", name="备用伙伴"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, 0)",
        (user, "qingluan", name),
    )
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? AND name=?", (user, name))[0]["pet_id"]


def test_routes_and_unregistered_browsing_are_read_only(game, play):
    assert COMMANDS["灵宠境界赏"] == "realm_milestone_rewards"
    assert COMMANDS["灵宠境界领奖"] == "realm_milestone_claim"
    assert handlers._parse("灵宠境界领奖 17 凝气") == ("realm_milestone_claim", "17 凝气")

    listing = play("realm_milestone_rewards", user="u9")
    assert listing.title == "灵宠境界赏 1/1"
    assert listing.inline_commands[0].command == "灵宠领养 "
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="先完成领养"):
        play("realm_milestone_claim", "1 凝气", user="u9")


def test_catalog_paginates_reached_realms_and_skips_initial_realm(game, play):
    play("adopt", "青鸾")
    first_id = pet(game[1])["pet_id"]
    second_id = add_pet(game, name="第二只青鸾")
    sql(game[1], "UPDATE pets SET realm=3 WHERE pet_id IN (?, ?)", (first_id, second_id))

    first = play("realm_milestone_rewards")
    assert first.title == "灵宠境界赏 1/2"
    assert len(first.inline_commands) == 5
    assert first.inline_commands[0].command == f"灵宠境界领奖 {first_id} 凝气"
    assert first.inline_commands[-1].command == f"灵宠境界领奖 {second_id} 筑基"
    assert "凝气" in first.text() and "启灵" not in first.text()
    second = play("realm_milestone_rewards", "2")
    assert second.title == "灵宠境界赏 2/2"
    assert [link.command for link in second.inline_commands] == [
        f"灵宠境界领奖 {second_id} 金丹",
    ]
    with pytest.raises(GameError, match="共 2 页"):
        play("realm_milestone_rewards", "3")


def test_claims_are_per_pet_and_replay_safe(game, play):
    play("adopt", "青鸾")
    first_id = pet(game[1])["pet_id"]
    second_id = add_pet(game, name="第二只青鸾")
    sql(game[1], "UPDATE pets SET realm=1 WHERE pet_id IN (?, ?)", (first_id, second_id))
    before_stones = player(game[1])["stones"]
    before_pills = items(game[1]).get("exp_pill", 0)

    first = play("realm_milestone_claim", f"{first_id} 凝气", op="realm-first")
    assert first.title == "境界里程碑奖励"
    assert player(game[1])["stones"] == before_stones + 10
    assert items(game[1])["exp_pill"] == before_pills + 1
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(first_id, "ningqi"),),
    ) == [{"progress": 1, "claimed": 1}]
    assert play("realm_milestone_claim", f"{first_id} 凝气", op="realm-first") == first
    with pytest.raises(GameError, match="已领取"):
        play("realm_milestone_claim", f"{first_id} 凝气")

    second = play("realm_milestone_claim", f"{second_id} 凝气")
    assert "灵石 +10" in second.text()
    assert items(game[1])["exp_pill"] == before_pills + 2


def test_archived_pet_milestones_remain_reviewable_and_claimable(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET realm=1, archived=1 WHERE pet_id=?", (pet_id,))

    listing = play("realm_milestone_rewards")
    assert "已封存 · 凝气" in listing.text()
    assert [link.command for link in listing.inline_commands] == [
        f"灵宠境界领奖 {pet_id} 凝气",
    ]
    assert play("realm_milestone_claim", f"{pet_id} 凝气").title == "境界里程碑奖励"


def test_unreached_foreign_unknown_and_duplicate_entries_are_rejected(game, play):
    play("adopt", "青鸾")
    owner_pet = pet(game[1])["pet_id"]
    play("adopt", "玄狐", user="u2")
    other_pet = pet(game[1], "u2")["pet_id"]
    sql(game[1], "UPDATE pets SET realm=1 WHERE pet_id=?", (other_pet,))

    with pytest.raises(GameError, match="尚未达到筑基境界"):
        play("realm_milestone_claim", f"{owner_pet} 筑基")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("realm_milestone_claim", f"{other_pet} 凝气")
    with pytest.raises(GameError, match="未找到可领奖"):
        play("realm_milestone_claim", f"{owner_pet} 元始")
    with pytest.raises(GameError, match="未找到可领奖"):
        play("realm_milestone_claim", f"{owner_pet} 启灵")
    with pytest.raises(GameError, match="格式"):
        play("realm_milestone_claim", str(owner_pet))

    sql(game[1], "UPDATE pets SET realm=99 WHERE pet_id=?", (owner_pet,))
    invalid = play("realm_milestone_rewards")
    assert "境界数据异常" in invalid.text()
    assert invalid.inline_commands == ()
    with pytest.raises(GameError, match="境界记录异常"):
        play("realm_milestone_claim", f"{owner_pet} 凝气")


def test_missing_exp_pill_definition_hides_link_and_rejects_claim(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET realm=1 WHERE pet_id=?", (pet_id,))
    original = game[0].content
    missing_items = dict(original.items)
    missing_items.pop("exp_pill")
    game[0].content = replace(original, items=missing_items)

    listing = play("realm_milestone_rewards")
    assert listing.inline_commands == ()
    assert "奖励待修复" in listing.text()
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="蕴灵丹定义缺失"):
        play("realm_milestone_claim", f"{pet_id} 凝气")
    assert player(game[1])["stones"] == before
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?",
               (claim_id(pet_id, "ningqi"),)) == []


def test_claim_persistence_failure_rolls_back_resources_and_allows_retry(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET realm=1 WHERE pet_id=?", (pet_id,))
    before_player, before_items = player(game[1]), items(game[1])
    marker = claim_id(pet_id, "ningqi")
    sql(
        game[1],
        "CREATE TRIGGER reject_realm_reward BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{marker}' BEGIN SELECT RAISE(ABORT, 'injected realm reward failure'); END",
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected realm reward failure"):
        play("realm_milestone_claim", f"{pet_id} 凝气", op="realm-retry")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (marker,)) == []
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items

    sql(game[1], "DROP TRIGGER reject_realm_reward")
    result = play("realm_milestone_claim", f"{pet_id} 凝气", op="realm-retry")
    assert result.title == "境界里程碑奖励"
    assert player(game[1])["stones"] == before_player["stones"] + 10


def test_help_and_objectives_expose_realm_rewards(game, play):
    help_page = play("help", "成长")
    assert "灵宠境界赏 页码" in help_page.text()
    assert "灵宠境界领奖 宠物编号 境界名" in help_page.text()
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET realm=2 WHERE pet_id=?", (pet_id,))

    hub = play("objectives")
    assert "境界里程碑奖励：可领 2 项 · 已达成 2 项" in hub.text()
    assert hub.inline_commands[-1].command == "灵宠境界赏"
    play("realm_milestone_claim", f"{pet_id} 凝气")
    assert "境界里程碑奖励：可领 1 项 · 已达成 2 项" in play("objectives").text()
