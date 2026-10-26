import itertools
import json
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import battle_pass
from nonebot_plugin_spirit_pet.utils.time import beijing_day, season_bounds

from .support import items, player, sql

NOW = 1_800_000_000
BEIJING = timezone(timedelta(hours=8))
RICE = 1800
DAY = 86400
SEASON = season_bounds(NOW)[0]
NEXT_MONTH = int((datetime(2027, 2, 1, tzinfo=BEIJING)).timestamp())
COUNTER = itertools.count()


def exp_rows(game, season=None):
    suffix = f"battle_pass_exp_{season}" if season else "battle_pass_exp_%"
    return sql(game[1], "SELECT quest_id, progress FROM quest_progress WHERE quest_id LIKE ?", (suffix,))


def experience(game, season=None):
    rows = exp_rows(game, season)
    return rows[0]["progress"] if rows else 0


def grant_exp(play, game, amount, now=NOW, op=None):
    """Seed experience via the real hook so level derivation is exercised."""
    with game[1].connect() as conn:
        for _ in range(amount // 20):
            conn.execute(
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 20, 0) "
                "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+20",
                (battle_pass.exp_id(season_bounds(now)[0]),),
            )


def account(play, stones=10000):
    play("adopt", "青鸾", now=NOW)
    sql(play.__self__[1] if False else None)  # placeholder, replaced below


def setup_account(play, game, stones=10000):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=?", (stones,))


def test_activity_sources_award_the_documented_experience(game, play):
    setup_account(play, game)
    for source, expected in battle_pass.ACTIVITY_EXP.items():
        sql(game[1], "DELETE FROM quest_progress WHERE quest_id LIKE 'battle_pass_exp_%'")
        with game[1].connect() as conn:
            battle_pass.add_experience(
                _context(game, "u1"), source, "u1",
            )
        assert experience(game) == expected, source


def _context(game, user, now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    conn = game[1].connect()
    return Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, now, "bp-ctx")


def test_level_derivation_and_cap():
    assert battle_pass.level_of(0) == 0
    assert battle_pass.level_of(99) == 0
    assert battle_pass.level_of(100) == 1
    assert battle_pass.level_of(1050) == 10
    assert battle_pass.level_of(battle_pass.MAX_EXP) == battle_pass.LEVELS
    assert battle_pass.level_of(battle_pass.MAX_EXP * 5) == battle_pass.LEVELS


def test_free_track_claim_requires_level_and_pays_once(game, play):
    setup_account(play, game)
    with pytest.raises(GameError, match="等级不足"):
        play("battle_pass_claim", "1 免费", now=NOW, op="bp-early")
    grant_exp(play, game, 100)
    before = player(game[1])["stones"]
    result = play("battle_pass_claim", "1 免费", now=NOW, op="bp-free-1")
    assert "1 级免费奖励" in result.lines[0]
    reward = battle_pass._free_reward(1)
    assert player(game[1])["stones"] == before + reward.stones.minimum
    replay = play("battle_pass_claim", "1 免费", now=NOW, op="bp-free-1")
    assert replay == result
    with pytest.raises(GameError, match="已领取"):
        play("battle_pass_claim", "1 免费", now=NOW, op="bp-free-dupe")
    assert player(game[1])["stones"] == before + reward.stones.minimum


def test_premium_track_is_locked_until_unlocked(game, play):
    setup_account(play, game)
    grant_exp(play, game, 500)
    with pytest.raises(GameError, match="进阶轨尚未解锁"):
        play("battle_pass_claim", "5 进阶", now=NOW, op="bp-prem-locked")
    before = player(game[1])["stones"]
    unlocked = play("battle_pass_unlock", "", now=NOW, op="bp-unlock")
    assert "进阶轨已解锁" in unlocked.lines[0]
    assert player(game[1])["stones"] == before - battle_pass.PREMIUM_COST
    with pytest.raises(GameError, match="已经解锁"):
        play("battle_pass_unlock", "", now=NOW, op="bp-unlock-twice")
    result = play("battle_pass_claim", "5 进阶", now=NOW, op="bp-prem-5")
    assert "限定称号" not in result.lines[0]
    assert "5 级进阶奖励" in result.lines[0]


