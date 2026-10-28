"""Weekly team trial: rotation, readiness, round limit, weekly rewards and records."""

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import team_trial
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql
from .team_support import USERS, UIDS, create_players, create_team

NOW = 1_800_000_000
WEEK = 7 * 86400


def trials(game):
    return sorted(game[0].content.team_trials.values(), key=lambda trial: trial.id)


def week_start_of(now):
    return beijing_week(now)[0]


def trial_now(game):
    entries = trials(game)
    return entries[(week_start_of(NOW) // 86400) % len(entries)]


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def add_pet(game, user, species, name, *, realm=5):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp,"
        " affinity, energy, energy_updated, archived) VALUES (?, ?, ?, ?, 10, 4, 0, 0, 100, ?, 0)",
        (user, species, name, realm, NOW),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def roster(play, user, *pet_ids):
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids), user=user)


def two_member_team(play, game, *, extra_leader_pets=("bifang", "chiyanhu")):
    """Two boosted players, each ready; leader carries up to three distinct species."""
    create_players(play, 2)
    create_team(play, 0, (1,))
    boost(game, USERS[0])
    boost(game, USERS[1])
    for index, species in enumerate(extra_leader_pets):
        add_pet(game, USERS[0], species, f"{species}{index}")
    leader_pets = sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? ORDER BY pet_id", (USERS[0],))
    roster(play, USERS[0], *[row["pet_id"] for row in leader_pets])
    play("team_ready", user=USERS[0])
    play("team_ready", user=USERS[1])


def trial_at(game, now=NOW):
    entries = trials(game)
    return entries[(week_start_of(now) // 86400) % len(entries)]


def marker(game, user, trial_id, now=NOW):
    return sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, team_trial._key(week_start_of(now), trial_id)),
    )


def test_content_defines_three_trials_with_limits(game):
    entries = trials(game)
    assert [trial.id for trial in entries] == ["hall_break", "thunder_raid", "tide_hunt"]
    assert [trial.round_limit for trial in entries] == [8, 10, 8]
    assert {trial.min_realm for trial in entries} == {"ningqi", "zhuji", "jindan"}
    for trial in entries:
        assert trial.enemies and all(key in game[0].content.enemies for key in trial.enemies)
        assert all(item in game[0].content.items for item in trial.reward.items)
        assert trial.reward.stones.maximum > 0 and 3 <= trial.round_limit <= 30


def test_rotation_is_stable_within_the_week_and_advances(game):
    current = trial_now(game)
    assert trial_at(game, NOW + 3600).id == current.id
    assert trial_at(game, NOW + WEEK).id != current.id


def test_page_without_a_team_is_read_only_and_guides_to_teams(game, play):
    play("adopt", "青鸾")
    page = play("team_trial")
    assert page.lines[0].startswith("本周试炼：")
    assert "尚未组队" in page.text()
    assert "灵宠队伍" in page.commands and "灵宠秘境" in page.commands


def test_page_reports_members_progress_and_leader_entry(game, play):
    two_member_team(play, game)
    page = play("team_trial", user=USERS[0])
    trial = trial_now(game)
    assert trial.name in page.text()
    assert f"回合上限：{trial.round_limit} 回合内击破" in page.text()
    assert "已准备 2/2" in page.text()
    assert "队长 UID 10000" in page.text() and "队员 UID 10001" in page.text()
    assert "队伍最佳：本周尚无通关记录" in page.text()
    assert "灵宠团队试炼 挑战" in page.commands


def test_only_the_leader_may_start_and_all_members_must_be_ready(game, play):
    create_players(play, 2)
    create_team(play, 0, (1,))
    boost(game, USERS[0])
    boost(game, USERS[1])
    with pytest.raises(GameError, match="队长"):
        play("team_trial", "挑战", user=USERS[1])
    with pytest.raises(GameError, match="准备"):
        play("team_trial", "挑战", user=USERS[0])
    play("team_ready", user=USERS[0])
    with pytest.raises(GameError, match="准备"):
        play("team_trial", "挑战", user=USERS[0])
    page = play("team_trial", user=USERS[1])
    assert "灵宠团队试炼 挑战" not in page.commands
    assert "仅队长可以发起" in page.text()


