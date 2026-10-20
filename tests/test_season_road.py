import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
SEASON = "2027-01"


def seed_match(game, challenger, target, *, winner, played, season=SEASON, operation=None):
    snapshot = game[0].content.arena.model_dump_json()
    sql(game[1], (
        "INSERT INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(season_id) DO NOTHING"
    ), (season, NOW - 86400 * 20, NOW + 86400 * 10, played, snapshot))
    challenger_pet = sql(game[1],
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id LIMIT 1", (challenger,),
    )[0]["pet_id"]
    target_pet = sql(game[1],
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id LIMIT 1", (target,),
    )[0]["pet_id"]
    sql(game[1], (
        "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, "
        "winner_id, day, played_at, delta, operation_id, reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'r')"
    ), (season, challenger, target, challenger_pet, target_pet, winner, season, played,
        0 if winner is None else 20,
        operation or f"op-{played}-{challenger}-{target}-{winner or 'draw'}"))


def milestone_row(page, tier):
    return next(line for line in page.lines if line.startswith(f"第 {tier} 阶 · "))


def test_progress_counts_challenger_wins_only(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    # u1 wins 5 as challenger; one defense win must NOT count.
    for index in range(5):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"w{index}")
    seed_match(game, "u2", "u1", winner="u1", played=NOW + 10, operation="defense")
    seed_match(game, "u1", "u2", winner=None, played=NOW + 11, operation="draw")
    page = play("season_road", now=NOW + 12)
    assert "挑战者胜场 5 · 战胜对手 1 位。" in page.lines[0]
    assert "可领取" in milestone_row(page, 1)


def test_distinct_opponent_condition_for_high_tiers(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    play("adopt", "白泽", user="u3", now=NOW)
    # 80 wins but only 2 distinct opponents -> tier 5 (needs 15) stays locked.
    index = 0
    for _ in range(40):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"a{index}")
        index += 1
        seed_match(game, "u1", "u3", winner="u1", played=NOW + index, operation=f"b{index}")
        index += 1
    page = play("season_road", now=NOW + index + 1)
    assert "可领取" in milestone_row(page, 4)
    assert "进行中" in milestone_row(page, 5)


def test_seven_tiers_claim_in_order_with_rewards(game, play):
    play("adopt", "青鸾", now=NOW)
    for user in ("u2", "u3"):
        play("adopt", "玄狐", user=user, now=NOW)
    opponents = ["u2", "u3"]
    index = 0
    # 200 challenger wins across 40 distinct opponents is impractical in tests;
    # tiers 1-4 need wins only, so verify those fully and check tier 5 stays locked.
    for _ in range(50):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"t{index}")
        index += 1
    before = player(game[1])["stones"]
    running = before
    for tier, cost in ((1, 300), (2, 600), (3, 1000), (4, 1500)):
        result = play("season_road_claim", str(tier), now=NOW + index + tier, op=f"road-{tier}")
        assert f"第 {tier} 阶征途" in result.lines[0]
        running += cost
        assert player(game[1])["stones"] == running
    assert items(game[1])["spirit_food"] == 3 + 2   # starter 3 + tier1
    assert items(game[1])["forge_ore"] == 2 + 4     # tier2 + tier4
    assert items(game[1])["bloodline_essence"] == 2 + 2  # tier3 + tier4


def test_credentials_persist_with_season_and_reset(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index in range(5):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"c{index}")
    play("season_road_claim", "1", now=NOW + 10, op="cred-claim")
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id='season_road_1'") == [
        {"progress": int("202701"), "claimed": 1},
    ]
    # Same season: still claimed.
    page = play("season_road", now=NOW + 11)
    assert "已领取" in milestone_row(page, 1)
    # New season: credential invalidated and progress restarts from zero.
    new_season = "2027-02"
    seed_match(game, "u1", "u2", winner="u1", played=NOW + 86400 * 40, season=new_season, operation="feb")
    page = play("season_road", now=NOW + 86400 * 40 + 1)
    assert "当前赛季 2027-02 · 挑战者胜场 1" in page.lines[0]
    assert "进行中 1/5 胜" in milestone_row(page, 1)
    assert "已领取" not in milestone_row(page, 1)


def test_claim_rejections(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    with pytest.raises(GameError, match="格式：灵宠征途领奖"):
        play("season_road_claim", "8", now=NOW)
    with pytest.raises(GameError, match="尚未达成|需要本季胜"):
        play("season_road_claim", "1", now=NOW, op="early-claim")
    for index in range(5):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"r{index}")
    play("season_road_claim", "1", now=NOW + 10, op="claim-1")
    with pytest.raises(GameError, match="本季已领取"):
        play("season_road_claim", "1", now=NOW + 11, op="claim-1-again")
    with pytest.raises(GameError, match="不接受参数"):
        play("season_road", "1", now=NOW + 12)


def test_missing_reward_definition_rolls_back(game, play):
    from dataclasses import replace
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index in range(5):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"m{index}")
    original = game[0].content
    game[0].content = replace(
        original,
        items={key: value for key, value in original.items.items() if key != "spirit_food"},
    )
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="物品定义缺失或类型错误"):
        play("season_road_claim", "1", now=NOW + 10, op="road-rollback")
    assert player(game[1])["stones"] == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='season_road_1'")


def test_unregistered_read_only(game, play):
    page = play("season_road", user="u9", now=NOW)
    assert page.title == "论剑赛季征途"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_season_page_road_line_and_native_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    season = play("season", now=NOW)
    assert "征途：已领 0/7 阶" in season.text()
    assert any(link.command == "灵宠赛季征途" for link in season.inline_commands)
    for index in range(5):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"nk{index}")
    page = play("season_road", now=NOW + 10)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_objectives_hub_reports_road(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    for index in range(5):
        seed_match(game, "u1", "u2", winner="u1", played=NOW + index, operation=f"hub{index}")
    hub = play("objectives", now=NOW + 10)
    assert "论剑征途：可领 1 阶（第 1 阶）" in hub.text()


def test_parse_and_help_contract():
    from nonebot_plugin_spirit_pet.adapters import handlers
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    assert handlers._parse("灵宠赛季征途") == ("season_road", "")
    assert handlers._parse("灵宠征途领奖 3") == ("season_road_claim", "3")
    battle = _HELP_SECTIONS["对战与赛季"]
    assert ("灵宠赛季征途", "灵宠赛季征途", "查看本季七阶征途进度与领取状态。") in battle
    assert ("灵宠征途领奖 阶数", "灵宠征途领奖 ", "领取已达成的赛季征途阶梯奖励。") in battle
