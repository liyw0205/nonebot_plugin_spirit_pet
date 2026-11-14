import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import world_boss, world_boss_rank_rewards

from .support import items, player, player_uid, sql
from .test_commands import onebot_event

NOW = 1_800_000_000
WEEK = world_boss.week_ordinal(NOW)


def adopt(game, play, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW, op=f"adopt-{user}")


def contribution(game, user, amount, week=WEEK):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 0) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress, claimed=0",
        (user, f"{world_boss.THREAT_PREFIX}{week}", amount),
    )


def test_content_has_ordered_rank_rewards(game):
    rewards = game[0].content.world_boss_rank_rewards
    assert sorted(rewards) == [1, 3, 10]
    assert rewards[1].name == "首功名录"
    assert rewards[1].stones == 600
    assert rewards[10].stones == 120


def test_unregistered_page_is_read_only_and_routes_are_shared(game, play):
    page = play("world_boss_rank_rewards", user="ghost", now=NOW)
    assert page.title == "首领贡献榜"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []
    assert handlers._parse("灵宠首领榜") == ("world_boss_rank_rewards", "")
    assert handlers._parse("灵宠首领榜领奖 3") == ("world_boss_rank_rewards", "3")


def test_rank_uses_real_threat_rows_and_claims_each_threshold_once(game, play):
    for user in ("u1", "u2", "u3", "u4"):
        adopt(game, play, user)
    contribution(game, "u1", 40)
    contribution(game, "u2", 30)
    contribution(game, "u3", 20)
    contribution(game, "u4", 10)

    page = play("world_boss_rank_rewards", now=NOW)
    assert page.lines[2] == f"1. UID {player_uid(game[1], 'u1')} · 威胁贡献 40"
    assert "你的本周贡献：40 · 当前第 1 名。" in page.lines
    assert [link.command for link in page.inline_commands] == [
        "灵宠首领榜领奖 1", "灵宠首领榜领奖 3", "灵宠首领榜领奖 10",
    ]

    before = player(game[1])["stones"]
    first = play("world_boss_rank_rewards", "领奖 1", now=NOW, op="boss-rank-1")
    assert "首功名录" in first.text()
    assert player(game[1])["stones"] == before + 600
    assert items(game[1])["forge_ore"] >= 3
    assert sql(
        game[1],
        "SELECT progress, claimed FROM quest_progress WHERE quest_id=? AND user_id='u1'",
        (world_boss_rank_rewards.claim_id(WEEK, 1),),
    ) == [{"progress": 1, "claimed": 1}]
    assert play("world_boss_rank_rewards", "领奖 1", now=NOW, op="boss-rank-1") == first
    with pytest.raises(GameError, match="已领取"):
        play("world_boss_rank_rewards", "领奖 1", now=NOW, op="boss-rank-1-again")


def test_week_rollover_restarts_rank_and_old_claim_is_not_reused(game, play):
    adopt(game, play)
    contribution(game, "u1", 50)
    play("world_boss_rank_rewards", "领奖 1", now=NOW, op="week-old")
    next_week = NOW + 7 * 86400
    page = play("world_boss_rank_rewards", now=next_week)
    assert "本周贡献：0" in page.text()
    assert "尚未入榜" in page.text()
    with pytest.raises(GameError, match="尚无首领贡献"):
        play("world_boss_rank_rewards", "领奖 1", now=next_week, op="week-new")
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'world_boss_rank_reward_%'")
    assert rows == [{"quest_id": world_boss_rank_rewards.claim_id(WEEK, 1)}]


def test_empty_board_and_non_winner_have_specific_read_and_claim_boundaries(game, play):
    adopt(game, play)
    empty = play("world_boss_rank_rewards", now=NOW)
    assert "本周还没有首领贡献" in empty.text()
    assert "尚未入榜" in empty.text()
    with pytest.raises(GameError, match="尚无首领贡献"):
        play("world_boss_rank_rewards", "领奖 1", now=NOW, op="empty-claim")

    # A player outside the top ten can read the board but cannot claim any tier.
    for index in range(2, 12):
        adopt(game, play, f"u{index}")
        contribution(game, f"u{index}", 100 - index)
    contribution(game, "u1", 1)
    page = play("world_boss_rank_rewards", now=NOW)
    assert "当前第 11 名" in page.text()
    with pytest.raises(GameError, match="尚未进入前 1 名"):
        play("world_boss_rank_rewards", "领奖 1", now=NOW, op="non-winner-1")
    with pytest.raises(GameError, match="尚未进入前 3 名"):
        play("world_boss_rank_rewards", "领奖 3", now=NOW, op="non-winner-3")
    with pytest.raises(GameError, match="尚未进入前 10 名"):
        play("world_boss_rank_rewards", "领奖 10", now=NOW, op="non-winner-10")


