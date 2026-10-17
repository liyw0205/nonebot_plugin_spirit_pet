import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player_uid, sql

NOW = 1_800_000_000  # 2027-01-15 Beijing


def keyboard_commands(reply):
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    return [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_board_orders_by_collected_then_first_pet(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    play("adopt", "白泽", user="u3", now=NOW)
    with game[1].connect() as conn:
        conn.executemany(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES (?,?,?,?)",
            [("u2", "jiaolong", "蛟龙一号", NOW), ("u3", "jiaolong", "蛟龙二号", NOW)],
        )
    page = play("collection_rank", now=NOW + 1)
    assert page.title == "灵宠收集榜"
    u1, u2, u3 = (player_uid(game[1], user) for user in ("u1", "u2", "u3"))
    assert page.lines[0] == f"1. UID {u2} · 收集 2/27 族"
    assert page.lines[1] == f"2. UID {u3} · 收集 2/27 族"
    assert page.lines[2] == f"3. UID {u1} · 收集 1/27 族"
    assert "你的当前名次：第 3 名 · 已收集 1/27 族。" in page.lines[-1]
    assert "灵宠图鉴奖励" in page.commands
    assert "灵宠收集" in page.commands


def test_retired_species_rows_do_not_count(game, play):
    play("adopt", "青鸾", now=NOW)
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u1','removed_species','旧种族',?)",
            (NOW,),
        )
    page = play("collection_rank", now=NOW + 1)
    assert "收集 1/27 族" in page.lines[0]
    assert "已收集 1/27 族" in page.lines[-1]


def test_sealed_pets_still_count(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "玄狐", user="u2", now=NOW)
    # A same-species duplicate (青鸾二号) is archived; the species must still count
    # once for the board and the personal rank, matching 灵宠收集 semantics.
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u2','xuanhu','玄狐二号',?)",
            (NOW,),
        )
    play("pet_archive", "3", user="u2", now=NOW + 1)
    page = play("collection_rank", user="u2", now=NOW + 2)
    assert "收集 1/27 族" in page.lines[0]
    # u1 adopted first (smaller first pet_id) and holds rank 1; u2 keeps rank 2
    # with its sealed duplicate still counting as one species.
    assert "你的当前名次：第 2 名 · 已收集 1/27 族。" in page.lines[-1]


def test_player_with_no_species_is_not_on_board(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    sql(game[1], "DELETE FROM pets WHERE user_id='u1'")
    page = play("collection_rank", now=NOW + 1)
    assert page.lines[0] == "尚无修士收得灵宠种族。"
    assert "你尚未收得灵宠种族 · 已收集 0/27 族。" in page.lines[-1]


def test_unregistered_browse_is_read_only(game, play):
    page = play("collection_rank", user="u9", now=NOW)
    assert page.title == "灵宠收集榜"
    assert page.lines[0] == "尚无修士收得灵宠种族。"
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_arguments_are_rejected(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="不接受参数"):
        play("collection_rank", "1", now=NOW + 1)


def test_collection_page_links_board_and_native_keyboard_stays_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    listing = play("collection", now=NOW)
    assert "灵宠收集榜" in listing.commands
    page = play("collection_rank", now=NOW + 1)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = keyboard_commands(page)
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}
    assert "灵宠图鉴奖励" in buttons or "灵宠收集" in buttons


def test_help_lists_board_and_parse_routes():
    from nonebot_plugin_spirit_pet.adapters import handlers
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    entries = _HELP_SECTIONS["身份与收集"]
    assert ("灵宠收集榜", "灵宠收集榜", "看看谁的收集最全，并查看自己的名次。") in entries
    assert handlers._parse("灵宠收集榜") == ("collection_rank", "")
    assert handlers._parse("灵宠收集") == ("collection", "")
