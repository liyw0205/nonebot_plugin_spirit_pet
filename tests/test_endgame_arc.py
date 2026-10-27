import itertools

import pytest

from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql

NOW = 1_800_000_000
COUNTER = itertools.count(5000)

NEW_DUNGEONS = ("starfall_altar", "mirror_lake", "sunken_court", "origin_peak")
NEW_ENEMIES = ("starfall_warden", "mirror_mirage", "sunken_sovereign", "origin_keeper")
PEERS = ("tribulation_avatar", "sky_gate_guard")
FINALE = ("journey_15", "journey_16")


def stones(game):
    return player(game[1])["stones"]


def essence(game):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='bloodline_essence'")
    return rows[0]["quantity"] if rows else 0


def entry(reply, name):
    return next(text for text in reply.lines if text.startswith(name + "（"))


def line(reply, name):
    return next(text for text in reply.lines if text.startswith(name + " ·"))


def win(game, dungeon_id, count=1, user="u1"):
    """Record permanent wins, which is what first clear and journey read."""
    for index in range(count):
        battle_id = next(COUNTER)
        sql(
            game[1],
            "INSERT INTO battle_records(battle_id, operation_id, initiator_id, kind, battle_key, title,"
            " winner_side, rounds, played_at, reply, snapshot, battle_log)"
            " VALUES (?, ?, ?, 'pve', ?, '', 0, 3, ?, '', '', '')",
            (battle_id, f"arc-{battle_id}", user, dungeon_id, NOW + index),
        )
        sql(
            game[1],
            "INSERT INTO battle_participants(battle_id, user_id, side, permission)"
            " VALUES (?, ?, 0, 'participant')",
            (battle_id, user),
        )


def profile(enemy):
    return (enemy.stats.hp, enemy.stats.attack, enemy.stats.defense, enemy.stats.speed)


def test_new_dungeons_are_endgame_tier(game):
    content = game[0].content
    assert len(content.dungeons) == 20
    assert len(content.enemies) == 23
    for dungeon_id in NEW_DUNGEONS:
        dungeon = content.dungeons[dungeon_id]
        assert dungeon.min_realm == "dujie"
        assert dungeon.team is True
        assert dungeon.energy >= 50
        assert dungeon.first_clear is not None
        assert set(dungeon.enemies) <= set(content.enemies)
    assert len({content.dungeons[dungeon_id].name for dungeon_id in NEW_DUNGEONS}) == 4


def test_new_enemies_reuse_same_realm_stats(game):
    content = game[0].content
    peers = {profile(content.enemies[enemy_id]) for enemy_id in PEERS}
    names = {content.enemies[enemy_id].name for enemy_id in PEERS}
    for enemy_id in NEW_ENEMIES:
        enemy = content.enemies[enemy_id]
        assert profile(enemy) in peers
        assert enemy.name not in names
        assert enemy.primary_element in enemy.elements
        assert enemy.signature_skill in content.skills


def test_first_clear_page_covers_twenty_dungeons(game, play):
    play("adopt", "青鸾")
    page = play("first_clear", "4")
    assert page.title == "灵宠秘境首通 4/4"
    assert page.lines[-1] == "共 20 处秘境，尚有 0 处可领取。"
    assert "星陨祭坛" in page.text() and "归元峰" in page.text()
    with pytest.raises(GameError, match="灵宠秘境首通共 4 页。"):
        play("first_clear", "5")


def test_new_dungeon_first_clear_claims_once(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未通关星陨祭坛"):
        play("first_clear_claim", "星陨祭坛")

    win(game, "starfall_altar")
    page = play("first_clear", "4")
    assert entry(page, "星陨祭坛").endswith("可领取")
    assert [link.command for link in page.inline_commands] == ["灵宠秘境首通领奖 星陨祭坛"]

    before = stones(game), essence(game)
    claim = play("first_clear_claim", "星陨祭坛", op="arc-first-clear")
    assert stones(game) == before[0] + 1250
    assert essence(game) == before[1] + 5
    assert play("first_clear_claim", "星陨祭坛", op="arc-first-clear").lines == claim.lines
    with pytest.raises(GameError, match="星陨祭坛的首通奖励已领取，不能重复领取。"):
        play("first_clear_claim", "星陨祭坛")


def test_dungeon_page_lists_the_new_entries(game, play):
    play("adopt", "青鸾")
    page = play("dungeons", "4")
    assert "星陨祭坛" in page.text()
    assert "归元峰" in page.text()


def test_journey_finale_chain(game, play):
    play("adopt", "青鸾")
    content = game[0].content
    assert len(content.journey) == 16
    first, second = (content.journey[chapter_id] for chapter_id in FINALE)
    assert first.previous_id == "journey_14"
    assert second.previous_id == "journey_15"
    assert first.realm == second.realm == "dujie"
    assert first.task.kind == "clear_dungeon" and first.task.target == "starfall_altar"
    assert second.task.kind == "win_at" and second.task.target == "origin_peak"
    assert second.task.count == 2

    page = play("journey", "3")
    assert page.title == "山海行纪 3/4"
    assert line(page, "星陨问道").endswith("未解锁")
    assert line(play("journey", "4"), "归元问鼎").endswith("未解锁")
    with pytest.raises(GameError, match="灵宠行纪共 4 页。"):
        play("journey", "5")


def test_journey_finale_claims_after_its_task(game, play):
    play("adopt", "青鸾")
    content = game[0].content
    for chapter_id in content.journey:
        if chapter_id not in FINALE:
            sql(
                game[1],
                "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)"
                " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
                (f"journey_{chapter_id}",),
            )

    assert line(play("journey", "3"), "星陨问道").endswith("进行中（0/1）")
    win(game, "starfall_altar")
    page = play("journey", "3")
    assert line(page, "星陨问道").endswith("可领取")
    assert [link.command for link in page.inline_commands] == ["灵宠行纪领奖 星陨问道"]

    before = stones(game)
    claim = play("journey_claim", "星陨问道", op="arc-journey-15")
    assert claim.title == "行纪奖励已领取"
    assert stones(game) == before + 1250
    assert play("journey_claim", "星陨问道", op="arc-journey-15").lines == claim.lines
    with pytest.raises(GameError, match="星陨问道的奖励已领取，不能重复领取。"):
        play("journey_claim", "星陨问道")

    assert line(play("journey", "4"), "归元问鼎").endswith("进行中（0/2）")
    win(game, "origin_peak", count=2)
    assert line(play("journey", "4"), "归元问鼎").endswith("可领取")


def test_ceilings_follow_the_content(game):
    content = game[0].content
    targets = {}
    for achievement in content.achievements.values():
        targets.setdefault(achievement.metric, set()).add(achievement.target)
    assert max(targets["first_clear_claims"]) == len(content.dungeons) == 20
    assert max(targets["journey_claims"]) == len(content.journey) == 16
    titles = {title.id: title for title in content.titles.values()}
    assert titles["first_clear_all"].target == 20
    assert titles["journey_end"].target == 16
    assert "二十处" in titles["first_clear_all"].description
    assert "十六段" in titles["journey_end"].description


def test_content_loads_with_the_arc():
    content = Catalog.load()
    assert len(content.dungeons) == 20
    assert len(content.journey) == 16
    assert len(content.achievements) == 77
    assert len(content.titles) == 25
