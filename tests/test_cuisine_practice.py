import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def prepare(game, play, *, meal="meal_rice", amount=1, level=True):
    play("adopt", "青鸾", now=NOW)
    if level:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','cuisine_dish_rice_porridge',1,1)",
        )
    sql(
        game[1],
        "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
        "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (meal, amount),
    )


def test_unregistered_page_is_read_only_and_command_is_real(game, play):
    page = play("cuisine_practice", user="u9")
    assert page.title == "灵宠膳房研修"
    assert "尚未结契" in page.text()
    assert not sql(game[1], "SELECT * FROM players")
    assert handlers._parse("灵宠膳房研修 开始 灵米粥") == (
        "cuisine_practice", "开始 灵米粥",
    )


def test_start_consumes_real_meal_and_three_steps_settle_growth(game, play):
    prepare(game, play)
    before = pet(game[1])
    start = play("cuisine_practice", "开始 灵米粥", op="practice-start")
    assert "已消耗 灵米粥 ×1" in start.text()
    assert items(game[1])["meal_rice"] == 0
    assert pet(game[1])["energy"] == before["energy"] - 8
    play("cuisine_practice", "稳火", op="practice-one")
    play("cuisine_practice", "添香", op="practice-two")
    done = play("cuisine_practice", "收盘", op="practice-three")
    assert "佳作" in done.text()
    assert "得分 6/6" in done.text()
    assert pet(game[1])["exp"] == before["exp"] + 30
    assert pet(game[1])["affinity"] == before["affinity"] + 8
    assert items(game[1])["spirit_food"] == 4
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='bond_exp_1'") == [
        {"progress": 12},
    ]
    assert "累计完成 1 局 · 佳作 1 局" in play("cuisine_practice", "记录").text()


def test_wrong_sequence_is_a_real_failed_settlement(game, play):
    prepare(game, play)
    before = pet(game[1])
    play("cuisine_practice", "开始 灵米粥", op="practice-fail-start")
    for index, action in enumerate(("添香", "收盘", "稳火")):
        reply = play("cuisine_practice", action, op=f"practice-fail-{index}")
    assert "失手" in reply.text()
    assert pet(game[1])["exp"] == before["exp"]
    assert pet(game[1])["affinity"] == before["affinity"]
    assert items(game[1])["spirit_food"] == 3
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cuisine_practice_total'") == [
        {"progress": 1},
    ]


def test_gates_do_not_mutate_inventory(game, play):
    play("adopt", "青鸾", now=NOW)
    before = items(game[1])
    with pytest.raises(GameError, match="厨艺不足"):
        play("cuisine_practice", "开始 灵米粥")
    assert items(game[1]) == before
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1','cuisine_dish_rice_porridge',1,1)",
    )
    with pytest.raises(GameError, match="没有灵米粥"):
        play("cuisine_practice", "开始 灵米粥")
    assert items(game[1]) == before


def test_outgoing_pet_is_not_a_valid_practice_consumer(game, play):
    prepare(game, play)
    play("expedition_start", "采灵药", now=NOW, op="practice-outing")
    with pytest.raises(GameError, match="外出派遣"):
        play("cuisine_practice", "开始 灵米粥", op="practice-outing-gate")
    assert items(game[1])["meal_rice"] == 1


def test_daily_gate_and_abandon_are_explicit(game, play):
    prepare(game, play)
    play("cuisine_practice", "开始 灵米粥", op="practice-abandon-start")
    abandoned = play("cuisine_practice", "放弃", op="practice-abandon")
    assert "今日名额均不退还" in abandoned.text()
    with pytest.raises(GameError, match="名额已用完"):
        play("cuisine_practice", "开始 灵米粥", op="practice-abandon-retry")
    assert items(game[1]).get("meal_rice", 0) == 0


def test_cross_day_reopens_quota_after_finished_round(game, play):
    prepare(game, play, amount=2)
    for operation, action in (
        ("day-start", "开始 灵米粥"), ("day-a", "稳火"),
        ("day-b", "添香"), ("day-c", "收盘"),
    ):
        play("cuisine_practice", action, now=NOW, op=operation)
    next_day = NOW + 86400
    page = play("cuisine_practice", now=next_day)
    assert "今日名额：可开启" in page.text()
    play("cuisine_practice", "开始 灵米粥", now=next_day, op="next-day-start")
    assert items(game[1])["meal_rice"] == 0


