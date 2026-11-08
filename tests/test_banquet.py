"""Household banquet: new dishes, the weekly occasion, refusals and the archive."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def give(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def set_heat(game, used, user="u1", day=None):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"cuisine_heat_{day or beijing_day(NOW)}", used),
    )


def master_dishes(game, count=4, user="u1"):
    """Insert already-cooked rows so 厨艺 reaches ``1 + count`` without spending heat."""
    dishes = ["rice_porridge", "herb_soup", "lotus_pastry", "beast_soup", "grain_cake"]
    for dish in dishes[:count]:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)",
            (user, f"cuisine_dish_{dish}"),
        )


def ready_to_banquet(game, *, stones=10000, food=10):
    sql(game[1], "UPDATE players SET stones=?", (stones,))
    give(game, {"spirit_food": food})
    master_dishes(game)
    sql(game[1], "UPDATE pets SET energy=10, affinity=0")


def test_content_defines_nine_dishes_up_to_level_seven(game):
    content = game[0].content
    assert len(content.cuisine) == 9
    assert sorted({dish.level for dish in content.cuisine.values()}) == [1, 2, 3, 4, 5, 6, 7]
    assert content.rules.cuisine.max_level == 7
    new = [content.cuisine[key] for key in ("moon_cake", "cave_banquet", "jade_banquet")]
    assert [dish.level for dish in new] == [6, 6, 7]
    assert content.cuisine["moon_cake"].item == "meal_moon"
    assert content.items["meal_moon"].effects.affinity == 25
    rule = content.rules.banquet
    assert (rule.min_level, rule.stones, rule.spirit_food, rule.heat) == (5, 200, 4, 3)
    assert rule.reward.stones.minimum == 400 and rule.reward.items["forge_ore"].minimum == 2


def test_unregistered_page_is_read_only(game, play):
    page = play("banquet", user="ghost", now=NOW)
    assert page.title == "灵宠家宴"
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM players") == []


def test_level_gate_and_page_state(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    give(game, {"spirit_food": 10})
    page = play("banquet", now=NOW)
    assert "本周家宴：未开席。" in page.text()
    assert "厨艺 1/5 级" in page.text()
    assert "厨艺未到 5 级" in page.text()
    assert "灵宠家宴 开席" not in {link.command for link in page.inline_commands}
    with pytest.raises(GameError, match="厨艺不足"):
        play("banquet", "开席", now=NOW + 1, op="banquet-low-level")
    assert player(game[1])["stones"] == 10000


def test_hold_serves_the_roster_and_pays_once_per_week(game, play):
    play("adopt", "青鸾", now=NOW)
    ready_to_banquet(game)
    result = play("banquet", "开席", now=NOW + 1, op="banquet-hold")
    assert "家宴开席：1 位伙伴" in result.text()
    assert player(game[1])["stones"] == 10200  # 10000 - 200 + 400
    bag = items(game[1])
    assert bag["spirit_food"] == 9  # starter 3 + 10 - 4
    assert bag["forge_ore"] == 2 and bag["bloodline_essence"] == 1
    assert pet(game[1])["energy"] == 35 and pet(game[1])["exp"] == 30
    rows = sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id LIKE 'banquet_%'",
    )
    assert rows == [{"progress": 1, "claimed": 1}]
    assert sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_banquets_held'",
    ) == [{"progress": 1}]
    assert "灵石 -200，灵粮 -4，灶火 -3（今日剩 3）。" in result.text()

    before = (player(game[1])["stones"], items(game[1]), len(rows))
    with pytest.raises(GameError, match="本周家宴已经办过"):
        play("banquet", "开席", now=NOW + 2, op="banquet-twice")
    assert before == (player(game[1])["stones"], items(game[1]), len(rows))

    page = play("banquet", now=NOW + 3)
    assert "本周家宴：已开席（宴请 1 位）。" in page.text()
    assert "下周一 00:00" in page.text()

    later = play("banquet", "开席", now=NOW + WEEK, op="banquet-next-week")
    assert "家宴开席" in later.text()
    # Two week rows now: this week's and the earlier one; no other banquet_ key exists.
    assert sql(
        game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE quest_id LIKE 'banquet_%'",
    )[0]["n"] == 2


def test_hold_refuses_shortages_without_writing(game, play):
    play("adopt", "青鸾", now=NOW)
    ready_to_banquet(game)

    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="灵石不足"):
        play("banquet", "开席", now=NOW + 1, op="banquet-no-stones")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'banquet_%'")

    sql(game[1], "UPDATE players SET stones=10000")
    sql(game[1], "DELETE FROM inventory WHERE item_id='spirit_food'")
    with pytest.raises(GameError, match="灵粮不足"):
        play("banquet", "开席", now=NOW + 2, op="banquet-no-food")

    give(game, {"spirit_food": 10})
    set_heat(game, 5)
    with pytest.raises(GameError, match="今日灶火不足"):
        play("banquet", "开席", now=NOW + 3, op="banquet-no-heat")
    assert player(game[1])["stones"] == 10000

    set_heat(game, 0)
    sql(game[1], "UPDATE pets SET archived=1")
    with pytest.raises(GameError, match="没有可宴请的伙伴"):
        play("banquet", "开席", now=NOW + 4, op="banquet-no-diners")
    assert player(game[1])["stones"] == 10000


def test_archive_lists_past_weeks(game, play):
    play("adopt", "青鸾", now=NOW)
    ready_to_banquet(game)
    play("banquet", "开席", now=NOW, op="archive-hold")
    archive = play("banquet", "往期", now=NOW + 3)
    assert "家宴往期（第 1/1 页，每页 6 周）：" in archive.text()
    assert "已开席 · 宴请 1 位" in archive.text()
    with pytest.raises(GameError, match="只有 1 页"):
        play("banquet", "往期 2", now=NOW + 4, op="archive-page-two")
    assert handlers._parse("灵宠家宴") == ("banquet", "")
    assert handlers._parse("灵宠家宴 开席") == ("banquet", "开席")
    assert handlers._parse("灵宠家宴 往期 2") == ("banquet", "往期 2")


def test_objectives_and_native_payload(game, play):
    play("adopt", "青鸾", now=NOW)
    ready_to_banquet(game)
    objectives = play("objectives", now=NOW)
    assert "家宴：本周未开席 · 厨艺 5/5 级" in objectives.text()
    page = play("banquet", now=NOW)
    assert "/灵宠家宴 开席" in {f"/{link.command}" for link in page.inline_commands}
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
    assert not (buttons & linked)

    play("banquet", "开席", now=NOW + 1, op="native-hold")
    after = play("objectives", now=NOW + 2)
    assert "家宴：本周已开席（宴请 1 位）" in after.text()
