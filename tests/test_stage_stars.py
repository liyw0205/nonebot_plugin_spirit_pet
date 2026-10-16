import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import stage_stars

from .support import items, player, sql

STAGE = "stage_01"
STAGE_NAME = "青木试锋"
STAGE_02 = "stage_02"


def seed(game, rounds, stage_id=STAGE, winner_side=0, user="u1", operation=None):
    """Insert one pve_stage record so the rating can be derived from real rows."""
    operation = operation or f"seed-{stage_id}-{rounds}-{winner_side}-{user}"
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id,initiator_id,kind,battle_key,title,winner_side,rounds,"
            "played_at,reply,snapshot,battle_log) VALUES (?,'u1','pve_stage',?,'关卡',?,?,1,'{}','{}','[]')",
            (operation, stage_id, winner_side, rounds),
        )
        conn.execute(
            "INSERT INTO battle_participants VALUES (?, ?, 0, 'participant')",
            (cursor.lastrowid, user),
        )


def test_rating_uses_the_per_enemy_allowance(game, play):
    play("adopt", "青鸾")
    content = game[0].content
    stage = content.stages[STAGE]
    assert len(stage.enemies) == 1
    rule = content.rules.stage_star_rounds
    assert (rule.three, rule.two) == (3, 5)
    for rounds, expected in ((1, 3), (3, 3), (4, 2), (5, 2), (6, 1), (20, 1)):
        assert stage_stars.stars_for(_context(game), stage, rounds) == expected, rounds
    assert stage_stars.stars_for(_context(game), stage, None) == 0


def _context(game, user="u1", now=1_800_000_000):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    with game[1].connect() as conn:
        return Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, now, "ctx")


def test_more_enemies_allow_more_rounds(game, play):
    play("adopt", "青鸾")
    content = game[0].content
    stage = content.stages[STAGE]
    three_enemy = next(s for s in content.stages.values() if len(s.enemies) == 3)
    assert stage_stars.stars_for(_context(game), three_enemy, 9) == 3
    assert stage_stars.stars_for(_context(game), three_enemy, 10) == 2
    assert stage_stars.stars_for(_context(game), three_enemy, 15) == 2
    assert stage_stars.stars_for(_context(game), three_enemy, 16) == 1
    assert stage_stars.stars_for(_context(game), stage, 9) == 1


def test_best_winning_rounds_are_kept_and_losses_ignored(game, play):
    play("adopt", "青鸾")
    assert stage_stars.best_rounds(_context(game), "u1", STAGE) is None
    seed(game, 7, operation="seed-win-slow")
    assert stage_stars.best_rounds(_context(game), "u1", STAGE) == 7
    seed(game, 2, operation="seed-win-fast")
    assert stage_stars.best_rounds(_context(game), "u1", STAGE) == 2
    seed(game, 1, winner_side=1, operation="seed-loss")
    assert stage_stars.best_rounds(_context(game), "u1", STAGE) == 2
    seed(game, 1, winner_side=-1, operation="seed-draw")
    assert stage_stars.best_rounds(_context(game), "u1", STAGE) == 2


def test_page_lists_stars_and_milestones(game, play):
    play("adopt", "青鸾")
    page = play("stage_stars")
    assert page.title == "灵宠关卡星级 1/4"
    assert "1. 青木试锋 · ☆☆☆" in page.text()
    assert "共 16 关，当前 0/48 星。" in page.text()
    assert "16 星 · 灵石 500，锻灵矿 5 · 还差 16 星" in page.text()
    assert page.inline_commands == ()
    with pytest.raises(GameError, match="共 4 页"):
        play("stage_stars", "5")


def test_clearing_a_stage_earns_stars(game, play):
    play("adopt", "青鸾")
    play("stage_challenge", "1")
    page = play("stage_stars")
    assert "1. 青木试锋 · ★★☆" in page.text()
    assert "共 16 关，当前 2/48 星。" in page.text()


def test_stage_detail_shows_the_rating(game, play):
    play("adopt", "青鸾")
    assert "评价：尚未通关" in play("stage_catalog", STAGE_NAME).text()
    play("stage_challenge", "1")
    detail = play("stage_catalog", STAGE_NAME).text()
    assert "评价：★★☆ · 最好 5 回合" in detail


def test_milestone_claim_requires_stars_and_pays_once(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="星级不足"):
        play("stage_stars_claim", "16")
    with pytest.raises(GameError, match="没有这一档"):
        play("stage_stars_claim", "17")
    for index in range(1, 9):
        seed(game, 1, stage_id=f"stage_{index:02d}", operation=f"seed-fast-{index}")
    assert stage_stars.total(_context(game), "u1") == 24
    before = player(game[1])["stones"]
    reply = play("stage_stars_claim", "16")
    assert reply.title == "关卡星级奖励"
    assert player(game[1])["stones"] == before + 500
    assert items(game[1])["forge_ore"] == 5
    assert "16 星 · 灵石 500，锻灵矿 5 · 已领取" in play("stage_stars").text()
    with pytest.raises(GameError, match="已领取"):
        play("stage_stars_claim", "16")
    assert player(game[1])["stones"] == before + 500


def test_replayed_claim_returns_the_same_reply_without_paying_twice(game, play):
    play("adopt", "青鸾")
    for index in range(1, 9):
        seed(game, 1, stage_id=f"stage_{index:02d}", operation=f"seed-fast-{index}")
    before = player(game[1])["stones"]
    first = play("stage_stars_claim", "16", op="stars-replay")
    again = play("stage_stars_claim", "16", op="stars-replay")
    assert again == first
    assert player(game[1])["stones"] == before + 500
    assert len(sql(game[1], "SELECT 1 FROM quest_progress WHERE quest_id='stage_stars_16'")) == 1


def test_unregistered_player_can_browse_without_an_account(game, play):
    page = play("stage_stars")
    assert page.title == "灵宠关卡星级"
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT 1 FROM players") == []
    with pytest.raises(GameError, match="先完成领养"):
        play("stage_stars_claim", "16")


def test_objectives_hub_reports_the_star_state(game, play):
    play("adopt", "青鸾")
    assert "关卡星级：暂无可领 · 当前 0/48 星" in play("objectives").text()
    for index in range(1, 9):
        seed(game, 1, stage_id=f"stage_{index:02d}", operation=f"seed-fast-{index}")
    assert "关卡星级：可领 1 档（16 星）· 当前 24/48 星" in play("objectives").text()
    play("stage_stars_claim", "16")
    assert "关卡星级：暂无可领 · 当前 24/48 星" in play("objectives").text()


def test_help_lists_the_star_entries(game, play):
    page = play("help", "秘境与关卡")
    assert "灵宠关卡星级：查看各关星级评价与星数里程碑奖励。" in page.text()
    assert "灵宠关卡星级领奖 星数：领取已达成的星数里程碑奖励。" in page.text()
