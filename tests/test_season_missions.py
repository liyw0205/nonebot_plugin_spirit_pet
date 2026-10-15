import itertools
import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import season_missions
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
OLD = NOW - 90 * 86400
NEXT_SEASON = NOW + 40 * 86400
COUNTER = itertools.count()


def stones(game):
    return player(game[1])["stones"]


def items(game, item_id):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id=?", (item_id,))
    return rows[0]["quantity"] if rows else 0


def value(game, user, mission_id):
    out = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "season")
        out.append(season_missions._value(ctx, user, game[0].content.season_missions[mission_id]))
        return Reply("season", ())

    game[1].transact(user, f"season-value-{user}-{next(COUNTER)}", NOW, run)
    return out[-1]


def discover(game, amount, at=NOW):
    for _ in range(amount):
        sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
            "VALUES ('u1',?,?)", (f"probe_{next(COUNTER)}", at))


def pvp(game, season_id, wins=0, losses=0):
    for index in range(wins + losses):
        winner = "'u1'" if index < wins else "NULL"
        delta = 10 if index < wins else 0
        sql(game[1], "INSERT INTO pvp_results(season_id,challenger_id,target_id,challenger_pet_id,"
            "target_pet_id,winner_id,day,played_at,delta,operation_id,reply) "
            f"VALUES (?, 'u1', 'u2', 1, 2, {winner}, '2027-01-15', ?, {delta}, ?, '{{}}')",
            (season_id, NOW, f"pvp-{season_id}-{index}"))


def row(reply, name):
    return next(text for text in reply.lines if text.startswith(name + " ·"))


def test_page_previews_without_an_account(game, play):
    reply = play("season_missions", user="u9", now=NOW)
    assert reply.title == "赛季任务"
    assert "尚未结契" in reply.text()
    assert [link.command for link in reply.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_page_lists_every_mission_with_the_season(game, play):
    play("adopt", "青鸾", now=NOW)
    total = len(game[0].content.season_missions)
    page = play("season_missions", now=NOW)
    assert page.title == "赛季任务 1/1"
    assert row(page, "论剑历练") == "论剑历练 · 灵石 300，锻灵矿 2 · 进行中（0/10）"
    assert row(page, "山海征战") == "山海征战 · 灵石 400，蕴灵丹 2 · 进行中（0/5）"
    assert "本赛季参加 10 场论剑。" in page.text()
    assert page.lines[-1].startswith("赛季 2027-01 · 剩余 ")
    assert f"已领取 0/{total} 项" in page.lines[-1]
    assert page.commands == ("灵宠赛季", "灵宠目标")
    assert page.inline_commands == ()


def test_progress_derives_from_season_records(game, play):
    play("adopt", "青鸾", now=NOW)
    play("adopt", "青鸾", user="u2", now=NOW)
    play("season", now=NOW)
    assert value(game, "u1", "season_matches") == 0
    pvp(game, "2027-01", wins=2, losses=1)
    assert value(game, "u1", "season_matches") == 3
    assert value(game, "u1", "season_wins") == 2

    play("challenge", "青岚林", now=NOW)
    assert value(game, "u1", "season_pve") == 1
    sql(game[1], "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) "
        "VALUES ('u1','spring',?)", (OLD,))
    assert value(game, "u1", "season_discoveries") == 0
    discover(game, 2)
    assert value(game, "u1", "season_discoveries") == 2

    sql(game[1], "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, "
        "reward_snapshot, reply) VALUES ('u1','first_contract',?,?,'{{}}','{{}}')", (f"claim-{next(COUNTER)}", OLD))
    assert value(game, "u1", "season_claims") == 0
    sql(game[1], "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at, "
        "reward_snapshot, reply) VALUES ('u1','three_companions',?,?,'{{}}','{{}}')", (f"claim-{next(COUNTER)}", NOW))
    assert value(game, "u1", "season_claims") == 1


def test_claim_grants_once_and_replays(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game, 3)
    page = play("season_missions", now=NOW)
    assert row(page, "奇闻寻访").endswith("可领取")
    assert [link.command for link in page.inline_commands] == ["灵宠赛季任务领奖 奇闻寻访"]

    before = stones(game), items(game, "spirit_food")
    reply = play("season_mission_claim", "奇闻寻访", now=NOW, op="season-one")
    assert reply.title == "赛季任务奖励"
    assert reply.lines[0] == "奇闻寻访 · 赛季 2027-01"
    assert (stones(game), items(game, "spirit_food")) == (before[0] + 350, before[1] + 3)
    assert play("season_mission_claim", "奇闻寻访", now=NOW, op="season-one").lines == reply.lines
    with pytest.raises(GameError, match="本赛季奖励已领取，下赛季再来"):
        play("season_mission_claim", "奇闻寻访", now=NOW)

    assert row(play("season_missions", now=NOW), "奇闻寻访").endswith("已领取")
    hub = next(text for text in play("objectives", now=NOW).lines if text.startswith("赛季任务："))
    assert hub == "赛季任务：暂无可领 · 已领取 1/5 项"


def test_unfinished_mission_is_refused(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="本赛季尚未完成：本赛季在秘境或关卡获胜 5 场。（0/5）"):
        play("season_mission_claim", "山海征战", now=NOW)


def test_next_season_resets_the_claim(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game, 3)
    play("season_mission_claim", "奇闻寻访", now=NOW)
    assert row(play("season_missions", now=NOW), "奇闻寻访").endswith("已领取")

    later = play("season_missions", now=NEXT_SEASON)
    assert later.lines[-1].startswith("赛季 2027-02 ·")
    assert row(later, "奇闻寻访").endswith("进行中（0/3）")
    discover(game, 3, at=NEXT_SEASON)
    assert row(play("season_missions", now=NEXT_SEASON), "奇闻寻访").endswith("可领取")


def test_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾", now=NOW)
    discover(game, 3)
    reply = play("season_missions", now=NOW)
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for line in segment.data["keyboard"].content.rows
        for button in line.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()


def test_help_lists_both_entries(game, play):
    text = play("help", "对战与赛季", now=NOW).text()
    assert "灵宠赛季任务" in text and "灵宠赛季任务领奖" in text


def test_catalog_requires_every_metric():
    content = Catalog.load()
    metrics = {mission.metric for mission in content.season_missions.values()}
    assert metrics == {
        "season_matches", "season_wins", "season_pve", "season_discoveries", "season_claims",
    }


def edit_content(tmp_path, change):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "season_missions.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    change(entries)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return target


def test_missing_metric_is_rejected(tmp_path):
    target = edit_content(tmp_path, lambda entries: entries.pop(0))
    with pytest.raises(ValueError, match="missing season mission metrics"):
        Catalog.load(target)


def test_duplicate_metric_target_is_rejected(tmp_path):
    def duplicate(entries):
        entries.append(dict(entries[0], id="season_matches_copy", name="重复目标"))
    target = edit_content(tmp_path, duplicate)
    with pytest.raises(ValueError, match="duplicate season mission metric target"):
        Catalog.load(target)


def test_unknown_reward_item_is_rejected(tmp_path):
    def retarget(entries):
        entries[0]["reward"]["items"] = {"no_such_item": {"minimum": 1, "maximum": 1}}
    target = edit_content(tmp_path, retarget)
    with pytest.raises(ValueError, match="unknown reward items"):
        Catalog.load(target)
