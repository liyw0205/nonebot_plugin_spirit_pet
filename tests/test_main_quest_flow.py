import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import journey
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, player, sql
from .test_targeted_care import snapshot
from .test_targeted_training import add_pet


def current_step(store, order):
    for previous in range(1, order):
        sql(store, "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
            (f"main_{previous:02d}",))


def test_main_rewards_lead_to_recruit_training_and_numbered_breakthrough(game, play):
    play("adopt", "青鸾")
    first = play("main_quest_claim", "初结灵契")
    summon = next(link.command for link in first.inline_commands if link.command == "灵宠召唤 1")
    play(*handlers._parse(summon))
    second = play("main_quest_claim", "双灵相伴")
    assert "吐纳有成" in second.text()
    assert any(link.command == "灵宠修炼 1" for link in second.inline_commands)
    now = 1_800_000_000
    while pet(game[1])["layer"] < 3:
        page = play("main_quests", now=now)
        command = next(link.command for link in page.inline_commands
                       if link.command.startswith(("灵宠修炼 ", "灵宠突破 ")))
        reply = play(*handlers._parse(command), now=now)
        assert "灵宠主线" in reply.commands
        assert any(link.command == "灵宠整备 1" for link in reply.inline_commands)
        now += 301
        assert now < 1_800_010_000
    third = play("main_quest_claim", "吐纳有成", now=now)
    assert "灵血初显" in third.text()
    assert any(link.command == "灵宠整备 1" for link in third.inline_commands)
    assert player(game[1])["stones"] == 420
    assert sql(game[1], "SELECT layer,exp FROM pets WHERE pet_id=2") == [{"layer": 1, "exp": 0}]
    assert sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'main_%' ORDER BY quest_id") == [
        {"quest_id": "main_01"}, {"quest_id": "main_02"}, {"quest_id": "main_03"},
    ]


