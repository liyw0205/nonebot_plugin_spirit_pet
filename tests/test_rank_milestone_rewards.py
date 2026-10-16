from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000


def adopt_accounts(game, play, count=1):
    for index in range(1, count + 1):
        play("adopt", "青鸾", user=f"u{index}")


def update_pet(game, user, *, realm=0, layer=1, exp=0, archived=0):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=?, exp=?, archived=? WHERE user_id=?",
        (realm, layer, exp, archived, user),
    )


def test_unregistered_catalog_is_read_only_and_prefix_is_unambiguous(game, play):
    page = play("rank_rewards", user="u9")
    assert page.title == "万灵榜奖励"
    assert "前 3 名 · 三甲争锋 · 灵石 1600，锻灵矿 4，血脉精华 2" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert _parse("灵宠排行奖励") == ("rank_rewards", "")
    assert _parse("灵宠排行领奖 3") == ("rank_reward_claim", "3")
    with pytest.raises(GameError, match="先完成领养|格式"):
        play("rank_reward_claim", "3", user="u9")


def test_board_uses_one_highest_active_pet_and_exposes_personal_rank(game, play):
    adopt_accounts(game, play, 3)
    update_pet(game, "u1", realm=1, layer=2, exp=10)
    update_pet(game, "u2", realm=3, layer=1, exp=2)
    update_pet(game, "u3", realm=6, layer=10, exp=999, archived=1)
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id, species_id, name, realm, layer, exp, energy_updated) "
            "VALUES ('u1', 'xuanhu', '更高伙伴', 4, 1, 1, ?)", (NOW,)
        )

    board = play("rank", user="u1")
    assert board.lines[0].startswith("1. UID 10000 · 更高伙伴 ·")
    assert "2. UID 10001" in board.text()
    assert "UID 10002" not in board.text()
    assert "你的当前名次：第 1 名。" in board.text()


def test_milestones_claim_once_and_snapshot_survives_rank_drop(game, play):
    adopt_accounts(game, play)
    update_pet(game, "u1", realm=6, layer=10, exp=999)
    page = play("rank_rewards")
    assert "当前万灵榜名次：第 1 名。" in page.text()
    assert page.inline_commands == tuple(
        link for link in page.inline_commands if link.command in {
            "灵宠排行领奖 3", "灵宠排行领奖 10", "灵宠排行领奖 20",
        }
    )
    before = player(game[1])["stones"]
    replies = {}
    for threshold in (3, 10, 20):
        replies[threshold] = play("rank_reward_claim", str(threshold), op=f"rank-claim-{threshold}")
    assert player(game[1])["stones"] == before + 1600 + 700 + 220
    assert items(game[1])["forge_ore"] == 7
    assert items(game[1])["bloodline_essence"] == 3
    rows = sql(
        game[1],
        "SELECT quest_id, progress, claimed FROM quest_progress "
        "WHERE user_id='u1' AND quest_id LIKE 'rank_milestone_%' ORDER BY quest_id",
    )
    assert rows == [
        {"quest_id": "rank_milestone_10", "progress": 1, "claimed": 1},
        {"quest_id": "rank_milestone_20", "progress": 1, "claimed": 1},
        {"quest_id": "rank_milestone_3", "progress": 1, "claimed": 1},
    ]
    with game[1].connect() as conn:
        for index in range(2, 7):
            conn.execute(
                "INSERT INTO players(user_id, stones, registered_at) VALUES (?, 0, ?)",
                (f"higher-{index}", NOW),
            )
            conn.execute("INSERT INTO player_identity(user_id) VALUES (?)", (f"higher-{index}",))
            conn.execute(
                "INSERT INTO pets(user_id, species_id, name, realm, layer, exp, energy_updated) "
                "VALUES (?, 'qingluan', ?, 6, 10, ?, ?)",
                (f"higher-{index}", f"高位{index}", 1000 - index, NOW),
            )
    dropped = play("rank_rewards")
    assert "前 3 名 · 三甲争锋" in dropped.text() and "已领取（第 1 名）" in dropped.text()
    assert play("rank_reward_claim", "3", op="rank-claim-3") == replies[3]


def test_rank_gate_and_invalid_arguments_do_not_create_progress(game, play):
    adopt_accounts(game, play, 4)
    update_pet(game, "u1", realm=1, layer=1, exp=0)
    update_pet(game, "u2", realm=6, layer=10, exp=10)
    update_pet(game, "u3", realm=5, layer=10, exp=10)
    update_pet(game, "u4", realm=4, layer=10, exp=10)
    with pytest.raises(GameError, match="尚未进入前 3 名"):
        play("rank_reward_claim", "3")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'rank_milestone_%'") == []
    for argument in ("", "4", "3 10", "abc"):
        with pytest.raises(GameError, match="格式"):
            play("rank_reward_claim", argument)


def test_missing_reward_and_corrupt_record_are_stable(game, play):
    adopt_accounts(game, play)
    update_pet(game, "u1", realm=6, layer=10, exp=999)
    original = game[0].content
    game[0].content = replace(
        original,
        items={key: value for key, value in original.items.items() if key != "forge_ore"},
    )
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="奖励物品定义缺失或类型错误"):
        play("rank_reward_claim", "3")
    assert player(game[1])["stones"] == before
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='rank_milestone_3'") == []

    game[0].content = original
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', 'rank_milestone_3', 99, 1)",
    )
    with pytest.raises(GameError, match="已领取"):
        play("rank_reward_claim", "3")
    assert "领取记录异常" in play("rank_rewards").text()


def test_objectives_help_and_native_links_are_connected(game, play):
    adopt_accounts(game, play)
    update_pet(game, "u1", realm=6, layer=10, exp=999)
    objective = play("objectives")
    line = next(line for line in objective.lines if line.startswith("万灵榜奖励："))
    assert line == "万灵榜奖励：可领 3 档（前 3 名、前 10 名、前 20 名）· 当前第 1 名"
    assert objective.inline_commands[objective.lines.index(line)].command == "灵宠排行奖励"
    help_page = play("help", "血脉与道具")
    assert "灵宠排行奖励：查看万灵榜名次奖励与自己的领取状态。" in help_page.text()
    assert "灵宠排行领奖 名次：领取已进入前 3、10 或 20 名的一次性奖励。" in help_page.text()
    page = play("rank_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & {link.command for link in page.inline_commands}
