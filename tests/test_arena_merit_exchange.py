"""Current-season ranked-win merit exchange contracts."""

import asyncio
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.arena_merit_content import ArenaMeritOffer
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.arena import merit_exchange as arena_merit_exchange
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import BEIJING, beijing_day, season_bounds

from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000  # 2027-01-15, matching the OneBot event fixture


def setup(game, play):
    play("adopt", "青鸾", now=NOW, user="u1", op="merit-adopt-1")
    play("adopt", "玄狐", now=NOW, user="u2", op="merit-adopt-2")
    sql(game[1], "UPDATE pets SET realm=1")
    play("season", now=NOW, user="u1", op="merit-season")


def seed_result(game, *, challenger="u1", target="u2", winner="u1", index=0, now=NOW):
    season = season_bounds(now)[0]
    challenger_pet = sql(
        game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id LIMIT 1", (challenger,)
    )[0]["pet_id"]
    target_pet = sql(
        game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id LIMIT 1", (target,)
    )[0]["pet_id"]
    sql(
        game[1],
        "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, "
        "winner_id, day, played_at, delta, operation_id, reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            season, challenger, target, challenger_pet, target_pet, winner,
            beijing_day(now), now + index, 0 if winner is None else 20,
            f"merit-seed-{challenger}-{target}-{index}",
            json.dumps({"title": "fixture", "lines": [], "commands": []}),
        ),
    )


def spent_row(game, season=None):
    season = season or season_bounds(NOW)[0]
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (arena_merit_exchange.spent_key(season),),
    )
    return rows[0]["progress"] if rows else 0


def test_content_is_ordered_and_references_real_usable_rewards(game):
    offers = arena_merit_exchange.offers(SimpleNamespace(content=game[0].content))
    assert [offer.name for offer in offers] == ["战备灵粮", "锻灵矿包", "论剑灵石袋", "破境丹", "血脉精华"]
    assert all(offer.cost > 0 for offer in offers)
    assert all(item_id in game[0].content.items for offer in offers for item_id in offer.items)


def test_offer_model_and_catalog_reject_broken_content(tmp_path):
    with pytest.raises(ValueError, match="must not be empty"):
        ArenaMeritOffer.model_validate({"id": "empty", "name": "空兑换", "description": "测试", "cost": 1})
    data = tmp_path / "data"
    shutil.copytree("src/plugins/nonebot_plugin_spirit_pet/data", data)
    path = data / "arena_merit_exchange.json"
    path.write_text(path.read_text().replace('"spirit_food"', '"ghost_item"', 1))
    with pytest.raises(ValueError, match="unknown"):
        Catalog.load(data)


def test_unregistered_preview_is_read_only(game, play):
    page = play("arena_merit_exchange", user="ghost", now=NOW)
    assert page.title == "论剑战勋兑换"
    assert "只读预览" in page.text()
    assert page.inline_commands == ()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='ghost'") == []
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_only_active_ranked_wins_earn_current_season_merit(game, play):
    setup(game, play)
    seed_result(game, index=1)
    seed_result(game, index=2)
    seed_result(game, index=3, winner=None)
    seed_result(game, challenger="u2", target="u1", winner="u1", index=4)
    page = play("arena_merit_exchange", now=NOW + 10)
    assert "赛季 2027-01 · 战勋可用 2（获得 2，已用 0）" in page.text()
    assert "主动论剑胜场" in page.text()
    assert "灵宠论剑战勋" in play("objectives", now=NOW + 11).text()


def test_exchange_credits_reward_and_replay_survives_restart(game, play):
    setup(game, play)
    for index in range(4):
        seed_result(game, index=index)
    before = items(game[1]).get("forge_ore", 0)
    first = play("arena_merit_exchange", "兑换 锻灵矿包", now=NOW, op="merit-exchange")
    assert "消耗 4 枚战勋" in first.text()
    assert items(game[1])["forge_ore"] == before + 1
    assert spent_row(game) == 4
    restarted = type(game[0])(game[1], game[0].config, game[0].rng)
    replay = restarted.execute("u1", "arena_merit_exchange", "兑换 锻灵矿包", "merit-exchange", NOW + 86400)
    assert replay == first
    assert spent_row(game) == 4


