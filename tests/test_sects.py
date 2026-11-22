"""Spirit sects: join/switch, daily practice, contribution ranks, rewards and passive."""

import json
import re
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.domain.sect_content import Sect
from nonebot_plugin_spirit_pet.gameplay import defense
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, player, sql

NOW = 1_800_000_000
DAY = 86400


def sects(game):
    return sorted(game[0].content.sects.values(), key=lambda sect: sect.id)


def stats(game, user="u1"):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, user, NOW, "sect-stats")
        return combatant(ctx)


def defense_stats(game, owner):
    service, store = game
    with closing(store.connect()) as conn:
        ctx = Context(Repository(conn), service.content, service.config, service.rng, "u1", NOW, "sect-defense")
        return defense.fighters(ctx, owner)[0]


def seed_contribution(game, sect_id, points, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, ?, 1)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=excluded.progress",
        (user, f"sect_contrib_{sect_id}", points),
    )


def contribution(game, sect_id, user="u1"):
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, f"sect_contrib_{sect_id}"),
    )
    return rows[0]["progress"] if rows else 0


def test_content_defines_four_eight_rank_sects_and_preserves_legacy_ranks(game):
    entries = sects(game)
    assert [sect.id for sect in entries] == ["dan_ding", "jian_ge", "xuan_men", "yu_shou"]
    assert {sect.id: sect.stat for sect in entries} == {
        "dan_ding": "defense", "jian_ge": "attack", "xuan_men": "hp", "yu_shou": "speed",
    }
    for sect in entries:
        assert [entry.rank for entry in sect.ranks] == list(range(1, 9))
        assert [entry.contribution for entry in sect.ranks[:5]] == [0, 60, 160, 320, 560]
        assert [entry.rate for entry in sect.ranks[:5]] == [0.02, 0.04, 0.06, 0.08, 0.10]
        assert [entry.stones for entry in sect.ranks[:5]] == [120, 240, 480, 900, 1600]
        assert [entry.contribution for entry in sect.ranks[5:]] == [900, 1400, 2000]
        assert [entry.rate for entry in sect.ranks[5:]] == [0.12, 0.14, 0.16]
        assert all(entry.stones > 0 and entry.items for entry in sect.ranks)
        assert all(item in game[0].content.items for entry in sect.ranks for item in entry.items)
    assert [entry.items["forge_ore"] for entry in game[0].content.sects["jian_ge"].ranks[:5]] == [1, 2, 3, 5, 8]
    assert [entry.items["spirit_food"] for entry in game[0].content.sects["xuan_men"].ranks[:5]] == [2, 4, 6, 8, 12]
    assert [entry.items["exp_pill"] for entry in game[0].content.sects["dan_ding"].ranks[:5]] == [1, 2, 3, 4, 6]
    assert [entry.items["bloodline_essence"] for entry in game[0].content.sects["yu_shou"].ranks[:5]] == [1, 2, 3, 4, 6]


def test_content_validation_rejects_broken_ladders():
    base = {
        "id": "jian_ge", "name": "剑阁", "description": "测试", "stat": "attack",
        "ranks": [
            {"rank": 1, "contribution": 0, "rate": 0.02, "stones": 10, "items": {"forge_ore": 1}},
            {"rank": 2, "contribution": 60, "rate": 0.04, "stones": 20},
        ],
    }
    assert Sect.model_validate(base).max_rank == 2
    with pytest.raises(ValidationError, match="zero contribution"):
        Sect.model_validate({**base, "ranks": [{**base["ranks"][0], "contribution": 10}, base["ranks"][1]]})
    with pytest.raises(ValidationError, match="must ascend"):
        Sect.model_validate({**base, "ranks": [base["ranks"][0], {**base["ranks"][1], "contribution": 0}]})
    with pytest.raises(ValidationError, match="must ascend"):
        Sect.model_validate({**base, "ranks": [base["ranks"][0], {**base["ranks"][1], "rate": 0.01}]})


@pytest.fixture
def sect_content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit_sect_content(content_dir, change):
    path = content_dir / "sects.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_catalog_rejects_missing_sect_or_rank(sect_content_dir):
    edit_sect_content(sect_content_dir, lambda data: data.pop())
    with pytest.raises(ValueError, match="four supported sects"):
        Catalog.load(sect_content_dir)