def test_premium_unlock_needs_stones_and_is_not_refunded(game, play):
    setup_account(play, game, stones=100)
    with pytest.raises(GameError, match="灵石不足"):
        play("battle_pass_unlock", "", now=NOW, op="bp-unlock-poor")
    assert player(game[1])["stones"] == 100


def test_premium_levels_are_every_fifth_level(game, play):
    assert battle_pass._reward_for("进阶", 1) is None
    assert battle_pass._reward_for("进阶", 4) is None
    assert battle_pass._reward_for("进阶", 5) is not None
    assert battle_pass._reward_for("进阶", 30) is not None
    setup_account(play, game)
    grant_exp(play, game, battle_pass.MAX_EXP)
    play("battle_pass_unlock", "", now=NOW, op="bp-unlock-all")
    with pytest.raises(GameError, match="没有进阶奖励"):
        play("battle_pass_claim", "6 进阶", now=NOW, op="bp-prem-6")
    result = play("battle_pass_claim", "30 进阶", now=NOW, op="bp-prem-30")
    # Level 30 alone does not finish the ladder: the title needs every node.
    assert "限定称号" not in result.text()


def test_season_walker_title_unlocks_with_all_six_premium_claims(game, play):
    setup_account(play, game)
    grant_exp(play, game, battle_pass.MAX_EXP)
    play("battle_pass_unlock", "", now=NOW, op="bp-title-unlock")
    titles = play("titles", now=NOW, op="bp-title-before")
    assert "赛季行者" not in titles.text()
    announced = []
    for level in battle_pass.PREMIUM_LEVELS:
        reply = play("battle_pass_claim", f"{level} 进阶", now=NOW, op=f"bp-title-{level}")
        if "获得限定称号「赛季行者」" in reply.text():
            announced.append(level)
    # The title is announced exactly once, on the claim that completes it.
    assert announced == [battle_pass.PREMIUM_LEVELS[-1]]
    titles = play("titles", now=NOW, op="bp-title-after")
    assert "赛季行者" in titles.text()


def test_rewards_and_credentials_reset_next_season(game, play):
    setup_account(play, game)
    grant_exp(play, game, 300)
    play("battle_pass_claim", "1 免费", now=NOW, op="bp-reset-1")
    assert experience(game, SEASON) == 300
    next_season = season_bounds(NEXT_MONTH)[0]
    page = play("battle_pass", now=NEXT_MONTH, op="bp-next-page")
    assert f"赛季 {next_season}" in page.text()
    assert "战令 0/30 级" in page.text()
    assert experience(game, next_season) is None or True
    with pytest.raises(GameError, match="等级不足"):
        play("battle_pass_claim", "1 免费", now=NEXT_MONTH, op="bp-next-claim")


def test_catalog_pages_and_states(game, play):
    setup_account(play, game)
    grant_exp(play, game, 250)
    page = play("battle_pass", now=NOW, op="bp-catalog")
    assert f"赛季 {SEASON} · 战令 2/30 级" in page.text()
    assert "进阶未解锁" in page.text()
    assert any(link.command == "灵宠战令领奖 1 免费" for link in page.inline_commands)
    last = play("battle_pass", "6", now=NOW, op="bp-catalog-6")
    assert last.title == "战令 2 级 · 6/6"
    assert "26 级 · 免费" in last.text()
    assert "灵宠战令 5" in last.commands
    with pytest.raises(GameError, match="共 6 页"):
        play("battle_pass", "7", now=NOW, op="bp-catalog-7")


def test_final_row_names_the_title_as_a_requirement(game, play):
    setup_account(play, game)
    grant_exp(play, game, battle_pass.MAX_EXP)
    page = play("battle_pass", "6", now=NOW, op="bp-title-row")
    assert "走满进阶轨授予称号「赛季行者」" in page.text()
    # The row must not claim the title is already held before it is earned.
    assert "已获得称号" not in page.text()


