import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql
from .test_arena_matching import NOW, register, uid

DUNGEON = "青岚林"
TEAM_DUNGEON = "上古灵殿"


def entry(reply, name):
    return next(text for text in reply.lines if text.startswith(name + "（"))


def stones(game):
    return player(game[1])["stones"]


def ore(game):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")
    return rows[0]["quantity"] if rows else 0


def test_page_lists_every_dungeon_with_states(game, play):
    play("adopt", "青鸾")
    total = len(game[0].content.dungeons)
    first = play("first_clear")
    assert first.title == "灵宠秘境首通 1/4"
    assert len([text for text in first.lines if "未通关" in text]) == 5
    assert first.lines[-1] == f"共 {total} 处秘境，尚有 0 处可领取。"
    assert first.inline_commands == ()
    last = play("first_clear", "4")
    assert last.title == "灵宠秘境首通 4/4"
    with pytest.raises(GameError, match="共 4 页"):
        play("first_clear", "5")


def test_uncleared_dungeon_cannot_be_claimed(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未通关月影谷"):
        play("first_clear_claim", "月影谷")


def test_winning_unlocks_the_claim_and_grants_once(game, play):
    play("adopt", "青鸾")
    play("challenge", DUNGEON)
    page = play("first_clear")
    assert entry(page, DUNGEON).endswith("可领取")
    assert [link.command for link in page.inline_commands] == [f"灵宠秘境首通领奖 {DUNGEON}"]
    assert page.lines[-1] == "共 16 处秘境，尚有 1 处可领取。"

    before = stones(game), ore(game)
    claim = play("first_clear_claim", DUNGEON, op="first-clear")
    assert claim.title == "秘境首通奖励"
    assert (stones(game), ore(game)) == (before[0] + 150, before[1] + 2)
    assert entry(play("first_clear"), DUNGEON).endswith("已领取")


def test_claim_rejects_a_second_time_and_replays(game, play):
    play("adopt", "青鸾")
    play("challenge", DUNGEON)
    first = play("first_clear_claim", DUNGEON, op="first-clear")
    assert play("first_clear_claim", DUNGEON, op="first-clear").lines == first.lines
    with pytest.raises(GameError, match="已领取，不能重复领取"):
        play("first_clear_claim", DUNGEON)


def test_unregistered_preview_creates_no_account(game, play):
    reply = play("first_clear", user="u9")
    assert "尚未结契" in reply.text()
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_hub_reports_the_claimable_first_clear(game, play):
    play("adopt", "青鸾")
    hub = lambda: next(text for text in play("objectives").lines if text.startswith("秘境首通："))
    assert hub() == "秘境首通：暂无可领 · 共 16 处"
    play("challenge", DUNGEON)
    assert hub() == f"秘境首通：可领 1 处（{DUNGEON}）· 共 16 处"
    play("first_clear_claim", DUNGEON)
    assert hub() == "秘境首通：暂无可领 · 共 16 处"


def test_team_dungeon_first_clear_follows_the_real_win(game, play):
    register(game, play)
    play("team_create", user="private-0", now=NOW)
    play("team_join", uid(0), user="private-1", now=NOW)
    play("team_accept", uid(1), user="private-0", now=NOW)
    for user in ("private-0", "private-1"):
        play("team_ready", user=user, now=NOW)
    play("team_challenge", TEAM_DUNGEON, user="private-0", now=NOW)
    record = sql(
        game[1], "SELECT battle_id, winner_side FROM battle_records WHERE kind='pve' AND battle_key='temple'",
    )[0]
    sides = {row["user_id"]: row["side"] for row in sql(
        game[1], "SELECT user_id, side FROM battle_participants WHERE battle_id=?", (record["battle_id"],))}
    for user in ("private-0", "private-1"):
        state = entry(play("first_clear", user=user, now=NOW), TEAM_DUNGEON)
        expected = "可领取" if sides[user] == record["winner_side"] else "未通关"
        assert state.endswith(expected)


def test_missing_first_clear_reward_is_rejected(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "dungeons.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    next(item for item in entries if item["id"] == "forest").pop("first_clear")
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="missing a first-clear reward"):
        Catalog.load(target)


def test_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾")
    play("challenge", DUNGEON)
    reply = play("first_clear")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for line in segment.data["keyboard"].content.rows
        for button in line.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()


def test_help_lists_both_entries(game, play):
    text = play("help", "秘境与关卡").text()
    assert "灵宠秘境首通" in text and "灵宠秘境首通领奖" in text