@pytest.mark.parametrize("order", range(2, 21))
def test_every_current_main_step_has_registered_actions_without_mutating_progress(game, play, order):
    play("adopt")
    current_step(game[1], order)
    before = snapshot(game[1])
    page = play("main_quests", str((order - 1) // 5 + 1))
    assert page.inline_commands
    assert all(handlers._parse(link.command) is not None for link in page.inline_commands)
    assert all(not link.command.startswith("灵宠主线领奖") for link in page.inline_commands)
    assert len(page.inline_commands) == len({link.command for link in page.inline_commands})
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("argument", ["0", "-1", "5", "many", "1 2", "9" * 5000])
def test_main_pages_reject_bad_parameters_without_creating_or_changing_state(game, play, argument):
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("main_quests", argument)
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("state,reason,command", [
    ("inactive", "尚未出战", "灵宠修炼 1"),
    ("archived", "已封存", "灵宠复原 1"),
    ("trip", "派遣", "灵宠行程"),
    ("cooldown", "调息", "灵宠任务"),
    ("tired", "精力不足", "灵宠喂养 1"),
    ("stones", "灵石不足", "灵宠任务"),
])
def test_main_growth_guidance_handles_prerequisites_without_switching_or_spending(game, play, state, reason, command):
    play("adopt")
    current_step(game[1], 3)
    if state == "inactive":
        sql(game[1], "DELETE FROM active_pet_slots")
        sql(game[1], "UPDATE players SET active_pet_id=NULL")
    elif state == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    elif state == "trip":
        play("expedition_start", "采灵药")
    elif state == "cooldown":
        sql(game[1], "UPDATE players SET last_train=1800000000")
    elif state == "tired":
        sql(game[1], "UPDATE pets SET energy=0")
    else:
        sql(game[1], "UPDATE players SET stones=0")
        sql(game[1], "UPDATE pets SET exp=100")
    before = snapshot(game[1])
    page = play("main_quests")
    assert reason in page.text()
    assert command in [link.command for link in page.inline_commands]
    assert snapshot(game[1]) == before


def test_main_growth_numbered_breakthrough_survives_switching_leader(game, play):
    play("adopt")
    current_step(game[1], 3)
    sql(game[1], "UPDATE pets SET exp=100")
    target_id = add_pet(game[1])
    page = play("main_quests")
    command = next(link.command for link in page.inline_commands if link.command == "灵宠突破 1")
    play("switch", str(target_id))
    reply = play(*handlers._parse(command), op="main-numbered-breakthrough")
    assert any(link.command == "灵宠整备 1" for link in reply.inline_commands)
    assert play(*handlers._parse(command), op="main-numbered-breakthrough") == reply
    assert sql(game[1], "SELECT layer,exp FROM pets ORDER BY pet_id") == [
        {"layer": 2, "exp": 70}, {"layer": 1, "exp": 0},
    ]
    assert player(game[1])["active_pet_id"] == target_id
    assert player(game[1])["stones"] == 90


@pytest.mark.parametrize("blocked", ["archived", "trip", "exp", "stones"])
def test_stale_main_growth_action_rechecks_target_and_rolls_back(game, play, blocked):
    play("adopt")
    current_step(game[1], 3)
    sql(game[1], "UPDATE pets SET exp=100")
    command = next(link.command for link in play("main_quests").inline_commands if link.command == "灵宠突破 1")
    if blocked == "archived":
        sql(game[1], "UPDATE pets SET archived=1")
    elif blocked == "trip":
        play("expedition_start", "采灵药")
    elif blocked == "exp":
        sql(game[1], "UPDATE pets SET exp=0")
    else:
        sql(game[1], "UPDATE players SET stones=0")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play(*handlers._parse(command))
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("action,arg", [("main_quest_claim", "初结灵契"), ("breakthrough", "1"), ("evolve", "1")])
def test_main_growth_settlement_write_failure_rolls_back_and_retries(game, play, monkeypatch, action, arg):
    play("adopt")
    sql(game[1], "UPDATE pets SET exp=100")
    sql(game[1], "UPDATE players SET stones=1000")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','bloodline_essence',3)")
    before = snapshot(game[1])
    original = Repository.save

    def fail(repo):
        original(repo)
        raise RuntimeError("injected main settlement failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "save", fail)
        with pytest.raises(RuntimeError, match="injected main settlement failure"):
            play(action, arg, op="main-retry")
    assert snapshot(game[1]) == before
    result = play(action, arg, op="main-retry")
    assert play(action, arg, op="main-retry") == result
    assert snapshot(game[1]) != before


def test_failed_evolution_keeps_numbered_result_and_exact_consumption(game, play, monkeypatch):
    play("adopt")
    target_id = add_pet(game[1])
    sql(game[1], "UPDATE pets SET exp=100 WHERE pet_id=?", (target_id,))
    sql(game[1], "UPDATE players SET stones=200")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','bloodline_essence',3)")
    monkeypatch.setattr(game[0].rng, "random", lambda: 1.0)
    reply = play("evolve", str(target_id), op="failed-evolution")
    assert reply.title == "进化未成"
    assert reply.commands == ("灵宠主线", "灵宠任务")
    assert reply.inline_commands[0].command == f"灵宠整备 {target_id}"
    assert sql(game[1], "SELECT exp,bloodline FROM pets ORDER BY pet_id") == [
        {"exp": 0, "bloodline": 0}, {"exp": 0, "bloodline": 0},
    ]
    assert player(game[1])["stones"] == 0
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='bloodline_essence'") == [{"quantity": 0}]
    assert play("evolve", str(target_id), op="failed-evolution") == reply


def test_completed_main_chain_leads_to_existing_long_term_play(game, play):
    play("adopt")
    current_step(game[1], 16)
    sql(game[1], "UPDATE pets SET realm=6")
    reply = play("main_quest_claim", "渡劫问鼎")
    assert "行纪三章" in reply.text()
    assert any(link.command == "灵宠行纪" for link in reply.inline_commands)
    page = play("main_quests", "4")
    assert "17. 行纪三章 · 进行中 · 0/3" in page.text()
    assert "20. 十族入册 · 未解锁" in page.text()


def test_long_term_main_steps_use_permanent_metrics_and_replay_claim(game, play):
    play("adopt")
    current_step(game[1], 17)
    for index in range(1, 4):
        sql(game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 0, 1)",
            (journey.claim_id(f"journey_{index:02d}"),))
    page = play("main_quests", "4")
    assert "17. 行纪三章 · 可领奖 · 3/3" in page.text()
    claim = next(link.command for link in page.inline_commands if link.command == "灵宠主线领奖 行纪三章")
    first = play(*handlers._parse(claim), op="main-long-term")
    stones_after = player(game[1])["stones"]
    assert "首通留名" in first.text()
    assert any(link.command == "灵宠秘境首通" for link in first.inline_commands)
    assert play(*handlers._parse(claim), op="main-long-term") == first
    assert player(game[1])["stones"] == stones_after
    assert sql(game[1], "SELECT claimed FROM quest_progress WHERE quest_id='main_17'") == [{"claimed": 1}]


def test_actual_journey_actions_unlock_main_continuation_and_permanent_replay(game, play):
    from .test_explore_ambush import skip_ambush

    play("adopt", "青鸾")
    current_step(game[1], 17)
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    play("challenge", "青岚林")
    first = play("journey_claim", "灵泉初醒", op="journey-start")
    explore = next(link.command for link in first.inline_commands if link.command.startswith("灵宠历练 "))
    skip_ambush(game)
    play(*handlers._parse(explore))
    play("journey_claim", "灵泉寻踪")
    for step in (1, 2):
        play("challenge", "月影谷", now=1_800_000_000 + step * 3600)
    play("journey_claim", "月影双行", now=1_800_007_200)
    reply = play("main_quest_claim", "行纪三章", now=1_800_007_200, op="journey-main")
    assert "首通留名" in reply.text()
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    assert play("main_quest_claim", "行纪三章", op="journey-main", now=1_800_086_400) == reply
    assert play("journey_claim", "灵泉初醒", op="journey-start", now=1_800_086_400) == first
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("order", [18, 19, 20])
def test_long_term_main_thresholds_and_once_only_rewards(game, play, order):
    play("adopt", "青鸾")
    current_step(game[1], order)
    quest = game[0].content.main_quests[f"main_{order}"]
    with pytest.raises(GameError, match="尚未达成"):
        play("main_quest_claim", quest.name)
    if order == 18:
        for dungeon in list(game[0].content.dungeons.values())[:quest.target]:
            sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,1,1)",
                (f"first_clear_{dungeon.id}",))
    elif order == 19:
        for index, achievement in enumerate(list(game[0].content.achievements.values())[:quest.target]):
            sql(game[1], "INSERT INTO achievement_claims(user_id,achievement_id,operation_id,claimed_at,reward_snapshot,reply) "
                "VALUES ('u1',?,?,1800000000,'{}','{}')", (achievement.id, f"seed-achievement-{index}"))
    else:
        for species in [key for key in game[0].content.species if key != "qingluan"][:quest.target - 1]:
            add_pet(game[1], species_id=species, name=species)
    before = player(game[1])["stones"]
    reply = play("main_quest_claim", quest.name)
    assert player(game[1])["stones"] == before + quest.reward.stones.minimum
    with pytest.raises(GameError, match="已领取"):
        play("main_quest_claim", quest.name)
    if order == 20:
        assert "主线已全部完成" in reply.text()
        assert reply.commands == ("灵宠周常", "灵宠目标")


