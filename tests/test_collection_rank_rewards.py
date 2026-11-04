"""One-time collection leaderboard rank rewards."""

import json
import shutil

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.collection_rank_reward_content import CollectionRankReward
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import collection_rank_rewards

from .support import items, player, sql

NOW = 1_800_000_000


def adopt(game, play, count=3):
    names = ("青鸾", "玄狐", "白泽", "蛟龙", "青鸾")
    for index in range(1, count + 1):
        play("adopt", names[index - 1], user=f"u{index}")


def add_species(game, user, species):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        (user, species, f"{species}-{user}", NOW),
    )


def state(store):
    return {
        "players": sql(store, "SELECT * FROM players ORDER BY 1"),
        "pets": sql(store, "SELECT * FROM pets ORDER BY 1"),
        "inventory": sql(store, "SELECT * FROM inventory ORDER BY 1"),
        "quest_progress": sql(store, "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        "battle_records": sql(store, "SELECT * FROM battle_records ORDER BY 1"),
    }


def test_content_has_three_ordered_milestones(game):
    rewards = game[0].content.collection_rank_rewards
    assert sorted(rewards) == [1, 3, 10]
    assert rewards[1].name == "三甲之首"
    assert rewards[1].stones == 500
    assert rewards[3].stones == 260
    assert rewards[10].stones == 120


def test_reward_model_rejects_empty_and_bad_rank():
    base = {"rank": 1, "name": "测试", "stones": 10, "items": {}}
    assert CollectionRankReward.model_validate(base).rank == 1
    with pytest.raises(ValidationError):
        CollectionRankReward.model_validate({**base, "stones": 0})
    with pytest.raises(ValidationError):
        CollectionRankReward.model_validate({**base, "rank": 11})
    with pytest.raises(ValidationError):
        CollectionRankReward.model_validate({**base, "items": {"x": 0}})


def test_catalog_rejects_missing_tier_and_unknown_item(tmp_path):
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    source = (data / "collection_rank_rewards.json").read_text()
    rewards = json.loads(source)
    (data / "collection_rank_rewards.json").write_text(json.dumps(rewards[:2], ensure_ascii=False))
    with pytest.raises(ValueError, match="cover ranks 1, 3 and 10"):
        Catalog.load(data)
    (data / "collection_rank_rewards.json").write_text(
        source.replace('"forge_ore": 3', '"no_such_item": 3', 1)
    )
    with pytest.raises(ValueError, match="unknown|reward items"):
        Catalog.load(data)


def test_unregistered_page_is_read_only(game, play):
    page = play("collection_rank_rewards", user="ghost")
    assert page.title == "灵宠收集榜奖励"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_page_lists_milestones_and_current_rank(game, play):
    adopt(game, play, 1)
    add_species(game, "u1", "xuanhu")
    page = play("collection_rank_rewards")
    assert "当前收集榜名次：第 1 名。" in page.text()
    assert "前 1 名 · 三甲之首 · 灵石 500" in page.text()
    assert "前 3 名 · 三甲在望 · 灵石 260" in page.text()
    assert "前 10 名 · 十强留名 · 灵石 120" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠收集榜领奖 1", "灵宠收集榜领奖 3", "灵宠收集榜领奖 10",
    ]
    assert page.commands == ("灵宠收集榜", "灵宠收集", "灵宠目标")


def test_rank_three_can_claim_three_and_ten_but_not_one(game, play):
    adopt(game, play, 3)
    add_species(game, "u2", "jiaolong")
    add_species(game, "u3", "jiaolong")
    page = play("collection_rank_rewards", user="u2")
    assert "当前收集榜名次：第 1 名。" in page.text()  # u2 has 2 species, rank 1
    # Give u1 and u3 three species so u2 falls to rank 3.
    add_species(game, "u1", "xuanhu")
    add_species(game, "u1", "jiaolong")
    add_species(game, "u3", "xuanhu")
    page = play("collection_rank_rewards", user="u2")
    assert "当前收集榜名次：第 3 名。" in page.text()
    links = [link.command for link in page.inline_commands]
    assert "灵宠收集榜领奖 1" not in links
    assert "灵宠收集榜领奖 3" in links and "灵宠收集榜领奖 10" in links


