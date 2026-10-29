"""Achievement point shop: derived balance, offers, redemption and refusals."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.achievement_shop_content import AchievementOffer
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import achievement_shop

from .support import items, player, sql

NOW = 1_800_000_000
POINTS = 10


def offers(game):
    return sorted(game[0].content.achievement_shop.values(), key=lambda offer: offer.cost)


def spent(game, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id='ach_points_spent'",
        (user,),
    )
    return rows[0]["progress"] if rows else 0


def claims(game, user="u1"):
    return sql(game[1], "SELECT COUNT(*) AS amount FROM achievement_claims WHERE user_id=?", (user,))[0]["amount"]


def seed_claims(game, count, user="u1", offset=0):
    """Insert `count` claim rows so the derived point balance grows by count * POINTS."""
    for index in range(offset, offset + count):
        sql(
            game[1],
            "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at,"
            " reward_snapshot, reply) VALUES (?, ?, ?, ?, '{}', 'seed')",
            (user, f"seed_{user}_{index}", f"seed-op-{user}-{index}", NOW),
        )


def ready(game, play, points=POINTS):
    play("adopt", "青鸾")
    play("achievement_claim", "初结灵契", op="first-claim")
    extra = points // POINTS - 1
    if extra > 0:
        seed_claims(game, extra)
    assert achievement_shop.balance(_ctx(game)) == points


def _ctx(game):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    with game[1].connect() as conn:
        return Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-points")


def test_points_rule_and_offers_are_defined(game):
    assert game[0].content.rules.achievement_points.per_claim == POINTS
    listed = offers(game)
    assert [offer.id for offer in listed] == [
        "food_bundle", "sunstone_pouch", "pill_single", "ore_pair", "essence_single", "grand_cache",
    ]
    assert [offer.cost for offer in listed] == [40, 50, 60, 70, 90, 220]
    assert all(item in game[0].content.items for offer in listed for item in offer.reward.items)


def test_offer_validation_rejects_broken_offers():
    base = {"id": "x", "name": "测试", "description": "测试", "cost": 10,
            "reward": {"stones": 100, "items": {}}}
    assert AchievementOffer.model_validate(base).cost == 10
    with pytest.raises(ValueError, match="must not be empty"):
        AchievementOffer.model_validate({**base, "reward": {"stones": 0, "items": {}}})
    with pytest.raises(ValueError):
        AchievementOffer.model_validate({**base, "cost": 0})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("achievement_shop", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert claims(game, "ghost") == 0


def test_points_are_zero_before_any_claim(game, play):
    play("adopt", "青鸾")
    page = play("achievement_shop")
    assert "成就点：可用 0（累计 0，已用 0）" in page.text()
    assert page.inline_commands == ()
    assert spent(game) == 0


def test_a_claim_grants_points(game, play):
    play("adopt", "青鸾")
    play("achievement_claim", "初结灵契", op="first-claim")
    page = play("achievement_shop")
    assert f"成就点：可用 {POINTS}（累计 {POINTS}，已用 0）" in page.text()
    assert "1. 灵粮包 · 40 点 · 灵粮 5 · 还差 30 点" in page.text()
    assert page.inline_commands == ()


def test_page_lists_every_offer_and_links_only_affordable_ones(game, play):
    ready(game, play, points=100)
    page = play("achievement_shop")
    listed = offers(game)
    for index, offer in enumerate(listed, 1):
        assert f"{index}. {offer.name} · {offer.cost} 点 ·" in page.text()
    affordable = [index for index, offer in enumerate(listed, 1) if offer.cost <= 100]
    assert [link.command for link in page.inline_commands] == [
        f"灵宠成就商店 兑换 {index}" for index in affordable
    ]
    assert page.text().count("可兑换") == len(affordable)
    assert page.commands == ("灵宠成就商店", "灵宠成就", "灵宠目标")


def test_redeeming_items_charges_points_and_credits_the_bag(game, play):
    ready(game, play, points=100)
    stones = player(game[1])["stones"]
    before = items(game[1]).get("spirit_food", 0)
    reply = play("achievement_shop", "兑换 1", op="redeem-1")
    assert reply.title == "成就点兑换"
    assert "消耗 40 点成就点" in reply.text()
    assert "灵粮 5" in reply.text()
    assert player(game[1])["stones"] == stones
    assert items(game[1])["spirit_food"] == before + 5
    assert spent(game) == 40
    assert f"可用 {100 - 40}" in reply.text()


def test_redeeming_the_stones_offer_credits_stones(game, play):
    ready(game, play, points=100)
    stones = player(game[1])["stones"]
    play("achievement_shop", "兑换 灵石袋", op="redeem-stones")
    assert player(game[1])["stones"] == stones + 500
    assert spent(game) == 50


def test_repeat_redemption_is_additive(game, play):
    ready(game, play, points=100)
    before = items(game[1]).get("spirit_food", 0)
    play("achievement_shop", "兑换 1", op="r1")
    play("achievement_shop", "兑换 1", op="r2")
    assert items(game[1])["spirit_food"] == before + 10
    assert spent(game) == 80


def test_insufficient_points_are_refused_before_any_write(game, play):
    ready(game, play, points=POINTS)
    stones = player(game[1])["stones"]
    food = items(game[1]).get("spirit_food", 0)
    with pytest.raises(GameError, match="成就点不足"):
        play("achievement_shop", "兑换 厚藏")
    assert (spent(game), player(game[1])["stones"], items(game[1]).get("spirit_food", 0)) == (
        0, stones, food,
    )


def test_unknown_index_and_name_are_refused(game, play):
    ready(game, play, points=100)
    with pytest.raises(GameError, match="序号需在 1-6 之间"):
        play("achievement_shop", "兑换 7")
    with pytest.raises(GameError, match="未找到|请检查"):
        play("achievement_shop", "兑换 不存在")
    with pytest.raises(GameError, match="格式"):
        play("achievement_shop", "兑换")
    with pytest.raises(GameError, match="格式"):
        play("achievement_shop", "额外")
    assert spent(game) == 0


def test_missing_item_definition_refuses_without_charge(game, play, monkeypatch):
    ready(game, play, points=100)
    offer = offers(game)[0]
    broken = offer.model_copy(
        update={"reward": offer.reward.model_copy(update={"items": {"ghost_item": 1}})}
    )
    monkeypatch.setitem(game[0].content.achievement_shop, offer.id, broken)
    with pytest.raises(GameError, match="物品定义缺失"):
        play("achievement_shop", "兑换 1")
    assert spent(game) == 0


def test_same_operation_replays_without_a_second_charge(game, play):
    ready(game, play, points=100)
    first = play("achievement_shop", "兑换 1", op="same")
    food = items(game[1])["spirit_food"]
    again = play("achievement_shop", "兑换 1", op="same")
    assert again.text() == first.text()
    assert items(game[1])["spirit_food"] == food
    assert spent(game) == 40


def test_points_and_spending_survive_a_restart(game, play):
    ready(game, play, points=100)
    play("achievement_shop", "兑换 1", op="persist")
    page = play("achievement_shop")
    assert "已用 40" in page.text()
    assert spent(game) == 40


def test_new_claims_keep_growing_the_balance_after_spending(game, play):
    ready(game, play, points=100)
    play("achievement_shop", "兑换 1", op="grow")
    assert "可用 60" in play("achievement_shop").text()
    seed_claims(game, 10, offset=10)
    assert "可用 160（累计 200，已用 40）" in play("achievement_shop").text()


def test_objective_help_and_parse(game, play):
    ready(game, play, points=100)
    assert "成就点：可用 100（累计 100）" in play("objectives").text()
    assert "灵宠成就商店" in play("help", "身份与收集").text()
    assert handlers._parse("灵宠成就商店") == ("achievement_shop", "")
    assert handlers._parse("灵宠成就商店 兑换 1") == ("achievement_shop", "兑换 1")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play, points=100)
    page = play("achievement_shop")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4
