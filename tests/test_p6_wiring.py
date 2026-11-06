"""P6 wiring: the two new counters feed achievements, a title and the hub."""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import achievements, counters, daily_encounters, titles
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "p6")


def count(game, metric, user="u1"):
    return counters.value(context(game, user), metric, user)


def grant(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def stones_option(game):
    return next(
        option for option in daily_encounters.todays(context(game)).options if option.cost.stones
    )


def item_option(game):
    return next(
        option for option in daily_encounters.todays(context(game)).options if option.cost.items
    )


def setup_cut(game, play):
    play("adopt", "青鸾", now=NOW)
    grant(game, {"spirit_bell": 1})
    play("equipment", "灵心铃", now=NOW)
    grant(game, {"gem_flame": 3})
    play("socket", "灵饰 赤炎石", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")


def last_page(total, size):
    return max(1, (total + size - 1) // size)


def test_a_choice_bumps_the_counter_once(game, play):
    play("adopt", "青鸾", now=NOW)
    grant(game, {"spirit_food": 3})
    sql(game[1], "UPDATE players SET stones=5000")
    option = item_option(game)
    play("encounters", option.label, now=NOW)
    assert count(game, "encounter_choices") == 1
    with pytest.raises(GameError):
        play("encounters", option.label, now=NOW)
    assert count(game, "encounter_choices") == 1


def test_a_refused_choice_does_not_bump(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=0")
    with pytest.raises(GameError):
        play("encounters", stones_option(game).label, now=NOW)
    assert count(game, "encounter_choices") == 0


def test_a_cut_bumps_the_counter_once(game, play):
    setup_cut(game, play)
    play("socket", "雕琢 灵饰", now=NOW)
    assert count(game, "gem_cuts") == 1


def test_a_refused_cut_does_not_bump(game, play):
    setup_cut(game, play)
    sql(game[1], "UPDATE players SET stones=0")
    with pytest.raises(GameError):
        play("socket", "雕琢 灵饰", now=NOW)
    assert count(game, "gem_cuts") == 0


def page_of(entries, name, size):
    names = [entry.name for entry in entries]
    return names.index(name) // size + 1


def test_the_first_choice_unlocks_the_achievement(game, play):
    play("adopt", "青鸾", now=NOW)
    grant(game, {"spirit_food": 3})
    sql(game[1], "UPDATE players SET stones=5000")
    play("encounters", item_option(game).label, now=NOW)
    page = page_of(game[0].content.achievements.values(), "路遇有缘", achievements.ACHIEVEMENT_PAGE_SIZE)
    reply = play("achievements", str(page), now=NOW)
    line = next(text for text in reply.lines if "路遇有缘" in text)
    assert "可领奖" in line


def test_the_first_cut_unlocks_the_achievement(game, play):
    setup_cut(game, play)
    play("socket", "雕琢 灵饰", now=NOW)
    page = page_of(game[0].content.achievements.values(), "琢玉成器", achievements.ACHIEVEMENT_PAGE_SIZE)
    reply = play("achievements", str(page), now=NOW)
    line = next(text for text in reply.lines if "琢玉成器" in text)
    assert "可领奖" in line


def test_the_title_tracks_the_counter(game, play):
    play("adopt", "青鸾", now=NOW)
    grant(game, {"spirit_food": 3})
    sql(game[1], "UPDATE players SET stones=5000")
    play("encounters", item_option(game).label, now=NOW)
    page = last_page(len(game[0].content.titles), titles.TITLE_PAGE_SIZE)
    reply = play("titles", str(page), now=NOW)
    line = next(text for text in reply.lines if "路遥知心" in text)
    assert "1/10" in line


def test_the_hub_shows_todays_encounter(game, play):
    play("adopt", "青鸾", now=NOW)
    reply = play("objectives", now=NOW)
    encounter = daily_encounters.todays(context(game))
    assert any(line.startswith("际遇：") and encounter.name in line for line in reply.lines)
    assert any(link.command == "灵宠际遇" for link in reply.inline_commands)


def test_the_counter_persists_in_the_database(game, play):
    play("adopt", "青鸾", now=NOW)
    grant(game, {"spirit_food": 3})
    sql(game[1], "UPDATE players SET stones=5000")
    play("encounters", item_option(game).label, now=NOW)
    assert player(game[1])["user_id"] == "u1"
    rows = sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_encounter_choices'")
    assert rows[0]["progress"] == 1
