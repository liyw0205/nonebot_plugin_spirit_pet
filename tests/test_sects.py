"""Spirit sects: join/switch, daily practice, contribution ranks, rewards and passive."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.sect_content import Sect
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86400


def sects(game):
    return sorted(game[0].content.sects.values(), key=lambda sect: sect.id)


def stats(game, user="u1"):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "sect-stats")
        return combatant(ctx)


def seed_contribution(game, sect_id, points, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"sect_contrib_{sect_id}", points),
    )


def contribution(game, sect_id, user="u1"):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"sect_contrib_{sect_id}"),
    )
    return rows[0]["progress"] if rows else 0


def test_content_defines_four_sects_with_five_ranks(game):
    entries = sects(game)
    assert [sect.id for sect in entries] == ["dan_ding", "jian_ge", "xuan_men", "yu_shou"]
    assert {sect.stat for sect in entries} == {"hp", "attack", "defense", "speed"}
    for sect in entries:
        assert [entry.rank for entry in sect.ranks] == [1, 2, 3, 4, 5]
        assert [entry.contribution for entry in sect.ranks] == [0, 60, 160, 320, 560]
        assert [entry.rate for entry in sect.ranks] == [0.02, 0.04, 0.06, 0.08, 0.10]
        assert all(item in game[0].content.items for entry in sect.ranks for item in entry.items)


def test_content_validation_rejects_broken_ladders():
    base = {
        "id": "jian_ge", "name": "剑阁", "description": "测试", "stat": "attack",
        "ranks": [
            {"rank": 1, "contribution": 0, "rate": 0.02, "stones": 10, "items": {"forge_ore": 1}},
            {"rank": 2, "contribution": 60, "rate": 0.04, "stones": 20},
        ],
    }
    assert Sect.model_validate(base).max_rank == 2
    with pytest.raises(ValidationError, match="zero contribution"):
        Sect.model_validate({**base, "ranks": [{**base["ranks"][0], "contribution": 10}, base["ranks"][1]]})
    with pytest.raises(ValidationError, match="must ascend"):
        Sect.model_validate({**base, "ranks": [base["ranks"][0], {**base["ranks"][1], "contribution": 0}]})
    with pytest.raises(ValidationError, match="must ascend"):
        Sect.model_validate({**base, "ranks": [base["ranks"][0], {**base["ranks"][1], "rate": 0.01}]})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("sect", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_a_sectless_player_sees_every_sect_and_join_entries(game, play):
    play("adopt", "青鸾")
    page = play("sect")
    assert "尚未拜入师门" in page.text()
    for name in ("剑阁", "玄门", "丹鼎门", "御兽宗"):
        assert name in page.text()
    assert {link.label for link in page.inline_commands} == {"拜入"}
    assert {link.command for link in page.inline_commands} == {
        "灵宠师门 拜入 剑阁", "灵宠师门 拜入 玄门", "灵宠师门 拜入 丹鼎门", "灵宠师门 拜入 御兽宗",
    }


def test_joining_is_free_and_starts_at_rank_one(game, play):
    play("adopt", "青鸾")
    before = player(game[1])["stones"]
    reply = play("sect", "拜入 剑阁")
    assert "已拜入剑阁" in reply.text()
    assert "首次拜入不消耗灵石" in reply.text()
    assert player(game[1])["stones"] == before
    page = play("sect")
    assert "当前：剑阁 · 1 阶 · 攻击 +2%" in page.text()
    assert "贡献 0/60" in page.text()


def test_joining_the_same_or_unknown_sect_is_refused(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    with pytest.raises(GameError, match="已在剑阁"):
        play("sect", "拜入 剑阁")
    with pytest.raises(GameError):
        play("sect", "拜入 不存在的门派")


def test_switching_costs_stones_and_keeps_both_contributions(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=2000 WHERE user_id='u1'")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 60)
    reply = play("sect", "拜入 玄门")
    assert "转投消耗灵石 500" in reply.text()
    assert player(game[1])["stones"] == 1500
    assert contribution(game, "jian_ge") == 60
    page = play("sect")
    assert "当前：玄门 · 1 阶 · 气血 +2%" in page.text()


def test_switching_without_enough_stones_is_refused(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=100 WHERE user_id='u1'")
    play("sect", "拜入 剑阁")
    with pytest.raises(GameError, match="灵石"):
        play("sect", "拜入 玄门")
    assert "当前：剑阁" in play("sect").text()


def test_practice_pays_contribution_and_exp_once_per_day(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    energy = pet(game[1])["energy"]
    exp = pet(game[1])["exp"]
    reply = play("sect", "修行")
    assert "贡献 +10" in reply.text() and "修为 +30" in reply.text()
    assert contribution(game, "jian_ge") == 10
    assert pet(game[1])["energy"] == energy - 20
    assert pet(game[1])["exp"] == exp + 30
    with pytest.raises(GameError, match="今日已修行"):
        play("sect", "修行")
    assert contribution(game, "jian_ge") == 10

    sql(game[1], "UPDATE pets SET energy=100, energy_updated=?", (NOW + DAY,))
    reply = play("sect", "修行", now=NOW + DAY)
    assert "贡献 +10" in reply.text()
    assert contribution(game, "jian_ge") == 20


def test_practice_needs_an_idle_pet_with_energy(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    sql(game[1], "UPDATE pets SET energy=10, energy_updated=? WHERE user_id='u1'", (NOW,))
    with pytest.raises(GameError, match="精力不足"):
        play("sect", "修行")
    assert contribution(game, "jian_ge") == 0
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("sect", "修行")
    assert contribution(game, "jian_ge") == 0


def test_practice_is_refused_without_a_sect(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未拜入师门"):
        play("sect", "修行")


def test_contribution_crossing_a_threshold_raises_the_rank(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 50)
    reply = play("sect", "修行")
    assert "阶位提升：1 阶 → 2 阶" in reply.text()
    page = play("sect")
    assert "剑阁 · 2 阶 · 攻击 +4%" in page.text()
    assert "贡献 60/160" in page.text()


def test_claim_pays_each_reached_rank_once(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    before = player(game[1])["stones"]
    first = play("sect", "领赏")
    assert "1 阶：灵石 +120" in first.text()
    assert player(game[1])["stones"] == before + 120
    assert items(game[1])["forge_ore"] == 1
    with pytest.raises(GameError, match="暂无可领"):
        play("sect", "领赏")

    seed_contribution(game, "jian_ge", 60)
    second = play("sect", "领赏")
    assert "2 阶：灵石 +240" in second.text()
    assert "1 阶" not in second.text()
    assert player(game[1])["stones"] == before + 360
    assert items(game[1])["forge_ore"] == 3


def test_claim_never_pays_a_rank_above_the_current_one(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 100)
    play("sect", "领赏")
    with pytest.raises(GameError, match="暂无可领"):
        play("sect", "领赏")


def test_the_passive_scales_with_rank_and_only_for_the_owner(game, play):
    play("adopt", "青鸾")
    base = stats(game).stats.attack
    play("sect", "拜入 剑阁")
    assert stats(game).stats.attack == int(base * 1.02 + 0.5)
    seed_contribution(game, "jian_ge", 560)
    assert stats(game).stats.attack == int(base * 1.10 + 0.5)

    play("adopt", "青鸾", user="u2")
    base_hp = stats(game, "u2").stats.hp
    play("sect", "拜入 玄门", user="u2")
    seed_contribution(game, "xuan_men", 560, user="u2")
    assert stats(game, "u1").stats.attack == int(base * 1.10 + 0.5)
    assert stats(game, "u2").stats.hp == int(base_hp * 1.10 + 0.5)


def test_a_sectless_player_gets_no_bonus(game, play):
    play("adopt", "青鸾")
    before = stats(game).stats
    play("adopt", "青鸾", user="u2")
    play("sect", "拜入 剑阁", user="u2")
    seed_contribution(game, "jian_ge", 560, user="u2")
    after = stats(game, "u1").stats
    assert (after.hp, after.attack, after.defense, after.speed) == (
        before.hp, before.attack, before.defense, before.speed,
    )


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    play("sect", "修行")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "sect", "", "restart-sect", NOW)
    assert "当前：剑阁 · 1 阶" in page.text()
    assert "贡献 10/60" in page.text()


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    first = play("sect", "修行", op="sect-op")
    again = play("sect", "修行", op="sect-op")
    assert again.text() == first.text()
    assert contribution(game, "jian_ge") == 10


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "成长")
    assert "灵宠师门" in guide.text() and "灵宠师门 领赏" in guide.text()
    assert "师门：尚未拜入" in play("objectives").text()
    play("sect", "拜入 剑阁")
    assert "师门：剑阁 1 阶 · 贡献 0/60" in play("objectives").text()
    assert handlers._parse("灵宠师门") == ("sect", "")
    assert handlers._parse("灵宠师门 拜入 剑阁") == ("sect", "拜入 剑阁")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    page = play("sect")
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
