import sqlite3
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.lineage_awakening_rewards import claim_id

from .support import items, pet, player, sql


BRANCH = "凌风鸾脉"


def add_pet(game, *, name, user="u1", bloodline=1, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, bloodline, archived, energy_updated) "
        "VALUES (?, 'qingluan', ?, ?, ?, 0)",
        (user, name, bloodline, archived),
    )
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? AND name=?", (user, name))[0]["pet_id"]


def select_branch(game, play, *, pet_id=None, branch=BRANCH):
    if pet_id is None:
        play("adopt", "青鸾")
        pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    sql(game[1], "UPDATE pets SET exp=10000, bloodline=1 WHERE pet_id=?", (pet_id,))
    sql(game[1], "INSERT OR REPLACE INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'bloodline_essence', 100)")
    if pet(game[1])["pet_id"] != pet_id:
        play("switch", str(pet_id))
    play("lineage_choose", branch)
    return pet_id


def test_routes_and_unregistered_browsing_are_read_only(game, play):
    assert COMMANDS["灵宠分支赏"] == "lineage_awakening_rewards"
    assert COMMANDS["灵宠分支领奖"] == "lineage_awakening_claim"
    assert handlers._parse("灵宠分支领奖 17 凌风鸾脉") == (
        "lineage_awakening_claim", "17 凌风鸾脉",
    )

    listing = play("lineage_awakening_rewards", user="u9")
    assert listing.title == "灵宠分支赏 1/1"
    assert "奖励：灵石 100、血脉精华 1" in listing.text()
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="先完成领养"):
        play("lineage_awakening_claim", "1 凌风鸾脉", user="u9")


def test_catalog_paginates_selected_and_archived_branches_with_claim_links(game, play):
    pet_id = select_branch(game, play)
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pet_id,))
    for index in range(6):
        add_pet(game, name=f"备用伙伴{index}")

    first = play("lineage_awakening_rewards")
    assert first.title == "灵宠分支赏 1/2"
    assert any("备用伙伴0 · 青鸾 · 当前灵血" in line for line in first.lines)
    assert any(" · 青鸾 · 已封存 · 当前灵血 · 凌风鸾脉 · 奖励：灵石 100、血脉精华 1 · 可领取" in line
               for line in first.lines)
    assert [link.command for link in first.inline_commands] == [
        f"灵宠分支领奖 {pet_id} {BRANCH}",
    ]
    assert "未选择分支" in first.text()

    second = play("lineage_awakening_rewards", "2")
    assert second.title == "灵宠分支赏 2/2"
    assert second.inline_commands == ()

    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(first.commands)
    assert not buttons & {link.command for link in first.inline_commands}


def test_claim_is_per_pet_idempotent_and_rejects_duplicate_claim(game, play):
    first_id = select_branch(game, play)
    second_id = add_pet(game, name="第二只伙伴")
    sql(game[1], "UPDATE pets SET exp=10000, bloodline=1 WHERE pet_id=?", (second_id,))
    play("switch", str(second_id))
    play("lineage_choose", "青木鸾脉")
    play("switch", str(first_id))
    before_stones = player(game[1])["stones"]
    before_essence = items(game[1])["bloodline_essence"]

    first = play("lineage_awakening_claim", f"{first_id} {BRANCH}", op="lineage-first")
    assert first.title == "血脉分支觉醒礼"
    assert player(game[1])["stones"] == before_stones + 100
    assert items(game[1])["bloodline_essence"] == before_essence + 1
    assert sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (claim_id(first_id, "qingluan_lingfeng"),),
    ) == [{"progress": 1, "claimed": 1}]
    assert play("lineage_awakening_claim", "ignored args", op="lineage-first") == first

    second = play("lineage_awakening_claim", f"{second_id} 青木鸾脉")
    assert "青木鸾脉觉醒礼已领取" in second.text()
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'lineage_awakening_reward_%'") == [
        {"quest_id": claim_id(first_id, "qingluan_lingfeng")},
        {"quest_id": claim_id(second_id, "qingluan_qingmu")},
    ]
    with pytest.raises(GameError, match="已领取"):
        play("lineage_awakening_claim", f"{first_id} {BRANCH}")


