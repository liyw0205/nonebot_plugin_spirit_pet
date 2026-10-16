import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

STARTER = "青鸾"
RARE = "玄武"


def row(reply, name):
    return next(text for text in reply.lines if text.startswith(name + " ·"))


def stones(game):
    return player(game[1])["stones"]


def test_every_species_has_exactly_one_non_empty_reward(game):
    content = game[0].content
    rewards = content.codex_rewards
    assert set(rewards) == set(content.species)
    assert len(rewards) == 27
    for species_id, reward in rewards.items():
        assert reward.species == species_id
        assert reward.stones > 0 or reward.items
        assert set(reward.items) <= set(content.items)
        assert all(amount > 0 for amount in reward.items.values())


def test_rewards_escalate_with_rarity(game):
    rewards = game[0].content.codex_rewards
    assert rewards["qingluan"].stones == 60 and rewards["qingluan"].items == {"spirit_food": 1}
    assert rewards["jiaolong"].stones == 100 and rewards["jiaolong"].items == {"spirit_food": 2}
    assert rewards["xuehu"].stones == 150 and rewards["xuehu"].items == {"bloodline_essence": 1}
    assert rewards["xuanwu"].stones == 240
    assert rewards["xuanwu"].items == {"bloodline_essence": 1, "spirit_food": 2}
    ordered = [rewards[key].stones for key in ("qingluan", "jiaolong", "xuehu", "xuanwu")]
    assert ordered == sorted(ordered) and len(set(ordered)) == len(ordered)


def test_page_lists_species_with_states_and_pages(game, play):
    play("adopt", STARTER)
    total = len(game[0].content.species)
    first = play("codex")
    assert first.title == "灵宠图鉴奖励 1/6"
    assert len([text for text in first.lines if "·" in text]) == 5
    assert row(first, STARTER).endswith("可领取")
    assert row(first, "玄狐").endswith("未收集")
    assert first.lines[-1] == f"共 {total} 族，已收集 1 族，尚有 1 族可领取。"
    assert [link.command for link in first.inline_commands] == ["灵宠图鉴领奖 青鸾"]
    last = play("codex", "6")
    assert last.title == "灵宠图鉴奖励 6/6"
    assert len([text for text in last.lines if "·" in text]) == 2
    with pytest.raises(GameError, match="共 6 页"):
        play("codex", "7")


def test_uncollected_species_cannot_be_claimed(game, play):
    play("adopt", STARTER)
    with pytest.raises(GameError, match="尚未收得玄武"):
        play("codex_claim", RARE)


def test_unknown_species_name_is_rejected(game, play):
    play("adopt", STARTER)
    with pytest.raises(GameError, match="未找到该内容"):
        play("codex_claim", "不存在的灵宠")


def test_claiming_a_collected_species_grants_once(game, play):
    play("adopt", STARTER)
    before = stones(game)
    reply = play("codex_claim", STARTER)
    assert reply.title == "图鉴收集奖励"
    assert "青鸾收集奖励已领取" in reply.text()
    assert stones(game) == before + 60
    assert items(game[1])["spirit_food"] == game[0].content.rules.starter_items["spirit_food"] + 1
    assert row(play("codex"), STARTER).endswith("已领取")
    assert "尚有 0 族可领取" in play("codex").lines[-1]
    with pytest.raises(GameError, match="已领取"):
        play("codex_claim", STARTER)
    assert stones(game) == before + 60


def test_sealed_pet_still_counts_as_collected(game, play):
    play("adopt", STARTER)
    sql(game[1], "UPDATE pets SET archived=1 WHERE user_id='u1'")
    assert row(play("codex"), STARTER).endswith("可领取")
    play("codex_claim", STARTER)
    assert row(play("codex"), STARTER).endswith("已领取")


def test_replayed_operation_returns_the_same_reply_without_paying_twice(game, play):
    play("adopt", STARTER)
    before = stones(game)
    first = play("codex_claim", STARTER, op="codex-replay")
    again = play("codex_claim", STARTER, op="codex-replay")
    assert again == first
    assert stones(game) == before + 60
    assert len(sql(game[1], "SELECT 1 FROM quest_progress WHERE quest_id='codex_qingluan'")) == 1


def test_unregistered_player_can_browse_without_an_account(game, play):
    page = play("codex")
    assert page.title == "灵宠图鉴奖励"
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT 1 FROM players") == []
    with pytest.raises(GameError, match="先完成领养"):
        play("codex_claim", STARTER)


def test_objectives_hub_reports_the_codex_state(game, play):
    play("adopt", STARTER)
    hub = play("objectives")
    assert "图鉴奖励：可领 1 族（青鸾）· 已领取 0/27 族" in hub.text()
    play("codex_claim", STARTER)
    assert "图鉴奖励：暂无可领 · 已领取 1/27 族" in play("objectives").text()


def test_help_lists_the_codex_entries(game, play):
    page = play("help", "身份与收集")
    assert "灵宠图鉴奖励：查看各族的一次性收集奖励与领取状态。" in page.text()
    assert "灵宠图鉴领奖 种族名：领取已收得种族的一份收集奖励。" in page.text()
