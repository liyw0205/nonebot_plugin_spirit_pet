import asyncio
import json
import re
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import items, pet, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def keyboard_commands(message):
    return {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }


def markdown_links(message):
    markdown = message["markdown"][0].data["markdown"].content
    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", markdown)
    ]


def start_job(play, game, *, user="u1", op="history-start", now=NOW):
    if not sql(game[1], "SELECT 1 FROM players WHERE user_id=?", (user,)):
        play("adopt", "青鸾", user=user, now=now)
    play("expedition_start", "采灵药", user=user, now=now, op=op)
    return sql(game[1], "SELECT * FROM expeditions WHERE user_id=? ORDER BY job_id DESC", (user,))[0]


def insert_cancelled_history(game, index, pet_id, user="u1"):
    started = NOW - 100_000 + index * 10
    sql(game[1],
        "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,"
        "finishes_at,state,reward_snapshot,settled_at) VALUES(?,?,?,?,?,?,?,'cancelled',?,?)",
        (user, pet_id, "herb_gathering", "采灵药", f"history-seed-{index}", started,
         started + 3600, json.dumps({"exp": 0, "stones": 0, "items": {}}), started + 1),
    )
    return sql(
        game[1], "SELECT job_id FROM expeditions WHERE source_operation_id=?",
        (f"history-seed-{index}",),
    )[0]["job_id"]


def test_history_is_read_only_without_a_player_and_rejects_unknown_jobs(game, play):
    listing = play("expedition_history", now=NOW)
    assert listing.title == "灵宠行程记录 1/1"
    assert "尚无委托行程记录。" in listing.lines
    assert "灵宠行程" not in listing.commands
    assert not sql(game[1], "SELECT * FROM players")

    with pytest.raises(GameError, match="没有属于你的这项行程"):
        play("expedition_history_detail", "999", now=NOW)
    assert not sql(game[1], "SELECT * FROM players")


def test_help_lists_expedition_history_commands(play):
    reply = play("help", "组队与派遣")
    assert "灵宠行程记录 [页]" in reply.text()
    assert "灵宠行程回顾 行程号" in reply.text()


def test_history_tracks_running_pending_claimed_and_cancelled_jobs(game, play):
    job = start_job(play, game)
    job_id = str(job["job_id"])

    running = play("expedition_history_detail", job_id, now=NOW)
    assert "外出中，剩余 3600 秒" in running.lines
    assert running.inline_commands[0].label == "提前召回"
    assert running.inline_commands[0].command == f"灵宠召回 {job_id}"

    snapshot = json.loads(job["reward_snapshot"])
    first_item = next((item, amount) for item, amount in snapshot["items"].items() if amount)
    item_name = game[0].content.items[first_item[0]].name
    pending = play("expedition_history_detail", job_id, now=job["finishes_at"])
    assert "已完成，待归来领取" in pending.lines
    preview = (
        f"待领取预览：修为 +{snapshot['exp']}、灵石 +{snapshot['stones']}、"
        f"{item_name} +{first_item[1]}"
    )
    assert preview in pending.lines
    assert pending.inline_commands[0].command == f"灵宠归来 {job_id}"

    claimed_reply = play(
        "expedition_claim", job_id, now=job["finishes_at"], op="history-claim",
    )
    reward_before = (player(game[1])["stones"], pet(game[1])["exp"], items(game[1]))
    assert play("expedition_claim", "ignored", now=job["finishes_at"], op="history-claim") == claimed_reply
    claimed = play("expedition_history_detail", job_id, now=job["finishes_at"])
    assert "奖励已领取" in claimed.lines
    assert f"实际发放：修为 +{snapshot['exp']}、灵石 +{snapshot['stones']}" in claimed.lines
    assert f"实际道具：{item_name} +{first_item[1]}" in claimed.lines
    assert "领取凭证：已永久保存" in claimed.lines
    assert claimed.inline_commands == ()
    restarted = Game(Store(game[1].path), game[0].config, content=game[0].content)
    assert restarted.execute(
        "u1", "expedition_history_detail", job_id, "history-after-restart", job["finishes_at"],
    ) == claimed

    current = game[0].content
    tasks = dict(current.expeditions)
    tasks.pop(job["task_id"])
    catalog = dict(current.items)
    catalog.pop(first_item[0])
    game[0].content = replace(current, expeditions=tasks, items=catalog)
    historical = play("expedition_history_detail", job_id, now=job["finishes_at"] + 1)
    assert f"行程 {job_id} · {job['task_name']}" in historical.lines[0]
    assert f"物品 {first_item[0]} +{first_item[1]}" in historical.lines[5]
    assert reward_before == (player(game[1])["stones"], pet(game[1])["exp"], items(game[1]))
    game[0].content = current

    second = start_job(play, game, op="history-cancel", now=job["finishes_at"] + 1)
    play("expedition_cancel", str(second["job_id"]), now=second["started_at"] + 1)
    cancelled = play("expedition_history_detail", str(second["job_id"]), now=second["started_at"] + 1)
    assert "已提前召回，无奖励" in cancelled.lines
    assert "出发精力不退" in "\n".join(cancelled.lines)
    assert not cancelled.inline_commands


