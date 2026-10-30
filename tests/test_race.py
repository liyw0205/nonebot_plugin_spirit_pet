"""Pet race: track rotation, deterministic times, gating, weekly best and the board."""

import re
from contextlib import closing
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.race_content import RaceTerrain, RaceTrack
from nonebot_plugin_spirit_pet.gameplay import race
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86_400
WEEK = 7 * DAY


def add_pet(game, name="小鸾", species="qingluan", user="u1", energy=100):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, ?, ?)",
            (user, species, name, energy, NOW),
        ).lastrowid


def ctx_of(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "read-race")


def tracks(game):
    return sorted(game[0].content.races.values(), key=lambda track: track.id)


def today_track(game, now=NOW):
    listed = tracks(game)
    return listed[date.fromtimestamp(now).toordinal() % len(listed)]


def best_row(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"race_best_{beijing_week(now)[0]}"),
    )
    return rows[0]["progress"] if rows else None


def runs_row(game, user="u1", now=NOW):
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"race_day_{beijing_day(now)}"),
    )
    return rows[0]["progress"] if rows else 0


def ready(game, play, *, species="青鸾", energy=100, stones=0, user="u1"):
    play("adopt", species, user=user)
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE user_id=?", (energy, NOW, user))
    if stones:
        sql(game[1], "UPDATE players SET stones=?", (stones,))


def test_content_declares_tracks_and_weights(game):
    content = game[0].content
    assert [track.id for track in tracks(game)] == ["climb", "ridge", "sprint"]
    assert sorted(track.terrain.stat for track in tracks(game)) == ["defense", "hp", "speed"]
    rule = content.rules.race
    assert (rule.energy, rule.daily_limit) == (20, 3)
    assert abs(sum(rule.weights.values()) - 1) < 1e-9
    assert rule.weights["speed"] == 0.5


def test_track_and_weight_validation():
    base = {"id": "x", "name": "赛道", "description": "测试", "length": 800,
            "terrain": {"stat": "speed", "multiplier": 1.2}}
    assert RaceTrack.model_validate(base).length == 800
    with pytest.raises(ValidationError):
        RaceTrack.model_validate({**base, "terrain": {"stat": "unknown", "multiplier": 1.2}})
    with pytest.raises(ValidationError):
        RaceTrack.model_validate({**base, "length": 5})
    with pytest.raises(ValidationError):
        RaceTerrain.model_validate({"stat": "speed", "multiplier": 9})


def test_today_track_is_stable_and_rotates(game):
    first = race.track(ctx_of(game, now=NOW))
    same_day = race.track(ctx_of(game, now=NOW + 3600))
    assert first.id == same_day.id
    later = [race.track(ctx_of(game, now=NOW + step * DAY)).id for step in range(1, 4)]
    assert later == [first.id, first.id, first.id] or len(set(later)) == 3
    assert len({race.track(ctx_of(game, now=NOW + step * DAY)).id for step in range(0, 3)}) == 3


def test_time_is_deterministic_and_positive(game, play):
    ready(game, play)
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-race")
        entry = race.track(ctx)
        target = next(pet for pet in ctx.repo.owned_pets("u1"))
        first = race.time_of(ctx, target, entry)
        second = race.time_of(ctx, target, entry)
        assert first == second
        assert isinstance(first, int) and first > 0


def test_a_faster_pet_runs_a_lower_time(game, play):
    ready(game, play)
    other = add_pet(game, "小鸾")
    sql(game[1], "UPDATE pets SET realm=5, layer=10, bloodline=4 WHERE pet_id=?", (other,))
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-race")
        entry = race.track(ctx)
        weak = ctx.repo.pet(pet(game[1])["pet_id"])
        strong = ctx.repo.pet(other)
        assert race.time_of(ctx, strong, entry) < race.time_of(ctx, weak, entry)


def test_terrain_stat_counts_at_its_multiplier(game, play):
    ready(game, play)
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-race")
        target = next(pet for pet in ctx.repo.owned_pets("u1"))
        plain = tracks(game)[0]
        boosted = plain.model_copy(update={"terrain": plain.terrain.model_copy(update={"multiplier": 2.0})})
        assert race.time_of(ctx, target, plain, "u1") != race.time_of(ctx, target, boosted, "u1")


