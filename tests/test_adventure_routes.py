import sqlite3

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql


def test_route_catalog_shows_choices_and_reward_ranges_without_spending_resources(game, play):
    play("adopt", "青鸾")
    before_player, before_pet = player(game[1]), pet(game[1])

    reply = play("explore")

    assert reply.title == "山海历练路线"
    assert {"灵泉修行", "星谷采集", "古洞寻珍"} <= set(
        line.split("：", 1)[0] for line in reply.lines if "：" in line
    )
    assert {"赤霞寻脉", "归墟拾遗", "太虚巡界", "劫云问道"} <= set(
        line.split("：", 1)[0] for line in reply.lines if "：" in line
    )
    assert any("锻灵矿" in line for line in reply.lines)
    assert any("血脉精华" in line for line in reply.lines)
    assert any("启灵起" in line for line in reply.lines)
    assert any("凝气起" in line for line in reply.lines)
    assert any("筑基起" in line for line in reply.lines)
    assert any("金丹起" in line for line in reply.lines)
    assert any("元婴起" in line for line in reply.lines)
    assert any("化神起" in line for line in reply.lines)
    assert any("渡劫起" in line for line in reply.lines)
    assert "奇遇概率：灵泉寻踪 55% · 古阵修复 45%" in reply.lines
    assert "奇遇概率：灵草采集 56% · 坠星采矿 44%" in reply.lines
    assert "奇遇概率：洞府幻阵 50% · 封印宝匣 50%" in reply.lines
    assert "奇遇概率：焚心炼魄 60% · 金脉采矿 40%" in reply.lines
    assert "奇遇概率：归墟拾脉 50% · 青冥守镜 50%" in reply.lines
    assert "奇遇概率：太虚观剑 58% · 幽庭渡魂 42%" in reply.lines
    assert "奇遇概率：劫海采雷 40% · 天门问道 60%" in reply.lines
    assert reply.commands[:3] == (
        "灵宠历练 灵泉修行", "灵宠历练 星谷采集", "灵宠历练 古洞寻珍",
    )
    assert player(game[1]) == before_player
    assert pet(game[1]) == before_pet
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='explore_once'")


def test_selected_route_limits_encounters_and_replay_does_not_grant_twice(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET realm=1")
    game[0].rng.random = lambda: 0.99

    reply = play("explore", "星谷采集", op="star-valley-explore")

    assert reply.title == "山海历练 · 星谷采集"
    assert "奇遇：坠星采矿" in reply.text()
    assert "星落谷的坠星痕迹" in reply.text()
    assert "古树" not in reply.text()
    assert pet(game[1])["energy"] == 75
    assert player(game[1])["last_explore"] == 1_800_000_000
    assert items(game[1])["forge_ore"] == 1
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='explore_once'")[0]["progress"] == 1

    assert play("explore", "星谷采集", op="star-valley-explore") == reply
    assert pet(game[1])["energy"] == 75
    assert items(game[1])["forge_ore"] == 1


def test_route_realm_gate_prevents_early_rare_material_farming(game, play):
    play("adopt", "青鸾")
    before_player, before_pet = player(game[1]), pet(game[1])

    with pytest.raises(GameError, match="古洞寻珍需要筑基境界"):
        play("explore", "古洞寻珍")

    assert player(game[1]) == before_player
    assert pet(game[1]) == before_pet
    assert items(game[1]) == {"spirit_food": 3}
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='explore_once'")

    sql(game[1], "UPDATE pets SET realm=2")
    assert play("explore", "古洞寻珍").title == "山海历练 · 古洞寻珍"


def test_unknown_route_does_not_change_player_state(game, play):
    play("adopt", "青鸾")
    before_player, before_pet = player(game[1]), pet(game[1])

    with pytest.raises(GameError, match="未找到"):
        play("explore", "不存在的路线")

    assert player(game[1]) == before_player
    assert pet(game[1]) == before_pet
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='explore_once'")


@pytest.mark.parametrize(("realm", "route", "encounter", "item_id"), [
    (3, "赤霞寻脉", "金脉采矿", "forge_ore"),
    (4, "归墟拾遗", "青冥守镜", "forge_ore"),
    (5, "太虚巡界", "幽庭渡魂", "bloodline_essence"),
    (6, "劫云问道", "天门问道", "bloodline_essence"),
])
def test_high_realm_routes_gate_and_settle_rewards(game, play, realm, route, encounter, item_id):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET realm=?, energy=100, exp=0", (realm - 1,))
    before_player, before_pet = player(game[1]), pet(game[1])

    with pytest.raises(GameError, match=f"{route}需要"):
        play("explore", route)

    assert player(game[1]) == before_player
    assert pet(game[1]) == before_pet

    sql(game[1], "UPDATE pets SET realm=?, energy=100, exp=0", (realm,))
    game[0].rng.random = lambda: 0.99
    reply = play("explore", route)

    assert reply.title == f"山海历练 · {route}"
    assert f"奇遇：{encounter}" in reply.text()
    assert pet(game[1])["exp"] > 0
    assert items(game[1])[item_id] > 0


def test_adventure_codex_hides_undiscovered_text_and_records_first_discovery(game, play):
    now = 1_800_000_000
    play("adopt", "青鸾", now=now)
    before = play("adventure_codex", now=now)
    assert "奇闻发现：0/14" in before.text()
    assert "未遇 · 灵泉寻踪：尚未触发。" in before.text()
    assert "踏入青岚秘境，在古树下寻得一处灵泉。" not in before.text()
    assert "灵宠奇闻 2" in before.commands

    game[0].rng.random = lambda: 0.0
    result = play("explore", "灵泉修行", now=now, op="discover-spring")
    assert "新奇闻已收入灵宠奇闻。" in result.lines
    assert play("explore", "不存在的路线", now=now, op="discover-spring") == result
    assert sql(game[1], "SELECT encounter_id FROM adventure_discoveries WHERE user_id='u1'") == [
        {"encounter_id": "spring"},
    ]

    after = play("adventure_codex", now=now + 1)
    assert "奇闻发现：1/14" in after.text()
    assert "已遇 · 灵泉寻踪：踏入青岚秘境，在古树下寻得一处灵泉。" in after.text()
    assert "踏入青岚秘境，在古树下寻得一处灵泉。" not in play(
        "adventure_codex", user="u2", now=now + 1,
    ).text()


def test_adventure_discovery_rolls_back_with_a_failed_reward(game, play):
    now = 1_800_000_000
    play("adopt", "青鸾", now=now)
    sql(game[1], "UPDATE pets SET realm=1, energy=100")
    game[0].rng.random = lambda: 0.99
    with game[1].connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_exploration_reward BEFORE INSERT ON inventory "
            "WHEN NEW.item_id='forge_ore' BEGIN SELECT RAISE(ABORT,'injected exploration failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected exploration failure"):
        play("explore", "星谷采集", now=now, op="rollback-exploration-discovery")

    assert not sql(game[1], "SELECT * FROM adventure_discoveries")
    assert pet(game[1])["energy"] == 100
    assert player(game[1])["last_explore"] is None
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id='explore_once'")


