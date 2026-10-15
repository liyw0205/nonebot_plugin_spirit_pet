import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql

NOW = 1_800_000_000
NEXT_WEEK = NOW + 8 * 86400


def stones(game):
    return player(game[1])["stones"]


def owned(game):
    return len(sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'"))


def marker(game):
    return sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id='free_summon_weekly'")


def fill_roster(game, cap=50):
    for index in range(cap - owned(game)):
        sql(
            game[1],
            "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES ('u1','qingluan',?,?)",
            (f"填充{index}", NOW),
        )


def test_page_previews_without_an_account(game, play):
    reply = play("free_summon", user="u9", now=NOW)
    assert reply.title == "每周免费召唤"
    assert "尚未结契" in reply.text()
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_page_offers_the_free_pull_and_the_hub_reports_it(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("free_summon", now=NOW)
    assert page.lines[0] == "本周免费召唤：可领取。"
    assert [link.command for link in page.inline_commands] == ["灵宠每周召唤领取"]
    assert page.commands == ("灵宠列表", "我的灵宠", "灵宠图鉴")
    hub = next(text for text in play("objectives", now=NOW).lines if text.startswith("每周召唤："))
    assert hub == "每周召唤：可领取"


def test_claim_draws_ten_without_spending_stones(game, play):
    play("adopt", "青鸾", now=NOW)
    before, pets = stones(game), owned(game)
    reply = play("free_summon_claim", now=NOW, op="free-summon")
    assert reply.title == "每周免费召唤"
    assert reply.lines[0] == "本周免费十连已领取。"
    assert reply.lines[1] == "本次召唤不消耗灵石。"
    assert owned(game) == pets + 10
    assert stones(game) == before
    assert "保底" in reply.text()
    assert marker(game)[0]["claimed"] == 1
    assert play("free_summon", now=NOW).lines[0] == "本周免费召唤：本周已领取。"
    hub = next(text for text in play("objectives", now=NOW).lines if text.startswith("每周召唤："))
    assert hub == "每周召唤：本周已领取"


def test_claim_rejects_a_second_time_and_replays(game, play):
    play("adopt", "青鸾", now=NOW)
    first = play("free_summon_claim", now=NOW, op="free-summon")
    assert play("free_summon_claim", now=NOW, op="free-summon").lines == first.lines
    with pytest.raises(GameError, match="本周免费召唤已领取"):
        play("free_summon_claim", now=NOW)


def test_claim_resets_next_week(game, play):
    play("adopt", "青鸾", now=NOW)
    play("free_summon_claim", now=NOW)
    assert play("free_summon", now=NOW).lines[0] == "本周免费召唤：本周已领取。"
    assert play("free_summon", now=NEXT_WEEK).lines[0] == "本周免费召唤：可领取。"
    pets = owned(game)
    play("free_summon_claim", now=NEXT_WEEK)
    assert owned(game) == pets + 10


def test_full_roster_refuses_without_spending_the_week(game, play):
    play("adopt", "青鸾", now=NOW)
    fill_roster(game)
    assert owned(game) == 50
    with pytest.raises(GameError, match="灵宠名册上限"):
        play("free_summon_claim", now=NOW)
    assert marker(game) == []
    assert play("free_summon", now=NOW).lines[0] == "本周免费召唤：可领取。"


def test_paid_summon_still_charges_stones(game, play):
    play("adopt", "青鸾", now=NOW)
    before = stones(game)
    play("summon", now=NOW)
    assert stones(game) == before - 100


def test_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾", now=NOW)
    reply = play("free_summon", now=NOW)
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for line in segment.data["keyboard"].content.rows
        for button in line.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()


def test_help_lists_both_entries(game, play):
    text = play("help", "结契", now=NOW).text()
    assert "灵宠每周召唤" in text and "灵宠每周召唤领取" in text
