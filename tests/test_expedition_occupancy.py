import json
from contextlib import closing
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.content import Range
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import pet, player, sql

NOW = 1_800_000_000
DURATION = 3600


def prepare(game, play, user="u1", name="青云"):
    play("adopt", "青鸾", user=user)
    play("dao_name", name, user=user)
    sql(game[1], "UPDATE players SET stones=100000 WHERE user_id=?", (user,))
    sql(game[1], "UPDATE pets SET realm=1, bloodline=1, exp=10000, energy=80 WHERE user_id=?", (user,))
    with closing(game[1].connect()) as conn:
        conn.executemany("INSERT INTO inventory VALUES (?, ?, 100) ON CONFLICT(user_id, item_id) "
                         "DO UPDATE SET quantity=100", ((user, item) for item in game[0].content.items))
    play("equipment", "青岚翎", user=user)
    play("learn", "风刃术", user=user)
    play("learn", "青木回春", user=user)
    play("unequip_skill", "青木回春", user=user)


def occupy(game, user="u1", pet_id=None):
    pet_id = pet_id or pet(game[1], user)["pet_id"]
    rows = sql(game[1], "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, "
               "started_at, finishes_at, state, reward_snapshot) VALUES (?, ?, 'gather_herbs', '采灵药', ?, "
               "?, ?, 'running', ?) RETURNING job_id", (
                   user, pet_id, f"occupancy-{user}-{pet_id}", NOW, NOW + DURATION,
                   json.dumps({"exp": 30, "stones": 40, "items": {"spirit_food": 1}}),
               ))
    return rows[0]["job_id"]


def snapshot(game):
    tables = ("players", "pets", "inventory", "equipment", "unequipped_equipment", "learned_skills",
              "teams", "team_members", "team_requests", "duels", "pvp_pairs", "quest_progress", "expeditions")
    return {table: sql(game[1], f"SELECT * FROM {table} ORDER BY rowid") for table in tables}


BLOCKED_ACTIONS = (
    ("train", ""), ("explore", ""), ("challenge", "青岚林"),
    ("breakthrough", ""), ("evolve", ""), ("lineage_choose", "凌风鸾脉"),
    ("feed", ""), ("use", "回元丹"), ("use", "蕴灵丹"),
    ("equipment", "灵心铃"), ("unequip", "灵器"), ("enhance", "灵器"),
    ("learn", "凝神术"), ("equip_skill", "青木回春"), ("unequip_skill", "风刃术"),
    ("team_ready", ""),
)


@pytest.mark.parametrize("elapsed", [0, DURATION, DURATION + 1])
@pytest.mark.parametrize("action,arg", BLOCKED_ACTIONS)
def test_busy_pet_actions_reject_without_mutations(game, play, action, arg, elapsed):
    prepare(game, play)
    play("team_create")
    occupy(game)
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play(action, arg, now=NOW + elapsed)
    assert snapshot(game) == before


@pytest.mark.parametrize("action,arg", BLOCKED_ACTIONS)
def test_same_actions_remain_available_without_occupation(game, play, action, arg):
    prepare(game, play)
    play("team_create")
    play(action, arg)


@pytest.mark.parametrize("mode", ["pvp", "spar"])
@pytest.mark.parametrize("busy_user", ["u1", "u2"])
def test_both_invitation_modes_check_each_players_pet(game, play, mode, busy_user):
    prepare(game, play)
    prepare(game, play, "u2", "赤霄")
    occupy(game, busy_user)
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play(mode, "赤霄")
    assert snapshot(game) == before


@pytest.mark.parametrize("mode", ["pvp", "spar"])
@pytest.mark.parametrize("busy_user", ["u1", "u2"])
def test_pending_duel_rechecks_both_pets_when_accepted(game, play, mode, busy_user):
    prepare(game, play)
    prepare(game, play, "u2", "赤霄")
    play(mode, "赤霄")
    occupy(game, busy_user)
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("accept", user="u2")
    assert snapshot(game) == before
    play("reject", user="u2")
    assert not sql(game[1], "SELECT * FROM duels")


def test_team_battle_rechecks_all_pets_even_with_stale_ready_rows(game, play):
    prepare(game, play)
    prepare(game, play, "u2", "赤霄")
    play("team_create")
    play("team_join", "青云", user="u2")
    play("team_accept", "赤霄")
    play("team_ready")
    play("team_ready", user="u2")
    occupy(game, "u2")
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("team_challenge", "上古灵殿")
    assert snapshot(game) == before


