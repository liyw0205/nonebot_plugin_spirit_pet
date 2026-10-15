import itertools
import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import daily_assignment
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
YESTERDAY = NOW - 86400
TOMORROW = NOW + 86400
COUNTER = itertools.count()


def stones(game):
    return player(game[1])["stones"]


def context(game, user, now=NOW):
    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now,
        f"assignment-{next(COUNTER)}",
    )


def todays(game, now=NOW):
    return daily_assignment.todays(context(game, "u1", now))


def value(game, user, assignment_id, now=NOW):
    out = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, now, "assignment")
        out.append(daily_assignment._value(ctx, user, game[0].content.daily_assignments[assignment_id]))
        return Reply("assignment", ())

    game[1].transact(user, f"assignment-value-{user}-{next(COUNTER)}", now, run)
    return out[-1]


def satisfy(game, play, assignment, now=NOW):
    """Make one assignment's condition true today."""
    metric = assignment.metric
    if metric == "daily_pve":
        play("challenge", "青岚林", now=now)
    elif metric == "daily_pvp":
        play("adopt", "青鸾", user="u2", now=now)
        play("season", now=now)
        sql(game[1], "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,"
            "target_pet_id,winner_id,day,played_at,delta,operation_id,reply) "
            "VALUES ('2027-01','u1','u2',1,2,'u1','2027-01-15',?,10,?, '{}')",
            (now, f"pvp-{next(COUNTER)}"))
    elif metric == "daily_discovery":
        sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
            "VALUES ('u1',?,?)", (f"probe_{next(COUNTER)}", now))
    elif metric == "daily_expedition":
        play("expedition_start", "采灵药", now=now)
        sql(game[1], "UPDATE expeditions SET state='claimed', settled_at=? WHERE user_id='u1'", (now,))
    elif metric == "daily_claim":
        sql(game[1], "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, "
            "reward_snapshot, reply) VALUES ('u1',?,?,?,'{}','{}')",
            (f"probe_{next(COUNTER)}", f"claim-{next(COUNTER)}", now))
    else:
        play("train", now=now)


def row(reply, name):
    return next(text for text in reply.lines if text.startswith(name + " ·"))


def test_page_previews_without_an_account(game, play):
    reply = play("daily_assignment", user="u9", now=NOW)
    assert reply.title == "今日课题"
    assert "尚未结契" in reply.text()
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_three_stable_assignments_rotate_by_day(game, play):
    play("adopt", "青鸾", now=NOW)
    offered = todays(game)
    assert len(offered) == 3
    assert len({entry.id for entry in offered}) == 3
    assert [entry.id for entry in todays(game)] == [entry.id for entry in offered]

    page = play("daily_assignment", now=NOW)
    assert page.title == "今日课题"
    for entry in offered:
        assert row(page, entry.name).endswith("进行中（0/1）")
    assert page.lines[-1] == "今日尚未领取；三项任选其一，其余两项当日作废。"
    assert page.commands == ("灵宠任务", "灵宠目标")
    assert page.inline_commands == ()

    tomorrow = [entry.id for entry in todays(game, TOMORROW)]
    assert tomorrow != [entry.id for entry in offered]
    assert len(set(tomorrow) & {entry.id for entry in offered}) < 3


def test_progress_only_counts_today(game, play):
    play("adopt", "青鸾", now=NOW)
    assert value(game, "u1", "daily_pve") == 0
    play("challenge", "青岚林", now=NOW)
    assert value(game, "u1", "daily_pve") == 1
    assert value(game, "u1", "daily_pve", YESTERDAY) == 0

    sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
        "VALUES ('u1','old_one',?)", (YESTERDAY,))
    assert value(game, "u1", "daily_discovery") == 0
    sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
        "VALUES ('u1','new_one',?)", (NOW,))
    assert value(game, "u1", "daily_discovery") == 1

    sql(game[1], "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, "
        "reward_snapshot, reply) VALUES ('u1','old_claim',?,?,'{}','{}')", (f"claim-{next(COUNTER)}", YESTERDAY))
    assert value(game, "u1", "daily_claim") == 0
    sql(game[1], "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, "
        "reward_snapshot, reply) VALUES ('u1','new_claim',?,?,'{}','{}')", (f"claim-{next(COUNTER)}", NOW))
    assert value(game, "u1", "daily_claim") == 1

    assert value(game, "u1", "daily_training") == 0
    play("train", now=NOW)
    assert value(game, "u1", "daily_training") == 1
    assert value(game, "u1", "daily_training", YESTERDAY) == 0


