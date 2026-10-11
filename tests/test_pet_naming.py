import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import sql


def test_unregistered_naming_uses_first_adoption_guidance_without_writing(game, play):
    assert _parse("灵宠命名 1 听风") == ("pet_name", "1 听风")
    with pytest.raises(GameError) as rejected:
        play("pet_name")
    reply = rejected.value.reply
    assert reply is not None
    assert "首次领养" in reply.text()
    assert not sql(game[1], "SELECT * FROM players")


def test_naming_active_pet_persists_and_replays_after_restart(game, play):
    play("adopt", "青鸾", now=1_800_000_000)
    prompt = play("pet_name")
    assert prompt.inline_commands[0].command == "灵宠命名 1 "

    renamed = play("pet_name", "听风", op="rename-active")
    assert "青鸾已改名为听风" in renamed.text()
    assert sql(game[1], "SELECT name FROM pets WHERE pet_id=1") == [{"name": "听风"}]
    assert "听风" in play("status").text()

    Store(game[1].path).initialize()
    assert "听风" in play("status", op="status-after-restart").text()


def test_naming_explicit_owned_pet_does_not_require_active_roster(game, play):
    play("adopt", "青鸾")
    play("summon")
    play("pet_name", "2 霜羽", op="rename-second")
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")

    renamed = play("pet_name", "2 雪团", op="rename-archived")
    assert "霜羽已改名为雪团" in renamed.text()
    assert sql(game[1], "SELECT name FROM pets WHERE pet_id=2") == [{"name": "雪团"}]


def test_naming_without_active_pet_points_to_roster(game, play):
    play("adopt", "青鸾")
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")

    prompt = play("pet_name")
    assert "没有出战伙伴" in prompt.text()
    assert len(prompt.inline_commands) == 1
    assert prompt.inline_commands[0].command == "灵宠列表"
    with pytest.raises(GameError) as missing_target:
        play("pet_name", "雪团", op="rename-without-id")
    assert missing_target.value.reply is not None
    assert missing_target.value.reply.inline_commands[0].command == "灵宠列表"
    assert play("pet_name", "1 雪团", op="rename-without-roster").title == "灵宠新名"


@pytest.mark.parametrize("arg", ["1 太长的灵宠名字真的超过十二字", "1 带_空", "1 @名字"])
def test_naming_rejects_unsafe_names(game, play, arg):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="1-12 个汉字"):
        play("pet_name", arg)


def test_naming_links_are_contextual_blue_links_and_onebot_text_is_readable(game, play):
    pytest.importorskip("nonebot.adapters.qq")
    play("adopt", "青鸾")
    reply = play("pet_list")
    fallback, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    markdown = message["markdown"][0].data["markdown"].content
    link = re.search(r"\[改名\]\((mqqapi://[^)]+)\)", markdown)
    assert link is not None
    assert parse_qs(urlparse(link.group(1)).query)["command"] == ["/灵宠命名 1 "]
    assert "改名（灵宠命名 1）" in fallback

    _, status_message = _qq_segments(play("status"), Config(spirit_pet_qq_mode="native"))
    status_markdown = status_message["markdown"][0].data["markdown"].content
    status_link = re.search(r"\[给灵宠改名\]\((mqqapi://[^)]+)\)", status_markdown)
    assert status_link is not None
    assert parse_qs(urlparse(status_link.group(1)).query)["command"] == ["/灵宠命名 1 "]