def test_a_one_member_team_cannot_run_the_trial(game, play):
    create_players(play, 1)
    play("team_create", user=USERS[0])
    boost(game, USERS[0])
    play("team_ready", user=USERS[0])
    with pytest.raises(GameError, match="两名玩家"):
        play("team_trial", "挑战", user=USERS[0])


def test_win_pays_every_member_once_and_records_the_best_rounds(game, play):
    two_member_team(play, game)
    trial = trial_now(game)
    before = [player(game[1], user)["stones"] for user in USERS[:2]]
    reply = play("team_trial", "挑战", user=USERS[0])
    assert reply.lines[0].startswith(f"{trial.name} · ")
    assert "首通" in reply.text()
    for user in USERS[:2]:
        assert marker(game, user, trial.id), "both members must receive a weekly marker"
        assert player(game[1], user)["stones"] >= before[USERS.index(user)]
    rounds = marker(game, USERS[1], trial.id)[0]["progress"]
    assert rounds <= trial.round_limit
    for user in USERS[:2]:
        assert f"UID {10000 + USERS.index(user)}首通" in reply.text()
    assert "助战，不重复发放奖励" not in reply.text()


def test_a_repeat_run_is_a_support_run_without_rewards(game, play):
    two_member_team(play, game)
    trial = trial_now(game)
    play("team_trial", "挑战", user=USERS[0])
    first = marker(game, USERS[1], trial.id)[0]["progress"]
    stones = [player(game[1], user)["stones"] for user in USERS[:2]]
    sql(game[1], "UPDATE pets SET energy=100, energy_updated=?", (NOW + 1200,))
    energy = [sql(game[1], "SELECT energy FROM pets WHERE user_id=?", (user,))[0]["energy"] for user in USERS[:2]]
    play("team_ready", user=USERS[0], now=NOW + 1200)
    play("team_ready", user=USERS[1], now=NOW + 1200)
    reply = play("team_trial", "挑战", user=USERS[0], now=NOW + 1200)
    assert "本周已通关，本次为助战，不重复发放奖励" in reply.text()
    assert [player(game[1], user)["stones"] for user in USERS[:2]] == stones
    assert marker(game, USERS[1], trial.id)[0]["progress"] == first
    after = [sql(game[1], "SELECT energy FROM pets WHERE user_id=?", (user,))[0]["energy"] for user in USERS[:2]]
    assert after == [value - trial.energy for value in energy]


def test_a_timeout_paid_outside_the_limit_grants_nothing(game, play, monkeypatch):
    two_member_team(play, game)
    trial = trial_now(game)
    stones = [player(game[1], user)["stones"] for user in USERS[:2]]
    monkeypatch.setattr(
        team_trial, "fight",
        lambda *args, **kwargs: SimpleNamespace(
            winner=0, rounds=trial.round_limit + 1, lines=["超时线"], history=[], skill_uses=[{}, {}],
        ),
    )
    reply = play("team_trial", "挑战", user=USERS[0])
    assert "超过" in reply.text() and "未通过" in reply.text()
    assert "首通" not in reply.text()
    assert [player(game[1], user)["stones"] for user in USERS[:2]] == stones
    assert marker(game, USERS[0], trial.id) == []


def test_a_loss_consumes_energy_but_pays_nothing(game, play, monkeypatch):
    two_member_team(play, game)
    trial = trial_now(game)
    monkeypatch.setattr(
        team_trial, "fight",
        lambda *args, **kwargs: SimpleNamespace(
            winner=1, rounds=4, lines=["败退线"], history=[], skill_uses=[{}, {}],
        ),
    )
    reply = play("team_trial", "挑战", user=USERS[0])
    assert "未通过" in reply.text() and "首通" not in reply.text()
    assert marker(game, USERS[0], trial.id) == []
    assert sql(game[1], "SELECT energy FROM pets WHERE user_id=?", (USERS[0],))[0]["energy"] <= 75


