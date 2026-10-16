import json
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql


def seed_battle(
    game,
    *,
    user="u1",
    kind="pve",
    side=0,
    winner_side=0,
    operation="seed-battle",
    participants=None,
):
    participants = participants or [(user, side)]
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, title, winner_side, rounds, "
            "played_at, reply, snapshot, battle_log) VALUES (?, ?, ?, 'seed', ?, 3, 1, '{}', ?, '[]')",
            (operation, user, kind, winner_side, json.dumps({"teams": []})),
        )
        conn.executemany(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) VALUES (?, ?, ?, 'participant')",
            [(cursor.lastrowid, participant, participant_side) for participant, participant_side in participants],
        )


def test_unregistered_catalog_is_read_only(game, play):
    page = play("battle_merits", user="u9")
    assert page.title == "战斗功勋"
    assert "5 胜 · 初阵告捷 · 灵石 180，锻灵矿 1" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    with pytest.raises(GameError, match="先完成领养|格式"):
        play("battle_merit_claim", "5", user="u9")


def test_valid_battle_wins_exclude_spar_losses_and_draws(game, play):
    play("adopt", "青鸾")
    seed_battle(game, operation="pve-win")
    seed_battle(game, kind="pve_stage", operation="stage-win")
    seed_battle(game, kind="pvp", operation="pvp-win")
    seed_battle(game, kind="pvp", side=1, winner_side=1, operation="defender-win")
    seed_battle(game, kind="spar", operation="spar-win")
    seed_battle(game, winner_side=1, operation="pve-loss")
    seed_battle(game, winner_side=-1, operation="pve-draw")
    page = play("battle_merits")
    assert "当前有效胜场：4 场" in page.text()
    assert "5 胜 · 初阵告捷 · 灵石 180，锻灵矿 1 · 还差 1 场" in page.text()
    assert page.inline_commands == ()


def test_team_win_counts_once_per_participant(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    seed_battle(
        game, user="u1", operation="team-win", participants=[("u1", 0), ("u2", 0)],
    )
    assert "当前有效胜场：1 场" in play("battle_merits", user="u1").text()
    assert "当前有效胜场：1 场" in play("battle_merits", user="u2").text()


def test_milestones_pay_once_and_persist_claim_progress(game, play):
    play("adopt", "青鸾")
    for index in range(5):
        seed_battle(game, operation=f"win-{index}")
    before_stones = player(game[1])['stones']
    reply = play("battle_merit_claim", "5", op="merit-claim")
    assert reply.title == "战斗功勋奖励"
    assert player(game[1])['stones'] == before_stones + 180
    assert items(game[1])['forge_ore'] == 1
    row = sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id='battle_merit_5'")[0]
    assert row == {"progress": 5, "claimed": 1}
    assert play("battle_merits").lines[1].endswith("· 已领取")
    with pytest.raises(GameError, match="已领取"):
        play("battle_merit_claim", "5")
    replay = play("battle_merit_claim", "5", op="merit-claim")
    assert replay == reply
    assert player(game[1])['stones'] == before_stones + 180


def test_all_milestones_can_be_claimed_from_derived_history(game, play):
    play("adopt", "青鸾")
    for index in range(50):
        seed_battle(game, operation=f"many-wins-{index}")
    assert "可领取" in play("battle_merits").text()
    before = player(game[1])['stones']
    play("battle_merit_claim", "5")
    play("battle_merit_claim", "20")
    play("battle_merit_claim", "50")
    assert player(game[1])['stones'] == before + 180 + 600 + 1500
    assert items(game[1])['forge_ore'] == 6
    assert items(game[1])['bloodline_essence'] == 4
    assert all("已领取" in line for line in play("battle_merits").lines[1:])


@pytest.mark.parametrize("argument", ["", "6", "5 20", "abc"])
def test_claim_rejects_invalid_milestone_arguments(game, play, argument):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="格式"):
        play("battle_merit_claim", argument)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'battle_merit_%'") == []


def test_missing_reward_definition_fails_without_mutation(game, play):
    play("adopt", "青鸾")
    for index in range(5):
        seed_battle(game, operation=f"missing-reward-{index}")
    original = game[0].content
    game[0].content = replace(original, items={key: value for key, value in original.items.items() if key != "forge_ore"})
    before = player(game[1])['stones']
    with pytest.raises(GameError, match="奖励物品定义缺失或类型错误"):
        play("battle_merit_claim", "5")
    assert player(game[1])['stones'] == before
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='battle_merit_5'") == []


def test_objectives_help_and_native_links_are_connected(game, play):
    play("adopt", "青鸾")
    for index in range(5):
        seed_battle(game, operation=f"hub-win-{index}")
    objective = play("objectives")
    assert "战斗功勋：可领 1 档（5 胜）· 当前 5 胜" in objective.text()
    assert objective.inline_commands[objective.lines.index("战斗功勋：可领 1 档（5 胜）· 当前 5 胜")].command == "灵宠战斗功勋"
    help_page = play("help", "对战与赛季")
    assert "灵宠战斗功勋：查看有效胜场与长期功勋奖励。" in help_page.text()
    assert "灵宠战斗功勋领奖 胜场：领取已达成的战斗功勋里程碑奖励。" in help_page.text()
    page = play("battle_merits")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & {link.command for link in page.inline_commands}
