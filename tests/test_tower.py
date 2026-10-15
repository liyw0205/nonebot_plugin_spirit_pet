import re
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import Stats
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql, uid_label

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)
    return uid_label(game[1], user)


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def seed_floors(game, orders, user="u1"):
    for order in orders:
        sql(
            game[1],
            "INSERT INTO pve_stage_progress VALUES (?, ?, ?, ?)",
            (user, f"tower_{order:02d}", NOW, f"seed-{user}-{order}"),
        )


def test_content_defines_a_contiguous_single_player_ladder(game):
    floors = sorted(game[0].content.tower.values(), key=lambda floor: floor.order)
    assert [floor.order for floor in floors] == list(range(1, 17))
    assert [floor.id for floor in floors] == [f"tower_{index:02d}" for index in range(1, 17)]
    for index, floor in enumerate(floors):
        assert floor.previous_id == (floors[index - 1].id if index else None)
        assert floor.energy <= 100
        assert all(enemy in game[0].content.enemies for enemy in floor.enemies)
        assert all(item in game[0].content.items for item in floor.reward.items)
        assert not hasattr(floor, "team")
    assert len(floors[-1].enemies) == 3
    assert floors[0].energy < floors[-1].energy
    assert floors[0].reward.exp.maximum < floors[-1].reward.exp.maximum


def test_list_links_only_openable_floors_and_keeps_bounded_actions(game, play):
    account(game, play)
    listing = play("tower_catalog")
    assert listing.title == "万灵塔 1/4"
    assert listing.lines[0] == "当前深度：0/16 层。"
    assert "1. 初入塔门 · 可挑战" in listing.text()
    assert "2. 雷泽回响 · 未解锁" in listing.text()
    assert links(listing) == [(1, "前往挑战", "灵宠挑战万灵塔 1")]
    assert listing.commands == ("灵宠万灵塔 2", "灵宠关卡", "灵宠秘境")
    assert len(set(listing.commands)) == len(listing.commands) <= 4
    assert not {command for _, _, command in links(listing)} & set(listing.commands)
    second = play("tower_catalog", "2")
    assert second.title == "万灵塔 2/4"
    assert links(second) == []
    assert second.commands == ("灵宠万灵塔 1", "灵宠万灵塔 3", "灵宠关卡", "灵宠秘境")


def test_unregistered_player_can_browse_without_creating_an_account(game, play):
    listing = play("tower_catalog")
    detail = play("tower_catalog", "初入塔门")
    assert "尚未结契" in listing.text()
    assert "进度：尚未结契" in detail.text()
    assert links(listing) == []
    assert not sql(game[1], "SELECT * FROM players")


def test_detail_shows_progress_rewards_and_the_run_entry(game, play):
    account(game, play)
    # A bare number is a page, exactly like the chapter catalogue; details use the floor name.
    assert play("tower_catalog", "2").title == "万灵塔 2/4"
    locked = play("tower_catalog", "雷泽回响")
    assert locked.title == "万灵塔 2 · 雷泽回响"
    assert "进度：未解锁 · 当前深度 0/16 层" in locked.text()
    assert "首通奖励" in locked.text() and "锻灵矿" in locked.text()
    assert "灵宠挑战万灵塔 2" not in locked.commands
    first = play("tower_catalog", "初入塔门")
    assert first.title == "万灵塔 1 · 初入塔门"
    assert "进度：可挑战" in first.text()
    assert "单人 · 启灵起 · 精力 20 · 敌手：林间傀儡" in first.text()
    assert "灵宠挑战万灵塔 1" in first.commands
    assert "首通奖励只领取一次" in first.text()


def test_first_clear_grants_once_and_repeats_only_practice(game, play):
    account(game, play)
    before = (pet(game[1])["exp"], player(game[1])["stones"], items(game[1]))
    first = play("tower_challenge", "1", op="tower-first")
    assert first.title == "塔层首通"
    assert sql(game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'") == [
        {"stage_id": "tower_01"}
    ]
    assert pet(game[1])["energy"] == 80
    assert player(game[1])["last_pve"] == NOW
    after_first = (pet(game[1])["exp"], player(game[1])["stones"], items(game[1]))
    assert after_first != before
    report = sql(game[1], "SELECT kind, battle_key FROM battle_records WHERE operation_id='tower-first'")[0]
    assert report == {"kind": "pve_stage", "battle_key": "tower_01"}
    assert play("tower_catalog").lines[0] == "当前深度：1/16 层。"
    assert "2. 雷泽回响 · 可挑战" in play("tower_catalog").text()

    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    repeat = play("tower_challenge", "1", op="tower-repeat")
    assert repeat.title == "塔层再胜"
    assert "不重复发放首通奖励" in repeat.text()
    assert (pet(game[1])["exp"], player(game[1])["stones"], items(game[1])) == after_first
    assert pet(game[1])["energy"] == 80
    assert player(game[1])["last_pve"] == NOW
    assert len(sql(game[1], "SELECT * FROM pve_stage_progress WHERE user_id='u1'")) == 1


