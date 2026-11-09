"""Merchant contracts: staged deliveries, deposit at risk, history and expiry."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import merchant, merchant_contract
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86_400
GRAIN = "grain_run"


def game_ctx(game, now=NOW):
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config,
        game[0].rng, "u1", now, "contract-read",
    )


def set_stones(game, amount):
    sql(game[1], "UPDATE players SET stones=?", (amount,))


def give(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def set_rep(game, value, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, 'merchant_rep', ?, 1) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, value),
    )


def finish_first_stage(game, play, op="stage-one"):
    contract = game[0].content.merchant_contracts[GRAIN]
    give(game, contract.stages[0].items)
    return play("merchant", "交货", now=NOW + 10, op=op)


def test_content_ships_four_contracts_with_three_stages(game):
    content = game[0].content
    assert len(content.merchant_contracts) == 4
    ordered = sorted(content.merchant_contracts.values(), key=lambda entry: entry.min_rep)
    assert [entry.min_rep for entry in ordered] == [0, 20, 40, 60]
    for contract in ordered:
        assert len(contract.stages) == 3
        assert all(stage.items for stage in contract.stages)
        assert contract.bonus.items or contract.bonus.stones.maximum
        assert contract.deposit <= contract.payout
        for stage in contract.stages:
            assert all(item_id in content.items for item_id in stage.items)


def test_page_and_history_are_read_only_before_adoption(game, play):
    for action, arg in (("大单", ""), ("记录", "")):
        page = play("merchant", f"{action} {arg}".strip(), user="ghost", now=NOW)
        assert "尚未结契" in page.text()
        assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM players") == []


def test_accept_charges_the_deposit_and_blocks_a_second_contract(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    page = play("merchant", "大单", now=NOW)
    assert "当前没有进行中的大单" in page.text()
    assert "粮道大单" in page.text() and "可接" in page.text()
    assert "血脉大单" in page.text() and "声望不足" in page.text()

    reply = play("merchant", f"接单 粮道大单", now=NOW + 1, op="accept-grain")
    assert "接下粮道大单" in reply.text()
    assert player(game[1])["stones"] == 880
    assert merchant_contract.current_id(game_ctx(game)) == GRAIN
    assert merchant_contract.stage_index(game_ctx(game)) == 1
    assert merchant_contract.deadline(game_ctx(game)) == NOW + 1 + 5 * DAY

    with pytest.raises(GameError, match="已经有一份进行中的大单"):
        play("merchant", "接单 粮道大单", now=NOW + 2, op="accept-twice")
    # The reputation gate is covered by the dedicated refusal test below; with an
    # active contract the one-at-a-time guard fires first.
    with pytest.raises(GameError, match="已经有一份进行中的大单"):
        play("merchant", "接单 血脉大单", now=NOW + 3, op="accept-high")


def test_accept_refuses_low_rep_and_short_stones_without_writing(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    before = (player(game[1])["stones"], len(sql(game[1], "SELECT * FROM quest_progress")))
    with pytest.raises(GameError, match="需要商会声望 20"):
        play("merchant", "接单 矿脉大单", now=NOW + 1, op="accept-rep")
    assert before == (player(game[1])["stones"], len(sql(game[1], "SELECT * FROM quest_progress")))

    set_stones(game, 100)
    with pytest.raises(GameError, match="定金 120 灵石"):
        play("merchant", "接单 粮道大单", now=NOW + 2, op="accept-poor")
    assert player(game[1])["stones"] == 100
    assert merchant_contract.current_id(game_ctx(game)) is None


def test_delivery_is_staged_and_pays_each_stage(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    play("merchant", "接单 粮道大单", now=NOW + 1, op="stage-accept")
    contract = game[0].content.merchant_contracts[GRAIN]

    with pytest.raises(GameError, match="物品不足"):
        play("merchant", "交货", now=NOW + 2, op="stage-short")
    assert merchant_contract.stage_index(game_ctx(game)) == 1
    assert player(game[1])["stones"] == 880

    first = finish_first_stage(game, play)
    assert "第 1/3 段已交货" in first.text()
    assert player(game[1])["stones"] == 880 + contract.stages[0].stones
    assert merchant_contract.stage_index(game_ctx(game)) == 2
    assert items(game[1])["spirit_food"] == 3  # starter only; 6 consumed

    give(game, contract.stages[1].items)
    second = play("merchant", "交货", now=NOW + 11, op="stage-two")
    assert "第 2/3 段已交货" in second.text()
    assert merchant_contract.stage_index(game_ctx(game)) == 3


def test_completion_pays_bonus_returns_deposit_and_records(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    play("merchant", "接单 粮道大单", now=NOW + 1, op="done-accept")
    contract = game[0].content.merchant_contracts[GRAIN]
    now = NOW + 1
    for stage in contract.stages:
        give(game, stage.items)
        now += 10
        reply = play("merchant", "交货", now=now, op=f"done-{now}")
    assert reply.title == "灵宠商会 · 大单完成"
    expected = 1000 - contract.deposit + sum(stage.stones for stage in contract.stages) \
        + contract.deposit + contract.bonus.stones.maximum
    assert player(game[1])["stones"] == expected
    assert items(game[1])["forge_ore"] == 2
    assert merchant.rep(game_ctx(game)) == contract.rep
    assert merchant_contract.current_id(game_ctx(game)) is None
    assert merchant_contract.stage_index(game_ctx(game)) == 0
    with pytest.raises(GameError, match="没有进行中的大单"):
        play("merchant", "交货", now=now + 1, op="done-after")


def test_abandon_forfeits_the_deposit_and_records_it(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    play("merchant", "接单 粮道大单", now=NOW + 1, op="abandon-accept")
    finish_first_stage(game, play, op="abandon-first")
    stones = player(game[1])["stones"]
    reply = play("merchant", "弃单", now=NOW + 20, op="abandon")
    assert "定金 120 灵石不退" in reply.text()
    assert "已交付 1/3 段" in reply.text()
    assert player(game[1])["stones"] == stones
    assert merchant_contract.current_id(game_ctx(game)) is None
    with pytest.raises(GameError, match="没有进行中的大单"):
        play("merchant", "弃单", now=NOW + 21, op="abandon-again")
    record = play("merchant", "记录", now=NOW + 22)
    assert "粮道大单 · 弃单 · 交付 1/3 段" in record.text()


def test_expiry_fails_lazily_on_the_next_read(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    play("merchant", "接单 粮道大单", now=NOW + 1, op="expire-accept")
    late = NOW + 1 + 6 * DAY
    page = play("merchant", "大单", now=late)
    assert "当前没有进行中的大单" in page.text()
    assert merchant_contract.current_id(game_ctx(game)) is None
    record = play("merchant", "记录", now=late + 1)
    assert "粮道大单 · 误期" in record.text()
    with pytest.raises(GameError, match="物品不足|没有进行中的大单"):
        play("merchant", "交货", now=late + 2, op="expire-deliver")


def test_history_pages_newest_first(game, play):
    play("adopt", "青鸾", now=NOW)
    contract = game[0].content.merchant_contracts[GRAIN]
    for index in range(7):
        stamp = NOW + index * 100
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 3, 1)",
            (f"mc_done_{stamp}_{contract.id}",),
        )
    first = play("merchant", "记录", now=NOW + 1000)
    assert "大单记录（第 1/2 页，每页 6 条）" in first.text()
    assert f"{beijing_day(NOW + 600)} · 粮道大单 · 完成" in first.text()
    second = play("merchant", "记录 2", now=NOW + 1001)
    assert f"{beijing_day(NOW)} · 粮道大单 · 完成" in second.text()
    with pytest.raises(GameError, match="共 2 页"):
        play("merchant", "记录 3", now=NOW + 1002, op="history-range")


def test_objectives_today_help_and_native_contract(game, play):
    play("adopt", "青鸾", now=NOW)
    set_stones(game, 1000)
    objectives = play("objectives", now=NOW)
    assert "大单：未接单 · 可接 1 种" in objectives.text()
    play("merchant", "接单 粮道大单", now=NOW + 1, op="nav-accept")
    objectives = play("objectives", now=NOW + 2)
    assert "大单：粮道大单 1/3 段" in objectives.text()

    from nonebot_plugin_spirit_pet.gameplay import today as today_module

    ctx = game_ctx(game, now=NOW + 3)
    labels = [entry["label"] for entry in today_module.collect(ctx)[0] + today_module.collect(ctx)[1]]
    assert any("大单第 1 段" in label for label in labels), labels

    guide = play("help", "灵物与灵术", now=NOW)
    for command in ("灵宠商会 大单", "灵宠商会 接单", "灵宠商会 交货", "灵宠商会 弃单"):
        assert command in guide.text()
    assert handlers._parse("灵宠商会 大单") == ("merchant", "大单")
    assert handlers._parse("灵宠商会 接单 粮道大单") == ("merchant", "接单 粮道大单")
    assert handlers._parse("灵宠商会 交货") == ("merchant", "交货")

    page = play("merchant", "大单", now=NOW + 4)
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
