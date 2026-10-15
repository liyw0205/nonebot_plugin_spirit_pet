import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql

NOW = 1_800_000_000
NEW_FLOORS = tuple(f"tower_{index:02d}" for index in range(9, 17))


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def seed_floors(game, orders, user="u1"):
    for order in orders:
        sql(
            game[1],
            "INSERT INTO pve_stage_progress VALUES (?, ?, ?, ?)",
            (user, f"tower_{order:02d}", NOW, f"seed-{user}-{order}"),
        )


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def test_new_floors_extend_the_ladder(game):
    content = game[0].content
    floors = sorted(content.tower.values(), key=lambda floor: floor.order)
    assert len(floors) == 16
    assert [floor.order for floor in floors] == list(range(1, 17))
    assert [floor.id for floor in floors] == [f"tower_{index:02d}" for index in range(1, 17)]
    for index, floor in enumerate(floors):
        assert floor.previous_id == (floors[index - 1].id if index else None)
        assert floor.energy <= 100
        assert all(enemy in content.enemies for enemy in floor.enemies)
        assert all(item in content.items for item in floor.reward.items)

    old_top, new_top = floors[7], floors[-1]
    assert [floor.min_realm for floor in floors[8:]] == ["dujie"] * 8
    assert len(new_top.enemies) == 3
    assert old_top.energy < new_top.energy
    assert old_top.reward.exp.maximum < new_top.reward.exp.maximum
    assert old_top.reward.stones.maximum < new_top.reward.stones.maximum
    for earlier, later in zip(floors[8:], floors[9:]):
        assert earlier.energy < later.energy
        assert earlier.reward.exp.maximum < later.reward.exp.maximum


def test_new_floors_stay_locked_until_the_old_top_is_cleared(game, play):
    account(game, play)
    seed_floors(game, range(1, 9))
    listing = play("tower_catalog", "2")
    assert listing.title == "万灵塔 2/4"
    assert "9. 星陨回廊 · 可挑战" in listing.text()
    assert "10. 镜心迷途 · 未解锁" in listing.text()
    # Earlier floors stay openable for practice, so the new floor is one link among several.
    assert "灵宠挑战万灵塔 9" in {command for _, _, command in links(listing)}

    account(game, play, user="u2")
    seed_floors(game, range(1, 9), user="u2")
    sql(game[1], "DELETE FROM pve_stage_progress WHERE user_id='u2' AND stage_id='tower_08'")
    with pytest.raises(GameError, match="前置塔层"):
        play("tower_challenge", "9", user="u2")

    last = play("tower_catalog", "4")
    assert last.title == "万灵塔 4/4"
    assert "16. 归元绝顶 · 未解锁" in last.text()


def test_new_floor_first_clear_pays_once(game, play):
    account(game, play)
    seed_floors(game, range(1, 9))
    sql(game[1], "UPDATE pets SET realm=6, layer=10, affinity=100, bloodline=4, energy=100")
    before = (pet(game[1])["exp"], player(game[1])["stones"])
    first = play("tower_challenge", "9", op="tower-finale")
    assert first.title == "塔层首通"
    assert {"stage_id": "tower_09"} in sql(
        game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'"
    )
    assert (pet(game[1])["exp"], player(game[1])["stones"]) != before
    assert play("tower_catalog").lines[0] == "当前深度：9/16 层。"
    assert "10. 镜心迷途 · 可挑战" in play("tower_catalog", "2").text()

    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    repeat = play("tower_challenge", "9", op="tower-finale-repeat")
    assert repeat.title == "塔层再胜"
    assert len(sql(game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'")) == 9


def test_depth_and_ceilings_follow_the_content(game, play):
    content = game[0].content
    targets = {}
    for achievement in content.achievements.values():
        targets.setdefault(achievement.metric, set()).add(achievement.target)
    assert max(targets["tower_depth"]) == len(content.tower) == 16
    assert {3, 6} <= targets["tower_depth"]
    titles = {title.id: title for title in content.titles.values()}
    assert titles["tower_lord"].target == 16
    assert "十六层" in titles["tower_lord"].description
    assert titles["tower_guard"].target == 3

    account(game, play)
    seed_floors(game, range(1, 17))
    listing = play("tower_catalog")
    assert listing.lines[0] == "当前深度：16/16 层。"
    assert "16. 归元绝顶 · 已通关" in play("tower_catalog", "4").text()
    assert all("未解锁" not in text for text in play("tower_catalog", "4").lines)


def test_tower_page_keeps_links_out_of_the_buttons(game, play):
    account(game, play)
    seed_floors(game, range(1, 9))
    listing = play("tower_catalog", "2")
    assert not {command for _, _, command in links(listing)} & set(listing.commands)
    assert len(set(listing.commands)) == len(listing.commands) <= 4
