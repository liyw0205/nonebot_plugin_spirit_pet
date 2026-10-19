import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
DURATION = 3600


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_hasten_pricing_rounds_up_and_caps(game, play):
    from nonebot_plugin_spirit_pet.gameplay.expeditions import hasten_cost

    assert hasten_cost(3600) == 600      # full duration hits the cap
    assert hasten_cost(3001) == 510      # ceil(3001/60)=51 minutes
    assert hasten_cost(3000) == 500
    assert hasten_cost(1) == 10          # sub-minute bills one minute
    assert hasten_cost(0) == 0


def test_status_shows_remaining_and_hasten_budget(game, play):
    play("adopt", "青鸾", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-status")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    page = play("expedition_status", now=NOW + 600)
    assert "外出中，剩余 3000 秒；加急需 500 灵石。" in page.lines[1]
    assert any(link.command == f"灵宠加急 {job_id}" for link in page.inline_commands)


def test_hasten_completes_now_and_claim_grants_full_reward(game, play):
    play("adopt", "青鸾", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-full")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    sql(game[1], "UPDATE players SET stones=10000")
    before = player(game[1])["stones"]

    result = play("expedition_hasten", str(job_id), now=NOW + 600, op="hs-pay")
    assert f"已支付 500 灵石" in result.lines[0]
    assert player(game[1])["stones"] == before - 500
    row = sql(game[1], "SELECT finishes_at, state FROM expeditions")[0]
    assert row["finishes_at"] == NOW + 600
    assert row["state"] == "running"

    # The pet stays occupied until 归来; claim path is untouched.
    claimed = play("expedition_claim", str(job_id), now=NOW + 601, op="hs-claim")
    assert "完成采灵药" in claimed.lines[0]
    assert "修为 +" in claimed.text() and "灵石 +" in claimed.text()
    assert sql(game[1], "SELECT state FROM expeditions")[0]["state"] == "claimed"


def test_hasten_cap_limits_full_duration_charge(game, play):
    play("adopt", "青鸾", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-cap")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    sql(game[1], "UPDATE players SET stones=10000")
    before = player(game[1])["stones"]
    result = play("expedition_hasten", str(job_id), now=NOW + 1, op="hs-cap-pay")
    assert "已支付 600 灵石" in result.lines[0]
    assert "已达单次加急上限" in result.lines[1]
    assert player(game[1])["stones"] == before - 600


def test_insufficient_stones_rejects_without_changes(game, play):
    play("adopt", "青鸾", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-poor")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    before = player(game[1]), sql(game[1], "SELECT finishes_at FROM expeditions")[0]["finishes_at"]
    with pytest.raises(GameError, match="灵石不足"):
        play("expedition_hasten", str(job_id), now=NOW + 600, op="hs-poor-pay")
    assert (player(game[1]), sql(game[1], "SELECT finishes_at FROM expeditions")[0]["finishes_at"]) == before


def test_finished_foreign_and_clock_rollback_rejected(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-edge")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    play("expedition_hasten", str(job_id), now=NOW + DURATION - 1, op="hs-finish")
    with pytest.raises(GameError, match="行程已经完成"):
        play("expedition_hasten", str(job_id), now=NOW + DURATION, op="hs-again")
    with pytest.raises(GameError, match="没有属于你的这项行程"):
        play("expedition_hasten", str(job_id), user="u2", now=NOW + 1, op="hs-foreign")
    play("expedition_start", "采灵药", user="u2", now=NOW + DURATION + 2, op="hs-u2")
    job2 = sql(game[1], "SELECT job_id FROM expeditions WHERE user_id='u2'")[0]["job_id"]
    with pytest.raises(GameError, match="当前时间早于出发时间"):
        play("expedition_hasten", str(job2), user="u2", now=NOW + DURATION + 1, op="hs-rollback")


def test_replayed_operation_returns_original_reply(game, play):
    play("adopt", "青鸾", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-replay")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    sql(game[1], "UPDATE players SET stones=10000")
    first = play("expedition_hasten", str(job_id), now=NOW + 600, op="hs-replay-pay")
    again = play("expedition_hasten", str(job_id), now=NOW + 700, op="hs-replay-pay")
    assert again == first
    assert player(game[1])["stones"] == 10000 - 500  # charged once


def test_unregistered_cannot_hasten(game, play):
    with pytest.raises(GameError):
        play("expedition_hasten", "1", user="u9", now=NOW)
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_native_keyboard_clean_and_parse(game, play):
    play("adopt", "青鸾", now=NOW)
    play("expedition_start", "采灵药", now=NOW, op="hs-native")
    job_id = sql(game[1], "SELECT job_id FROM expeditions")[0]["job_id"]
    page = play("expedition_status", now=NOW + 600)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert f"灵宠加急 {job_id}" not in buttons
    assert not set(buttons) & {link.command for link in page.inline_commands}
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠加急 1") == ("expedition_hasten", "1")
    assert handlers._parse("灵宠加急") == ("expedition_hasten", "")
