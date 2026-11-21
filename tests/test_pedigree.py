import json
import re
import sqlite3
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000


def _account(game, play, *, user="u1"):
    play("adopt", "青鸾", user=user)
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id=?", (user,))


def _pet(game, *, user="u1", name):
    with closing(game[1].connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO pets(user_id,species_id,name,affinity,energy_updated) VALUES (?, 'qingluan', ?,100,?)",
            (user, name, NOW),
        )
        return int(cursor.lastrowid)


def _breed_pair(game, play, suffix=""):
    first = _pet(game, name="亲本甲" + suffix)
    second = _pet(game, name="亲本乙" + suffix)
    play("breeding", f"{first} {second}", op=f"breed-{suffix or 'one'}")
    return first, second


def _children(game):
    return sql(game[1], "SELECT * FROM pet_lineage_eggs ORDER BY egg_record_id")


def _seed_families(store, count):
    with closing(store.connect()) as conn:
        for index in range(count):
            parent_a, parent_b, child = [
                int(conn.execute(
                    "INSERT INTO pets(user_id,species_id,name,energy_updated) "
                    "VALUES ('u1','qingluan',?,?)",
                    (f"家族{index + 1}成员{member}", NOW),
                ).lastrowid)
                for member in ("甲", "乙", "幼灵")
            ]
            operation_id = f"seed-family-{index}"
            conn.execute(
                "INSERT INTO pet_pedigree_operations(operation_id,user_id,kind,created_at,snapshot,reply) "
                "VALUES (?,'u1','breed',?,'{}','{}')",
                (operation_id, NOW),
            )
            conn.execute(
                "INSERT INTO pet_lineage_eggs(user_id,item_id,species_id,parent_a_id,parent_a_name,"
                "parent_a_species_id,parent_b_id,parent_b_name,parent_b_species_id,operation_id,status,"
                "child_pet_id,child_name,created_at,finished_at) "
                "VALUES ('u1','egg_qingluan','qingluan',?,?,'qingluan',?,?,'qingluan',?,'hatched',?,?,?,?)",
                (parent_a, f"家族{index + 1}成员甲", parent_b, f"家族{index + 1}成员乙",
                 operation_id, child, f"家族{index + 1}幼灵", NOW, NOW),
            )


def test_breeding_receipt_is_permanent_and_pedigree_egg_snapshots_both_parents(game, play):
    _account(game, play)
    first = _pet(game, name="亲本甲")
    second = _pet(game, name="亲本乙")
    reply = play("breeding", f"{first} {second}", op="breed-permanent")
    before = (player(game[1]), items(game[1]), _children(game))
    sql(game[1], "DELETE FROM operations")

    assert game[0].execute("u1", "breeding", f"{first} {second}", "breed-permanent", NOW + 9 * 86400) == reply
    assert (player(game[1]), items(game[1]), _children(game)) == before
    row = _children(game)[0]
    assert (row["parent_a_id"], row["parent_a_name"]) == (first, "亲本甲")
    assert (row["parent_b_id"], row["parent_b_name"]) == (second, "亲本乙")
    assert row["status"] == "available"


def test_breeding_lineage_failure_rolls_back_cost_and_retries(game, play):
    _account(game, play)
    first, second = _pet(game, name="亲本甲"), _pet(game, name="亲本乙")
    before = (
        player(game[1]), items(game[1]),
        sql(game[1], "SELECT pet_id,energy,energy_updated FROM pets ORDER BY pet_id"),
    )
    sql(
        game[1],
        "CREATE TRIGGER fail_lineage_breed BEFORE INSERT ON pet_lineage_eggs "
        "BEGIN SELECT RAISE(ABORT,'injected lineage breed failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected lineage breed"):
        play("breeding", f"{first} {second}", op="breed-lineage-retry")
    after = (
        player(game[1]), items(game[1]),
        sql(game[1], "SELECT pet_id,energy,energy_updated FROM pets ORDER BY pet_id"),
    )
    assert after == before
    assert not sql(game[1], "SELECT * FROM pet_pedigree_operations")
    sql(game[1], "DROP TRIGGER fail_lineage_breed")

    assert "灵卵" in play("breeding", f"{first} {second}", op="breed-lineage-retry").text()
    assert len(_children(game)) == 1


