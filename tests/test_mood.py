"""Pet mood: derived decay, care hooks, soothing and the combat rate."""

import re
from contextlib import closing
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.mood_content import MoodLevel, mood_of
from nonebot_plugin_spirit_pet.gameplay import mood
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86_400


def add_pet(game, name="小鸾", species="qingluan", user="u1", day=NOW):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, 100, ?)",
            (user, species, name, day),
        ).lastrowid


def stats(game, user="u1"):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "read-mood")
        return combatant(ctx, user, pet_id=ctx.repo.player(user).active_pet_id).stats


def give(game, quantity, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, 'spirit_food', ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=excluded.quantity",
        (user, quantity),
    )


def care_rows(game, pet_id, user="u1"):
    return sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"last_care_{pet_id}"),
    )


def set_care(game, pet_id, *, days_ago=0, user="u1"):
    """Record care `days_ago` Beijing days before NOW, using the same encoding as the game."""
    ordinal = date.fromtimestamp(NOW).toordinal() - days_ago
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"last_care_{pet_id}", ordinal),
    )


def test_mood_content_and_rules_agree(game):
    content = game[0].content
    rule = content.rules.mood
    assert rule.max == 3 and rule.decay_days == 2 and rule.soothe_items == 1
    levels = content.moods
    assert sorted(levels) == ["high", "low", "normal", "sad"]
    assert [entry.name for entry in levels.values()] == ["心情大好", "心境平稳", "心情低落", "心灰意冷"]
    for entry in levels.values():
        assert rule.rates[entry.id] == entry.rate
    assert {entry.threshold: entry.rate for entry in levels.values()} == {3: 0.05, 2: 0.0, 1: -0.05, 0: -0.1}


def test_mood_of_picks_the_highest_matching_threshold(game):
    levels = list(game[0].content.moods.values())
    assert mood_of(levels, 3).id == "high"
    assert mood_of(levels, 2).id == "normal"
    assert mood_of(levels, 1).id == "low"
    assert mood_of(levels, 0).id == "sad"
    assert mood_of(levels, -5).id == "sad"


def test_mood_level_validation():
    base = {"id": "high", "name": "大好", "description": "测试", "threshold": 3, "rate": 0.05}
    assert MoodLevel.model_validate(base).rate == 0.05
    with pytest.raises(ValidationError):
        MoodLevel.model_validate({**base, "rate": 0.5})
    with pytest.raises(ValidationError, match="must not be a bonus"):
        MoodLevel.model_validate({**base, "threshold": 0, "rate": 0.05})


def test_a_new_pet_starts_at_full_mood(game, play):
    play("adopt", "青鸾")
    page = play("mood")
    assert "心情大好 3/3" in page.text()
    assert "所有伙伴心境都已回满。" in page.text()
    assert page.inline_commands == ()
    assert care_rows(game, pet(game[1])["pet_id"]) == []


def test_mood_decays_one_point_per_interval(game, play):
    play("adopt", "青鸾")
    give(game, 5)
    pet_id = pet(game[1])["pet_id"]
    set_care(game, pet_id, days_ago=0)
    assert care_rows(game, pet_id) != []
    same_day = play("mood", now=NOW + 3600)
    assert "心情大好 3/3" in same_day.text()
    one_interval = play("mood", now=NOW + 2 * DAY)
    assert "心境平稳 2/3" in one_interval.text()
    two = play("mood", now=NOW + 4 * DAY)
    assert "心情低落 1/3" in two.text()
    three = play("mood", now=NOW + 6 * DAY)
    assert "心灰意冷 0/3" in three.text()
    floor = play("mood", now=NOW + 40 * DAY)
    assert "心灰意冷 0/3" in floor.text()


def test_reading_the_page_does_not_write_state(game, play):
    play("adopt", "青鸾")
    play("mood")
    play("mood", now=NOW + 5 * DAY)
    assert care_rows(game, pet(game[1])["pet_id"]) == []
    assert sql(game[1], "SELECT * FROM quest_progress") == []


def test_a_neglected_pet_loses_stats_and_a_cared_pet_keeps_them(game, play):
    play("adopt", "青鸾")
    give(game, 5)
    pet_id = pet(game[1])["pet_id"]
    set_care(game, pet_id, days_ago=2)          # 心境平稳: no modifier at all
    neutral = stats(game)
    set_care(game, pet_id, days_ago=0)          # 心情大好: +5%
    happy = stats(game)
    set_care(game, pet_id, days_ago=20)         # 心灰意冷: -10%
    sad = stats(game)
    assert (happy.hp, happy.attack) == (int(neutral.hp * 1.05 + 0.5), int(neutral.attack * 1.05 + 0.5))
    assert (sad.hp, sad.attack, sad.defense, sad.speed) == (
        int(neutral.hp * 0.9 + 0.5), int(neutral.attack * 0.9 + 0.5),
        int(neutral.defense * 0.9 + 0.5), int(neutral.speed * 0.9 + 0.5),
    )


