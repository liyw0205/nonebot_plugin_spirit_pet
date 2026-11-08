"""Farm ladder: six plots, 农事 gating from real harvests, and level rewards."""

import re

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400
RICE = 1800


def buy_seed(game, seed_id="seed_spirit_rice", amount=10):
    sql(game[1], "UPDATE players SET stones=20000")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (seed_id, amount),
        )


def set_harvests(game, amount, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, "
        "'stat_farm_harvests', ?, 0) ON CONFLICT(user_id, quest_id) "
        "DO UPDATE SET progress=excluded.progress",
        (user, amount),
    )


def test_content_defines_six_plots_and_a_five_rung_ladder(game):
    content = game[0].content
    assert len(content.farm_levels) == 5
    levels = [content.farm_levels[i] for i in sorted(content.farm_levels)]
    assert [entry.harvests for entry in levels] == [0, 6, 16, 30, 50]
    assert levels[0].stones == 0 and not levels[0].items
    assert all(entry.stones or entry.items for entry in levels[1:])
    for entry in levels[1:]:
        assert all(item_id in content.items for item_id in entry.items)


def test_plots_five_and_six_require_farm_levels(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=20000")
    page = play("farm", now=NOW)
    assert "农事 1 级 · 累计收获 0 次" in page.text()
    assert "田位 5 · 需农事 2 级解锁（当前 1 级）" in page.text()
    assert "田位 6 · 需农事 3 级解锁（当前 1 级）" in page.text()
    with pytest.raises(GameError, match="需要农事 2 级"):
        play("farm_open", "5", now=NOW + 1, op="locked-five")
    assert player(game[1])["stones"] == 20000
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='farm_open_5'")

    set_harvests(game, 6)
    page = play("farm", now=NOW + 2)
    assert "农事 2 级" in page.text()
    assert "田位 5 · 待开垦（4000 灵石）" in page.text()
    play("farm_open", "5", now=NOW + 3, op="open-five")
    assert player(game[1])["stones"] == 16000
    page = play("farm", now=NOW + 4)
    assert "田位 5 · 待播种" in page.text()
    with pytest.raises(GameError, match="需要农事 3 级"):
        play("farm_open", "6", now=NOW + 5, op="locked-six")

    set_harvests(game, 16)
    play("farm_open", "6", now=NOW + 6, op="open-six")
    page = play("farm", now=NOW + 7)
    assert "田位 6 · 待播种" in page.text()
    assert "已开垦 2/6 块田位" in play("farm_progress", now=NOW + 8).text()


def test_harvest_advances_the_counter_and_the_level(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=20000")
    play("farm_open", "1", now=NOW, op="h-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW + 1, op="h-plant")
    play("farm_harvest", "1", now=NOW + 1 + RICE, op="h-harvest")
    rows = sql(
        game[1], "SELECT progress FROM quest_progress WHERE quest_id='stat_farm_harvests'",
    )
    assert rows == [{"progress": 1}]
    page = play("farm_progress", now=NOW + 2 + RICE)
    assert "农事 1 级 · 累计收获 1 次" in page.text()
    assert "下一等级：2 级，累计收获 6 次（还差 5 次）" in page.text()


def test_level_rewards_claim_once_and_refuse_unreached(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=1000")
    with pytest.raises(GameError, match="暂无可领"):
        play("farm_progress", "领奖", now=NOW, op="claim-none")

    set_harvests(game, 6)
    page = play("farm_progress", now=NOW + 1)
    assert "2 级 · 灵石 250 · 灵粮 2 · 可领取" in page.text()
    result = play("farm_progress", "领奖 2", now=NOW + 2, op="claim-two")
    assert "2 级：修为 +0，灵石 +250，灵粮 +2。" in result.text()
    assert player(game[1])["stones"] == 1250
    assert items(game[1])["spirit_food"] == 5  # starter 3 + reward 2
    assert sql(
        game[1], "SELECT claimed FROM quest_progress WHERE quest_id='farm_level_claim_2'",
    ) == [{"claimed": 1}]

    with pytest.raises(GameError, match="已经领取"):
        play("farm_progress", "领奖 2", now=NOW + 3, op="claim-two-again")
    with pytest.raises(GameError, match="尚未达到 3 级"):
        play("farm_progress", "领奖 3", now=NOW + 4, op="claim-three-early")
    assert player(game[1])["stones"] == 1250

    set_harvests(game, 16)
    played = play("farm_progress", "领奖", now=NOW + 5, op="claim-all")
    assert "3 级：修为 +0，灵石 +500，锻灵矿 +2。" in played.text()
    assert player(game[1])["stones"] == 1750


def test_page_is_read_only_and_help_parse_contract(game, play):
    ghost = play("farm_progress", user="ghost", now=NOW)
    assert ghost.title == "灵宠农事"
    assert "尚未结契" in ghost.text()
    assert ghost.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM players") == []

    play("adopt", "青鸾", now=NOW)
    set_harvests(game, 6)
    before = (
        player(game[1])["stones"],
        sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress")[0]["n"],
    )
    play("farm_progress", now=NOW + 1)
    assert before == (
        player(game[1])["stones"],
        sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress")[0]["n"],
    )
    guide = play("help", "血脉与道具", now=NOW)
    assert "灵宠农事" in guide.text() and "灵宠农事 领奖" in guide.text()
    assert handlers._parse("灵宠农事") == ("farm_progress", "")
    assert handlers._parse("灵宠农事 领奖 2") == ("farm_progress", "领奖 2")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾", now=NOW)
    set_harvests(game, 6)
    page = play("farm_progress", now=NOW)
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
    from urllib.parse import parse_qs, urlparse

    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not (buttons & linked)
    assert "/灵宠农事 领奖 2" in linked