def test_direct_hatching_consumes_unknown_first_then_known_eggs_fifo(game, play):
    _account(game, play)
    first_parents = _breed_pair(game, play, "一")
    second_parents = _breed_pair(game, play, "二")
    records = _children(game)
    assert len(records) == 2
    sql(
        game[1],
        "UPDATE inventory SET quantity=quantity+1 WHERE user_id='u1' AND item_id='egg_qingluan'",
    )

    reply = play("use", "egg_qingluan 2", op="mixed-hatch")
    unknown_child = int(reply.lines[1].rsplit(" ", 1)[-1].rstrip("。"))
    first_known_child = int(reply.lines[2].rsplit(" ", 1)[-1].rstrip("。"))
    status = {row["egg_record_id"]: row["status"] for row in _children(game)}
    assert status == {records[0]["egg_record_id"]: "hatched", records[1]["egg_record_id"]: "available"}
    assert not sql(game[1], "SELECT * FROM pet_lineage_eggs WHERE child_pet_id=?", (unknown_child,))
    assert sql(game[1], "SELECT child_pet_id,parent_a_id,parent_b_id FROM pet_lineage_eggs "
                        "WHERE child_pet_id=?", (first_known_child,))[0] == {
                            "child_pet_id": first_known_child,
                            "parent_a_id": first_parents[0],
                            "parent_b_id": first_parents[1],
                        }

    second_reply = play("use", "egg_qingluan", op="next-known-hatch")
    second_child = int(second_reply.lines[1].rsplit(" ", 1)[-1].rstrip("。"))
    second_record = sql(
        game[1], "SELECT child_pet_id,parent_a_id,parent_b_id FROM pet_lineage_eggs "
        "WHERE child_pet_id=?", (second_child,),
    )[0]
    assert (second_record["parent_a_id"], second_record["parent_b_id"]) == second_parents
    assert all(row["status"] == "hatched" for row in _children(game))
    assert items(game[1]).get("egg_qingluan", 0) == 0


def test_hatching_unknown_egg_does_not_invent_parentage(game, play):
    _account(game, play)
    sql(
        game[1],
        "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','egg_qingluan',1)",
    )
    reply = play("use", "egg_qingluan", op="unknown-hatch")
    child = int(reply.lines[1].rsplit(" ", 1)[-1].rstrip("。"))
    assert not sql(game[1], "SELECT * FROM pet_lineage_eggs WHERE child_pet_id=?", (child,))
    page = play("pedigree")
    assert "没有可验证的双亲" in play("pedigree", str(child)).text()
    assert "未知 0 枚" in page.text()


def test_nursery_reserves_returns_and_hatches_the_same_lineage_egg(game, play):
    _account(game, play)
    first, second = _breed_pair(game, play)
    record = _children(game)[0]
    play("nursery", "入巢 egg_qingluan", op="nursery-reserve")
    assert sql(game[1], "SELECT status,reservation_id FROM pet_lineage_eggs")[0]["status"] == "reserved"
    assert not sql(game[1], "SELECT reservation_id FROM pet_lineage_eggs "
                           "WHERE reservation_id=?", (record["operation_id"],))
    play("nursery", "撤回", op="nursery-return")
    restored = sql(game[1], "SELECT status,reservation_id FROM pet_lineage_eggs")[0]
    assert tuple(restored.values()) == ("available", None)
    assert items(game[1])["egg_qingluan"] == 1

    day = NOW + 86400
    play("nursery", "入巢 egg_qingluan", now=day, op="nursery-reserve-again")
    reply = play("nursery", "迎接", now=day + 1200, op="nursery-lineage-hatch")
    child = sql(game[1], "SELECT child_pet_id,parent_a_id,parent_b_id,status FROM pet_lineage_eggs")[0]
    assert child["status"] == "hatched"
    assert (child["parent_a_id"], child["parent_b_id"]) == (first, second)
    assert child["child_pet_id"] > second
    assert "灵宠谱系" in reply.commands