def test_catalog_rejects_missing_rank(sect_content_dir):
    edit_sect_content(sect_content_dir, lambda data: data[0]["ranks"].pop())
    with pytest.raises(ValueError, match="ranks 1 through 8"):
        Catalog.load(sect_content_dir)


def test_catalog_rejects_duplicate_rank_and_wrong_true_disciple_threshold(sect_content_dir):
    edit_sect_content(sect_content_dir, lambda data: data[0]["ranks"][6].update({"rank": 6}))
    with pytest.raises(ValidationError, match="contiguous"):
        Catalog.load(sect_content_dir)


def test_catalog_rejects_wrong_true_disciple_threshold(sect_content_dir):
    edit_sect_content(
        sect_content_dir,
        lambda data: data[0]["ranks"][7].update({"contribution": 1999}),
    )
    with pytest.raises(ValueError, match="900/1400/2000"):
        Catalog.load(sect_content_dir)


def test_catalog_rejects_true_disciple_passive_above_cap(sect_content_dir):
    edit_sect_content(sect_content_dir, lambda data: data[0]["ranks"][7].update({"rate": 0.18}))
    with pytest.raises(ValidationError, match="0.16"):
        Catalog.load(sect_content_dir)


def test_catalog_rejects_changed_sect_core_passive(sect_content_dir):
    edit_sect_content(sect_content_dir, lambda data: data[0].update({"stat": "defense"}))
    with pytest.raises(ValueError, match="retain its core passive"):
        Catalog.load(sect_content_dir)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda data: data[0]["ranks"][5].update({"stones": 0, "items": {}}), "must not be empty"),
        (lambda data: data[0]["ranks"][5].update({"stones": 10001}), "exceeds content limits"),
        (lambda data: data[0]["ranks"][5].update({"items": {"forge_ore": 21}}), "exceeds content limits"),
        (lambda data: data[0]["ranks"][5].update({"items": {"wind_feather": 1}}), "consumables or materials"),
        (lambda data: data[0]["ranks"][5].update({"items": {"unknown_item": 1}}), "unknown sect rank items"),
    ],
)
def test_catalog_rejects_invalid_true_disciple_rewards(sect_content_dir, change, message):
    edit_sect_content(sect_content_dir, change)
    with pytest.raises(ValueError, match=message):
        Catalog.load(sect_content_dir)


def test_page_without_a_pet_is_read_only(game, play):
    page = play("sect", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)


def test_a_sectless_player_sees_every_sect_and_join_entries(game, play):
    play("adopt", "青鸾")
    page = play("sect")
    assert "尚未拜入师门" in page.text()
    for name in ("剑阁", "玄门", "丹鼎门", "御兽宗"):
        assert name in page.text()
    assert {link.label for link in page.inline_commands} == {"拜入"}
    assert {link.command for link in page.inline_commands} == {
        "灵宠师门 拜入 剑阁", "灵宠师门 拜入 玄门", "灵宠师门 拜入 丹鼎门", "灵宠师门 拜入 御兽宗",
    }


def test_joining_is_free_and_starts_at_rank_one(game, play):
    play("adopt", "青鸾")
    before = player(game[1])["stones"]
    reply = play("sect", "拜入 剑阁")
    assert "已拜入剑阁" in reply.text()
    assert "首次拜入不消耗灵石" in reply.text()
    assert player(game[1])["stones"] == before
    page = play("sect")
    assert "当前：剑阁 · 1 阶 · 攻击 +2%" in page.text()
    assert "贡献 0/60" in page.text()


