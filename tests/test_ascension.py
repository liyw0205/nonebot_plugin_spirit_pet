"""Ascension trial contracts: three-stage fights, permanent marker, cycles, UX.

The trial is deliberately tuned so the same deterministic RNG produces three
distinct outcomes from real content: a deep-bloodline 渡劫 pet clears all three
stages, a mid-bloodline pet clears 雷劫 and falls to 心魔, and a shallow one falls
at 雷劫. Tests seed those pets directly instead of mocking the combat engine.
"""

from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import ascension
from nonebot_plugin_spirit_pet.gameplay.battle_records import _member_text, capture_snapshot
from nonebot_plugin_spirit_pet.gameplay.combat import Battle, enemy_fighter, pet_stats
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000
WEEK = 7 * 86400


def account(play, user="u1"):
    play("adopt", "青鸾", user=user)


def add_pet(game, user="u1", species="qingluan"):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, 100, ?)",
            (user, species, species, NOW),
        ).lastrowid


def maxed(game, pet_id, bloodline=4):
    sql(
        game[1],
        "UPDATE pets SET realm=6, layer=10, bloodline=?, affinity=100, energy=100 WHERE pet_id=?",
        (bloodline, pet_id),
    )
    return pet_id


def stats(game, pet_id):
    with game[1].connect() as conn:
        return pet_stats(Repository(conn).pet(pet_id), game[0].content)


def credentials(game, prefix):
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE ?"
        " ORDER BY quest_id",
        (f"{prefix}%",),
    )


def test_content_defines_three_ordered_stages_backed_by_real_enemies(game):
    stages = sorted(game[0].content.ascension.values(), key=lambda stage: stage.order)
    assert [stage.order for stage in stages] == [1, 2, 3]
    assert [stage.name for stage in stages] == ["雷劫", "心魔", "天道"]
    for stage in stages:
        assert stage.enemy in game[0].content.enemies
        assert stage.description


def test_content_validation_requires_three_stages_and_real_enemies(game):
    content = game[0].content
    without_heaven = {key: value for key, value in content.ascension.items() if key != "heaven"}
    with pytest.raises(ValueError, match="exactly three trial stages"):
        replace(content, ascension=without_heaven).validate()
    unknown_enemy = {
        **content.ascension,
        "thunder": content.ascension["thunder"].model_copy(update={"enemy": "missing_enemy"}),
    }
    with pytest.raises(ValueError, match="unknown ascension trial enemy"):
        replace(content, ascension=unknown_enemy).validate()


def test_unregistered_preview_is_read_only(game, play):
    reply = play("ascension", user="u9")
    assert "尚未结契" in reply.text()
    assert "雷劫、心魔、天道" in reply.text()
    assert reply.commands == ("灵宠帮助",)
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_unmet_realm_and_layer_are_rejected(game, play):
    account(play)
    target = pet(game[1])["pet_id"]
    with pytest.raises(GameError, match="尚未达到渡劫十层"):
        play("ascension", str(target))
    sql(game[1], "UPDATE pets SET realm=6, layer=9 WHERE pet_id=?", (target,))
    with pytest.raises(GameError, match="尚未达到渡劫十层"):
        play("ascension", str(target))


def test_non_owned_pet_is_rejected(game, play):
    account(play, "u1")
    account(play, "u2")
    other = pet(game[1], "u2")["pet_id"]
    maxed(game, other)
    with pytest.raises(GameError, match="没有属于你的在册灵宠"):
        play("ascension", str(other))


def test_expedition_pet_is_busy_and_cannot_start(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"])
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot) VALUES ('u1', ?, 't', '采灵药',"
        " 'seed-exp', ?, ?, 'running', '{}')",
        (target, NOW - 10, NOW + 1000),
    )
    with pytest.raises(GameError, match="正在外出派遣"):
        play("ascension", str(target))


