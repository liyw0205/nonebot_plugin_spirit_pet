from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.storage.database import Store

from .support import sql


def test_naming_command_is_removed(game):
    assert _parse("灵宠命名 1 听风") is None


def test_historical_pet_name_remains_readable_after_restart(game, play):
    play("adopt", "青鸾", now=1_800_000_000)
    sql(game[1], "UPDATE pets SET name='听风' WHERE pet_id=1")
    assert "听风" in play("status").text()
    assert "听风" in play("pet_list").text()

    Store(game[1].path).initialize()
    assert "听风" in play("status", op="status-after-restart").text()


def test_pet_pages_have_no_naming_actions(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET name='听风' WHERE pet_id=1")
    for action in ("status", "pet_list", "pet_archive_list"):
        assert all("命名" not in command.command for command in play(action).inline_commands)