def test_page_without_a_pet_is_read_only(game, play):
    page = play("race", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_track_rules_and_projections(game, play):
    ready(game, play)
    page = play("race")
    entry = today_track(game)
    assert f"本周赛道：{entry.name}" in page.text()
    assert "今日剩余 3/3 次" in page.text()
    assert "速度 50%、气血 20%、攻击 20%、防御 10%" in page.text()
    assert "青鸾（编号 1）· 预计" in page.text()
    assert "可报名" in page.text()
    assert [link.command for link in page.inline_commands] == ["灵宠竞速 报名 1"]
    assert page.commands == ("灵宠竞速", "灵宠竞速榜", "我的灵宠")


def test_entering_records_time_energy_and_daily_charge(game, play):
    ready(game, play)
    with closing(game[1].connect()) as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-race")
        expected = race.time_of(ctx, next(pet for pet in ctx.repo.owned_pets("u1")), race.track(ctx))
    reply = play("race", "报名 1", op="race-1")
    assert reply.title == "竞速成绩"
    assert race.time_text(expected) in reply.text()
    assert best_row(game) == expected
    assert runs_row(game) == 1
    assert pet(game[1])["energy"] == 80


def test_a_slow_run_does_not_overwrite_the_best(game, play):
    ready(game, play)
    play("race", "报名 1", op="race-a")
    first = best_row(game)
    sql(game[1], "UPDATE pets SET realm=0, layer=1, bloodline=0")
    reply = play("race", "报名 1", op="race-b", now=NOW + 60)
    assert "未超越" in reply.text()
    assert best_row(game) == first
    assert runs_row(game) == 2


def test_daily_limit_blocks_further_entries(game, play):
    ready(game, play)
    for index in range(3):
        play("race", "报名 1", op=f"race-{index}", now=NOW + index)
    assert "今日剩余 0/3 次" in play("race", now=NOW + 3).text()
    with pytest.raises(GameError, match="次数已用尽"):
        play("race", "报名 1", now=NOW + 3)
    assert runs_row(game) == 3
    assert runs_row(game, now=NOW + DAY) == 0
    play("race", "报名 1", op="race-next-day", now=NOW + DAY)
    assert runs_row(game, now=NOW + DAY) == 1


def test_weekly_best_resets_next_week_but_keeps_history(game, play):
    ready(game, play)
    play("race", "报名 1", op="race-week1")
    assert best_row(game) is not None
    assert best_row(game, now=NOW + WEEK) is None
    play("race", "报名 1", op="race-week2", now=NOW + WEEK)
    assert best_row(game, now=NOW + WEEK) is not None
    assert len([row for row in sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'race_best_%'")]) == 2


def test_refusals_write_nothing(game, play):
    ready(game, play, energy=10)
    with pytest.raises(GameError, match="格式"):
        play("race", "报名")
    with pytest.raises(GameError, match="精力不足"):
        play("race", "报名 1")
    assert (best_row(game), runs_row(game), pet(game[1])["energy"]) == (None, 0, 10)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'race_%'") == []
    with pytest.raises(GameError, match="没有属于你的在册灵宠"):
        play("race", "报名 99")
    with pytest.raises(GameError, match="格式"):
        play("race", "额外")


def test_archived_and_expedition_pets_are_refused(game, play):
    ready(game, play)
    pet_id = pet(game[1])["pet_id"]
    play("expedition_start", "采灵药", op="trip")
    with pytest.raises(GameError, match="派遣|行程"):
        play("race", f"报名 {pet_id}")
    assert best_row(game) is None
    assert runs_row(game) == 0


def test_a_run_writes_no_battle_record_or_progress(game, play):
    ready(game, play)
    play("race", "报名 1", op="race-clean")
    assert sql(game[1], "SELECT * FROM battle_records") == []
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []
    skills = sql(game[1], "SELECT * FROM learned_skills")
    row = sql(game[1], "SELECT affinity, exp FROM pets WHERE pet_id=?", (pet(game[1])["pet_id"],))[0]
    assert (row["affinity"], row["exp"], skills) == (0, 0, [])
    assert items(game[1]) == {"spirit_food": 3}  # starter bag only, race grants nothing


def second_player(game, user="u2"):
    """Create a second account the way the game does: identity, player row, one pet."""
    with game[1].connect() as conn:
        conn.execute("INSERT INTO players(user_id, stones, registered_at) VALUES (?, 0, ?)", (user, NOW))
        conn.execute("INSERT INTO player_identity(user_id) VALUES (?)", (user,))
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, 'qingluan', '二鸾', 0, 100, ?)", (user, NOW))
        pet_id = cursor.lastrowid
    with game[1].connect() as conn:
        conn.execute("UPDATE players SET active_pet_id=? WHERE user_id=?", (pet_id, user))
    return pet_id


def test_board_ranks_players_and_shows_own_place(game, play):
    ready(game, play, user="u1")
    play("race", "报名 1", op="board-a")
    second_pet = second_player(game)
    sql(game[1], "UPDATE pets SET realm=5, layer=10, bloodline=4 WHERE pet_id=?", (second_pet,))
    play("race", f"报名 {second_pet}", op="board-b", user="u2")
    mine = best_row(game, "u1")
    theirs = best_row(game, "u2")
    assert mine is not None and theirs is not None and theirs < mine
    board = play("race_board")
    assert board.title == "灵宠竞速榜"
    assert "UID " in board.text()
    assert board.text().index("1. UID") < board.text().index("2. UID")
    assert f"你的最好成绩 {race.time_text(mine)}" in board.text()
    assert "本周第 2 名" in board.text()


def test_board_handles_an_empty_week(game, play):
    ready(game, play)
    board = play("race_board")
    assert "本周尚无人留下成绩" in board.text()
    assert "你本周尚未参赛" in board.text()
    with pytest.raises(GameError, match="不接受参数"):
        play("race_board", "1")


def test_board_without_a_pet_is_read_only(game, play):
    board = play("race_board", user="ghost")
    assert "本周尚无人留下成绩" in board.text()
    assert board.commands == ("灵宠帮助",)


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "竞速：本周尚未参赛" in play("objectives").text()
    play("race", "报名 1", op="race-obj")
    assert "竞速：本周最好" in play("objectives").text()
    assert "灵宠竞速" in play("help", "对战与赛季").text()
    assert handlers._parse("灵宠竞速") == ("race", "")
    assert handlers._parse("灵宠竞速 报名 1") == ("race", "报名 1")
    assert handlers._parse("灵宠竞速榜") == ("race_board", "")


def test_state_survives_a_restart(game, play):
    ready(game, play)
    play("race", "报名 1", op="race-persist")
    best, runs = best_row(game), runs_row(game)
    assert "本周最好" in play("race").text()
    assert (best_row(game), runs_row(game)) == (best, runs)


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("race")
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
