"""灵宠约战: asynchronous spar requests settled when the other side answers."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import spar_requests
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, player_uid, sql

NOW = 1_800_000_000
HOUR = 3600


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "spar")


def two_players(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    return player_uid(game[1], "u1"), player_uid(game[1], "u2")


def requests_for(game, user):
    return {
        row["quest_id"]: row["progress"]
        for row in sql(
            game[1],
            "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ?",
            (user, f"{spar_requests.PREFIX}%"),
        )
    }


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY user_id, quest_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
        sql(game[1], "SELECT user_id, rating FROM season_entries ORDER BY user_id"),
    )


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("spar_request", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []


# ---------------------------------------------------------------- sending

def test_a_request_lands_on_the_target_row_with_an_expiry(game, play):
    _, target = two_players(game, play)
    reply = play("spar_request", str(target))
    assert "已向" in reply.text()
    rows = requests_for(game, "u2")
    assert rows == {f"{spar_requests.PREFIX}u1": NOW + 24 * HOUR}


def test_sending_to_yourself_is_refused(game, play):
    mine, _ = two_players(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="不能向自己"):
        play("spar_request", str(mine))
    assert snapshot(game) == before


def test_sending_to_an_unknown_uid_is_refused(game, play):
    two_players(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="没有找到这位玩家"):
        play("spar_request", "999999")
    assert snapshot(game) == before


def test_a_target_without_a_lineup_cannot_be_challenged(game, play):
    two_players(game, play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    _, target = player_uid(game[1], "u1"), player_uid(game[1], "u2")
    with pytest.raises(GameError, match="对方尚未选择出战灵宠"):
        play("spar_request", str(target))
    assert requests_for(game, "u2") == {}


def test_a_challenger_without_a_lineup_cannot_send(game, play):
    _, target = two_players(game, play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    with pytest.raises(GameError, match="尚未选择出战灵宠"):
        play("spar_request", str(target))
    assert requests_for(game, "u2") == {}


def test_sending_twice_refreshes_one_row_instead_of_stacking(game, play):
    _, target = two_players(game, play)
    play("spar_request", str(target), now=NOW)
    play("spar_request", str(target), now=NOW + 2 * HOUR)
    rows = requests_for(game, "u2")
    assert len(rows) == 1
    assert rows[f"{spar_requests.PREFIX}u1"] == NOW + 2 * HOUR + 24 * HOUR


# ---------------------------------------------------------------- page

def test_the_page_lists_incoming_and_outgoing(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    page = play("spar_request", user="u2")
    assert "待我应战 1 条" in page.text()
    labels = {link.label for link in page.inline_commands}
    assert "应战" in labels
    sent = play("spar_request", user="u1")
    assert "我发出 1 条" in sent.text()
    assert "撤回" in {link.label for link in sent.inline_commands}


def test_an_empty_page_says_so(game, play):
    two_players(game, play)
    page = play("spar_request")
    assert "目前没有待处理的约战" in page.text()
    assert page.inline_commands == ()


def test_every_rendered_link_reparses(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    for user in ("u1", "u2"):
        page = play("spar_request", user=user)
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None


# ---------------------------------------------------------------- accepting

def test_accepting_runs_the_fight_and_clears_the_request(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    reply = play("spar_request", f"应战 {mine}", user="u2")
    assert reply.title == "约战结算"
    assert "约战不消耗资源" in reply.text()
    assert requests_for(game, "u2") == {}
    records = sql(game[1], "SELECT battle_id FROM battle_records")
    assert len(records) == 1


def test_accepting_without_a_request_is_refused(game, play):
    mine, _ = two_players(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="没有向你发出约战"):
        play("spar_request", f"应战 {mine}", user="u2")
    assert snapshot(game) == before


def test_an_expired_request_cannot_be_accepted_and_leaves_no_trace(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    later = NOW + 25 * HOUR
    before = snapshot(game)
    with pytest.raises(GameError, match="已经过期"):
        play("spar_request", f"应战 {mine}", user="u2", now=later)
    assert snapshot(game) == before


def test_accepting_requires_the_challenger_to_still_have_a_lineup(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    with pytest.raises(GameError, match="对方已经撤下出战灵宠"):
        play("spar_request", f"应战 {mine}", user="u2")
    assert len(requests_for(game, "u2")) == 1


def test_accepting_requires_the_defender_to_have_a_lineup(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    with pytest.raises(GameError, match="请先选择出战灵宠"):
        play("spar_request", f"应战 {mine}", user="u2")


def test_accepting_costs_no_energy_stones_or_exp(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    before = (
        player(game[1], "u1")["stones"], player(game[1], "u2")["stones"],
        sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id"),
    )
    play("spar_request", f"应战 {mine}", user="u2")
    after = (
        player(game[1], "u1")["stones"], player(game[1], "u2")["stones"],
        sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id"),
    )
    assert after == before


def test_accepting_does_not_touch_the_season(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    play("spar_request", f"应战 {mine}", user="u2")
    assert sql(game[1], "SELECT * FROM season_entries") == []


# ---------------------------------------------------------------- withdraw

def test_withdrawing_removes_the_request(game, play):
    _, target = two_players(game, play)
    play("spar_request", str(target))
    assert "已撤回" in play("spar_request", f"撤回 {target}").text()
    assert requests_for(game, "u2") == {}


def test_withdrawing_without_a_request_is_refused(game, play):
    _, target = two_players(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="没有待应战的约战"):
        play("spar_request", f"撤回 {target}")
    assert snapshot(game) == before


# ---------------------------------------------------------------- surfaces

def test_a_pending_request_survives_a_restart(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    Store(game[1].path).initialize()
    assert "待我应战 1 条" in play("spar_request", user="u2").text()
    play("spar_request", f"应战 {mine}", user="u2")
    assert sql(game[1], "SELECT battle_id FROM battle_records") != []


def test_help_and_parser_cover_the_command(game, play):
    two_players(game, play)
    assert _parse("灵宠约战") == ("spar_request", "")
    assert _parse("灵宠约战 10001") == ("spar_request", "10001")
    assert _parse("灵宠约战 应战 10000") == ("spar_request", "应战 10000")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["对战与赛季"]}
    assert "灵宠约战 UID" in rows
    assert "灵宠约战 应战 UID" in rows


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    mine, target = two_players(game, play)
    play("spar_request", str(target))
    page = play("spar_request", user="u2")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_the_onebot_text_page_spells_the_command(game, play):
    two_players(game, play)
    rendered = _qq_segments(play("spar_request"), Config(spirit_pet_qq_mode="text"))[0]
    assert "【灵宠约战】" in rendered


def test_the_objectives_page_does_not_grow_a_line(game, play):
    two_players(game, play)
    assert all(not line.startswith("约战") for line in play("objectives").lines)
    assert spar_requests.objective_line(None, "u1") == ""