def test_nursery_reserve_withdraw_and_hatch_failures_keep_the_lineage_egg(game, play):
    _account(game, play)
    _breed_pair(game, play)
    sql(
        game[1],
        "CREATE TRIGGER fail_lineage_reserve BEFORE UPDATE OF status ON pet_lineage_eggs "
        "WHEN NEW.status='reserved' BEGIN SELECT RAISE(ABORT,'injected lineage reserve failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected lineage reserve"):
        play("nursery", "入巢 egg_qingluan", op="nursery-reserve-retry")
    assert items(game[1])["egg_qingluan"] == 1
    assert _children(game)[0]["status"] == "available"
    sql(game[1], "DROP TRIGGER fail_lineage_reserve")
    play("nursery", "入巢 egg_qingluan", op="nursery-reserve-retry")

    sql(
        game[1],
        "CREATE TRIGGER fail_lineage_return BEFORE UPDATE OF status ON pet_lineage_eggs "
        "WHEN NEW.status='available' BEGIN SELECT RAISE(ABORT,'injected lineage return failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected lineage return"):
        play("nursery", "撤回", op="nursery-return-retry")
    assert items(game[1]).get("egg_qingluan", 0) == 0
    assert _children(game)[0]["status"] == "reserved"
    sql(game[1], "DROP TRIGGER fail_lineage_return")
    play("nursery", "撤回", op="nursery-return-retry")

    day = NOW + 86400
    play("nursery", "入巢 egg_qingluan", now=day, op="nursery-finish-retry-start")
    pet_count = len(sql(game[1], "SELECT pet_id FROM pets"))
    sql(
        game[1],
        "CREATE TRIGGER fail_lineage_nursery_hatch BEFORE UPDATE OF status ON pet_lineage_eggs "
        "WHEN NEW.status='hatched' BEGIN SELECT RAISE(ABORT,'injected nursery lineage hatch failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected nursery lineage hatch"):
        play("nursery", "迎接", now=day + 1200, op="nursery-finish-retry")
    assert len(sql(game[1], "SELECT pet_id FROM pets")) == pet_count
    assert _children(game)[0]["status"] == "reserved"
    sql(game[1], "DROP TRIGGER fail_lineage_nursery_hatch")

    play("nursery", "迎接", now=day + 1200, op="nursery-finish-retry")
    assert _children(game)[0]["status"] == "hatched"


def test_tempering_consumes_lineage_receipt_without_hatching_it(game, play):
    _account(game, play)
    _breed_pair(game, play)
    play("temper", "亲本甲")
    row = _children(game)[0]
    assert row["status"] == "consumed"
    assert row["child_pet_id"] is None


def test_tempering_lineage_consumption_failure_rolls_back_and_retries(game, play):
    _account(game, play)
    _breed_pair(game, play)
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM pets ORDER BY pet_id"))
    sql(
        game[1],
        "CREATE TRIGGER fail_lineage_temper BEFORE UPDATE OF status ON pet_lineage_eggs "
        "WHEN NEW.status='consumed' BEGIN SELECT RAISE(ABORT,'injected lineage temper failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected lineage temper"):
        play("temper", "亲本甲", op="temper-lineage-retry")
    after = (player(game[1]), items(game[1]), sql(game[1], "SELECT * FROM pets ORDER BY pet_id"))
    assert after == before
    assert _children(game)[0]["status"] == "available"
    sql(game[1], "DROP TRIGGER fail_lineage_temper")

    play("temper", "亲本甲", op="temper-lineage-retry")
    assert _children(game)[0]["status"] == "consumed"


