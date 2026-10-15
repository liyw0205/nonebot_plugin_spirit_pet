import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def claimed_ids(game, user="u1"):
    return [
        row["quest_id"] for row in sql(
            game[1], "SELECT quest_id FROM quest_progress WHERE user_id=? AND claimed=1 ORDER BY quest_id",
            (user,),
        )
    ]


def test_content_defines_an_ordered_chain(game):
    quests = sorted(game[0].content.main_quests.values(), key=lambda quest: quest.order)
    assert [quest.order for quest in quests] == list(range(1, 17))
    assert [quest.id for quest in quests] == [f"main_{index:02d}" for index in range(1, 17)]
    for index, quest in enumerate(quests):
        assert quest.previous_id == (quests[index - 1].id if index else None)
        assert quest.target > 0 and quest.description
        assert all(item in game[0].content.items for item in quest.reward.items)
    assert quests[0].reward.stones.minimum < quests[-1].reward.stones.minimum


def test_list_shows_states_and_links_only_the_current_step(game, play):
    account(game, play)
    listing = play("main_quests")
    assert listing.title == "灵宠主线 1/4"
    assert "1. 初结灵契 · 可领奖 · 1/1 · 灵石 100，灵粮 2" in listing.text()
    assert "2. 双灵相伴 · 未解锁" in listing.text()
    assert "当前目标：初结灵契 · 与第一位伙伴结下灵契。" in listing.text()
    assert links(listing) == [(1, "领取奖励", "灵宠主线领奖 初结灵契")]
    assert listing.commands == ("灵宠主线 2", "灵宠任务")
    assert not {command for _, _, command in links(listing)} & set(listing.commands)


def test_unregistered_player_can_read_the_chain_without_an_account(game, play):
    listing = play("main_quests")
    assert "尚未结契" in listing.text()
    assert links(listing) == [(1, "开始领养", "灵宠领养 ")]
    assert not sql(game[1], "SELECT * FROM players")


def test_claim_grants_the_reward_and_unlocks_the_next_step(game, play):
    account(game, play)
    before = (player(game[1])["stones"], items(game[1]))
    result = play("main_quest_claim", "初结灵契", op="main-1")
    assert result.title == "主线奖励已领取"
    assert "初结灵契已完成。" in result.text()
    assert "修为 +0，灵石 +100" in result.text()
    assert "灵粮 +2" in result.text()
    assert "下一步：双灵相伴。" in result.text()
    assert player(game[1])["stones"] == before[0] + 100
    assert items(game[1])["spirit_food"] == before[1].get("spirit_food", 0) + 2
    assert claimed_ids(game) == ["main_01"]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='main_01'") == [
        {"progress": 1}
    ]

    listing = play("main_quests")
    assert "1. 初结灵契 · 已完成" in listing.text()
    assert "2. 双灵相伴 · 进行中 · 1/2" in listing.text()
    assert links(listing) == []


def test_claim_rejects_unmet_out_of_order_unknown_and_repeat(game, play):
    account(game, play)
    with pytest.raises(GameError, match="未找到该内容"):
        play("main_quest_claim", "不存在的步骤")
    with pytest.raises(GameError, match="按序推进"):
        play("main_quest_claim", "吐纳有成")
    play("main_quest_claim", "初结灵契", op="main-repeat")
    # 双灵相伴 is the current step now, but the player still owns a single pet.
    with pytest.raises(GameError, match="主线尚未达成"):
        play("main_quest_claim", "双灵相伴")
    with pytest.raises(GameError, match="已领取"):
        play("main_quest_claim", "初结灵契", op="main-repeat-again")
    assert claimed_ids(game) == ["main_01"]
    assert player(game[1])["stones"] == 200


def test_daily_reset_keeps_main_claim_but_clears_daily_rows(game, play):
    account(game, play)
    play("main_quest_claim", "初结灵契", op="main-day")
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', 'sign_once', 1, 1)")
    sql(game[1], "UPDATE players SET quest_day='2026-01-01'")
    play("quests")
    assert claimed_ids(game) == ["main_01"]
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='sign_once'")


def test_same_operation_replays_without_granting_twice(game, play):
    account(game, play)
    first = play("main_quest_claim", "初结灵契", op="main-replay")
    state = (player(game[1])["stones"], items(game[1]), claimed_ids(game))
    assert play("main_quest_claim", "初结灵契", op="main-replay", now=NOW + 1) == first
    assert (player(game[1])["stones"], items(game[1]), claimed_ids(game)) == state


def test_help_lists_the_main_quest_entries(game, play):
    guide = play("help", "秘境与关卡")
    assert "灵宠主线" in guide.text()
    assert "灵宠主线领奖 步骤名" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    account(game, play)
    listing = play("main_quests")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in listing.inline_commands}
    assert not linked & buttons