def test_claim_grants_once_and_locks_the_others(game, play):
    play("adopt", "青鸾", now=NOW)
    offered = todays(game)
    target = offered[0]
    satisfy(game, play, target)

    page = play("daily_assignment", now=NOW)
    assert row(page, target.name).endswith("可领取")
    assert [link.command for link in page.inline_commands] == [f"灵宠课题领奖 {target.name}"]
    hub = next(text for text in play("objectives", now=NOW).lines if text.startswith("今日课题："))
    assert hub == f"今日课题：可领 1 项（{target.name}）· 今日三项任选其一"

    before = stones(game)
    reply = play("daily_assignment_claim", target.name, now=NOW, op="assignment-one")
    assert reply.title == "今日课题奖励"
    assert reply.lines[0] == f"{target.name} · {target.description}"
    assert stones(game) == before + target.reward.stones.minimum
    assert reply.lines[-1] == "今日其余课题已作废，次日 00:00 换新。"

    after = play("daily_assignment", now=NOW)
    assert row(after, target.name).endswith("今日已选")
    for entry in offered[1:]:
        assert row(after, entry.name).endswith("今日已错过")
    assert after.inline_commands == ()
    assert next(text for text in play("objectives", now=NOW).lines if text.startswith("今日课题：")) == (
        f"今日课题：今日已选「{target.name}」"
    )

    assert play("daily_assignment_claim", target.name, now=NOW, op="assignment-one").lines == reply.lines
    with pytest.raises(GameError, match=f"今日已选「{target.name}」，明日再来"):
        play("daily_assignment_claim", offered[1].name, now=NOW)


def test_claim_rejects_unoffered_and_unfinished(game, play):
    play("adopt", "青鸾", now=NOW)
    offered = {entry.id for entry in todays(game)}
    outside = next(
        entry for entry in game[0].content.daily_assignments.values() if entry.id not in offered
    )
    with pytest.raises(GameError, match=f"今日课题没有「{outside.name}」"):
        play("daily_assignment_claim", outside.name, now=NOW)

    target = next(entry for entry in todays(game) if entry.metric == "daily_pve")
    with pytest.raises(GameError, match="今日尚未完成：今日在秘境或关卡获胜 1 场。（0/1）"):
        play("daily_assignment_claim", target.name, now=NOW)


def test_next_day_offers_a_fresh_choice(game, play):
    play("adopt", "青鸾", now=NOW)
    target = todays(game)[0]
    satisfy(game, play, target)
    play("daily_assignment_claim", target.name, now=NOW)

    tomorrow = play("daily_assignment", now=TOMORROW)
    assert tomorrow.lines[-1] == "今日尚未领取；三项任选其一，其余两项当日作废。"
    for entry in todays(game, TOMORROW):
        assert row(tomorrow, entry.name).endswith("进行中（0/1）")
    assert next(text for text in play("objectives", now=TOMORROW).lines if text.startswith("今日课题：")) == (
        "今日课题：暂无可领 · 今日三项任选其一"
    )


def test_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾", now=NOW)
    satisfy(game, play, todays(game)[0])
    reply = play("daily_assignment", now=NOW)
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for line in segment.data["keyboard"].content.rows
        for button in line.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()


def test_help_lists_both_entries(game, play):
    text = play("help", "秘境与关卡", now=NOW).text()
    assert "灵宠课题" in text and "灵宠课题领奖" in text


def test_catalog_requires_every_metric():
    content = Catalog.load()
    metrics = {entry.metric for entry in content.daily_assignments.values()}
    assert metrics == {
        "daily_pve", "daily_pvp", "daily_discovery", "daily_expedition", "daily_claim",
        "daily_training",
    }


def edit_content(tmp_path, change):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "daily_assignments.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    change(entries)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return target


def test_missing_metric_is_rejected(tmp_path):
    target = edit_content(tmp_path, lambda entries: entries.__setitem__(
        slice(None), [entry for entry in entries if entry["metric"] != "daily_pve"],
    ))
    with pytest.raises(ValueError, match="missing daily assignment metrics"):
        Catalog.load(target)


def test_duplicate_metric_target_is_rejected(tmp_path):
    def duplicate(entries):
        entries.append(dict(entries[0], id="daily_pve_copy", name="重复目标"))
    target = edit_content(tmp_path, duplicate)
    with pytest.raises(ValueError, match="duplicate daily assignment metric target"):
        Catalog.load(target)


def test_unknown_reward_item_is_rejected(tmp_path):
    def retarget(entries):
        entries[0]["reward"]["items"] = {"no_such_item": {"minimum": 1, "maximum": 1}}
    target = edit_content(tmp_path, retarget)
    with pytest.raises(ValueError, match="unknown reward items"):
        Catalog.load(target)