def test_pedigree_tracks_multiple_generations_and_family_thresholds(game, play):
    _account(game, play)
    first, second = _breed_pair(game, play)
    play("use", "egg_qingluan", op="first-generation")
    child = sql(game[1], "SELECT child_pet_id FROM pet_lineage_eggs")[0]["child_pet_id"]
    sql(game[1], "UPDATE pets SET affinity=100 WHERE pet_id=?", (child,))
    play("breeding", f"{first} {child}", op="second-generation")
    play("use", "egg_qingluan", op="second-generation-hatch")
    descendants = sql(
        game[1],
        "SELECT child_pet_id,parent_a_id,parent_b_id FROM pet_lineage_eggs "
        "WHERE status='hatched' ORDER BY child_pet_id",
    )
    grandchild = descendants[-1]["child_pet_id"]
    assert (descendants[-1]["parent_a_id"], descendants[-1]["parent_b_id"]) == (first, child)
    detail = play("pedigree", str(grandchild))
    assert "4 位" in detail.text() and "2 代已知关系" in detail.text()
    reward = play("pedigree", "领奖 deep_roots", op="claim-deep-roots")
    assert "根脉绵延" in reward.text()
    assert items(game[1]).get("bloodline_essence", 0) == 1


def test_hatching_lineage_failure_rolls_back_then_same_operation_retries(game, play):
    _account(game, play)
    _breed_pair(game, play)
    pet_count = sql(game[1], "SELECT COUNT(*) AS count FROM pets")[0]["count"]
    sql(
        game[1],
        "CREATE TRIGGER fail_pedigree_hatch BEFORE UPDATE OF status ON pet_lineage_eggs "
        "WHEN NEW.status='hatched' BEGIN SELECT RAISE(ABORT,'injected lineage hatch failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected lineage hatch"):
        play("use", "egg_qingluan", op="lineage-hatch-retry")
    assert items(game[1])["egg_qingluan"] == 1
    assert _children(game)[0]["status"] == "available"
    assert sql(game[1], "SELECT COUNT(*) AS count FROM pets")[0]["count"] == pet_count
    sql(game[1], "DROP TRIGGER fail_pedigree_hatch")

    reply = play("use", "egg_qingluan", op="lineage-hatch-retry")
    assert "灵卵孵化" in reply.title
    assert _children(game)[0]["status"] == "hatched"