@pytest.mark.parametrize("elapsed,label", [(0, "外出"), (DURATION, "待领取")])
def test_status_and_pet_list_show_occupation_without_releasing_it(game, play, elapsed, label):
    prepare(game, play)
    job = occupy(game)
    before = sql(game[1], "SELECT * FROM expeditions")
    for action in ("status", "pet_list"):
        reply = play(action, now=NOW + elapsed)
        assert label in reply.text()
        assert "采灵药" in reply.text()
        assert "灵宠行程" in reply.commands
    assert sql(game[1], "SELECT * FROM expeditions") == before
    with closing(game[1].connect()) as conn:
        row = Repository(conn).active_expedition(pet(game[1])["pet_id"])
        assert row["job_id"] == job


@pytest.mark.parametrize("action,arg", [
    ("equipment", ""), ("skills", ""), ("lineage_catalog", ""), ("catalog", "青鸾"),
    ("quests", ""), ("bag", ""), ("shop", ""), ("rename", "凌风"), ("dao_name", "归元"),
    ("buy", "灵粮"), ("craft", "青岚翎"), ("salvage", "青岚翎"),
    ("summon", "1"), ("use", "青藤灵卵"),
    ("team_status", ""), ("team_unready", ""), ("team_disband", ""),
])
def test_queries_account_operations_and_management_remain_available(game, play, action, arg):
    prepare(game, play)
    play("team_create")
    occupy(game)
    before = sql(game[1], "SELECT * FROM expeditions")
    play(action, arg)
    assert sql(game[1], "SELECT * FROM expeditions") == before


def test_switching_to_busy_pet_is_allowed_but_does_not_clear_occupation(game, play):
    prepare(game, play)
    original = pet(game[1])["pet_id"]
    occupy(game)
    play("summon")
    other = sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets")[0]["pet_id"]
    play("switch", str(other))
    play("train")
    assert "外出" not in play("status").text()
    assert "外出" in play("pet_list").text()
    play("switch", str(original))
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("train")
    assert sql(game[1], "SELECT state FROM expeditions") == [{"state": "running"}]


def test_zero_exp_account_rewards_do_not_touch_busy_pet(game, play):
    prepare(game, play)
    occupy(game)
    sql(game[1], "UPDATE players SET quest_day=?", (beijing_day(NOW),))
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1', 'train_once', 1, 0)")
    sql(game[1], "UPDATE pets SET energy=7, energy_updated=?", (NOW - 10000,))
    before = pet(game[1])
    play("sign")
    play("claim", "吐纳一周天")
    assert pet(game[1]) == before
    assert player(game[1])["stones"] == 100250


def test_exp_quest_reward_is_blocked_and_not_marked_claimed(game, play):
    prepare(game, play)
    occupy(game)
    sql(game[1], "UPDATE players SET quest_day=?", (beijing_day(NOW),))
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1', 'pve_once', 1, 0)")
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("claim", "斩破迷障")
    assert snapshot(game) == before


def test_reward_with_possible_exp_rejects_before_random_or_daily_marker(game, play):
    prepare(game, play)
    occupy(game)
    rules = game[0].content.rules
    daily = rules.daily_reward.model_copy(update={"exp": Range(minimum=0, maximum=1)})
    game[0].content = replace(game[0].content, rules=rules.model_copy(update={"daily_reward": daily}))

    class NoDraws:
        def randint(self, start, stop):
            raise AssertionError("occupied pet reward must be rejected before drawing")

    game[0].rng = NoDraws()
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣|待领取"):
        play("sign")
    assert snapshot(game) == before


@pytest.mark.parametrize("state,settled_at", [("claimed", NOW + DURATION), ("cancelled", NOW + 1)])
def test_settled_expeditions_no_longer_occupy_pet(game, play, state, settled_at):
    prepare(game, play)
    job = occupy(game)
    sql(game[1], "UPDATE expeditions SET state=?, settled_at=? WHERE job_id=?", (state, settled_at, job))
    with closing(game[1].connect()) as conn:
        assert Repository(conn).active_expedition(pet(game[1])["pet_id"]) is None
    play("train", now=settled_at)
    assert "待领取" not in play("status", now=settled_at).text()
