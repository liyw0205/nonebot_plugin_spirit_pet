import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000
RESTED = NOW + 601


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def seed_battle(game, dungeon_id, winner_side, user="u1", operation="seed"):
    sql(
        game[1],
        "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title,"
        " winner_side, rounds, played_at, reply, snapshot, battle_log)"
        " VALUES (?, ?, 'pve', ?, 'seed', ?, 1, ?, '', '', '')",
        (operation, user, dungeon_id, winner_side, NOW),
    )
    battle_id = sql(
        game[1], "SELECT battle_id FROM battle_records WHERE operation_id=?", (operation,),
    )[0]["battle_id"]
    sql(
        game[1],
        "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
        " VALUES (?, ?, 0, 'participant')",
        (battle_id, user),
    )


def quest_progress(game, quest_id, user="u1"):
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?", (user, quest_id),
    )
    return rows[0]["progress"] if rows else 0


def test_sweep_needs_a_previous_clear(game, play):
    account(game, play)
    with pytest.raises(GameError, match="尚未通关青岚林"):
        play("sweep", "青岚林")
    # A defeat is not a clear either.
    seed_battle(game, "forest", 1, operation="lost-run")
    with pytest.raises(GameError, match="尚未通关青岚林"):
        play("sweep", "青岚林")


def test_sweep_pays_the_dungeon_reward_and_costs_energy(game, play):
    account(game, play)
    play("challenge", "青岚林")
    before = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    # Pin the energy clock so the assertion does not depend on passive regeneration.
    sql(game[1], "UPDATE pets SET energy=100, energy_updated=?", (RESTED,))
    reply = play("sweep", "青岚林", now=RESTED)
    assert reply.title == "秘境扫荡"
    assert reply.lines[0] == "扫荡：青岚林"
    assert "修为 +35，灵石 +40" in reply.lines
    assert "锻灵矿 +1" in reply.lines
    assert "血脉精华 +1" in reply.lines
    assert reply.lines[-1] == "每只灵宠精力 -20；扫荡不写入战报，也不计入获胜场次。"
    assert reply.commands == ("灵宠秘境", "灵宠战报", "我的灵宠", "灵宠任务")
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == before + 40
    assert sql(game[1], "SELECT energy FROM pets WHERE user_id='u1'")[0]["energy"] == 80
    assert sql(game[1], "SELECT last_pve FROM players WHERE user_id='u1'")[0]["last_pve"] == RESTED


def test_sweep_writes_no_battle_record_and_no_win_credit(game, play):
    account(game, play)
    play("challenge", "青岚林")
    records = len(sql(game[1], "SELECT battle_id FROM battle_records"))
    progress = quest_progress(game, "pve_once")
    play("sweep", "青岚林", now=RESTED)
    assert len(sql(game[1], "SELECT battle_id FROM battle_records")) == records
    assert quest_progress(game, "pve_once") == progress


def test_sweep_rejects_team_dungeons(game, play):
    account(game, play)
    with pytest.raises(GameError, match="组队秘境"):
        play("sweep", "上古灵殿")


def test_sweep_rejects_a_pet_below_the_realm_gate(game, play):
    account(game, play)
    seed_battle(game, "moon", 0, operation="moon-clear")
    with pytest.raises(GameError, match="境界不足，月影谷需要凝气"):
        play("sweep", "月影谷")


def test_sweep_rejects_while_resting(game, play):
    account(game, play)
    play("challenge", "青岚林")
    play("sweep", "青岚林", now=RESTED)
    with pytest.raises(GameError, match="尚需调息"):
        play("sweep", "青岚林", now=RESTED + 1)


def test_sweep_rejects_a_missing_or_unknown_name(game, play):
    account(game, play)
    with pytest.raises(GameError, match="请填写秘境名称"):
        play("sweep", "")
    with pytest.raises(GameError, match="未找到该内容"):
        play("sweep", "不存在的地方")


def test_sweep_replays_one_operation_once(game, play):
    account(game, play)
    play("challenge", "青岚林")
    first = play("sweep", "青岚林", now=RESTED, op="sweep-once")
    stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    again = play("sweep", "青岚林", now=RESTED, op="sweep-once")
    assert again.title == first.title and again.lines == first.lines
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones


def test_help_lists_the_sweep_entry(game, play):
    assert "灵宠扫荡" in play("help", "秘境与关卡").text()


def test_native_payload_keeps_buttons_without_links(game, play):
    account(game, play)
    play("challenge", "青岚林")
    reply = play("sweep", "青岚林", now=RESTED)
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(reply.commands)
    assert reply.inline_commands == ()