def test_round_survives_restart_and_replay_is_original_reply(game, play):
    prepare(game, play)
    first = play("cuisine_practice", "开始 灵米粥", op="practice-restart-start")
    play("cuisine_practice", "稳火", op="practice-restart-step")
    restarted = Game(Store(game[1].path), Config(), game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "cuisine_practice", "", "practice-restart-page", NOW + 1)
    assert "第 2/3 段" in page.text()
    replay = restarted.execute("u1", "cuisine_practice", "添香", "practice-restart-step", NOW + 2)
    assert replay.text().startswith("【灵宠膳房研修】")
    assert play("cuisine_practice", "开始 不存在", op="practice-restart-start") == first


def test_old_step_after_finished_round_cannot_start_a_new_step(game, play):
    prepare(game, play, amount=2)
    play("cuisine_practice", "开始 灵米粥", op="practice-old-start")
    play("cuisine_practice", "稳火", op="practice-old-a")
    play("cuisine_practice", "添香", op="practice-old-b")
    play("cuisine_practice", "收盘", op="practice-old-c")
    with pytest.raises(GameError, match="没有进行中的"):
        play("cuisine_practice", "稳火", op="practice-old-button")


def test_concurrent_starts_have_one_daily_round_and_one_consumption(game, play):
    prepare(game, play, amount=2)

    def attempt(operation):
        try:
            return "ok", game[0].execute(
                "u1", "cuisine_practice", "开始 灵米粥", operation, NOW,
            )
        except GameError as exc:
            return "error", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("practice-race-a", "practice-race-b")))
    assert [kind for kind, _ in results].count("ok") == 1
    assert [kind for kind, _ in results].count("error") == 1
    assert items(game[1])["meal_rice"] == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id LIKE 'cuisine_practice_day_%'") == [
        {"n": 1},
    ]


def test_failed_final_reward_rolls_back_growth_and_round_state(game, play, monkeypatch):
    prepare(game, play)
    play("cuisine_practice", "开始 灵米粥", op="practice-fail-reward-start")
    play("cuisine_practice", "稳火", op="practice-fail-reward-a")
    play("cuisine_practice", "添香", op="practice-fail-reward-b")
    before = pet(game[1]), items(game[1])
    original = Repository.add_item

    def fail_reward(self, user_id, item_id, amount):
        if item_id == "spirit_food":
            raise RuntimeError("injected cuisine practice reward failure")
        return original(self, user_id, item_id, amount)

    monkeypatch.setattr(Repository, "add_item", fail_reward)
    with pytest.raises(RuntimeError, match="injected cuisine practice reward failure"):
        play("cuisine_practice", "收盘", op="practice-fail-reward-c")
    assert (pet(game[1]), items(game[1])) == before
    active = play("cuisine_practice", "记录", op="practice-fail-reward-page")
    assert "进行中" in active.text()
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='cuisine_practice_total'") == []


def test_objectives_help_and_native_links_are_connected(game, play):
    prepare(game, play)
    objective = play("objectives")
    assert any("膳房研修：" in line for line in objective.lines)
    assert any(link.command == "灵宠膳房研修" for link in objective.inline_commands)
    help_page = play("help", "成长")
    assert "灵宠膳房研修：每天消费一份真实单膳" in help_page.text()
    page = play("cuisine_practice")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert not buttons & {link.command for link in page.inline_commands}
    assert handlers._parse("灵宠膳房研修 稳火") == ("cuisine_practice", "稳火")


def test_onebot_can_open_practice_page(game, monkeypatch):
    service, store = game
    service.execute("12345", "cuisine_practice", "", "practice-onebot-page", NOW)
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
        send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠膳房研修", 1), "!灵宠膳房研修")
        message = bot.send.call_args.args[1]
        assert "膳房研修" in message
        assert "！" not in message

    asyncio.run(run())