def test_batch_stone_exchange_and_cross_season_reset(game, play):
    setup(game, play)
    for index in range(12):
        seed_result(game, index=index)
    before = player(game[1])["stones"]
    play("arena_merit_exchange", "兑换 论剑灵石袋 2", now=NOW, op="merit-stones")
    assert player(game[1])["stones"] == before + 240
    assert spent_row(game) == 12
    february = int(datetime(2027, 2, 2, 12, tzinfo=BEIJING).timestamp())
    page = play("arena_merit_exchange", now=february)
    assert "赛季 2027-02 · 战勋可用 0（获得 0，已用 0）" in page.text()
    with pytest.raises(GameError, match="战勋不足"):
        play("arena_merit_exchange", "兑换 战备灵粮", now=february, op="merit-empty-next-season")


def test_insufficient_bad_arguments_and_missing_reward_do_not_write(game, play):
    setup(game, play)
    seed_result(game, index=0)
    before = (spent_row(game), items(game[1]), player(game[1])["stones"])
    with pytest.raises(GameError, match="战勋不足"):
        play("arena_merit_exchange", "兑换 破境丹", now=NOW, op="merit-too-expensive")
    with pytest.raises(GameError, match="序号需在 1-5"):
        play("arena_merit_exchange", "兑换 6", now=NOW, op="merit-bad-index")
    with pytest.raises(GameError, match="数量"):
        play("arena_merit_exchange", "兑换 战备灵粮 0", now=NOW, op="merit-bad-quantity")
    offer = arena_merit_exchange.offers(SimpleNamespace(content=game[0].content))[0]
    game[0].content.arena_merit_exchange[offer.id] = offer.model_copy(update={"items": {"ghost_item": 1}})
    page = play("arena_merit_exchange", now=NOW, op="merit-missing-page")
    assert "奖励待修复" in page.text()
    with pytest.raises(GameError, match="奖励定义缺失"):
        play("arena_merit_exchange", "兑换 1", now=NOW, op="merit-missing")
    assert (spent_row(game), items(game[1]), player(game[1])["stones"]) == before


def test_concurrent_exchange_cannot_overspend(game, play):
    setup(game, play)
    seed_result(game, index=0)
    seed_result(game, index=1)

    def attempt(index):
        try:
            return play("arena_merit_exchange", "兑换 战备灵粮", now=NOW, op=f"merit-concurrent-{index}")
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    assert spent_row(game) == 2


def test_reward_write_failure_rolls_back_and_retry_succeeds(game, play, monkeypatch):
    setup(game, play)
    seed_result(game, index=0)
    seed_result(game, index=1)
    original = Repository.add_item

    def fail(self, user_id, item_id, amount):
        raise RuntimeError("injected merit reward failure")

    monkeypatch.setattr(Repository, "add_item", fail)
    with pytest.raises(RuntimeError, match="injected merit reward failure"):
        play("arena_merit_exchange", "兑换 战备灵粮", now=NOW, op="merit-retry")
    assert spent_row(game) == 0
    monkeypatch.setattr(Repository, "add_item", original)
    reply = play("arena_merit_exchange", "兑换 战备灵粮", now=NOW, op="merit-retry")
    assert "兑换成功" in reply.text()
    assert spent_row(game) == 2


def test_help_native_and_onebot_share_the_same_entry(game, play, monkeypatch):
    assert handlers._parse("灵宠论剑战勋 兑换 1") == ("arena_merit_exchange", "兑换 1")
    assert "灵宠论剑战勋" in play("help", "对战与赛季").text()
    setup(game, play)
    seed_result(game, index=0)
    page = play("arena_merit_exchange", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert not buttons & {link.command for link in page.inline_commands}

    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config())
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("灵宠论剑战勋", 901), "灵宠论剑战勋")

    asyncio.run(run())
    assert "只读预览" in bot.send.call_args.args[1]
    assert "mqqapi://" not in bot.send.call_args.args[1]