def test_history_paginates_newest_first_and_native_links_stay_out_of_buttons(game, play):
    claimed = start_job(play, game, op="history-page-claimed")
    play("expedition_claim", str(claimed["job_id"]), now=claimed["finishes_at"])
    cancelled = start_job(play, game, op="history-page-cancel", now=claimed["finishes_at"] + 1)
    play("expedition_cancel", str(cancelled["job_id"]), now=cancelled["started_at"] + 1)
    pet_id = pet(game[1])["pet_id"]
    for index in range(4):
        insert_cancelled_history(game, index, pet_id)

    first = play("expedition_history", now=NOW + 5000)
    assert first.title == "灵宠行程记录 1/2"
    assert len(first.inline_commands) == 5
    ids = [int(line.split(" · ", 1)[0].removeprefix("行程 ")) for line in first.lines[::2]]
    assert ids == sorted(ids, reverse=True)
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    buttons = keyboard_commands(message)
    assert len(buttons) <= 4
    assert not buttons & {link.command for link in first.inline_commands}
    assert markdown_links(message) == [("查看详情", f"/{link.command}") for link in first.inline_commands]

    last = play("expedition_history", "2", now=NOW + 5000)
    assert last.title == "灵宠行程记录 2/2"
    assert 1 <= len(last.inline_commands) <= 5
    oldest_id = last.lines[0].split(" · ", 1)[0].removeprefix("行程 ")
    detail = play("expedition_history_detail", oldest_id, now=NOW + 5000)
    assert "灵宠行程记录 2" in detail.commands
    with pytest.raises(GameError, match="灵宠行程记录共 2 页"):
        play("expedition_history", "3", now=NOW + 5000)


def test_history_hides_other_players_jobs_and_reports_corrupt_snapshots(game, play):
    job = start_job(play, game, op="history-private")
    play("adopt", "玄狐", user="u2")
    with pytest.raises(GameError) as unknown:
        play("expedition_history_detail", str(job["job_id"]), user="u2")
    with pytest.raises(GameError) as private:
        play("expedition_history_detail", "999999", user="u2")
    assert str(unknown.value) == str(private.value)
    assert job["task_name"] not in str(unknown.value)

    before = player(game[1]), pet(game[1]), items(game[1])
    sql(game[1], "UPDATE expeditions SET reward_snapshot='not-json' WHERE job_id=?", (job["job_id"],))
    with pytest.raises(GameError, match="奖励快照暂不可回顾"):
        play("expedition_history_detail", str(job["job_id"]), now=job["finishes_at"])
    listing = play("expedition_history", now=job["finishes_at"])
    assert "奖励快照异常" in "\n".join(listing.lines)
    with pytest.raises(GameError, match="奖励快照暂不可领取"):
        play("expedition_claim", str(job["job_id"]), now=job["finishes_at"])
    assert sql(game[1], "SELECT state FROM expeditions WHERE job_id=?", (job["job_id"],)) == [
        {"state": "running"},
    ]
    assert (player(game[1]), pet(game[1]), items(game[1])) == before


def test_failed_expedition_reward_leaves_history_pending_and_retryable(game, play):
    job = start_job(play, game, op="history-failed-reward")
    reward_items = json.loads(job["reward_snapshot"])["items"]
    item_id, amount = next((item, count) for item, count in reward_items.items() if count)
    before = player(game[1]), pet(game[1]), items(game[1])
    sql(game[1],
        "CREATE TRIGGER fail_history_reward_update BEFORE UPDATE ON inventory "
        f"WHEN OLD.item_id='{item_id}' BEGIN SELECT RAISE(ABORT,'history reward failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="history reward failure"):
        play("expedition_claim", str(job["job_id"]), now=job["finishes_at"], op="history-retry")
    assert sql(game[1], "SELECT state FROM expeditions WHERE job_id=?", (job["job_id"],)) == [
        {"state": "running"},
    ]
    assert (player(game[1]), pet(game[1]), items(game[1])) == before
    pending = play("expedition_history_detail", str(job["job_id"]), now=job["finishes_at"])
    assert "已完成，待归来领取" in pending.lines

    sql(game[1], "DROP TRIGGER fail_history_reward_update")
    play("expedition_claim", str(job["job_id"]), now=job["finishes_at"], op="history-retry")
    assert "奖励已领取" in play(
        "expedition_history_detail", str(job["job_id"]), now=job["finishes_at"],
    ).lines


def test_onebot_can_open_personal_expedition_history(game, monkeypatch):
    service, store = game
    service.execute("12345", "adopt", "青鸾", "history-onebot-adopt", NOW)
    service.execute("12345", "expedition_start", "采灵药", "history-onebot-start", NOW)
    job_id = sql(store, "SELECT job_id FROM expeditions WHERE user_id='12345'")[0]["job_id"]
    monkeypatch.setattr(handlers, "game", service)
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_command_prefix="!"))
    bot = SimpleNamespace(
        self_id="9000", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"), send=AsyncMock(),
    )

    async def run():
        await handlers._run(bot, onebot_event("!灵宠行程记录", 1), "!灵宠行程记录")
        listing = bot.send.call_args.args[1]
        assert f"查看详情（!灵宠行程回顾 {job_id}）" in listing
        await handlers._run(bot, onebot_event(f"!灵宠行程回顾 {job_id}", 2), f"!灵宠行程回顾 {job_id}")
        detail = bot.send.call_args.args[1]
        assert "提前召回（!灵宠召回" in detail

    asyncio.run(run())
