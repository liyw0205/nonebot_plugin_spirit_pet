"""Skill study: page state, proficiency gain, carry-over, caps and refusals."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import ResearchRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import research
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql

NOW = 1_800_000_000
DAY = 86_400
STARTER_BAG = 3


def add_pet(game, name="小鸾", species="qingluan", user="u1", energy=100):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 0, ?, ?)",
            (user, species, name, energy, NOW),
        ).lastrowid


def activate(game, pet_id, user="u1"):
    sql(game[1], "UPDATE players SET active_pet_id=? WHERE user_id=?", (pet_id, user))


def learn(game, pet_id, skill_id, *, equipped=1, level=1, proficiency=0):
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(pet_id, skill_id) DO UPDATE SET equipped=excluded.equipped,"
        " level=excluded.level, proficiency=excluded.proficiency",
        (pet_id, skill_id, equipped, level, proficiency),
    )


def skill_row(game, pet_id, skill_id):
    rows = sql(
        game[1], "SELECT level, proficiency FROM learned_skills WHERE pet_id=? AND skill_id=?",
        (pet_id, skill_id),
    )
    return (rows[0]["level"], rows[0]["proficiency"]) if rows else None


def give_food(game, quantity, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, 'spirit_food', ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
        (user, quantity),
    )


def counters(game, user="u1"):
    rows = sql(
        game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND"
        " (quest_id LIKE 'research_day_%' OR quest_id LIKE 'research_%')",
        (user,),
    )
    return {row["quest_id"]: row["progress"] for row in rows}


def pet_key(now, pet_id):
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    return f"research_{beijing_day(now)}_{pet_id}"


def ready(game, play, *, skill="wind_slash", energy=100, food=5):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    sql(game[1], "UPDATE pets SET energy=?, energy_updated=? WHERE pet_id=?", (energy, NOW, pet_id))
    give_food(game, food)
    learn(game, pet_id, skill)
    return pet_id


def test_research_rule_is_defined(game):
    entry = game[0].content.rules.research
    assert (entry.energy, entry.food, entry.gain) == (12, 1, 8)
    assert (entry.daily_limit, entry.pet_daily_limit) == (4, 2)
    assert ResearchRule.model_validate({
        "energy": 1, "food": 0, "gain": 1, "daily_limit": 2, "pet_daily_limit": 2,
    }).gain == 1
    with pytest.raises(ValidationError, match="cannot exceed"):
        ResearchRule.model_validate({
            "energy": 1, "food": 0, "gain": 1, "daily_limit": 1, "pet_daily_limit": 2,
        })


def test_page_without_a_pet_is_read_only(game, play):
    page = play("research", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_without_equipped_skills_says_so(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    learn(game, pet_id, "wind_slash", equipped=0)
    page = play("research")
    assert "当前没有携带中的灵术" in page.text()
    assert "风刃术" not in page.text()
    assert page.inline_commands == ()


def test_page_lists_equipped_skills_with_gain_and_next_level(game, play):
    pet_id = ready(game, play)
    learn(game, pet_id, "meditation", equipped=0)
    page = play("research")
    assert "青鸾研习：每次消耗 12 精力与 灵粮 1 份，熟练度 +8。" in page.text()
    assert "今日剩余 4/4 次，青鸾今日可研习 2/2 次。" in page.text()
    assert "风刃术 · 1级 · 熟练度 0/20 · 可研习" in page.text()
    assert "凝神术" not in page.text()
    assert [link.command for link in page.inline_commands] == ["灵宠研习 风刃术"]


def test_page_announces_the_level_a_study_would_reach(game, play):
    pet_id = ready(game, play)
    learn(game, pet_id, "wind_slash", level=1, proficiency=14)
    page = play("research")
    assert "熟练度 14/20 · 可研习，可升至 2 级" in page.text()


def test_studying_grants_proficiency_and_spends_resources(game, play):
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    pet_id = ready(game, play)
    reply = play("research", "风刃术", op="study-1")
    assert reply.title == "研习灵术"
    assert "熟练度 +8" in reply.text()
    assert skill_row(game, pet_id, "wind_slash") == (1, 8)
    assert pet(game[1])["energy"] == 88
    # give_food sets the bag outright, so the starter 3 are replaced rather than added
    assert items(game[1])["spirit_food"] == 5 - 1
    assert counters(game) == {
        f"research_day_{beijing_day(NOW)}": 1,
        pet_key(NOW, pet_id): 1,
    }


def test_level_up_carries_the_overflow_like_combat(game, play):
    pet_id = ready(game, play)
    learn(game, pet_id, "wind_slash", level=1, proficiency=18)
    reply = play("research", "风刃术", op="study-carry")
    assert "提升到 2 级" in reply.text()
    assert skill_row(game, pet_id, "wind_slash") == (2, 6)


def test_reaching_level_three_points_at_specialization(game, play):
    pet_id = ready(game, play)
    learn(game, pet_id, "wind_slash", level=2, proficiency=46)
    reply = play("research", "风刃术", op="study-spec")
    assert "提升到 3 级" in reply.text()
    assert "灵宠专精" in reply.text()
    assert skill_row(game, pet_id, "wind_slash") == (3, 4)


def test_a_maxed_skill_is_refused(game, play):
    pet_id = ready(game, play)
    learn(game, pet_id, "wind_slash", level=5, proficiency=0)
    energy = pet(game[1])["energy"]
    with pytest.raises(GameError, match="已经满级"):
        play("research", "风刃术")
    assert pet(game[1])["energy"] == energy
    assert counters(game) == {}
    assert skill_row(game, pet_id, "wind_slash") == (5, 0)


def test_unequipped_unlearned_and_unknown_skills_are_refused(game, play):
    pet_id = ready(game, play)
    learn(game, pet_id, "meditation", equipped=0)
    with pytest.raises(GameError, match="未携带"):
        play("research", "凝神术")
    with pytest.raises(GameError, match="尚未学会"):
        play("research", "赤焰术")
    with pytest.raises(GameError, match="未找到"):
        play("research", "不存在的灵术")
    with pytest.raises(GameError, match="未找到"):
        play("research", "风刃术 额外")
    assert counters(game) == {}
    assert skill_row(game, pet_id, "meditation") == (1, 0)


def test_energy_and_food_shortages_refuse_before_any_write(game, play):
    pet_id = ready(game, play, energy=11)
    with pytest.raises(GameError, match="精力不足"):
        play("research", "风刃术")
    assert (skill_row(game, pet_id, "wind_slash"), counters(game), pet(game[1])["energy"]) == (
        (1, 0), {}, 11,
    )
    sql(game[1], "UPDATE pets SET energy=100 WHERE pet_id=?", (pet_id,))
    sql(game[1], "DELETE FROM inventory WHERE item_id='spirit_food'")
    with pytest.raises(GameError, match="灵粮不足"):
        play("research", "风刃术")
    assert (skill_row(game, pet_id, "wind_slash"), counters(game)) == ((1, 0), {})


def test_an_expedition_pet_cannot_study(game, play):
    pet_id = ready(game, play)
    play("expedition_start", "采灵药", op="trip")
    with pytest.raises(GameError, match="派遣|行程"):
        play("research", "风刃术")
    assert (skill_row(game, pet_id, "wind_slash"), counters(game)) == ((1, 0), {})


def test_the_per_pet_cap_limits_one_pet_without_blocking_another(game, play):
    first = ready(game, play)
    second = add_pet(game, "小鸾")
    learn(game, second, "wind_slash")
    play("research", "风刃术", op="pet1-a")
    play("research", "风刃术", op="pet1-b")
    assert "青鸾今日可研习 0/2 次" in play("research").text()
    with pytest.raises(GameError, match="今日已研习 2 次"):
        play("research", "风刃术", op="pet1-c")
    activate(game, second)
    reply = play("research", "风刃术", op="pet2-a")
    assert reply.title == "研习灵术"
    assert counters(game)[pet_key(NOW, second)] == 1
    assert skill_row(game, second, "wind_slash") == (1, 8)


def test_the_daily_cap_stops_the_fourth_study(game, play):
    first = ready(game, play)
    second = add_pet(game, "小鸾")
    third = add_pet(game, "三鸾")
    for target in (first, second, third):
        learn(game, target, "wind_slash")
    for index, target in enumerate((first, second)):
        activate(game, target)
        play("research", "风刃术", op=f"cap-a-{index}")
    activate(game, first)
    play("research", "风刃术", op="cap-a-2")
    activate(game, second)
    play("research", "风刃术", op="cap-b")
    assert counters(game)[pet_key(NOW, first)] == 2
    assert counters(game)[pet_key(NOW, second)] == 2
    activate(game, third)
    assert "今日剩余 0/4 次" in play("research").text()
    with pytest.raises(GameError, match="今日研习次数已用尽"):
        play("research", "风刃术", op="cap-c")
    assert counters(game).get(pet_key(NOW, third)) is None
    assert skill_row(game, third, "wind_slash") == (1, 0)


def test_both_counters_reset_the_next_day(game, play):
    from nonebot_plugin_spirit_pet.utils.time import beijing_day

    pet_id = ready(game, play)
    play("research", "风刃术", op="day-1")
    assert counters(game)[pet_key(NOW, pet_id)] == 1
    tomorrow = NOW + DAY
    assert f"research_day_{beijing_day(tomorrow)}" not in counters(game)
    assert pet_key(tomorrow, pet_id) not in counters(game)
    play("research", "风刃术", op="day-2", now=tomorrow)
    assert counters(game)[pet_key(tomorrow, pet_id)] == 1
    assert counters(game)[f"research_day_{beijing_day(tomorrow)}"] == 1


def test_studying_writes_no_battle_or_player_state(game, play):
    pet_id = ready(game, play)
    before = sql(game[1], "SELECT stones, last_train, last_pve FROM players WHERE user_id='u1'")
    play("research", "风刃术", op="clean-1")
    assert sql(game[1], "SELECT * FROM battle_records") == []
    assert sql(game[1], "SELECT * FROM pve_stage_progress") == []
    assert sql(game[1], "SELECT stones, last_train, last_pve FROM players WHERE user_id='u1'") == before
    row = sql(game[1], "SELECT affinity, exp FROM pets WHERE pet_id=?", (pet_id,))[0]
    assert (row["affinity"], row["exp"]) == (0, 0)


def test_objective_help_and_parse(game, play):
    ready(game, play)
    assert "研习：今日可用 4 次" in play("objectives").text()
    assert "灵宠研习" in play("help", "灵物与灵术").text()
    assert handlers._parse("灵宠研习") == ("research", "")
    assert handlers._parse("灵宠研习 风刃术") == ("research", "风刃术")


def test_same_operation_replays_identically(game, play):
    pet_id = ready(game, play)
    first = play("research", "风刃术", op="replay")
    second = play("research", "风刃术", op="replay")
    assert second.text() == first.text()
    assert skill_row(game, pet_id, "wind_slash") == (1, 8)
    assert counters(game)[pet_key(NOW, pet_id)] == 1


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    ready(game, play)
    page = play("research")
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
    assert len(page.commands) <= 4
