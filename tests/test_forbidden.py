"""Weekly forbidden zone: rotation, restrictions, weekly rewards and records."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def zones(game):
    return sorted(game[0].content.forbidden.values(), key=lambda zone: zone.id)


def zone_now(game, zone_id):
    """First Monday midday whose rotation lands on `zone_id`."""
    entries = zones(game)
    index = [zone.id for zone in entries].index(zone_id)
    start, _ = beijing_week(NOW)
    for step in range(12):
        candidate = start + step * WEEK
        if (candidate // 86400) % len(entries) == index:
            return candidate + 12 * 3600
    raise AssertionError(f"no week maps to {zone_id}")


def week_start_of(now):
    return beijing_week(now)[0]


def boost(game, user="u1", realm=5):
    sql(
        game[1],
        "UPDATE pets SET realm=?, layer=10, bloodline=4, energy=100, energy_updated=? WHERE user_id=?",
        (realm, NOW, user),
    )


def add_pet(game, user, species, name, *, realm=5):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp,"
        " affinity, energy, energy_updated, archived) VALUES (?, ?, ?, ?, 10, 4, 0, 0, 100, ?, 0)",
        (user, species, name, realm, NOW),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def markers(game, user="u1"):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE 'forbidden_%'"
        " ORDER BY quest_id",
        (user,),
    )


def clear_depth(game, now, depth_id, user="u1", rounds=3):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)",
        (user, f"forbidden_{week_start_of(now)}_{depth_id}", rounds),
    )


def free_cooldown(game):
    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")


def roster(play, *pet_ids):
    play("lineup", " ".join(str(pet_id) for pet_id in pet_ids))


def test_content_defines_three_zones_with_contiguous_depths(game):
    entries = zones(game)
    assert [zone.id for zone in entries] == ["ember_crypt", "frost_prison", "void_shrine"]
    assert {zone.restriction.type for zone in entries} == {"solo", "duo", "same_element"}
    depth_ids = []
    for zone in entries:
        assert [depth.order for depth in zone.depths] == [1, 2, 3]
        assert [depth.min_realm for depth in zone.depths] == ["ningqi", "zhuji", "jindan"]
        assert [depth.energy for depth in zone.depths] == [20, 25, 30]
        assert zone.bonus.stones.maximum > 0 and zone.bonus.items
        for depth in zone.depths:
            depth_ids.append(depth.id)
            assert depth.id.startswith(zone.id)
            assert all(enemy in game[0].content.enemies for enemy in depth.enemies)
            assert all(item in game[0].content.items for item in depth.reward.items)
            assert depth.reward.stones.maximum > 0
    assert len(set(depth_ids)) == len(depth_ids) == 9


def test_rotation_is_stable_within_a_week_and_shifts_next_week(game, play):
    play("adopt", "青鸾")
    first = play("forbidden")
    again = play("forbidden", now=NOW + 3600)
    assert first.lines[0] == again.lines[0]
    zone = zones(game)[(week_start_of(NOW) // 86400) % 3]
    assert f"本周禁地：{zone.name}" in first.text()
    upcoming = zones(game)[(week_start_of(NOW) // 86400 + 1) % 3]
    assert f"下周：{upcoming.name}" in first.text()
    later = play("forbidden", now=NOW + WEEK)
    assert f"本周禁地：{upcoming.name}" in later.text()


def test_unregistered_page_is_read_only(game, play):
    page = play("forbidden", user="u9")
    assert page.title == "灵宠禁地"
    assert "尚未结契" in page.text()
    assert page.inline_commands == ()
    assert sql(game[1], "SELECT * FROM players") == []


def test_page_lists_depths_and_links_only_openable_ones(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    page = play("forbidden", now=now)
    assert "1. 焦土外环 · 可挑战" in page.text()
    assert "2. 熔岩回廊 · 未解锁" in page.text()
    assert "3. 焚心祭坛 · 未解锁" in page.text()
    assert [(link.line, link.command) for link in page.inline_commands] == [
        (3, "灵宠挑战禁地 1"),
    ]
    assert page.commands == ("灵宠秘境", "灵宠关卡", "灵宠战报", "我的灵宠")
    assert not {link.command for link in page.inline_commands} & set(page.commands)


def test_detail_shows_restriction_reward_and_best(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    detail = play("forbidden", "1", now=now)
    assert detail.title == "焚骨禁地 · 焦土外环"
    assert "禁制：独行 · 只允许一只灵宠出战" in detail.text()
    assert "精力 20" in detail.text() and "林间傀儡" in detail.text()
    assert "本周最佳：尚未通关" in detail.text()
    assert "单层首通奖励（每周一次）：修为 120-180 · 灵石 100-140 · 锻灵矿 1" in detail.text()
    assert "全清奖励（每周一次）：灵石 200-260 · 锻灵矿 3 · 血脉精华 1" in detail.text()
    assert "灵宠挑战禁地 1" in detail.commands


def test_solo_zone_rejects_a_multi_pet_lineup(game, play):
    play("adopt", "青鸾")
    boost(game)
    extra = add_pet(game, "u1", "xuanhu", "小玄")
    roster(play, 1, extra)
    now = zone_now(game, "ember_crypt")
    before = player(game[1])
    with pytest.raises(GameError, match="独行"):
        play("forbidden_challenge", "1", now=now)
    assert markers(game) == []
    assert player(game[1])["stones"] == before["stones"]


def test_duo_zone_requires_exactly_two_pets(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "frost_prison")
    with pytest.raises(GameError, match="双生"):
        play("forbidden_challenge", "1", now=now)
    second = add_pet(game, "u1", "xuanhu", "小玄")
    third = add_pet(game, "u1", "baize", "小白")
    roster(play, 1, second, third)
    with pytest.raises(GameError, match="双生"):
        play("forbidden_challenge", "1", now=now)
    assert markers(game) == []
    roster(play, 1, second)
    reply = play("forbidden_challenge", "1", now=now)
    assert reply.title == "禁地首通"


def test_same_element_zone_rejects_mixed_primary_elements(game, play):
    play("adopt", "青鸾")
    boost(game)
    other = add_pet(game, "u1", "xuanhu", "小玄")
    roster(play, 1, other)
    now = zone_now(game, "void_shrine")
    with pytest.raises(GameError, match="同心"):
        play("forbidden_challenge", "1", now=now)
    assert markers(game) == []


def test_same_element_zone_accepts_a_matching_lineup(game, play):
    play("adopt", "青鸾")
    boost(game)
    other = add_pet(game, "u1", "fenghu", "追风")
    roster(play, 1, other)
    now = zone_now(game, "void_shrine")
    reply = play("forbidden_challenge", "1", now=now)
    assert reply.title == "禁地首通"
    assert markers(game)[0]["quest_id"] == f"forbidden_{week_start_of(now)}_void_shrine_1"


def test_sequential_unlock_requires_the_previous_depth_this_week(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    with pytest.raises(GameError, match="前置层"):
        play("forbidden_challenge", "2", now=now)
    clear_depth(game, now, "ember_crypt_1")
    page = play("forbidden", now=now)
    assert "1. 焦土外环 · 本周已通关" in page.text()
    assert "2. 熔岩回廊 · 可挑战" in page.text()
    reply = play("forbidden_challenge", "2", now=now)
    assert reply.title in ("禁地首通", "禁地败退", "禁地平局")


def test_first_clear_pays_once_and_repeats_are_practice(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    before = player(game[1])["stones"]
    before_items = items(game[1])
    first = play("forbidden_challenge", "1", now=now)
    assert first.title == "禁地首通"
    assert "首通焦土外环" in first.text()
    after = player(game[1])["stones"]
    assert after - before >= 100
    assert items(game[1]).get("forge_ore", 0) - before_items.get("forge_ore", 0) >= 1
    rows = markers(game)
    assert len(rows) == 1 and rows[0]["progress"] >= 1

    free_cooldown(game)
    stones = player(game[1])["stones"]
    again = play("forbidden_challenge", "1", now=now)
    assert again.title == "禁地再胜"
    assert "不重复发放周奖励" in again.text()
    assert player(game[1])["stones"] == stones
    assert markers(game) == rows


def test_all_clear_bonus_pays_once(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    clear_depth(game, now, "ember_crypt_1")
    clear_depth(game, now, "ember_crypt_2")
    stones = player(game[1])["stones"]
    reply = play("forbidden_challenge", "3", now=now)
    assert reply.title == "禁地首通"
    assert "焚骨禁地全清" in reply.text()
    assert player(game[1])["stones"] - stones >= 500
    keys = [row["quest_id"] for row in markers(game)]
    assert f"forbidden_{week_start_of(now)}_all" in keys
    assert f"forbidden_{week_start_of(now)}_ember_crypt_3" in keys

    free_cooldown(game)
    stones = player(game[1])["stones"]
    again = play("forbidden_challenge", "3", now=now)
    assert again.title == "禁地再胜"
    assert player(game[1])["stones"] == stones


def test_weekly_reset_reopens_depth_one_and_pays_again(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    play("forbidden_challenge", "1", now=now)
    assert len(markers(game)) == 1
    later = now + 3 * WEEK
    assert zones(game)[(week_start_of(later) // 86400) % 3].id == "ember_crypt"
    page = play("forbidden", now=later)
    assert "1. 焦土外环 · 可挑战" in page.text()
    assert f"本周进度：0/3 层" in page.text()
    free_cooldown(game)
    stones = player(game[1])["stones"]
    reply = play("forbidden_challenge", "1", now=later)
    assert reply.title == "禁地首通"
    assert player(game[1])["stones"] > stones
    assert len(markers(game)) == 2


def test_best_rounds_reads_this_weeks_winning_record(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    reply = play("forbidden_challenge", "1", now=now)
    rounds = int(re.search(r"(\d+) 回合", reply.text()).group(1))
    page = play("forbidden", now=now)
    assert f"本周最佳 {rounds} 回合" in page.text()
    detail = play("forbidden", "1", now=now)
    assert f"本周最佳：{rounds} 回合" in detail.text()


def test_gates_reject_realm_energy_cooldown_and_bad_input(game, play):
    play("adopt", "青鸾")
    now = zone_now(game, "ember_crypt")
    with pytest.raises(GameError, match="境界不足"):
        play("forbidden_challenge", "1", now=now)

    boost(game)
    with pytest.raises(GameError, match="1-3"):
        play("forbidden_challenge", "9", now=now)
    with pytest.raises(GameError, match="未找到"):
        play("forbidden_challenge", "不存在", now=now)
    with pytest.raises(GameError, match="本周禁地"):
        play("forbidden_challenge", "寒铁牢门", now=now)

    sql(game[1], "UPDATE pets SET energy=5, energy_updated=?", (now,))
    with pytest.raises(GameError, match="精力不足"):
        play("forbidden_challenge", "1", now=now)

    sql(game[1], "UPDATE pets SET energy=100, energy_updated=?", (now,))
    play("forbidden_challenge", "1", now=now, op="forbidden-cooldown")
    with pytest.raises(GameError, match="调息"):
        play("forbidden_challenge", "1", now=now, op="forbidden-cooldown-2")


def test_same_operation_replays_and_other_identity_is_rejected(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    first = play("forbidden_challenge", "1", now=now, op="forbidden-replay")
    sql(game[1], "DELETE FROM operations WHERE operation_id='forbidden-replay'")
    state = (player(game[1]), items(game[1]), markers(game))
    assert play("forbidden_challenge", "1", now=now + 1, op="forbidden-replay") == first
    assert (player(game[1]), items(game[1]), markers(game)) == state

    play("adopt", "玄狐", user="u2")
    boost(game, "u2")
    sql(game[1], "DELETE FROM operations WHERE operation_id='forbidden-replay'")
    with pytest.raises(GameError, match="reused by a different user"):
        play("forbidden_challenge", "1", now=now, op="forbidden-replay", user="u2")
    assert [row for row in markers(game, "u2")] == []


def test_battle_is_recorded_as_a_stage_battle_outside_stage_stats(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    play("forbidden_challenge", "1", now=now)
    row = sql(
        game[1],
        "SELECT kind, battle_key, rounds FROM battle_records WHERE kind='pve_stage'",
    )[0]
    assert row["battle_key"] == "ember_crypt_1"
    stats = play("stage_stats", now=now)
    assert "焦土外环" not in stats.text()
    reports = play("battle_reports", now=now)
    assert "焦土外环" in reports.text()


def test_help_objectives_and_parse_contract(game, play):
    guide = play("help", "秘境与关卡")
    assert "灵宠禁地" in guide.text()
    assert "灵宠挑战禁地" in guide.text()
    assert handlers._parse("灵宠禁地 1") == ("forbidden", "1")
    assert handlers._parse("灵宠挑战禁地 焦土外环") == ("forbidden_challenge", "焦土外环")

    play("adopt", "青鸾")
    hub = play("objectives")
    zone = zones(game)[(week_start_of(NOW) // 86400) % 3]
    assert f"灵宠禁地：本周 0/3 层 · 下一层 {zone.depths[0].name}" in hub.text()
    link = next(link for link in hub.inline_commands if link.command == "灵宠禁地")
    assert hub.lines[link.line].startswith("灵宠禁地：")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    boost(game)
    now = zone_now(game, "ember_crypt")
    page = play("forbidden", now=now)
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
