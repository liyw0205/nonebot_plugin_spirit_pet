import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay.arena import common, scoring, seasons
from nonebot_plugin_spirit_pet.gameplay.combat import Battle
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day

from .support import items, player, sql


def stamp(year, month, day=1, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=BEIJING).timestamp())


JAN = stamp(2028, 1)
FEB = stamp(2028, 2)
OWNER = "ladder-owner"
OPPONENTS = 8


def register(play, count=OPPONENTS + 1):
    for index in range(count):
        user = OWNER if index == 0 else f"ladder-opponent-{index}"
        play("adopt", "青鸾", user=user, now=JAN)


def invoke(game, handler, arg="", now=JAN, user=OWNER, operation=None):
    operation = operation or str(uuid4())

    def run(conn):
        repo = Repository(conn)
        ctx = Context(repo, game[0].content, game[0].config, game[0].rng, user, now, operation)
        reply = handler(ctx, arg)
        repo.save()
        return reply

    return game[1].transact(user, operation, now, run)


def record(game, opponent, winner=0, now=JAN, operation=None):
    """Record one ranked result for the owner, mirroring the real settlement path."""

    def run(ctx, arg):
        season = common.current_season(ctx)
        first, second = ctx.player(OWNER), ctx.player(opponent)
        delta, lines = scoring.settle_ranked(ctx, season, opponent, Battle(winner, 1, (), ({}, {})))
        reply = Reply("score", lines)
        ctx.repo.conn.execute(
            "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,target_pet_id,"
            "winner_id,day,played_at,delta,operation_id,reply) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (season.season_id, OWNER, opponent, first.active_pet_id, second.active_pet_id,
             None if winner == -1 else (OWNER, opponent)[winner], beijing_day(now), now, delta,
             ctx.operation_id, json.dumps(asdict(reply), ensure_ascii=False)),
        )
        return reply

    return invoke(game, run, now=now, operation=operation)


def climb(game, wins):
    """Win `wins` ranked matches, spreading them so each pair stays inside the per-season limit."""
    for index in range(wins):
        record(game, f"ladder-opponent-{index % OPPONENTS + 1}", winner=0, now=JAN + index * 60)


def rating(game, season_id="2028-01", user=OWNER):
    rows = sql(game[1], "SELECT rating FROM season_entries WHERE season_id=? AND user_id=?",
               (season_id, user))
    return rows[0]["rating"] if rows else None


def status(game, now=JAN):
    return invoke(game, seasons.status, now=now)


def test_ladder_has_six_unique_ordered_tiers(game):
    tiers = game[0].content.arena.tiers
    assert [tier.name for tier in tiers] == ["青云", "凌霄", "天阙", "星海", "太虚", "归元"]
    assert [tier.minimum_rating for tier in tiers] == [0, 1050, 1150, 1250, 1350, 1450]
    assert len({tier.id for tier in tiers}) == len(tiers)
    assert len({tier.name for tier in tiers}) == len(tiers)
    assert tiers[0].minimum_rating == 0
    assert all(later.minimum_rating > earlier.minimum_rating for earlier, later in zip(tiers, tiers[1:]))


def test_ladder_rewards_escalate_with_the_ladder(game):
    tiers = game[0].content.arena.tiers
    assert [tier.stones for tier in tiers] == [300, 600, 1000, 1400, 1900, 2500]
    assert all(later.stones > earlier.stones for earlier, later in zip(tiers, tiers[1:]))
    assert [tier.items["forge_ore"] for tier in tiers] == [3, 6, 10, 13, 16, 20]
    essence = [tier.items.get("bloodline_essence", 0) for tier in tiers]
    assert essence == [0, 2, 4, 5, 6, 8]
    assert all(later >= earlier for earlier, later in zip(essence, essence[1:]))
    assert all(set(tier.items) <= set(game[0].content.items) for tier in tiers)


@pytest.mark.parametrize(("score", "expected"), [
    (0, "青云"), (1049, "青云"), (1050, "凌霄"), (1149, "凌霄"), (1150, "天阙"),
    (1249, "天阙"), (1250, "星海"), (1349, "星海"), (1350, "太虚"), (1449, "太虚"),
    (1450, "归元"), (2000, "归元"),
])
def test_tier_boundaries_map_to_the_right_tier(game, play, score, expected):
    register(play)
    status(game)
    sql(game[1], "INSERT INTO season_entries(season_id,user_id,rating,wins,losses,draws) "
                 "VALUES ('2028-01',?,?,0,0,0) ON CONFLICT(season_id,user_id) "
                 "DO UPDATE SET rating=excluded.rating", (OWNER, score))
    reply = status(game)
    assert f"当前积分档位：{expected}" in reply.text()


def test_rules_pages_cover_the_six_tiers_in_two_pages(game, play):
    register(play)
    first = invoke(game, seasons.catalog, "规则")
    assert "1/2" in first.title
    assert all(name in first.text() for name in ("青云", "凌霄", "天阙", "星海"))
    assert "归元" not in first.text()
    assert "灵宠赛季奖励 规则 2028-01 分页 2" in first.commands
    last = invoke(game, seasons.catalog, "规则 分页 2")
    assert "2/2" in last.title
    assert all(name in last.text() for name in ("太虚", "归元"))
    assert "青云" not in last.text()
    assert "灵宠赛季奖励 规则 2028-01 分页 1" in last.commands
    with pytest.raises(GameError, match="页"):
        invoke(game, seasons.catalog, "规则 分页 3")


def test_season_claim_pays_the_new_top_tier(game, play):
    register(play)
    climb(game, 23)
    assert rating(game) == 1460
    before = player(game[1], OWNER)["stones"]
    reply = invoke(game, seasons.claim, "2028-01", now=FEB)
    assert "归元" in reply.text()
    assert player(game[1], OWNER)["stones"] == before + 2500
    bag = items(game[1], OWNER)
    assert bag["forge_ore"] == 20 and bag["bloodline_essence"] == 8


def test_season_claim_pays_a_mid_new_tier(game, play):
    register(play)
    climb(game, 13)
    assert rating(game) == 1260
    before = player(game[1], OWNER)["stones"]
    reply = invoke(game, seasons.claim, "2028-01", now=FEB)
    assert "星海" in reply.text() and "归元" not in reply.text()
    assert player(game[1], OWNER)["stones"] == before + 1400
    bag = items(game[1], OWNER)
    assert bag["forge_ore"] == 13 and bag["bloodline_essence"] == 5


def test_claim_stays_idempotent_under_concurrent_replays(game, play):
    register(play)
    climb(game, 23)
    before = player(game[1], OWNER)["stones"]

    def attempt(_):
        try:
            invoke(game, seasons.claim, "2028-01", now=FEB)
            return "claimed"
        except GameError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("claimed") == 1
    assert player(game[1], OWNER)["stones"] == before + 2500
    assert len(sql(game[1], "SELECT 1 FROM season_claims WHERE user_id=?", (OWNER,))) == 1