def test_all_adventure_discoveries_unlock_and_claim_codex_milestones(game, play):
    now = 1_800_000_000
    play("adopt", "青鸾", now=now)
    sql(game[1], "UPDATE pets SET realm=6, energy=100")
    encounter_index = 0
    intermediate_milestones = {5: "奇闻初见", 10: "博闻山海"}
    for route in game[0].content.exploration_routes.values():
        for index, encounter_id in enumerate(route.encounters):
            sql(game[1], "UPDATE pets SET energy=100")
            game[0].rng.random = lambda value=index: 0.0 if value == 0 else 0.99
            play(
                "explore", route.name, now=now + encounter_index * 901,
                op=f"discover-{encounter_id}",
            )
            encounter_index += 1
            if encounter_index in intermediate_milestones:
                name = intermediate_milestones[encounter_index]
                assert sql(game[1], "SELECT COUNT(*) AS amount FROM adventure_discoveries WHERE user_id='u1'") == [
                    {"amount": encounter_index},
                ]
                play(
                    "achievement_claim", name,
                    now=now + encounter_index * 901 + 1,
                    op=f"claim-{name}",
                )

    assert sql(game[1], "SELECT COUNT(*) AS amount FROM adventure_discoveries WHERE user_id='u1'") == [
        {"amount": 14},
    ]
    assert "奇闻发现：14/14" in play("adventure_codex", "2", now=now + 20_000).text()
    play("achievement_claim", "尽览奇闻", now=now + 20_001, op="claim-尽览奇闻")
    assert sql(game[1], "SELECT achievement_id FROM achievement_claims WHERE user_id='u1' ORDER BY achievement_id") == [
        {"achievement_id": "adventure_all"},
        {"achievement_id": "adventure_five"},
        {"achievement_id": "adventure_ten"},
    ]


def test_adventure_rank_orders_unique_discoveries_and_hides_user_ids(game, play):
    now = 1_800_000_000
    empty = play("adventure_rank", user="u4", now=now)
    assert empty.lines == ("尚无修士发现历练奇闻。",)
    for user_id, species in (("u1", "青鸾"), ("u2", "玄狐"), ("u3", "白泽")):
        play("adopt", species, user=user_id, now=now)
    with game[1].connect() as conn:
        conn.executemany(
            "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)",
            (
                ("u1", "spring", 1),
                ("u2", "spring", 2), ("u2", "valley", 20),
                ("u3", "spring", 3), ("u3", "mountain", 10),
                ("u3", "removed_event", 999),
            ),
        )

    reply = play("adventure_rank", now=now + 1)
    names = [player(game[1], user_id)["dao_name"] for user_id in ("u2", "u3", "u1")]

    assert reply.title == "山海奇闻榜"
    assert [line.split(". ", 1)[1].split(" · ", 1)[0] for line in reply.lines] == names
    assert "奇闻 2/14" in reply.lines[0]
    assert "奇闻 1/14" in reply.lines[2]
    assert all(user_id not in reply.text() for user_id in ("u1", "u2", "u3"))