def test_joining_the_same_or_unknown_sect_is_refused(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    with pytest.raises(GameError, match="已在剑阁"):
        play("sect", "拜入 剑阁")
    with pytest.raises(GameError):
        play("sect", "拜入 不存在的门派")


def test_switching_costs_stones_and_keeps_both_contributions(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=2000 WHERE user_id='u1'")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 60)
    reply = play("sect", "拜入 玄门")
    assert "转投消耗灵石 500" in reply.text()
    assert player(game[1])["stones"] == 1500
    assert contribution(game, "jian_ge") == 60
    page = play("sect")
    assert "当前：玄门 · 1 阶 · 气血 +2%" in page.text()


def test_switching_without_enough_stones_is_refused(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=100 WHERE user_id='u1'")
    play("sect", "拜入 剑阁")
    with pytest.raises(GameError, match="灵石"):
        play("sect", "拜入 玄门")
    assert "当前：剑阁" in play("sect").text()


def test_practice_pays_contribution_and_exp_once_per_day(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    energy = pet(game[1])["energy"]
    exp = pet(game[1])["exp"]
    reply = play("sect", "修行")
    assert "贡献 +10" in reply.text() and "修为 +30" in reply.text()
    assert contribution(game, "jian_ge") == 10
    assert pet(game[1])["energy"] == energy - 20
    assert pet(game[1])["exp"] == exp + 30
    with pytest.raises(GameError, match="今日已修行"):
        play("sect", "修行")
    assert contribution(game, "jian_ge") == 10

    sql(game[1], "UPDATE pets SET energy=100, energy_updated=?", (NOW + DAY,))
    reply = play("sect", "修行", now=NOW + DAY)
    assert "贡献 +10" in reply.text()
    assert contribution(game, "jian_ge") == 20


def test_practice_needs_an_idle_pet_with_energy(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    sql(game[1], "UPDATE pets SET energy=10, energy_updated=? WHERE user_id='u1'", (NOW,))
    with pytest.raises(GameError, match="精力不足"):
        play("sect", "修行")
    assert contribution(game, "jian_ge") == 0
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
    play("expedition_start", "采灵药")
    with pytest.raises(GameError, match="外出派遣"):
        play("sect", "修行")
    assert contribution(game, "jian_ge") == 0


def test_practice_is_refused_without_a_sect(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未拜入师门"):
        play("sect", "修行")


def test_contribution_crossing_a_threshold_raises_the_rank(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 50)
    reply = play("sect", "修行")
    assert "阶位提升：1 阶 → 2 阶" in reply.text()
    page = play("sect")
    assert "剑阁 · 2 阶 · 攻击 +4%" in page.text()
    assert "贡献 60/160" in page.text()


def test_claim_pays_each_reached_rank_once(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    before = player(game[1])["stones"]
    first = play("sect", "领赏")
    assert "1 阶：灵石 +120" in first.text()
    assert player(game[1])["stones"] == before + 120
    assert items(game[1])["forge_ore"] == 1
    with pytest.raises(GameError, match="暂无可领"):
        play("sect", "领赏")

    seed_contribution(game, "jian_ge", 60)
    second = play("sect", "领赏")
    assert "2 阶：灵石 +240" in second.text()
    assert "1 阶：" not in second.text()
    assert player(game[1])["stones"] == before + 360
    assert items(game[1])["forge_ore"] == 3


@pytest.mark.parametrize(
    ("sect_id", "sect_name", "stat", "stat_label"),
    [
        ("jian_ge", "剑阁", "attack", "攻击"),
        ("xuan_men", "玄门", "hp", "气血"),
        ("dan_ding", "丹鼎门", "defense", "防御"),
        ("yu_shou", "御兽宗", "speed", "速度"),
    ],
)
def test_all_sects_reach_true_disciple_passives_in_real_combatants(
    game, play, sect_id, sect_name, stat, stat_label,
):
    play("adopt", "青鸾")
    base = getattr(stats(game).stats, stat)
    play("sect", f"拜入 {sect_name}")
    for points, rank, rate in ((560, 5, 0.10), (900, 6, 0.12), (1400, 7, 0.14), (2000, 8, 0.16)):
        seed_contribution(game, sect_id, points)
        page = play("sect")
        assert f"当前：{sect_name} · {rank} 阶 · {stat_label} +{rate:.0%}" in page.text()
        assert f"{sect_name} {rank} 阶" in page.text()
        assert getattr(stats(game).stats, stat) == int(base * (1 + rate) + 0.5)
        assert f"师门：{sect_name} {rank} 阶" in play("objectives").text()


def test_true_disciple_claim_preserves_old_receipts_and_pays_once(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    before_stones = player(game[1])["stones"]
    seed_contribution(game, "jian_ge", 560)
    play("sect", "领赏", op="claim-old-ranks")
    seed_contribution(game, "jian_ge", 2000)
    before_items = items(game[1]).get("forge_ore", 0)
    first = play("sect", "领赏", op="claim-true-disciple")
    assert "6 阶：灵石 +2200" in first.text()
    assert "7 阶：灵石 +3000" in first.text()
    assert "8 阶：灵石 +4000" in first.text()
    assert player(game[1])["stones"] == before_stones + sum((120, 240, 480, 900, 1600, 2200, 3000, 4000))
    assert items(game[1])["forge_ore"] == before_items + 37
    assert [row["progress"] for row in sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'sect_claim_jian_ge_%' ORDER BY quest_id",
    )] == [1] * 8
    assert play("sect", "anything", op="claim-true-disciple") == first
    with pytest.raises(GameError, match="暂无可领"):
        play("sect", "领赏", op="claim-true-disciple-again")


def test_sect_home_and_objectives_show_claimable_true_disciple_without_writing_progress(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 900)
    before = sql(game[1], "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id='u1' ORDER BY quest_id")
    page = play("sect")
    objective = play("objectives")
    assert "可领阶位奖励：1、2、3、4、5、6 阶" in page.text()
    assert "6 阶真传：灵石 2200 · 锻灵矿 10" in page.text()
    assert "真传可领 6 阶" in objective.text()
    assert sql(game[1], "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id='u1' ORDER BY quest_id") == before


def test_switching_sects_keeps_high_rank_claims_with_their_original_sect(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=10000 WHERE user_id='u1'")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 900)
    play("sect", "领赏")
    seed_contribution(game, "jian_ge", 1400)
    play("sect", "拜入 玄门")
    page = play("sect")
    assert "各派贡献：丹鼎门 1 阶 贡献 0/60；剑阁 7 阶 贡献 1400/2000" in page.text()
    assert "当前：玄门 · 1 阶" in page.text()
    switched_claim = play("sect", "领赏")
    assert "玄门阶位奖励" in switched_claim.text()
    assert sql(game[1], "SELECT 1 FROM quest_progress WHERE user_id='u1' AND quest_id='sect_claim_jian_ge_7'") == []
    play("sect", "拜入 剑阁")
    assert "7 阶：灵石 +3000" in play("sect", "领赏").text()
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='sect_claim_jian_ge_6'")[0]["progress"] == 1


def test_true_disciple_progress_and_claims_survive_restart(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 2000)
    play("sect", "领赏", op="restart-true-disciple-claim")
    before = sql(game[1], "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id='u1' ORDER BY quest_id")

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "sect", "", "restart-true-disciple-page", NOW)
    assert "当前：剑阁 · 8 阶 · 攻击 +16%" in page.text()
    with pytest.raises(GameError, match="暂无可领"):
        restarted.execute("u1", "sect", "领赏", "restart-true-disciple-duplicate", NOW)
    assert sql(reopened, "SELECT quest_id, progress, claimed FROM quest_progress WHERE user_id='u1' ORDER BY quest_id") == before


def test_defense_mirror_uses_the_defended_owners_true_disciple_passive(game, play):
    play("adopt", "青鸾")
    base_u1 = stats(game, "u1").stats.attack
    play("adopt", "玄狐", user="u2")
    base_u2 = stats(game, "u2").stats.hp
    play("sect", "拜入 剑阁", user="u1")
    play("sect", "拜入 玄门", user="u2")
    seed_contribution(game, "jian_ge", 2000, user="u1")
    seed_contribution(game, "xuan_men", 2000, user="u2")

    assert defense_stats(game, "u1").stats.attack == int(base_u1 * 1.16 + 0.5)
    assert defense_stats(game, "u2").stats.hp == int(base_u2 * 1.16 + 0.5)


def test_true_disciple_claim_rolls_back_as_one_transaction_and_retries(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 2000)
    stones_before = player(game[1])["stones"]
    items_before = items(game[1])
    with game[1].connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_sect_rank_claim BEFORE INSERT ON quest_progress "
            "WHEN NEW.quest_id='sect_claim_jian_ge_6' "
            "BEGIN SELECT RAISE(ABORT,'injected sect reward failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected sect reward failure"):
        play("sect", "领赏", op="rollback-sect-claim")
    assert player(game[1])["stones"] == stones_before
    assert items(game[1]) == items_before
    assert sql(game[1], "SELECT 1 FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'sect_claim_jian_ge_%'") == []

    with game[1].connect() as conn:
        conn.execute("DROP TRIGGER fail_sect_rank_claim")

    reply = play("sect", "领赏", op="rollback-sect-claim")
    assert "8 阶：灵石 +4000" in reply.text()
    assert player(game[1])["stones"] == stones_before + sum((120, 240, 480, 900, 1600, 2200, 3000, 4000))
    assert items(game[1])["forge_ore"] == 56


def test_true_disciple_claim_is_concurrent_and_grants_once(game, play):
    play("adopt", "玄狐", user="u2")
    play("sect", "拜入 剑阁", user="u2")
    seed_contribution(game, "jian_ge", 2000, user="u2")
    stones_before = player(game[1], "u2")["stones"]

    def claim(index):
        try:
            return play("sect", "领赏", user="u2", op=f"parallel-sect-claim-{index}")
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(claim, range(2)))
    assert sum(reply is not None for reply in replies) == 1
    assert player(game[1], "u2")["stones"] == stones_before + sum((120, 240, 480, 900, 1600, 2200, 3000, 4000))
    assert items(game[1], "u2")["forge_ore"] == 56
    assert len(sql(game[1], "SELECT 1 FROM quest_progress WHERE user_id='u2' AND quest_id LIKE 'sect_claim_jian_ge_%'")) == 8


def test_claim_never_pays_a_rank_above_the_current_one(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    seed_contribution(game, "jian_ge", 100)
    play("sect", "领赏")
    with pytest.raises(GameError, match="暂无可领"):
        play("sect", "领赏")


def test_the_passive_scales_with_rank_and_only_for_the_owner(game, play):
    play("adopt", "青鸾")
    base = stats(game).stats.attack
    play("sect", "拜入 剑阁")
    assert stats(game).stats.attack == int(base * 1.02 + 0.5)
    seed_contribution(game, "jian_ge", 560)
    assert stats(game).stats.attack == int(base * 1.10 + 0.5)

    play("adopt", "青鸾", user="u2")
    base_hp = stats(game, "u2").stats.hp
    play("sect", "拜入 玄门", user="u2")
    seed_contribution(game, "xuan_men", 560, user="u2")
    assert stats(game, "u1").stats.attack == int(base * 1.10 + 0.5)
    assert stats(game, "u2").stats.hp == int(base_hp * 1.10 + 0.5)


def test_a_sectless_player_gets_no_bonus(game, play):
    play("adopt", "青鸾")
    before = stats(game).stats
    play("adopt", "青鸾", user="u2")
    play("sect", "拜入 剑阁", user="u2")
    seed_contribution(game, "jian_ge", 560, user="u2")
    after = stats(game, "u1").stats
    assert (after.hp, after.attack, after.defense, after.speed) == (
        before.hp, before.attack, before.defense, before.speed,
    )


def test_state_survives_a_restart(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    play("sect", "修行")
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "sect", "", "restart-sect", NOW)
    assert "当前：剑阁 · 1 阶" in page.text()
    assert "贡献 10/60" in page.text()


def test_same_operation_replays_identically(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    first = play("sect", "修行", op="sect-op")
    again = play("sect", "修行", op="sect-op")
    assert again.text() == first.text()
    assert contribution(game, "jian_ge") == 10


def test_help_objectives_and_parse_contract(game, play):
    play("adopt", "青鸾")
    guide = play("help", "成长")
    assert "灵宠师门" in guide.text() and "灵宠师门 领赏" in guide.text()
    assert "师门：尚未拜入" in play("objectives").text()
    play("sect", "拜入 剑阁")
    assert "师门：剑阁 1 阶 · 贡献 0/60" in play("objectives").text()
    assert handlers._parse("灵宠师门") == ("sect", "")
    assert handlers._parse("灵宠师门 拜入 剑阁") == ("sect", "拜入 剑阁")


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    play("adopt", "青鸾")
    play("sect", "拜入 剑阁")
    page = play("sect")
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
