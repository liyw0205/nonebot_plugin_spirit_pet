import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player_uid, sql

NOW = 1_800_000_000  # 2027-01-15 Beijing


def seed_match(game, other, *, winner, season="2027-01", played=NOW, challenger="u1"):
    """Insert a finished ranked match; each side references its first active pet."""
    bounds = {"2026-11": (1_793_548_800, 1_796_140_800), "2026-12": (1_796_227_200, 1_798_818_000),
              "2027-01": (1_798_904_400, 1_801_582_800)}
    start, end = bounds.get(season, (played - 1, played + 1))
    snapshot = game[0].content.arena.model_dump_json()
    sql(game[1], (
        "INSERT INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(season_id) DO NOTHING"
    ), (season, start, end, played, snapshot))
    challenger_pet = sql(game[1],
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id LIMIT 1", (challenger,),
    )[0]["pet_id"]
    other_pet = sql(game[1],
        "SELECT pet_id FROM pets WHERE user_id=? AND archived=0 ORDER BY pet_id LIMIT 1", (other,),
    )[0]["pet_id"]
    sql(game[1], (
        "INSERT INTO pvp_results(season_id, challenger_id, target_id, challenger_pet_id, target_pet_id, "
        "winner_id, day, played_at, delta, operation_id, reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'r')"
    ), (season, challenger, other, challenger_pet, other_pet, winner, season, played,
        0 if winner is None else 20,
        f"op-{season}-{played}-{other}-{winner or 'draw'}-{challenger}"))


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_head_to_head_counts_both_perspectives_and_groups_by_season(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    other_uid = player_uid(game[1], "u2")
    seed_match(game, "u2", winner="u1", season="2027-01", played=NOW)           # I challenged, won
    seed_match(game, "u2", winner="u2", season="2027-01", played=NOW + 1)       # I challenged, lost
    seed_match(game, "u1", winner="u1", season="2026-12", played=NOW + 2, challenger="u2")  # opponent challenged me, I defended and won
    seed_match(game, "u1", winner=None, season="2026-12", played=NOW + 3, challenger="u2")  # draw

    page = play("pvp_head_to_head", str(other_uid), now=NOW + 4)
    assert page.title == f"论剑交锋 · UID {other_uid}"
    assert "交锋 4 场 · 2 胜 1 负 1 平。" in page.lines[0]
    assert "最近一场：2026-12 赛季" in page.lines[1]
    assert row(page, "2027-01 · 2 场 · 1 胜 1 负 0 平")
    assert row(page, "2026-12 · 2 场 · 1 胜 0 负 1 平")
    assert "切磋不计入论剑交锋" in page.text()
    commands = {link.command for link in page.inline_commands}
    assert f"灵宠论剑 {other_uid}" in commands
    assert "灵宠战报" in commands


def test_season_rows_are_ordered_newest_first(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    other_uid = player_uid(game[1], "u2")
    seed_match(game, "u2", winner="u1", season="2026-11", played=NOW)
    seed_match(game, "u2", winner="u1", season="2027-01", played=NOW + 1)
    page = play("pvp_head_to_head", str(other_uid), now=NOW + 2)
    season_lines = [line for line in page.lines if " 场 · " in line and line[:4].isdigit()]
    assert season_lines[0].startswith("2027-01")
    assert season_lines[1].startswith("2026-11")


def test_unknown_self_and_unmet_opponents_are_stable(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="没有找到这位玩家"):
        play("pvp_head_to_head", "99999", now=NOW)
    own_uid = player_uid(game[1], "u1")
    with pytest.raises(GameError, match="不能查看与自己"):
        play("pvp_head_to_head", str(own_uid), now=NOW)
    play("adopt", "白泽", user="u3", now=NOW)
    unmet = play("pvp_head_to_head", str(player_uid(game[1], "u3")), now=NOW)
    assert "还没有论剑交锋记录" in unmet.text()
    assert unmet.inline_commands[0].command == "灵宠匹配"


def test_spar_matches_are_excluded(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    play("spar", str(player_uid(game[1], "u2")), now=NOW)
    page = play("pvp_head_to_head", str(player_uid(game[1], "u2")), now=NOW + 1)
    assert "还没有论剑交锋记录" in page.text()


def test_unregistered_players_cannot_review(game, play):
    with pytest.raises(GameError):
        play("pvp_head_to_head", "10001", user="u9", now=NOW)
    from .support import sql

    assert sql(game[1], "SELECT user_id FROM players") == []


def test_season_page_links_head_to_head_without_button_duplication(game, play):
    from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments as segments

    play("adopt", "青鸾", now=NOW)
    season = play("season", now=NOW)
    assert "灵宠论剑交锋" in season.text()
    assert "灵宠论剑交锋 " in season.inline_commands[0].command
    _, message = segments(season, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert "灵宠论剑交锋 " not in buttons


def test_parse_routes_head_to_head():
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠论剑交锋") == ("pvp_head_to_head", "")
    assert handlers._parse("灵宠论剑交锋 10001") == ("pvp_head_to_head", "10001")
    assert handlers._parse("灵宠论剑 10001") == ("pvp", "10001")
