import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql

NOW = 1_800_000_000
NEW_STAGES = tuple(f"stage_{index:02d}" for index in range(9, 17))


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def seed_stages(game, orders, user="u1"):
    for order in orders:
        sql(
            game[1],
            "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id)"
            " VALUES (?, ?, ?, ?)",
            (user, f"stage_{order:02d}", NOW, f"seed-{user}-{order}"),
        )


def maxed(game, user="u1"):
    sql(game[1], "UPDATE pets SET realm=6, layer=10, affinity=100, bloodline=4, energy=100 WHERE user_id=?",
        (user,))


def test_new_stages_extend_the_chapter_ladder(game):
    content = game[0].content
    stages = sorted(content.stages.values(), key=lambda stage: stage.order)
    assert len(stages) == 16
    assert [stage.order for stage in stages] == list(range(1, 17))
    assert [stage.id for stage in stages] == [f"stage_{index:02d}" for index in range(1, 17)]
    for index, stage in enumerate(stages):
        assert stage.previous_id == (stages[index - 1].id if index else None)
        assert stage.energy <= 100
        assert all(enemy in content.enemies for enemy in stage.enemies)
        assert all(item in content.items for item in stage.reward.items)

    old_top, new_top = stages[7], stages[-1]
    assert [stage.min_realm for stage in stages[8:]] == ["dujie"] * 8
    assert old_top.energy < new_top.energy
    assert old_top.reward.exp.maximum < new_top.reward.exp.maximum
    assert old_top.reward.stones.maximum < new_top.reward.stones.maximum
    for earlier, later in zip(stages[8:], stages[9:]):
        assert earlier.energy < later.energy
        assert earlier.reward.exp.maximum < later.reward.exp.maximum
    assert [stage.team for stage in stages[8:]] == [False, True, False, True, False, True, False, True]
    assert len(new_top.enemies) == 3


def test_new_stages_unlock_in_order(game, play):
    account(game, play)
    seed_stages(game, range(1, 9))
    listing = play("stage_catalog", "2")
    assert "9. 星陨残关 · 可挑战" in listing.text()
    assert "10. 镜心重围 · 未解锁" in listing.text()
    assert "灵宠挑战关卡 9" in {link.command for link in listing.inline_commands}

    account(game, play, user="u2")
    seed_stages(game, range(1, 9), user="u2")
    sql(game[1], "DELETE FROM pve_stage_progress WHERE user_id='u2' AND stage_id='stage_08'")
    with pytest.raises(GameError, match="前置关卡"):
        play("stage_challenge", "9", user="u2")

    last = play("stage_catalog", "4")
    assert last.title == "灵宠关卡 4/4"
    assert "16. 归元绝顶 · 未解锁" in last.text()


def test_new_stage_first_clear_pays_once(game, play):
    account(game, play)
    seed_stages(game, range(1, 9))
    maxed(game)
    before = (pet(game[1])["exp"], player(game[1])["stones"])
    first = play("stage_challenge", "9", op="stage-finale")
    assert first.title == "关卡首通"
    assert {"stage_id": "stage_09"} in sql(
        game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'"
    )
    assert (pet(game[1])["exp"], player(game[1])["stones"]) != before

    sql(game[1], "UPDATE players SET last_pve=NULL")
    sql(game[1], "UPDATE pets SET energy=100")
    repeat = play("stage_challenge", "9", op="stage-finale-repeat")
    assert repeat.title != "关卡首通"
    assert len(sql(game[1], "SELECT stage_id FROM pve_stage_progress WHERE user_id='u1'")) == 9


def test_ceilings_follow_the_content(game, play):
    content = game[0].content
    targets = {}
    for achievement in content.achievements.values():
        targets.setdefault(achievement.metric, set()).add(achievement.target)
    assert max(targets["stage_clears"]) == len(content.stages) == 16
    assert {1, 5} <= targets["stage_clears"]

    account(game, play)
    seed_stages(game, range(1, 17))
    assert "16. 归元绝顶 · 已通关" in play("stage_catalog", "4").text()
    assert all("未解锁" not in text for text in play("stage_catalog", "4").lines)


def test_stage_page_keeps_links_out_of_the_buttons(game, play):
    account(game, play)
    seed_stages(game, range(1, 9))
    listing = play("stage_catalog", "2")
    assert not {link.command for link in listing.inline_commands} & set(listing.commands)
    assert len(set(listing.commands)) == len(listing.commands) <= 4