def test_the_round_limit_gate_is_pure(game):
    trial = trial_now(game)
    assert team_trial._passed(SimpleNamespace(winner=0, rounds=trial.round_limit), trial)
    assert not team_trial._passed(SimpleNamespace(winner=0, rounds=trial.round_limit + 1), trial)
    assert not team_trial._passed(SimpleNamespace(winner=1, rounds=1), trial)


def test_next_week_rotates_and_rewards_again(game, play):
    two_member_team(play, game)
    following = trial_at(game, NOW + WEEK)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 3, 1)",
        (USERS[0], team_trial._key(week_start_of(NOW), trial_now(game).id)),
    )
    play("team_trial", "挑战", user=USERS[0], now=NOW + WEEK)
    assert marker(game, USERS[0], following.id, NOW + WEEK), "last week's marker must not block the new week"


def test_energy_realm_and_cooldown_gates_apply_per_member(game, play):
    two_member_team(play, game)
    trial = trial_now(game)
    sql(game[1], "UPDATE pets SET energy=1 WHERE user_id=?", (USERS[1],))
    with pytest.raises(GameError, match="精力"):
        play("team_trial", "挑战", user=USERS[0])
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id=?", (USERS[1],))
    sql(game[1], "UPDATE players SET last_pve=? WHERE user_id=?", (NOW - 10, USERS[1]))
    with pytest.raises(GameError, match="调息"):
        play("team_trial", "挑战", user=USERS[0])
    sql(game[1], "UPDATE players SET last_pve=NULL WHERE user_id=?", (USERS[1],))
    sql(game[1], "UPDATE pets SET realm=0 WHERE user_id=?", (USERS[1],))
    with pytest.raises(GameError, match="境界"):
        play("team_trial", "挑战", user=USERS[0])
    assert marker(game, USERS[0], trial.id) == []


def test_the_same_operation_replays_and_a_foreign_battle_is_refused(game, play):
    two_member_team(play, game)
    trial = trial_now(game)
    reply = play("team_trial", "挑战", user=USERS[0], op="trial-op")
    again = play("team_trial", "挑战", user=USERS[0], op="trial-op")
    assert again.text() == reply.text()

    play("adopt", "青鸾", user=USERS[2])
    play("adopt", "青鸾", user=USERS[3])
    create_team(play, 2, (3,))
    boost(game, USERS[2])
    boost(game, USERS[3])
    play("team_ready", user=USERS[2])
    play("team_ready", user=USERS[3])
    with pytest.raises(GameError, match="reused by a different user"):
        play("team_trial", "挑战", user=USERS[2], op="trial-op")


def test_the_battle_is_a_stage_record_and_keeps_dungeon_stats_clean(game, play):
    two_member_team(play, game)
    trial = trial_now(game)
    play("team_trial", "挑战", user=USERS[0])
    rows = sql(game[1], "SELECT kind, battle_key, title FROM battle_records WHERE battle_key=?", (trial.id,))
    assert rows and rows[0] == {"kind": "pve_stage", "battle_key": trial.id, "title": "团队试炼通关"}
    assert sql(game[1], "SELECT * FROM pve_stage_progress WHERE stage_id=?", (trial.id,)) == []


def test_help_objectives_and_parsing_cover_the_trial(game, play):
    play("adopt", "青鸾")
    overview = play("help", "组队与派遣")
    assert "灵宠团队试炼 挑战" in overview.text()
    objectives = play("objectives")
    assert "团队试炼：尚未组队" in objectives.text()
    parsed = handlers._parse("灵宠团队试炼 挑战")
    assert parsed[0] == "team_trial" and parsed[1] == "挑战"
    assert handlers._parse("灵宠团队试炼")[0] == "team_trial"


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    two_member_team(play, game)
    page = play("team_trial", user=USERS[0])
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