def test_claimed_status_survives_reopen(game, play):
    adopt(game, play)
    contribution(game, "u1", 50)
    play("world_boss_rank_rewards", "领奖 1", now=NOW, op="restart-claim")
    reopened = type(game[0])(game[1].__class__(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    page = reopened.execute("u1", "world_boss_rank_rewards", "", "restart-page", NOW)
    assert "前 1 名 · 首功名录 · 灵石 600、锻灵矿 3、灵粮 2 · 已领取" in page.text()
    with pytest.raises(GameError, match="已领取"):
        reopened.execute("u1", "world_boss_rank_rewards", "领奖 1", "restart-repeat", NOW)


def test_concurrent_claims_allow_only_one_payout(game, play):
    adopt(game, play)
    contribution(game, "u1", 50)

    def attempt(operation):
        try:
            return ("ok", game[0].execute("u1", "world_boss_rank_rewards", "领奖 1", operation, NOW))
        except GameError as exc:
            return ("error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("concurrent-a", "concurrent-b")))
    assert [kind for kind, _ in results].count("ok") == 1
    assert [kind for kind, _ in results].count("error") == 1
    assert sql(
        game[1],
        "SELECT COUNT(*) AS count FROM quest_progress WHERE quest_id=? AND claimed=1",
        (world_boss_rank_rewards.claim_id(WEEK, 1),),
    )[0]["count"] == 1


def test_invalid_rank_and_failed_payout_leave_no_marker(game, play, monkeypatch):
    adopt(game, play)
    contribution(game, "u1", 20)
    before = (player(game[1])["stones"], items(game[1]), sql(
        game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'world_boss_rank_reward_%'"))
    with pytest.raises(GameError, match="仅有前 1、3、10"):
        play("world_boss_rank_rewards", "领奖 2", now=NOW, op="bad-rank")
    with pytest.raises(GameError, match="格式"):
        play("world_boss_rank_rewards", "领奖 1 extra", now=NOW, op="bad-format")

    def fail(*args, **kwargs):
        raise RuntimeError("injected reward failure")

    monkeypatch.setattr(world_boss_rank_rewards, "grant", fail)
    with pytest.raises(RuntimeError, match="injected"):
        play("world_boss_rank_rewards", "领奖 1", now=NOW, op="failed-payout")
    assert player(game[1])["stones"] == before[0]
    assert items(game[1]) == before[1]
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'world_boss_rank_reward_%'") == before[2]


def test_native_links_do_not_duplicate_buttons_and_onebot_parse_is_same(game, play, monkeypatch):
    adopt(game, play)
    contribution(game, "u1", 20)
    page = play("world_boss_rank_rewards", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", message["markdown"][0].data["markdown"].content)
    }
    assert not buttons & links
    assert "/灵宠首领榜领奖 1" in links
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    assert handlers._parse("!灵宠首领榜领奖 1") == ("world_boss_rank_rewards", "1")


def test_help_and_onebot_share_the_same_claim_entry(game, play, monkeypatch):
    guide = play("help", "秘境与关卡", now=NOW)
    assert "灵宠首领榜" in guide.text()
    assert "灵宠首领榜领奖 名次" in guide.text()

    service, store = game
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠领养 青鸾", 91), "!灵宠领养 青鸾")
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('12345', ?, 20, 0)",
                (f"{world_boss.THREAT_PREFIX}{world_boss.week_ordinal(time.time())}",),
            )
        await handlers._run(bot, onebot_event("!灵宠首领榜", 92), "!灵宠首领榜")
        listing = bot.send.call_args.args[1]
        assert "领取榜赏（!灵宠首领榜领奖 1）" in listing
        await handlers._run(bot, onebot_event("!灵宠首领榜领奖 1", 93), "!灵宠首领榜领奖 1")
        assert "首领榜赏" in bot.send.call_args.args[1]

    asyncio.run(run())
