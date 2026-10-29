"""Skill transfer: cost, eligibility, slot handling and refusals."""

import math
import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import transfer

from .support import items, pet, player, sql

NOW = 1_800_000_000


def add_pet(game, name="小鸾", species="qingluan", user="u1"):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, 100, ?)",
            (user, species, name, NOW),
        ).lastrowid


def learn(game, pet_id, skill_id, equipped=1):
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (?, ?, ?, 1, 0)"
        " ON CONFLICT(pet_id, skill_id) DO UPDATE SET equipped=excluded.equipped",
        (pet_id, skill_id, equipped),
    )


def give(game, item_id, quantity=5, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
        (user, item_id, quantity),
    )


def rich(game, stones=10000):
    sql(game[1], "UPDATE players SET stones=?", (stones,))


def cost_of(game, skill_id):
    content = game[0].content
    skill = content.skills[skill_id]
    price = content.items[skill.book_item].price or 0
    rate = content.rules.transfer
    return max(rate.min_stones, math.ceil(price * rate.price_rate)), rate.bloodline_essence


def slots_of(game, pet_id):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.gameplay.ascension_rules import skill_slots
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    with game[1].connect() as conn:
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, "u1", NOW, "read-slots")
        return skill_slots(ctx, ctx.repo.pet(pet_id))


def setup_teacher(game, play):
    play("adopt", "青鸾")
    student = add_pet(game, "小鸾")
    rich(game)
    give(game, "bloodline_essence", 5)
    teacher_id = pet(game[1])["pet_id"]
    learn(game, teacher_id, "wind_slash")
    return teacher_id, student


def test_transfer_rule_is_defined(game):
    rule = game[0].content.rules.transfer
    assert rule.price_rate == 0.8
    assert rule.min_stones == 80
    assert rule.bloodline_essence == 1


def test_page_without_a_pet_is_read_only(game, play):
    page = play("transfer", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_page_without_skills_says_so(game, play):
    play("adopt", "青鸾")
    page = play("transfer")
    assert "尚未学会灵术" in page.text()
    assert "格式：灵宠传功 <师父> <徒弟> <灵术>" in page.text()


def test_page_lists_teachable_skills_and_candidates(game, play):
    teacher_id, student = setup_teacher(game, play)
    learn(game, student, "meditation", equipped=0)
    page = play("transfer")
    stones, essence = cost_of(game, "wind_slash")
    assert f"师父：青鸾（编号 {teacher_id}" in page.text()
    assert f"风刃术 · 1级 · 熟练度 0/20 · 灵石 {stones} + 血脉精华 {essence} · 可传：小鸾" in page.text()


def test_teaching_copies_the_skill_and_charges_the_cost(game, play):
    teacher_id, student = setup_teacher(game, play)
    stones, essence = cost_of(game, "wind_slash")
    held = items(game[1])["bloodline_essence"]
    reply = play("transfer", "青鸾 小鸾 风刃术")
    assert reply.title == "传授灵术"
    assert "已自动携带" in reply.text()
    row = sql(game[1], "SELECT level, proficiency, equipped FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'", (student,))[0]
    assert (row["level"], row["proficiency"], row["equipped"]) == (1, 0, 1)
    assert player(game[1])["stones"] == 10000 - stones
    assert items(game[1])["bloodline_essence"] == held - essence


def test_a_full_slot_student_learns_without_equipping(game, play):
    teacher_id, student = setup_teacher(game, play)
    slots = slots_of(game, student)
    for index, skill_id in enumerate(["meditation", "pure_breath", "battle_chant"][:slots]):
        learn(game, student, skill_id, equipped=1)
    reply = play("transfer", "青鸾 小鸾 风刃术")
    assert "携带位已满" in reply.text()
    row = sql(game[1], "SELECT equipped FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'", (student,))[0]
    assert row["equipped"] == 0


def test_the_teacher_must_know_the_skill(game, play):
    teacher_id, student = setup_teacher(game, play)
    with pytest.raises(GameError, match="尚未学会"):
        play("transfer", "青鸾 小鸾 赤焰术")


def test_the_student_must_not_already_know_it(game, play):
    teacher_id, student = setup_teacher(game, play)
    learn(game, student, "wind_slash", equipped=0)
    with pytest.raises(GameError, match="已经学会"):
        play("transfer", "青鸾 小鸾 风刃术")


def test_the_same_pet_is_refused(game, play):
    teacher_id, student = setup_teacher(game, play)
    with pytest.raises(GameError, match="不能是同一只"):
        play("transfer", "青鸾 青鸾 风刃术")


def test_unknown_and_ambiguous_pets_are_refused(game, play):
    teacher_id, student = setup_teacher(game, play)
    with pytest.raises(GameError, match="没有找到"):
        play("transfer", "不存在 小鸾 风刃术")
    add_pet(game, "小鸾")
    with pytest.raises(GameError, match="请改用伙伴编号"):
        play("transfer", "青鸾 小鸾 风刃术")


def test_student_requirements_are_enforced(game, play):
    teacher_id, student = setup_teacher(game, play)
    fire = add_pet(game, "火狐", species="xuanhu")
    with pytest.raises(GameError, match="无法满足|不满足|需要"):
        play("transfer", f"青鸾 {fire} 风刃术")


def test_stones_and_essence_are_checked_before_any_write(game, play):
    teacher_id, student = setup_teacher(game, play)
    rich(game, 10)
    with pytest.raises(GameError, match="灵石不足"):
        play("transfer", "青鸾 小鸾 风刃术")
    rich(game, 10000)
    sql(game[1], "DELETE FROM inventory WHERE item_id='bloodline_essence'")
    with pytest.raises(GameError, match="不足"):
        play("transfer", "青鸾 小鸾 风刃术")
    assert sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (student,)) == []


def test_an_expedition_pet_cannot_be_taught(game, play):
    teacher_id, student = setup_teacher(game, play)
    play("lineup", str(teacher_id))
    play("expedition_start", "采灵药", op="trip")
    with pytest.raises(GameError, match="派遣|行程"):
        play("transfer", "青鸾 小鸾 风刃术")


def test_replay_is_idempotent(game, play):
    teacher_id, student = setup_teacher(game, play)
    first = play("transfer", "青鸾 小鸾 风刃术", op="tx")
    stones = player(game[1])["stones"]
    again = play("transfer", "青鸾 小鸾 风刃术", op="tx")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones
    assert len(sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=? AND skill_id='wind_slash'", (student,))) == 1


def test_format_parse_and_help(game, play):
    setup_teacher(game, play)
    with pytest.raises(GameError, match="格式"):
        play("transfer", "青鸾 小鸾")
    assert handlers._parse("灵宠传功") == ("transfer", "")
    assert handlers._parse("灵宠传功 青鸾 小鸾 风刃术") == ("transfer", "青鸾 小鸾 风刃术")
    assert "灵宠传功" in play("help", "灵物与灵术").text()


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    setup_teacher(game, play)
    page = play("transfer")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
