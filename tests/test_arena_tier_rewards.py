import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import season_bounds

from .support import items, player, sql

NOW = 1_800_000_000
SEASON = season_bounds(NOW)[0]


def set_rating(game, score, season=SEASON, user="u1"):
    sql(game[1], "INSERT INTO season_entries(season_id,user_id,rating,wins,losses,draws) "
                 "VALUES (?,?,?,0,0,0) ON CONFLICT(season_id,user_id) "
                 "DO UPDATE SET rating=excluded.rating", (season, user, score))


def stones(game):
    return player(game[1])["stones"]


def test_every_tier_has_exactly_one_escalating_reward(game):
    content = game[0].content
    rewards = content.arena_tier_rewards
    assert set(rewards) == {tier.id for tier in content.arena.tiers}
    assert len(rewards) == 6
    ordered = [rewards[tier.id] for tier in content.arena.tiers]
    assert [reward.stones for reward in ordered] == [80, 160, 260, 380, 520, 700]
    assert all(later.stones > earlier.stones for earlier, later in zip(ordered, ordered[1:]))
    for reward in ordered:
        assert reward.stones > 0 or reward.items
        assert set(reward.items) <= set(content.items)
        assert all(amount > 0 for amount in reward.items.values())


def test_page_lists_tiers_with_states(game, play):
    play("adopt", "青鸾")
    page = play("arena_tier_rewards")
    assert page.title == f"灵宠段位奖励 · {SEASON}"
    assert "青云 · 0 分起 · 灵石 80 · 可领取" in page.text()
    assert "凌霄 · 1050 分起 · 灵石 160，锻灵矿 2 · 还差 50 分" in page.text()
    assert "归元 · 1450 分起 · 灵石 700，锻灵矿 10，血脉精华 4 · 还差 450 分" in page.text()
    assert f"赛季 {SEASON} · 当前积分 1000 · 当前档位 青云。" in page.text()
    assert [link.command for link in page.inline_commands] == ["灵宠段位领奖 青云"]


def test_claim_requires_the_rating_and_pays_once(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="积分不足"):
        play("arena_tier_claim", "凌霄")
    with pytest.raises(GameError, match="未找到该内容"):
        play("arena_tier_claim", "不存在的段位")
    before = stones(game)
    reply = play("arena_tier_claim", "青云")
    assert reply.title == "段位奖励已领取"
    assert stones(game) == before + 80
    assert "青云 · 0 分起 · 灵石 80 · 已领取" in play("arena_tier_rewards").text()
    with pytest.raises(GameError, match="已领取"):
        play("arena_tier_claim", "青云")
    assert stones(game) == before + 80


def test_reaching_a_higher_tier_unlocks_more_rewards(game, play):
    play("adopt", "青鸾")
    play("arena_tier_rewards")
    set_rating(game, 1260)
    page = play("arena_tier_rewards")
    assert "当前积分 1260 · 当前档位 星海" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠段位领奖 青云", "灵宠段位领奖 凌霄", "灵宠段位领奖 天阙", "灵宠段位领奖 星海",
    ]
    before = stones(game)
    play("arena_tier_claim", "星海")
    assert stones(game) == before + 380
    assert items(game[1])["forge_ore"] == 6 and items(game[1])["bloodline_essence"] == 2
    with pytest.raises(GameError, match="积分不足"):
        play("arena_tier_claim", "太虚")


def test_a_new_season_makes_the_rewards_claimable_again(game, play):
    play("adopt", "青鸾")
    play("arena_tier_claim", "青云")
    assert "已领取" in play("arena_tier_rewards").text()
    later = NOW + 31 * 86400
    next_season = season_bounds(later)[0]
    assert next_season != SEASON
    play("arena_tier_rewards", now=later)
    set_rating(game, 1000, season=next_season)
    page = play("arena_tier_rewards", now=later)
    assert page.title == f"灵宠段位奖励 · {next_season}"
    assert "青云 · 0 分起 · 灵石 80 · 可领取" in page.text()
    before = stones(game)
    play("arena_tier_claim", "青云", now=later)
    assert stones(game) == before + 80


def test_replayed_claim_returns_the_same_reply_without_paying_twice(game, play):
    play("adopt", "青鸾")
    before = stones(game)
    first = play("arena_tier_claim", "青云", op="tier-replay")
    again = play("arena_tier_claim", "青云", op="tier-replay")
    assert again == first
    assert stones(game) == before + 80
    assert len(sql(game[1], f"SELECT 1 FROM quest_progress WHERE quest_id='arena_tier_{SEASON}_qingyun'")) == 1


def test_unregistered_player_can_browse_without_an_account(game, play):
    page = play("arena_tier_rewards")
    assert page.title == "灵宠段位奖励"
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT 1 FROM players") == []
    with pytest.raises(GameError, match="先完成领养"):
        play("arena_tier_claim", "青云")


def test_objectives_hub_reports_the_tier_state(game, play):
    play("adopt", "青鸾")
    assert "段位奖励：可领 1 档（青云）· 当前积分 1000" in play("objectives").text()
    play("arena_tier_claim", "青云")
    assert "段位奖励：暂无可领 · 当前积分 1000" in play("objectives").text()


def test_help_lists_the_tier_entries(game, play):
    page = play("help", "对战与赛季")
    assert "灵宠段位奖励：查看本赛季各档位的达成奖励与领取状态。" in page.text()
    assert "灵宠段位领奖 段位名：领取本赛季已达成的段位奖励，每档每季一次。" in page.text()
