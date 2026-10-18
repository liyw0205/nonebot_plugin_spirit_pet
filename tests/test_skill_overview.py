import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000


def row(page, text):
    return next(line for line in page.lines if text in line)


def test_catalog_lists_all_skills_with_unlearned_state(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "风刃术诀 1", now=NOW)
    play("learn", "风刃术", now=NOW)
    page = play("skill_overview", now=NOW + 1)
    assert page.title.startswith("万法总览 ")
    assert row(page, "风刃术") == "风刃术 · 修习 1 宠 · 最高 1 级 · 总熟练度 0"
    assert any(line == "赤焰术 · 尚未修习" for line in page.lines)
    assert "灵宠技能图鉴" in page.commands
    assert "灵宠灵术赏" in page.commands


def test_detail_lists_each_learner_with_mastery_and_equipped(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "风刃术诀 2", now=NOW)
    play("learn", "风刃术", now=NOW)
    play("summon", now=NOW + 1)  # FixedRandom draws 青鸾二号
    play("switch", "2", now=NOW + 2)
    play("learn", "风刃术", now=NOW + 3)
    sql(game[1], "UPDATE learned_skills SET proficiency=30, level=2 WHERE pet_id=1")
    detail = play("skill_overview", "风刃术", now=NOW + 4)
    assert detail.title == "万法总览 · 风刃术"
    assert "共 2 位伙伴修习。" in detail.lines[0]
    assert "青鸾（编号 1） · 2级 · 熟练度 30/50 · 已携带" in detail.lines[1]
    assert "青鸾（编号 2） · 1级 · 熟练度 0/20 · 已携带" in detail.text()
    assert "灵宠技能图鉴 风刃术" in detail.commands
    assert {link.command for link in detail.inline_commands} == {
        "灵宠技能图鉴 风刃术", "灵宠灵术赏",
    }


def test_unequipped_and_sealed_pets_are_included(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "风刃术诀 2", now=NOW)
    play("learn", "风刃术", now=NOW)
    play("unequip_skill", "风刃术", now=NOW + 1)
    play("summon", now=NOW + 2)
    play("switch", "2", now=NOW + 3)
    play("learn", "风刃术", now=NOW + 4)
    # After switching, pet 2 is active; pet 1 (also learned 风刃术) can be sealed.
    play("pet_archive", "1", now=NOW + 5)
    detail = play("skill_overview", "风刃术", now=NOW + 6)
    assert "（封存）" in detail.text()
    assert "未携带" in detail.text()
    assert "共 2 位伙伴修习。" in detail.lines[0]


def test_retired_skill_rows_are_excluded(game, play):
    play("adopt", "青鸾", now=NOW)
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (1,'removed_skill',0,1,0)"
        )
    page = play("skill_overview", now=NOW + 1)
    assert "removed_skill" not in page.text()
    assert page.title.startswith("万法总览 ")


def test_unregistered_and_empty_states(game, play):
    page = play("skill_overview", user="u9", now=NOW)
    assert page.title == "万法总览"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    play("adopt", "青鸾", now=NOW)
    empty = play("skill_overview", now=NOW + 1)
    assert "风刃术 · 尚未修习" in empty.text()
    with pytest.raises(GameError, match="还没有伙伴修习风刃术"):
        play("skill_overview", "风刃术", now=NOW + 2)
    with pytest.raises(GameError, match="未找到该内容"):
        play("skill_overview", "不存在的灵术", now=NOW + 2)


def test_pagination_rejects_overflow(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="万法总览共 4 页"):
        play("skill_overview", "5", now=NOW)


def test_skills_page_links_overview_and_native_keyboard_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    view = play("skills", now=NOW)
    assert "灵宠万法总览" in view.commands
    sql(game[1], "UPDATE players SET stones=10000")
    play("buy", "风刃术诀 1", now=NOW)
    play("learn", "风刃术", now=NOW + 1)
    page = play("skill_overview", now=NOW + 2)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_parse_and_help_contract():
    from nonebot_plugin_spirit_pet.adapters import handlers
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    assert handlers._parse("灵宠万法总览") == ("skill_overview", "")
    assert handlers._parse("灵宠万法总览 风刃术") == ("skill_overview", "风刃术")
    assert handlers._parse("灵宠技能") == ("skills", "")
    assert ("灵宠万法总览 技能名", "灵宠万法总览 ", "按灵术汇总全部伙伴的修习进度；不填查看总表。") in _HELP_SECTIONS["灵物与灵术"]
