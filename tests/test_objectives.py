import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, sql

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def line(reply, prefix):
    return next(text for text in reply.lines if text.startswith(prefix))


def test_hub_lists_every_system(game, play):
    account(game, play)
    content = game[0].content
    reply = play("objectives")
    assert reply.title == "灵宠目标"
    assert line(reply, "今日任务：") == f"今日任务：暂无可领 · 共 {len(content.quests)} 项"
    assert line(reply, "今日秘境：").startswith("今日秘境：")
    assert line(reply, "本周周常：") == f"本周周常：暂无可领 · 共 {len(content.weekly_quests)} 项"
    assert line(reply, "主线：").startswith("主线：下一步 ")
    assert line(reply, "成就：") == f"成就：可领 1 项（初结灵契）· 共 {len(content.achievements)} 项"
    assert line(reply, "称号：") == f"称号：初入仙途 · 已获得 1/{len(content.titles)} 项"
    assert line(reply, "套装完成奖励：") == f"套装完成奖励：暂无可领 · 共 {len(content.equipment_sets)} 套"


def test_hub_tracks_equipment_set_completion_rewards(game, play):
    account(game, play)
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    play("buy", "青岚翎")
    play("equipment", "青岚翎")
    play("buy", "灵心铃")
    play("equipment", "灵心铃")
    assert line(play("objectives"), "套装完成奖励：") == "套装完成奖励：可领 1 套（青岚风铃）· 共 4 套"

    play("equipment_set_claim", "青岚风铃")
    assert line(play("objectives"), "套装完成奖励：") == "套装完成奖励：暂无可领 · 共 4 套"


def test_hub_tracks_daily_claims(game, play):
    account(game, play)
    play("sign")
    assert line(play("objectives"), "今日任务：") == "今日任务：可领 1 项（晨光初至）· 共 10 项"
    play("claim", "晨光初至")
    assert line(play("objectives"), "今日任务：") == "今日任务：暂无可领 · 共 10 项"


def test_hub_shows_the_current_main_quest_and_title(game, play):
    account(game, play)
    reply = play("objectives")
    assert line(reply, "主线：") == "主线：下一步 初结灵契 · 可领奖（1/1）"
    assert line(reply, "称号：") == "称号：初入仙途 · 已获得 1/23 项"


def test_hub_previews_without_an_account(game, play):
    reply = play("objectives", user="u9")
    assert reply.title == "灵宠目标"
    assert "尚未结契" in reply.text()
    assert reply.commands == ("灵宠帮助",)
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_hub_rejects_arguments(game, play):
    account(game, play)
    with pytest.raises(GameError, match="灵宠目标 不接受参数"):
        play("objectives", "多余")


def test_hub_is_read_only(game, play):
    account(game, play)
    energy = pet(game[1])["energy"]
    play("objectives")
    assert sql(game[1], "SELECT battle_id FROM battle_records") == []
    assert sql(game[1], "SELECT achievement_id FROM achievement_claims") == []
    assert pet(game[1])["energy"] == energy


def test_hub_replays_one_operation_once(game, play):
    account(game, play)
    first = play("objectives", op="hub-once")
    again = play("objectives", op="hub-once")
    assert again.title == first.title and again.lines == first.lines


def test_help_lists_the_hub_entry(game, play):
    assert "灵宠目标" in play("help", "身份与收集").text()


def test_native_payload_keeps_buttons_without_links(game, play):
    account(game, play)
    reply = play("objectives")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in reply.inline_commands}
    assert buttons == set(reply.commands)
    assert buttons & links == set()


def test_every_hub_link_points_at_its_own_row(game, play):
    """Each 前往 link must land on the row of the system it opens.

    The hub used to enumerate HUB_PAGES independently of the row builders, so
    adding a row (season battle pass) shifted every later link one line up and
    the last entries drifted off the page entirely.
    """
    account(game, play)
    reply = play("objectives")
    rows = {line.split("：", 1)[0]: index for index, line in enumerate(reply.lines)}
    expected = {
        "灵宠签到奖励": "连续签到",
        "灵宠灵田": "灵田",
        "灵宠首领": "周首领",
        "灵宠战令": "赛季战令",
        "灵宠排行奖励": "万灵榜奖励",
        "灵宠套装": "套装完成奖励",
        "灵宠境界赏": "境界里程碑奖励",
    }
    for link in reply.inline_commands:
        assert link.line < len(reply.lines), f"{link.command} points past the page"
    for command, prefix in expected.items():
        link = next(link for link in reply.inline_commands if link.command == command)
        assert reply.lines[link.line].startswith(prefix), (
            f"{command} points at {reply.lines[link.line][:24]!r}"
        )