def test_full_mood_leaves_stats_untouched(game, play):
    play("adopt", "青鸾")
    before = stats(game)
    play("mood")
    assert stats(game) == before
    assert care_rows(game, pet(game[1])["pet_id"]) == []


def test_feeding_and_bonding_refresh_mood(game, play):
    play("adopt", "青鸾")
    give(game, 5)
    pet_id = pet(game[1])["pet_id"]
    play("feed", str(pet_id), op="feed-1")
    assert care_rows(game, pet_id) != []
    first = care_rows(game, pet_id)
    play("bond", "", op="bond-1")
    assert care_rows(game, pet_id) == first
    assert len(care_rows(game, pet_id)) == 1


def test_soothing_refills_and_charges_one_food(game, play):
    play("adopt", "青鸾")
    give(game, 3)
    pet_id = pet(game[1])["pet_id"]
    set_care(game, pet_id, days_ago=20)
    before = items(game[1])["spirit_food"]
    reply = play("mood", f"安抚 {pet_id}", op="soothe-b")
    assert reply.title == "安抚灵宠"
    assert "心境 0 → 3" in reply.text()
    assert items(game[1])["spirit_food"] == before - 1
    assert "心情大好 3/3" in play("mood").text()


def test_soothing_refusals_write_nothing(game, play):
    play("adopt", "青鸾")
    give(game, 3)
    pet_id = pet(game[1])["pet_id"]
    with pytest.raises(GameError, match="心境已满"):
        play("mood", f"安抚 {pet(game[1])['pet_id']}")
    assert care_rows(game, pet_id) == []
    with pytest.raises(GameError, match="没有属于你的在册灵宠"):
        play("mood", "安抚 999")
    sql(game[1], "DELETE FROM inventory WHERE item_id='spirit_food'")
    set_care(game, pet_id, days_ago=20)
    before = care_rows(game, pet_id)
    with pytest.raises(GameError, match="灵粮不足"):
        play("mood", f"安抚 {pet_id}")
    assert care_rows(game, pet_id) == before


def test_expedition_pets_cannot_be_soothed(game, play):
    play("adopt", "青鸾")
    give(game, 5)
    pet_id = pet(game[1])["pet_id"]
    play("expedition_start", "采灵药", op="trip")
    set_care(game, pet_id, days_ago=20)
    food = items(game[1])["spirit_food"]
    with pytest.raises(GameError, match="派遣|行程"):
        play("mood", f"安抚 {pet(game[1])['pet_id']}")
    assert items(game[1])["spirit_food"] == food


def test_page_lists_every_pet_and_only_sootheable_links(game, play):
    play("adopt", "青鸾")
    add_pet(game, "小鸾")
    give(game, 1)
    set_care(game, pet(game[1])["pet_id"], days_ago=20)
    page = play("mood")
    assert "青鸾（编号 1）· 心灰意冷 0/3 · 四维 -10%" in page.text()
    assert "小鸾（编号 2）· 心情大好 3/3 · 四维 +5%" in page.text()
    assert "共 1 只伙伴需要安抚。" in page.text()
    assert [link.command for link in page.inline_commands] == [
        f"灵宠心境 安抚 {pet(game[1])['pet_id']}"
    ]


def test_page_without_a_pet_is_read_only(game, play):
    page = play("mood", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_objective_help_and_parse(game, play):
    play("adopt", "青鸾")
    assert "心境：全员心境已满" in play("objectives").text()
    give(game, 5)
    set_care(game, pet(game[1])["pet_id"], days_ago=20)
    assert "心境：1 只待安抚" in play("objectives").text()
    assert "灵宠心境" in play("help", "成长").text()
    assert handlers._parse("灵宠心境") == ("mood", "")
    assert handlers._parse("灵宠心境 安抚 青鸾") == ("mood", "安抚 青鸾")
    with pytest.raises(GameError, match="格式"):
        play("mood", "额外")
    with pytest.raises(GameError, match="格式"):
        play("mood", "安抚")


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    give(game, 5)
    pet_id = pet(game[1])["pet_id"]
    set_care(game, pet_id, days_ago=20)
    reply = play("mood", f"安抚 {pet_id}", op="soothe-persist")
    assert reply.title == "安抚灵宠"
    assert care_rows(game, pet_id) != []
    assert "心情大好 3/3" in play("mood", now=NOW + DAY + 100).text()


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    give(game, 5)
    set_care(game, pet(game[1])["pet_id"], days_ago=20)
    page = play("mood")
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
