import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql

NOW = 1_800_000_000
ENCOUNTER = "灵泉寻踪"


def stones(game):
    return player(game[1])["stones"]


def items(game, item_id):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id=?", (item_id,))
    return rows[0]["quantity"] if rows else 0


def discover(game, encounter_id="spring"):
    sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
        "VALUES ('u1',?,?)", (encounter_id, NOW))


def row(reply, prefix):
    return next(text for text in reply.lines if text.startswith(prefix))


def test_page_previews_without_an_account(game, play):
    reply = play("echoes", user="u9", now=NOW)
    assert reply.title == "奇闻回响"
    assert "尚未结契" in reply.text()
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_page_lists_only_discovered_encounters(game, play):
    play("adopt", "青鸾", now=NOW)
    empty = play("echoes", now=NOW)
    assert empty.title == "奇闻回响 1/1"
    assert empty.lines == ("已发现 0/21 条奇闻，尚有 0 个选项可回响。",)
    assert empty.inline_commands == ()

    discover(game)
    page = play("echoes", now=NOW)
    assert row(page, ENCOUNTER) == "灵泉寻踪 · 取水 · 可回响"
    assert "灵泉寻踪 · 静坐 · 可回响" in page.text()
    assert [link.command for link in page.inline_commands] == [
        "灵宠回响选择 灵泉寻踪 取水", "灵宠回响选择 灵泉寻踪 静坐",
    ]
    assert page.lines[-1] == "已发现 1/21 条奇闻，尚有 2 个选项可回响。"


def test_choose_grants_the_option_and_locks_the_others(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game)
    before = stones(game), items(game, "spirit_food")
    reply = play("echo_choose", "灵泉寻踪 取水", now=NOW, op="echo-one")
    assert reply.title == "奇闻回响"
    assert reply.lines[0] == "灵泉寻踪 · 取水"
    assert reply.lines[1] == "你取了一瓢灵泉水，水汽在掌心凝成细碎的灵光。"
    assert (stones(game), items(game, "spirit_food")) == (before[0] + 60, before[1] + 1)

    page = play("echoes", now=NOW)
    assert row(page, ENCOUNTER) == "灵泉寻踪 · 取水 · 已回响（取水）"
    assert "灵泉寻踪 · 静坐 · 已错过" in page.text()
    assert page.inline_commands == ()
    hub = next(text for text in play("objectives", now=NOW).lines if text.startswith("回响："))
    assert hub == "回响：暂无可回响 · 已发现 1/21 条奇闻"


def test_choose_rejects_unknown_options_and_undiscovered_encounters(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game)
    with pytest.raises(GameError, match="没有这个选项；可选：取水、静坐"):
        play("echo_choose", "灵泉寻踪 泡茶", now=NOW)
    with pytest.raises(GameError, match="尚未发现古阵修复"):
        play("echo_choose", "古阵修复 修复", now=NOW)
    with pytest.raises(GameError, match="格式：灵宠回响选择 奇闻名 选项名"):
        play("echo_choose", "灵泉寻踪", now=NOW)


def test_choose_rejects_a_second_echo_and_replays(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game)
    first = play("echo_choose", "灵泉寻踪 取水", now=NOW, op="echo-one")
    assert play("echo_choose", "灵泉寻踪 取水", now=NOW, op="echo-one").lines == first.lines
    with pytest.raises(GameError, match="已回响（取水），其余选项已失效"):
        play("echo_choose", "灵泉寻踪 静坐", now=NOW)


def test_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game)
    reply = play("echoes", now=NOW)
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for line in segment.data["keyboard"].content.rows
        for button in line.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()


def test_help_lists_both_entries(game, play):
    text = play("help", "秘境与关卡", now=NOW).text()
    assert "灵宠回响" in text and "灵宠回响选择" in text


def test_every_encounter_offers_exclusive_options():
    content = Catalog.load()
    for encounter in content.encounters.values():
        assert 2 <= len(encounter.options) <= 3
        assert len({option.id for option in encounter.options}) == len(encounter.options)
        assert all(option.text and option.reward.stones.minimum > 0 for option in encounter.options)


def edit_content(tmp_path, change):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "adventures.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    change(entries)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return target


def test_single_option_is_rejected(tmp_path):
    target = edit_content(tmp_path, lambda entries: entries[0].update(options=entries[0]["options"][:1]))
    with pytest.raises(ValueError, match="needs two or three echo options"):
        Catalog.load(target)


def test_repeated_option_id_is_rejected(tmp_path):
    def duplicate(entries):
        entries[0]["options"][1]["id"] = entries[0]["options"][0]["id"]
    target = edit_content(tmp_path, duplicate)
    with pytest.raises(ValueError, match="repeats an echo option id"):
        Catalog.load(target)


def test_unknown_option_reward_item_is_rejected(tmp_path):
    def retarget(entries):
        entries[0]["options"][0]["reward"]["items"] = {"no_such_item": {"minimum": 1, "maximum": 1}}
    target = edit_content(tmp_path, retarget)
    with pytest.raises(ValueError, match="unknown reward items"):
        Catalog.load(target)