def test_claim_pays_once_and_records_the_rank(game, play):
    adopt(game, play, 1)
    add_species(game, "u1", "xuanhu")
    before = player(game[1])["stones"]
    reply = play("collection_rank_reward_claim", "1", op="rank-1")
    assert "第 1 名" in reply.text()
    assert player(game[1])["stones"] == before + 500
    assert items(game[1])["forge_ore"] == 3
    assert items(game[1])["spirit_food"] == 4
    record = sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (collection_rank_rewards.claim_id(1),),
    )
    assert record == [{"progress": 1, "claimed": 1}]
    assert play("collection_rank_reward_claim", "1", op="rank-1") == reply
    with pytest.raises(GameError, match="已经领取"):
        play("collection_rank_reward_claim", "1", op="rank-1b")


def test_claiming_does_not_revoke_after_dropping_rank(game, play):
    adopt(game, play, 4)
    add_species(game, "u1", "xuanhu")
    play("collection_rank_reward_claim", "1", op="rank-drop-claim")
    for index in range(2, 5):
        add_species(game, f"u{index}", "jiaolong")
        add_species(game, f"u{index}", "bai ze")
    page = play("collection_rank_rewards")
    assert "前 1 名 · 三甲之首" in page.text() and "已领取" in page.text()
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="已经领取"):
        play("collection_rank_reward_claim", "1", op="rank-drop-again")
    assert player(game[1])["stones"] == before


def test_unranked_rank_insufficient_and_bad_arguments_write_nothing(game, play):
    play("adopt", "青鸾")
    add_species(game, "u1", "xuanhu")
    add_species(game, "u1", "bai ze")
    add_species(game, "u1", "jiaolong")
    add_species(game, "u1", "removed_species")
    # u1 is rank 1 only for the four shipped species; the retired row does not count.
    before = state(game[1])
    for argument in ("", "0", "2", "11", "abc", "1 3"):
        with pytest.raises(GameError, match="格式"):
            play("collection_rank_reward_claim", argument, op=f"bad-{argument}")
    assert state(game[1]) == before


def test_no_species_and_rank_beyond_threshold(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    sql(game[1], "DELETE FROM pets WHERE user_id='u1'")
    with pytest.raises(GameError, match="尚未进入收集榜"):
        play("collection_rank_reward_claim", "10", op="no-species")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'collection_rank_reward_%'") == []


def test_pages_are_read_only(game, play):
    adopt(game, play, 2)
    add_species(game, "u1", "xuanhu")
    before = state(game[1])
    play("collection_rank_rewards")
    play("collection_rank_rewards", user="u2")
    assert state(game[1]) == before


def test_same_operation_is_idempotent(game, play):
    adopt(game, play, 1)
    add_species(game, "u1", "xuanhu")
    first = play("collection_rank_reward_claim", "10", op="rank-idem")
    before = state(game[1])
    again = play("collection_rank_reward_claim", "10", op="rank-idem")
    assert again.text() == first.text()
    assert state(game[1]) == before


def test_persists_across_restart(game, play):
    adopt(game, play, 1)
    add_species(game, "u1", "xuanhu")
    play("collection_rank_reward_claim", "1", op="rank-persist")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "collection_rank_rewards", "", "restart-rank", NOW)
    assert "已领取" in page.text()


def test_collection_board_links_to_rewards_and_buttons_stay_bounded(game, play):
    adopt(game, play, 1)
    add_species(game, "u1", "xuanhu")
    page = play("collection_rank")
    assert "灵宠收集榜奖励" in page.commands
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons <= set(page.commands)
    assert len(buttons) <= 4
    reward_page = play("collection_rank_rewards")
    _, reward_message = _qq_segments(reward_page, Config(spirit_pet_qq_mode="native"))
    reward_buttons = {
        button.action.data.removeprefix("/")
        for segment in reward_message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert len(reward_buttons) <= 4
    assert not reward_buttons & {link.command for link in reward_page.inline_commands}


def test_help_and_parser_cover_the_reward_commands(game, play):
    adopt(game, play, 1)
    assert _parse("灵宠收集榜奖励") == ("collection_rank_rewards", "")
    assert _parse("灵宠收集榜领奖 1") == ("collection_rank_reward_claim", "1")
    guide = play("help", "身份与收集")
    assert "灵宠收集榜奖励" in guide.text()
    assert "灵宠收集榜领奖 名次" in guide.text()


def test_objectives_are_unchanged(game, play):
    adopt(game, play, 1)
    add_species(game, "u1", "xuanhu")
    assert "收集" not in "\n".join(
        line for line in play("objectives").lines if line.startswith("收集榜")
    )
