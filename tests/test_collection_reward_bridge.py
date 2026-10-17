import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import sql

NOW = 1_800_000_000


def keyboard_commands(reply):
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    return [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]


def markdown_links(message):
    import re
    from urllib.parse import parse_qs, urlparse

    return [
        (label, parse_qs(urlparse(url).query)["command"][0])
        for label, url in re.findall(r"\[([^\]]+)\]\((mqqapi://[^)]+)\)", message["markdown"][0].data["markdown"].content)
    ]


def row(reply, name):
    return next(line for line in reply.lines if line.startswith(f"{name} · "))


def test_collection_rows_show_reward_state_and_link_claimable_species(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("collection", now=NOW)
    assert row(page, "青鸾") == "青鸾 · 已拥有（1只）· 奖励可领取"
    assert row(page, "玄狐") == "玄狐 · 未收集"
    assert "本页有 1 族收集奖励可领取" in page.lines[-1]
    assert [link.command for link in page.inline_commands] == ["灵宠图鉴领奖 青鸾"]
    assert page.inline_commands[0].line == next(
        index for index, line in enumerate(page.lines) if line.startswith("青鸾 · ")
    )
    assert "灵宠图鉴奖励" in page.commands
    assert page.commands[-4:] == ("灵宠图鉴", "灵宠成就", "灵宠图鉴奖励", "灵宠收集榜")


def test_claimed_species_show_claimed_without_a_link(game, play):
    play("adopt", "青鸾", now=NOW)
    play("codex_claim", "青鸾", now=NOW, op="bridge-claim")
    page = play("collection", now=NOW + 1)
    assert row(page, "青鸾") == "青鸾 · 已领取"
    assert page.inline_commands == ()
    assert "本页有" not in page.text()
    assert not sql(
        game[1],
        "SELECT quest_id FROM quest_progress WHERE quest_id='codex_qingluan' AND claimed=0",
    )


def test_sealed_pets_still_count_as_collected_for_reward_state(game, play):
    play("adopt", "青鸾", now=NOW)
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pet_id,))
    page = play("collection", now=NOW + 1)
    assert row(page, "青鸾") == "青鸾 · 已拥有（1只）· 奖励可领取"
    assert [link.command for link in page.inline_commands] == ["灵宠图鉴领奖 青鸾"]


def test_unregistered_browsing_stays_read_only_without_links(game, play):
    page = play("collection", user="u9", now=NOW)
    assert row(page, "青鸾") == "青鸾 · 未收集"
    assert page.inline_commands == ()
    assert not sql(game[1], "SELECT user_id FROM players")


def test_second_page_links_its_own_claimable_rows(game, play):
    play("adopt", "青鸾", now=NOW)
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id,species_id,name,energy_updated) VALUES ('u1','lingxi','灵犀一号',?)",
            (NOW,),
        )
    second = play("collection", "2", now=NOW)
    commands = [link.command for link in second.inline_commands]
    assert "灵宠图鉴领奖 灵汐獭" in commands
    assert "灵宠图鉴领奖 青鸾" not in commands
    first = play("collection", now=NOW)
    assert [link.command for link in first.inline_commands] == ["灵宠图鉴领奖 青鸾"]


def test_native_keyboard_keeps_only_page_actions_without_link_duplication(game, play):
    play("adopt", "青鸾", now=NOW)
    page = play("collection", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = keyboard_commands(page)
    assert len(buttons) <= 4
    assert "灵宠图鉴领奖 青鸾" not in buttons
    assert "灵宠收集 2" in buttons
    assert not set(buttons) & {link.command for link in page.inline_commands}
    assert markdown_links(message) == [("领取收集奖励", "/灵宠图鉴领奖 青鸾")]


def test_claim_rejects_uncollected_species_and_keeps_state_untouched(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="尚未收得"):
        play("codex_claim", "玄狐", now=NOW)
    page = play("collection", now=NOW)
    assert row(page, "玄狐") == "玄狐 · 未收集"
    assert row(page, "青鸾") == "青鸾 · 已拥有（1只）· 奖励可领取"