def test_failed_floor_consumes_resources_without_progress(game, play):
    account(game, play)
    service = game[0]
    enemy = service.content.enemies["wood_guard"]
    enemies = dict(service.content.enemies)
    enemies[enemy.id] = enemy.model_copy(update={
        "stats": Stats(hp=1_000_000, attack=1, defense=0, speed=1),
    })
    service.content = replace(service.content, enemies=enemies)
    before = (pet(game[1])["exp"], player(game[1])["stones"], items(game[1]))

    result = play("tower_challenge", "1", op="tower-loss")
    assert result.title == "塔层平局"
    assert "塔层进度不变" in result.text()
    assert not sql(game[1], "SELECT * FROM pve_stage_progress")
    assert pet(game[1])["energy"] == 80
    assert player(game[1])["last_pve"] == NOW
    assert (pet(game[1])["exp"], player(game[1])["stones"], items(game[1])) == before
    assert sql(game[1], "SELECT winner_side FROM battle_records WHERE operation_id='tower-loss'") == [
        {"winner_side": -1}
    ]
    assert play("tower_catalog").lines[0] == "当前深度：0/16 层。"


def test_gates_reject_locked_realm_energy_cooldown_and_bad_input(game, play):
    account(game, play)
    with pytest.raises(GameError, match="前置塔层"):
        play("tower_challenge", "2")
    with pytest.raises(GameError, match="共 4 页"):
        play("tower_catalog", "5")
    with pytest.raises(GameError, match="1-16 的整数"):
        play("tower_challenge", "17")
    with pytest.raises(GameError, match="未找到该内容"):
        play("tower_challenge", "不存在的塔层")
    seed_floors(game, (1, 2, 3, 4))
    with pytest.raises(GameError, match="境界不足"):
        play("tower_challenge", "5")

    play("tower_challenge", "1", op="tower-gate")
    with pytest.raises(GameError, match="调息"):
        play("tower_challenge", "1", op="tower-cooldown")
    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=5")
    with pytest.raises(GameError, match="精力不足"):
        play("tower_challenge", "1", op="tower-energy")
    assert len(sql(game[1], "SELECT * FROM pve_stage_progress WHERE user_id='u1'")) == 4


def test_same_operation_replays_and_another_identity_cannot_reuse(game, play):
    account(game, play, "u1")
    first = play("tower_challenge", "1", op="tower-replay")
    sql(game[1], "DELETE FROM operations WHERE operation_id='tower-replay'")
    state = (
        pet(game[1]), player(game[1]), items(game[1]),
        sql(game[1], "SELECT * FROM pve_stage_progress"),
    )
    assert play("tower_challenge", "1", op="tower-replay", now=NOW + 1) == first
    assert (
        pet(game[1]), player(game[1]), items(game[1]),
        sql(game[1], "SELECT * FROM pve_stage_progress"),
    ) == state
    account(game, play, "u2")
    # The durable battle guard rejects another identity before the handler runs, and the
    # second player gains no tower progress from the reused message.
    sql(game[1], "DELETE FROM operations WHERE operation_id='tower-replay'")
    with pytest.raises(GameError, match="reused by a different user"):
        play("tower_challenge", "1", op="tower-replay", user="u2")
    assert sql(game[1], "SELECT COUNT(*) AS total FROM pve_stage_progress WHERE user_id='u2'") == [
        {"total": 0}
    ]


def test_tower_depth_achievements_while_chapter_metric_stays_separate(game, play):
    account(game, play)
    seed_floors(game, (1, 2, 3))
    entries = list(game[0].content.achievements.values())
    index = next(index for index, entry in enumerate(entries) if entry.id == "tower_three")
    page = play("achievements", str(index // 5 + 1))
    assert "三层登临 · 可领奖" in page.text()
    assert "灵宠成就领奖 三层登临" in {link.command for link in page.inline_commands}
    with pytest.raises(GameError, match="成就尚未完成"):
        play("achievement_claim", "初战告捷")
    with pytest.raises(GameError, match="成就尚未完成"):
        play("achievement_claim", "六层凌云")
    claim = play("achievement_claim", "三层登临", op="tower-claim")
    assert claim.title == "成就奖励已领取" and "三层登临" in claim.text()
    assert player(game[1])["stones"] >= 400
    with pytest.raises(GameError, match="已领取"):
        play("achievement_claim", "三层登临", op="tower-claim-again")


def test_help_lists_the_tower_entries(game, play):
    guide = play("help", "秘境与关卡")
    assert "灵宠万灵塔" in guide.text()
    assert "灵宠挑战万灵塔" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    account(game, play)
    listing = play("tower_catalog")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in listing.inline_commands}
    assert not linked & buttons
