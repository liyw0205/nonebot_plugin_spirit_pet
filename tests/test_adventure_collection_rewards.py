from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.adventure_collection_rewards import MILESTONES, claim_id

from .support import items, player, sql

NOW = 1_800_000_000


def discover(game, count, *, user="u1", stamp=1):
    encounter_ids = tuple(game[0].content.encounters)[:count]
    with game[1].connect() as conn:
        conn.executemany(
            "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
            [(user, encounter_id, stamp + index) for index, encounter_id in enumerate(encounter_ids)],
        )
    return encounter_ids


def test_unregistered_catalog_is_read_only_and_commands_parse(game, play):
    page = play("adventure_collection_rewards", user="u9")
    assert page.title == "奇闻收集奖励"
    assert [line.split(" 条 · ", 1)[0] for line in page.lines[:4]] == ["3", "7", "14", "21"]
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert handlers._parse("灵宠奇闻奖励") == ("adventure_collection_rewards", "")
    assert handlers._parse("灵宠奇闻领奖 14") == ("adventure_collection_reward_claim", "14")
    with pytest.raises(GameError, match="先完成领养"):
        play("adventure_collection_reward_claim", "3", user="u9")


def test_discoveries_are_unique_and_rank_exposes_personal_milestones(game, play):
    play("adopt", "青鸾")
    discover(game, 3)
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
            ("u1", "removed_event", NOW),
        )
    rank = play("adventure_rank")
    assert "当前独立奇闻：3/21 条。" in rank.lines
    assert [link.command for link in rank.inline_commands] == ["灵宠奇闻奖励", "灵宠奇闻领奖 3"]
    assert "灵宠奇闻奖励" in rank.commands
    assert "奇闻 3/21" in rank.lines[0]


def test_all_milestones_grant_once_and_persist_in_quest_progress(game, play):
    play("adopt", "青鸾")
    discover(game, len(game[0].content.encounters))
    page = play("adventure_collection_rewards")
    assert [link.command for link in page.inline_commands] == [
        f"灵宠奇闻领奖 {threshold}" for threshold, _, _, _ in MILESTONES
    ]
    before_stones = player(game[1])["stones"]
    before_items = items(game[1])
    for threshold, name, stones, reward_items in MILESTONES:
        result = play("adventure_collection_reward_claim", str(threshold), op=f"adventure-claim-{threshold}")
        assert result.lines[0] == f"{threshold} 条里程碑「{name}」已领取。"
        assert player(game[1])["stones"] == before_stones + stones
        for item_id, amount in reward_items.items():
            assert items(game[1])[item_id] == before_items.get(item_id, 0) + amount
        assert play(
            "adventure_collection_reward_claim", str(threshold), op=f"adventure-claim-{threshold}"
        ) == result
        before_stones += stones
        before_items = items(game[1])

    assert sql(
        game[1],
        "SELECT quest_id, progress, claimed FROM quest_progress "
        "WHERE user_id='u1' AND quest_id LIKE 'adventure_collection_%' ORDER BY quest_id",
    ) == [
        {"quest_id": claim_id(threshold), "progress": 21, "claimed": 1}
        for threshold in (14, 21, 3, 7)
    ]


@pytest.mark.parametrize("argument", ["", "4", "03", "3 7", "many"])
def test_claim_rejects_invalid_or_unreached_threshold_without_progress(game, play, argument):
    play("adopt", "青鸾")
    discover(game, 2)
    with pytest.raises(GameError, match="格式：灵宠奇闻领奖"):
        play("adventure_collection_reward_claim", argument)
    assert not sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'adventure_collection_%'"
    )
    with pytest.raises(GameError, match="独立奇闻不足"):
        play("adventure_collection_reward_claim", "3")


def test_missing_reward_definition_rolls_back_without_claiming(game, play):
    play("adopt", "青鸾")
    discover(game, 3)
    original = game[0].content
    game[0].content = replace(
        original,
        items={key: value for key, value in original.items.items() if key != "spirit_food"},
    )
    before = player(game[1])["stones"]
    with pytest.raises(GameError, match="奖励物品定义缺失或类型错误"):
        play("adventure_collection_reward_claim", "3")
    assert player(game[1])["stones"] == before
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (claim_id(3),))


def test_objectives_help_and_native_links_are_connected(game, play):
    play("adopt", "青鸾")
    discover(game, 7)
    objective = play("objectives")
    line = next(line for line in objective.lines if line.startswith("奇闻收集："))
    assert line == "奇闻收集：可领 2 档（3 条、7 条）· 已发现 7/21 条"
    index = objective.lines.index(line)
    assert objective.inline_commands[index].command == "灵宠奇闻奖励"
    help_page = play("help", "秘境与关卡")
    assert "灵宠奇闻奖励：查看 3、7、14、21 条奇闻收集里程碑与领取状态。" in help_page.text()
    assert "灵宠奇闻领奖 数量：领取已发现 3、7、14 或 21 条奇闻的一次性奖励。" in help_page.text()
    page = play("adventure_collection_rewards")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in page.inline_commands}
    assert buttons == set(page.commands)
    assert not buttons & links