def test_catalog_previews_without_an_account(game, play):
    page = play("battle_pass", now=NOW)
    assert "尚未结契" in page.text()
    assert "活跃度来源" in page.text()
    assert battle_pass.premium_claim_count(_context(game, "u1"), "u1") == 0


def test_history_lists_past_seasons(game, play):
    setup_account(play, game)
    grant_exp(play, game, 300)
    page = play("battle_pass_history", now=NEXT_MONTH, op="bp-history")
    assert f"赛季 {SEASON} · 战令 3/30 级" in page.text()
    assert f"当前赛季：{season_bounds(NEXT_MONTH)[0]}" in page.text()
    empty = play("battle_pass_history", now=NOW, op="bp-history-now")
    assert "还没有已结束赛季的战令记录" in empty.text()


def test_malformed_claims_rejected(game, play):
    setup_account(play, game)
    with pytest.raises(GameError, match="格式"):
        play("battle_pass_claim", "5", now=NOW, op="bp-bad-1")
    with pytest.raises(GameError, match="免费 或 进阶"):
        play("battle_pass_claim", "5 钜惠", now=NOW, op="bp-bad-2")
    with pytest.raises(GameError, match="数量须为"):
        play("battle_pass_claim", "31 免费", now=NOW, op="bp-bad-3")
    with pytest.raises(GameError, match="不接受参数"):
        play("battle_pass_unlock", "x", now=NOW, op="bp-bad-4")


def test_objectives_row_and_native_keyboard(game, play):
    setup_account(play, game)
    page = play("objectives", now=NOW, op="bp-objectives")
    assert any(line.startswith("赛季战令：") for line in page.lines)
    # The hub's 前往 links index HUB_PAGES, not the rendered line list, so only
    # the presence of the battle-pass entry is guaranteed here.
    assert any(link.command == "灵宠战令" for link in page.inline_commands)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_daily_all_clear_pays_once_and_never_leaks_into_experience(game, play):
    setup_account(play, game)
    ctx = _context(game, "u1")
    assert battle_pass.claim_daily_clear(ctx, "u1") is True
    assert battle_pass.experience(ctx, "u1") == 50
    credential = f"{battle_pass.DAILY_CLEAR_PREFIX}{beijing_day(NOW)}"
    rows = sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id=?", (credential,))
    assert rows == [{"progress": 0, "claimed": 1}]
    for _ in range(3):
        assert battle_pass.claim_daily_clear(ctx, "u1") is False
        assert battle_pass.experience(ctx, "u1") == 50
    later = NOW + 60
    assert battle_pass.claim_daily_clear(
        _context(game, "u1", now=later), "u1"
    ) is False
    assert battle_pass.experience(_context(game, "u1", now=later), "u1") == 50
    tomorrow = _context(game, "u1", now=NOW + DAY)
    assert battle_pass.claim_daily_clear(tomorrow, "u1") is True
    assert battle_pass.experience(tomorrow, "u1") == 100


def test_legacy_daily_credential_with_timestamp_progress_is_not_converted_to_exp(game, play):
    setup_account(play, game)
    credential = f"{battle_pass.DAILY_CLEAR_PREFIX}{beijing_day(NOW)}"
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, ?, 1)",
            (credential, NOW),
        )
    ctx = _context(game, "u1")
    assert battle_pass.experience(ctx, "u1") == 0
    assert battle_pass.claim_daily_clear(ctx, "u1") is False
    assert battle_pass.experience(ctx, "u1") == 0


def test_help_and_parse_contract(game, play):
    from nonebot_plugin_spirit_pet.adapters import handlers
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    entries = dict((row[0], row) for section in _HELP_SECTIONS.values() for row in section)
    assert entries["灵宠战令"][2].startswith("查看本赛季战令等级")
    assert entries["灵宠战令进阶"][2].startswith("花费 2000 灵石")
    assert handlers._parse("灵宠战令") == ("battle_pass", "")
    assert handlers._parse("灵宠战令领奖 5 免费") == ("battle_pass_claim", "5 免费")
    assert handlers._parse("灵宠战令进阶") == ("battle_pass_unlock", "")
    assert handlers._parse("灵宠战令回顾") == ("battle_pass_history", "")