def test_main_team_goal_connects_to_real_preparation_battle_and_claim(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    current_step(game[1], 15)
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    page = play("main_quests", "3")
    command = next(link.command for link in page.inline_commands if link.command == "灵宠组队")
    play(*handlers._parse(command))
    play("team_join", "UID 10000", user="u2")
    play("team_accept", "UID 10001")
    for user in ("u1", "u2"):
        play("team_ready", user=user)
    page = play("main_quests", "3")
    command = next(link.command for link in page.inline_commands if link.command == "灵宠队伍 秘境")
    catalog = play(*handlers._parse(command))
    fight = next(link.command for link in catalog.inline_commands if link.command == "灵宠组队挑战 上古灵殿")
    assert play(*handlers._parse(fight)).title == "秘境获胜"
    page = play("main_quests", "3")
    claim = next(link.command for link in page.inline_commands if link.command == "灵宠主线领奖 并肩同行")
    reply = play(*handlers._parse(claim), op="main-team-claim")
    assert "并肩同行已完成" in reply.text()
    assert any(link.command == "灵宠主线领奖 渡劫问鼎" for link in reply.inline_commands)
    before = snapshot(game[1])
    assert play(*handlers._parse(claim), op="main-team-claim") == reply
    assert snapshot(game[1]) == before


def test_main_evolution_guidance_points_to_real_missing_material_source(game, play):
    play("adopt")
    current_step(game[1], 4)
    sql(game[1], "UPDATE pets SET exp=100")
    sql(game[1], "UPDATE players SET stones=200")
    page = play("main_quests")
    assert "血脉精华不足" in page.text()
    source = next(link.command for link in page.inline_commands if link.label == "寻找材料")
    details = play(*handlers._parse(source))
    assert "血脉精华" in details.text()
    assert any(link.command == "灵宠整备 1" for link in page.inline_commands)
    assert pet(game[1])["exp"] == 100 and player(game[1])["stones"] == 200


@pytest.mark.parametrize("prefix", ["", "/", "!"])
def test_main_progress_qq_guidance_and_navigation_have_no_duplicate_payloads(game, play, prefix):
    play("adopt")
    current_step(game[1], 3)
    reply = play("main_quests", "2")
    plain, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix))
    markdown = native["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    payloads = [button.action.data for segment in native["keyboard"]
                for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert set(links) == {prefix + link.command for link in reply.inline_commands}
    assert set(payloads) == {prefix + command for command in reply.commands}
    assert len(payloads) <= 4
    assert len(links + payloads) == len(set(links + payloads))
    assert f"积攒修为（{prefix}灵宠修炼 1）" in plain
    assert "mqqapi://" not in plain
