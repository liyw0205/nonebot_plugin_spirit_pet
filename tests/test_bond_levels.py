import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.bond_levels import level, THRESHOLDS

from .support import pet, sql

NOW = 1_800_000_000


def bond_exp(game, pet_id=1):
    rows = sql(game[1], f"SELECT progress FROM quest_progress WHERE quest_id='bond_exp_{pet_id}'")
    return rows[0]["progress"] if rows else 0


def seed_exp(game, amount, pet_id=1):
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, ?, 0) "
                 "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=progress+excluded.progress",
        (f"bond_exp_{pet_id}", amount))


def test_levels_rise_with_experience_thresholds():
    assert level(0) == 1
    assert level(THRESHOLDS[0] - 1) == 1
    assert level(THRESHOLDS[0]) == 2
    assert level(THRESHOLDS[-1]) == 5
    assert level(THRESHOLDS[-1] + 1) == 5


def test_interaction_grants_bond_experience(game, play):
    play("adopt", "青鸾")
    assert bond_exp(game) == 0
    play("bond", op="interact-1")
    assert bond_exp(game) == 10


def test_outing_and_play_game_grant_bond_experience(game, play):
    play("adopt", "青鸾")
    play("pet_outing", op="outing-1")
    assert bond_exp(game) == 10
    sql(game[1], "UPDATE pets SET affinity=50")
    play("play_game", "藏食寻宝", op="game-1")
    assert bond_exp(game) == 16


def test_bond_level_bonuses_apply_to_combat_stats(game, play):
    play("adopt", "青鸾")
    base = next(line for line in play("status").lines if line.startswith("气血："))
    seed_exp(game, THRESHOLDS[0])
    boosted = next(line for line in play("status").lines if line.startswith("气血："))
    assert boosted != base
    assert "气血" in boosted


def test_level_five_maxes_all_bonuses(game, play):
    play("adopt", "青鸾")
    seed_exp(game, THRESHOLDS[-1])
    page = play("bond_levels")
    assert "羁绊等级 MAX" in page.text()


def test_bond_catalog_lists_roster(game, play):
    play("adopt", "青鸾")
    page = play("bond_levels")
    assert "青鸾（编号 1）" in page.text()
    assert "羁绊等级 1" in page.text()


def test_bond_catalog_rejects_arguments(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="不接受参数"):
        play("bond_levels", "1", op="bond-arg")


def test_bond_exp_persists_and_accumulates(game, play):
    play("adopt", "青鸾")
    play("bond", op="bond-day1")
    sql(game[1], "UPDATE players SET last_bond_day='1999-01-01'")
    seed_exp(game, 100)
    assert bond_exp(game) == 110


def test_status_page_shows_bond_level(game, play):
    play("adopt", "青鸾")
    seed_exp(game, 200)
    status = play("status")
    assert any(line.startswith("羁绊等级：3") for line in status.lines)


def test_archived_pets_keep_exp_but_no_roster_row(game, play):
    play("adopt", "青鸾")
    seed_exp(game, 60)
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=1")
    page = play("bond_levels")
    assert "尚无在册灵宠" in page.text()
    assert bond_exp(game) == 60


def test_bond_levels_rejects_without_adoption(game, play):
    with pytest.raises(GameError):
        play("bond_levels", op="bond-no-player", user="u9")
