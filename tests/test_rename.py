import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, sql

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def add_pet(game, play, species="青鸾", user="u1"):
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id=?", (user,))
    play("summon", "1", user=user)


def names(game, user="u1"):
    return [row["name"] for row in sql(
        game[1], "SELECT name FROM pets WHERE user_id=? ORDER BY pet_id", (user,),
    )]


def test_rename_updates_the_name_and_the_roster(game, play):
    account(game, play)
    reply = play("rename", "1 凌霄")
    assert reply.title == "灵宠改名"
    assert reply.lines[0] == "青鸾（编号 1）已改名为凌霄。"
    assert reply.commands == ("灵宠切换 1", "灵宠列表", "我的灵宠")
    assert names(game) == ["凌霄"]
    assert sql(game[1], "SELECT species_id FROM pets WHERE pet_id=1")[0]["species_id"] == "qingluan"
    assert "编号 1：凌霄（青鸾）" in play("pet_list").text()


def test_rename_lets_the_pet_be_switched_by_its_new_name(game, play):
    account(game, play)
    play("rename", "1 凌霄")
    assert play("switch", "凌霄").lines == ("当前灵宠：凌霄（编号 1）。",)
    # The species name no longer matches this pet; the new name does.
    with pytest.raises(GameError, match="未找到灵宠或名字重复"):
        play("switch", "青鸾")


def test_rename_rejects_a_name_used_by_another_pet(game, play):
    account(game, play)
    add_pet(game, play)
    play("rename", "1 凌霄")
    with pytest.raises(GameError, match="名册中已有叫凌霄的灵宠"):
        play("rename", "2 凌霄")
    assert names(game) == ["凌霄", "青鸾"]


def test_rename_rejects_bad_names(game, play):
    account(game, play)
    for argument in ("", "1", "1 凌霄 多余"):
        with pytest.raises(GameError, match="请按 灵宠改名 编号 新名字 发送"):
            play("rename", argument)
    with pytest.raises(GameError, match="最多 8 个字符"):
        play("rename", "1 一二三四五六七八九")
    with pytest.raises(GameError, match="不能全是数字"):
        play("rename", "1 12345")
    with pytest.raises(GameError, match="名字没有变化"):
        play("rename", "1 青鸾")
    assert names(game) == ["青鸾"]


def test_rename_rejects_a_foreign_or_unknown_pet(game, play):
    account(game, play)
    with pytest.raises(GameError, match="数量须为"):
        play("rename", "abc 凌霄")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("rename", "99 凌霄")
    assert names(game) == ["青鸾"]


def test_rename_works_on_an_archived_pet_without_changing_its_state(game, play):
    account(game, play)
    add_pet(game, play)
    play("pet_archive", "2")
    reply = play("rename", "2 云隐")
    assert reply.lines[0] == "青鸾（编号 2）已改名为云隐。"
    assert sql(game[1], "SELECT archived FROM pets WHERE pet_id=2")[0]["archived"] == 1
    assert "云隐（青鸾）" in play("pet_archive_list").text()


def test_rename_costs_nothing_and_writes_no_records(game, play):
    account(game, play)
    stones = sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"]
    energy = pet(game[1])["energy"]
    bag = items(game[1])
    play("rename", "1 凌霄")
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == stones
    assert pet(game[1])["energy"] == energy
    assert items(game[1]) == bag
    assert sql(game[1], "SELECT battle_id FROM battle_records") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []


def test_rename_replays_one_operation_once(game, play):
    account(game, play)
    first = play("rename", "1 凌霄", op="rename-once")
    again = play("rename", "1 凌霄", op="rename-once")
    assert again.title == first.title and again.lines == first.lines
    assert names(game) == ["凌霄"]


def test_help_lists_the_rename_entry(game, play):
    assert "灵宠改名" in play("help", "结契").text()


def test_native_payload_keeps_buttons_without_links(game, play):
    account(game, play)
    reply = play("rename", "1 凌霄")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(reply.commands)
    assert reply.inline_commands == ()