def test_unselected_foreign_unknown_and_stale_branch_claims_are_rejected(game, play):
    first_id = select_branch(game, play)
    unselected_id = add_pet(game, name="未选伙伴")

    with pytest.raises(GameError, match="与此奖励不符"):
        play("lineage_awakening_claim", f"{first_id} 青木鸾脉")
    with pytest.raises(GameError, match="尚未选择"):
        play("lineage_awakening_claim", f"{unselected_id} {BRANCH}")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("lineage_awakening_claim", "999999 凌风鸾脉")

    play("adopt", "玄狐", user="u2")
    foreign_id = pet(game[1], "u2")["pet_id"]
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("lineage_awakening_claim", f"{foreign_id} 夜焰狐脉")
    with pytest.raises(GameError, match="未找到该血脉分支"):
        play("lineage_awakening_claim", f"{first_id} 未知分支")
    with pytest.raises(GameError, match="格式"):
        play("lineage_awakening_claim", str(first_id))


def test_corrupt_branch_data_is_visible_but_never_claimable(game, play):
    pet_id = select_branch(game, play)
    sql(game[1], "UPDATE pets SET lineage_id='xuanhu_yeyan' WHERE pet_id=?", (pet_id,))

    listing = play("lineage_awakening_rewards")
    assert "分支数据异常" in listing.text()
    assert listing.inline_commands == ()
    with pytest.raises(GameError, match="记录异常"):
        play("lineage_awakening_claim", f"{pet_id} 夜焰狐脉")


def test_missing_or_wrong_essence_definition_hides_link_and_rejects_claim(game, play):
    pet_id = select_branch(game, play)
    original = game[0].content
    before_player, before_items = player(game[1]), items(game[1])

    missing = dict(original.items)
    missing.pop("bloodline_essence")
    game[0].content = replace(original, items=missing)
    listing = play("lineage_awakening_rewards")
    assert "奖励待修复" in listing.text()
    assert listing.inline_commands == ()
    with pytest.raises(GameError, match="定义缺失或类型错误"):
        play("lineage_awakening_claim", f"{pet_id} {BRANCH}")
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?",
               (claim_id(pet_id, "qingluan_lingfeng"),)) == []

    wrong_kind = dict(original.items)
    wrong_kind["bloodline_essence"] = original.items["bloodline_essence"].model_copy(
        update={"kind": "consumable"},
    )
    game[0].content = replace(original, items=wrong_kind)
    with pytest.raises(GameError, match="定义缺失或类型错误"):
        play("lineage_awakening_claim", f"{pet_id} {BRANCH}")
    game[0].content = original


def test_claim_persistence_failure_rolls_back_and_allows_retry(game, play):
    pet_id = select_branch(game, play)
    marker = claim_id(pet_id, "qingluan_lingfeng")
    before_player, before_items = player(game[1]), items(game[1])
    sql(
        game[1],
        "CREATE TRIGGER reject_lineage_reward BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{marker}' BEGIN SELECT RAISE(ABORT, 'injected lineage reward failure'); END",
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected lineage reward failure"):
        play("lineage_awakening_claim", f"{pet_id} {BRANCH}", op="lineage-retry")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (marker,)) == []
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items

    sql(game[1], "DROP TRIGGER reject_lineage_reward")
    result = play("lineage_awakening_claim", f"{pet_id} {BRANCH}", op="lineage-retry")
    assert result.title == "血脉分支觉醒礼"
    assert player(game[1])["stones"] == before_player["stones"] + 100


def test_help_and_objectives_expose_lineage_rewards(game, play):
    help_page = play("help", "成长")
    assert "灵宠分支赏 页码" in help_page.text()
    assert "灵宠分支领奖 宠物编号 分支名" in help_page.text()
    pet_id = select_branch(game, play)

    hub = play("objectives")
    assert "血脉分支觉醒礼：可领 1 项 · 已选分支 1 只" in hub.text()
    assert "灵宠分支赏" in [link.command for link in hub.inline_commands]
    listing = play("lineage_awakening_rewards")
    assert f"灵宠分支领奖 {pet_id} {BRANCH}" in [link.command for link in listing.inline_commands]