def test_full_win_ascends_and_applies_stats_and_title(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    before = stats(game, target)
    reply = play("ascension", str(target))
    assert reply.title == "飞升成功"
    assert [line for line in reply.lines if line.startswith("第")] == [
        line for line in reply.lines if "段 " in line and "：" in line
    ]
    assert sum("：胜" in line for line in reply.lines) == 3
    assert "全属性 +10%" in reply.text()
    assert "破界者" in reply.text()
    assert credentials(game, "ascended_") == [{"quest_id": f"ascended_{target}", "progress": NOW}]
    assert credentials(game, "rebirth_count") == [{"quest_id": "rebirth_count", "progress": 1}]
    after = stats(game, target)
    for field in ("hp", "attack", "defense", "speed"):
        assert after.model_dump()[field] > before.model_dump()[field]
        assert abs(after.model_dump()[field] / before.model_dump()[field] - 1.10) < 0.01
    with game[1].connect() as conn:
        assert Repository(conn).pet(target).ascended is True
    titles = play("titles", "5").text()
    assert "24. 破界者 · 已获得" in titles
    assert "当前称号：破界者" in play("titles").text()


def test_partial_win_does_not_ascend_or_charge_anything(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=2)
    stones, energy = player(game[1])["stones"], pet(game[1])["energy"]
    before_items = items(game[1])
    reply = play("ascension", str(target))
    assert reply.title == "飞升未成"
    assert "第1段 雷劫：胜" in reply.text()
    assert "第2段 心魔：败" in reply.text()
    assert "未消耗任何资源" in reply.text()
    assert credentials(game, "ascended_") == []
    assert credentials(game, "rebirth_count") == []
    assert player(game[1])["stones"] == stones
    assert pet(game[1])["energy"] == energy
    assert items(game[1]) == before_items
    # A failed first trial keeps no weekly marker, so the player may retry.
    assert play("ascension", str(target)).title == "飞升未成"


def test_failed_trial_replay_returns_the_original_reply(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=2)
    first = play("ascension", str(target), op="ascension-once")
    again = play("ascension", str(target), op="ascension-once")
    assert again.title == first.title and again.lines == first.lines
    assert credentials(game, "ascended_") == []


def test_stages_start_at_full_health_and_never_exit_early(game, play, monkeypatch):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    full = stats(game, target).hp
    starts = []

    def fake_fight(left, right, rng, elements):
        starts.append(left[0].hp)
        return Battle(0, 1, (), ({}, {}))

    monkeypatch.setattr(ascension, "fight", fake_fight)
    assert play("ascension", str(target)).title == "飞升成功"
    assert starts == [full, full, full]


def test_weekly_repeat_advances_cycles_and_unlocks_rebirth_title(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    assert play("ascension", str(target)).title == "飞升成功"
    with pytest.raises(GameError, match="本周已经完成轮回试炼"):
        play("ascension", str(target))
    second = play("ascension", str(target), now=NOW + WEEK)
    assert second.title == "轮回试炼完成"
    assert "周目：2" in second.text()
    third = play("ascension", str(target), now=NOW + 2 * WEEK)
    assert third.title == "轮回试炼完成"
    assert "周目：3" in third.text()
    assert "轮回行者" in third.text()
    assert "当前称号：轮回行者" in play("titles", now=NOW + 2 * WEEK).text()


def test_ascension_and_cycles_persist_across_restart(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    play("ascension", str(target))
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    reply = restarted.execute("u1", "ascension", "", "restart-read", NOW)
    assert "已飞升 1 只" in reply.text()
    with reopened.connect() as conn:
        assert Repository(conn).pet(target).ascended is True


def test_archiving_and_restoring_keeps_the_ascended_mark(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    second = add_pet(game)
    play("ascension", str(target))
    play("switch", str(second))
    play("pet_archive", str(target))
    play("pet_restore", str(target))
    with game[1].connect() as conn:
        assert Repository(conn).pet(target).ascended is True
    assert stats(game, target).hp > 0


def test_fifth_slot_only_opens_for_an_ascended_pet(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    second = add_pet(game)
    skills = ("meditation", "pure_breath", "wind_slash", "wood_heal", "vine_lash")
    for pet_id in (target, second):
        for skill_id in skills:
            sql(
                game[1],
                "INSERT INTO learned_skills(pet_id, skill_id, equipped) VALUES (?, ?, 0)",
                (pet_id, skill_id),
            )
    # The base rule still stops an unascended pet at two carried skills.
    play("switch", str(second))
    with pytest.raises(GameError, match="技能位已满"):
        for name in ("凝神术", "清心灵息", "风刃术"):
            play("equip_skill", name)
    play("switch", str(target))
    assert "携带上限：2 个" in play("skills").text()
    assert play("ascension", str(target)).title == "飞升成功"
    assert "携带上限：5 个" in play("skills").text()
    for name in ("凝神术", "清心灵息", "风刃术"):
        play("equip_skill", name)
    assert sql(
        game[1], "SELECT COUNT(*) AS n FROM learned_skills WHERE pet_id=? AND equipped=1", (target,)
    )[0]["n"] == 3


def test_battle_snapshot_marks_the_ascended_pet(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    play("ascension", str(target))
    with game[1].connect() as conn:
        ctx = Context(
            Repository(conn), game[0].content, game[0].config, game[0].rng,
            "u1", NOW, "snapshot-op",
        )
        ally = combatant(ctx, "u1", pet_id=target)
        enemy = enemy_fighter(ctx.content.enemies["wood_guard"], ctx.content.skills)
        capture = capture_snapshot(ctx, ([ally], [enemy]), (["u1"], []))
    member = capture.snapshot["teams"][0]["members"][0]
    assert member["ascended"] is True
    assert "飞升" in _member_text(member)


def test_catalog_lists_states_and_row_links(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    page = play("ascension")
    assert page.title == "灵宠飞升 1/1"
    assert "轮回：0 周目 · 已飞升 0 只" in page.text()
    assert f"编号 {target}：青鸾 · 渡劫 10层 · 可挑战飞升" in page.text()
    assert [link.command for link in page.inline_commands] == [f"灵宠飞升 {target}"]
    play("ascension", str(target))
    page = play("ascension")
    assert "已飞升 1 只" in page.text()
    assert "本周轮回试炼已挑战" in page.text()
    assert page.inline_commands == ()


def test_native_payload_keeps_buttons_and_links_separate(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    reply = play("ascension")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in reply.inline_commands}
    assert buttons == set(reply.commands)
    assert buttons & links == set()
    assert links == {f"灵宠飞升 {target}"}
    trial = play("ascension", str(target))
    _, trial_message = _qq_segments(trial, Config(spirit_pet_qq_mode="native"))
    trial_buttons = {
        button.action.data.removeprefix("/")
        for segment in trial_message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert trial_buttons == set(trial.commands)
    assert trial.inline_commands == ()


def test_help_and_objectives_expose_the_trial(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    assert "灵宠飞升" in play("help", "成长").text()
    objectives = play("objectives")
    line = next(text for text in objectives.lines if text.startswith("飞升："))
    assert line == "飞升：已飞升 0 只 · 轮回 0 周目 · 可挑战：青鸾"
    link = next(link for link in objectives.inline_commands if link.command == "灵宠飞升")
    assert objectives.lines[link.line] == line
    play("ascension", str(target))
    assert "飞升：已飞升 1 只 · 轮回 1 周目" in play("objectives").text()

def test_cycles_require_the_whole_roster_to_ascend(game, play):
    account(play)
    first = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    second = maxed(game, add_pet(game), bloodline=4)
    first_reply = play("ascension", str(first))
    assert first_reply.title == "飞升成功"
    assert "队伍尚有伙伴未飞升" in first_reply.text()
    assert credentials(game, "rebirth_count") == []
    second_reply = play("ascension", str(second))
    assert second_reply.title == "飞升成功"
    assert "周目：1" in second_reply.text()
    assert credentials(game, "rebirth_count") == [{"quest_id": "rebirth_count", "progress": 1}]


def test_successful_trial_replay_does_not_double_ascend(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    first = play("ascension", str(target), op="ascend-once")
    again = play("ascension", str(target), op="ascend-once")
    assert again.title == first.title and again.lines == first.lines
    assert len(credentials(game, "ascended_")) == 1
    assert credentials(game, "rebirth_count") == [{"quest_id": "rebirth_count", "progress": 1}]


def test_archived_pet_cannot_start_the_trial(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    play("switch", str(add_pet(game)))
    play("pet_archive", str(target))
    with pytest.raises(GameError, match="已封存，请先复原后再飞升"):
        play("ascension", str(target))


def test_ascended_pet_has_no_downgrade_or_reset_path(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    play("ascension", str(target))
    with pytest.raises(GameError, match="已达当前最高境界十层"):
        play("breakthrough", str(target))
    row = pet(game[1])
    assert (row["realm"], row["layer"]) == (6, 10)

def test_persisted_battle_report_shows_the_ascended_mark(game, play):
    account(play)
    target = maxed(game, pet(game[1])["pet_id"], bloodline=4)
    play("ascension", str(target))
    assert play("challenge", "青岚林").title == "秘境获胜"
    detail = play("battle_reports", "查看 1")
    assert "飞升" in detail.text()