def test_milestone_receipt_failure_rolls_back_reward_and_can_retry(game, play):
    _account(game, play)
    _breed_pair(game, play)
    play("use", "egg_qingluan", op="claim-failure-child")
    before = player(game[1])["stones"]
    sql(
        game[1],
        "CREATE TRIGGER fail_pedigree_claim BEFORE INSERT ON pet_pedigree_claims "
        "BEGIN SELECT RAISE(ABORT,'injected pedigree claim failure'); END",
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected pedigree claim"):
        play("pedigree", "领奖 first_branch", op="claim-retry")
    assert player(game[1])["stones"] == before
    assert not sql(game[1], "SELECT * FROM pet_pedigree_claims")
    assert not sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE kind='milestone_claim'")
    sql(game[1], "DROP TRIGGER fail_pedigree_claim")

    assert play("pedigree", "领奖 first_branch", op="claim-retry").title == "灵宠谱系 · 里程碑"


def test_pedigree_pages_are_private_read_only_and_claims_are_permanent(game, play):
    _account(game, play)
    first, second = _breed_pair(game, play)
    play("use", "egg_qingluan", op="family-child")
    child = sql(game[1], "SELECT child_pet_id FROM pet_lineage_eggs")[0]["child_pet_id"]
    before = (sql(game[1], "SELECT * FROM pet_lineage_eggs"),
              sql(game[1], "SELECT * FROM pet_pedigree_claims"),
              sql(game[1], "SELECT * FROM pet_pedigree_operations"))
    page = play("pedigree")
    detail = play("pedigree", str(child))
    ancestors = play("pedigree", f"{child} 祖辈")
    history = play("pedigree", f"{child} 记录")
    assert f"编号 {first}" in detail.text() and f"编号 {second}" in detail.text()
    assert "亲本甲" in ancestors.text() and "亲本乙" in ancestors.text()
    assert "→" in history.text()
    assert "家族" in page.text()
    after = (sql(game[1], "SELECT * FROM pet_lineage_eggs"),
             sql(game[1], "SELECT * FROM pet_pedigree_claims"),
             sql(game[1], "SELECT * FROM pet_pedigree_operations"))
    assert after == before

    _account(game, play, user="u2")
    with pytest.raises(GameError, match="没有属于你的"):
        play("pedigree", str(child), user="u2")

    stones = player(game[1])["stones"]
    reward_count = items(game[1]).get("spirit_food", 0)
    reward = play("pedigree", "领奖 first_branch", op="claim-first-family")
    assert "初见枝叶" in reward.text()
    after_claim = (player(game[1])["stones"], items(game[1]).get("spirit_food", 0))
    assert after_claim == (stones + 200, reward_count + 1)
    sql(game[1], "DELETE FROM operations")
    assert game[0].execute(
        "u1", "pedigree", "领奖 first_branch", "claim-first-family", NOW + 8 * 86400,
    ) == reward
    assert (player(game[1])["stones"], items(game[1]).get("spirit_food", 0)) == after_claim
    with pytest.raises(GameError, match="已经领取"):
        play("pedigree", "领奖 first_branch", op="claim-first-again")


def test_middle_pedigree_page_has_bounded_qq_buttons_and_distinct_links(game, play):
    _account(game, play)
    _seed_families(game[1], 11)
    reply = play("pedigree", "家族 2")
    assert reply.title == "灵宠谱系 2/3"
    assert "灵宠谱系 家族 1" in reply.commands and "灵宠谱系 家族 3" in reply.commands

    pytest.importorskip("nonebot.adapters.qq")
    _, message = _qq_segments(
        reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"),
    )
    markdown = message["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    buttons = [button.action.data for segment in message["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert len(buttons) <= 4
    assert not set(links) & set(buttons)
    assert {link.command for link in reply.inline_commands} == {
        command.removeprefix("!") for command in links
    }
    assert all(handlers._parse(command) is not None for command in reply.commands)
    assert all(handlers._parse(command.removeprefix("!")) is not None for command in links)


def test_concurrent_milestone_claims_award_once(game, play):
    _account(game, play)
    _breed_pair(game, play)
    play("use", "egg_qingluan", op="concurrent-family-child")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda i: _claim_result(game, i), range(8),
        ))
    assert sum(result is not None for result in results) == 1
    assert len(sql(game[1], "SELECT * FROM pet_pedigree_claims WHERE milestone_id='first_branch'")) == 1
    assert player(game[1])["stones"] == 4400


def _claim_result(game, index):
    try:
        return game[0].execute("u1", "pedigree", "领奖 first_branch", f"family-claim-{index}", NOW)
    except GameError:
        return None


@pytest.mark.parametrize(
    "edit",
    [
        lambda data: data[1].update(minimum_generation=data[0]["minimum_generation"]),
        lambda data: data[1].update(minimum_members=3),
        lambda data: data[0]["reward"].update(items={"egg_qingluan": 1}),
        lambda data: data[0]["reward"].update(items={"missing_item": 1}),
        lambda data: data[0]["reward"].update(stones=10_001),
    ],
)
def test_pedigree_content_rejects_invalid_thresholds_and_rewards(tmp_path, edit):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "pedigree_milestones.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        Catalog.load(target)
