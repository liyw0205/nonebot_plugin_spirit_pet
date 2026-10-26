import itertools
import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import achievements
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
COUNTER = itertools.count()

NEW_METRICS = ("journey_claims", "echo_claims", "first_clear_claims")
PREFIX = {"journey_claims": "journey_", "echo_claims": "echo_", "first_clear_claims": "first_clear_"}


def metric(game, user, name):
    values = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "metric")
        values.append(achievements._metric(ctx, user, name))
        return Reply("metric", ())

    game[1].transact(user, f"metric-{user}-{name}-{next(COUNTER)}", NOW, run)
    return values[-1]


def mark(game, quest_id, claimed=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 0, ?)"
        " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=excluded.claimed",
        (user, quest_id, claimed),
    )


def markers(game, metric_name, count, user="u1"):
    """Claim the first `count` ids of the system behind a metric."""
    source = {
        "journey_claims": game[0].content.journey,
        "echo_claims": game[0].content.encounters,
        "first_clear_claims": game[0].content.dungeons,
    }[metric_name]
    for index, entry_id in enumerate(list(source)[:count]):
        mark(game, f"{PREFIX[metric_name]}{entry_id}", user=user)
    return list(source)[:count]


def stones(game):
    return player(game[1])["stones"]


def test_content_defines_the_new_metrics_and_their_milestones(game):
    content = game[0].content
    assert len(content.achievements) == 77
    assert len(content.titles) == 23
    metrics = {entry.metric for entry in content.achievements.values()}
    assert set(NEW_METRICS) <= metrics
    maxima = {
        "journey_claims": len(content.journey),
        "echo_claims": len(content.encounters),
        "first_clear_claims": len(content.dungeons),
    }
    for name, top in maxima.items():
        assert top in {entry.target for entry in content.achievements.values() if entry.metric == name}
    assert len({title.name for title in content.titles.values()}) == 23


def test_claim_markers_drive_the_three_metrics(game, play):
    play("adopt", "青鸾")
    for name in NEW_METRICS:
        assert metric(game, "u1", name) == 0

    markers(game, "journey_claims", 3)
    markers(game, "echo_claims", 2)
    markers(game, "first_clear_claims", 4)
    assert metric(game, "u1", "journey_claims") == 3
    assert metric(game, "u1", "echo_claims") == 2
    assert metric(game, "u1", "first_clear_claims") == 4
    assert metric(game, "u2", "journey_claims") == 0

    # An unclaimed marker and an unrelated quest id must not be counted.
    mark(game, "journey_unclaimed", claimed=0)
    mark(game, "quest_daily_one")
    mark(game, "weekly_one")
    assert metric(game, "u1", "journey_claims") == 3

    # A prefix must not leak into a sibling metric.
    assert metric(game, "u1", "echo_claims") == 2
    assert metric(game, "u1", "first_clear_claims") == 4


def test_journey_achievements_unlock_at_three_seven_and_fourteen(game, play):
    play("adopt", "青鸾")
    markers(game, "journey_claims", 3)
    page = play("achievements", "13")
    assert "行纪三章 · 可领奖 · 进度：3/3" in page.text()
    assert "灵宠成就领奖 行纪三章" in page.commands
    assert "行纪七章 · 进行中 · 进度：3/7" in play("achievements", "14").text()

    before = stones(game)
    reply = play("achievement_claim", "行纪三章", op="claim-journey-three")
    assert reply.title == "成就奖励已领取"
    assert stones(game) == before + 300
    assert play("achievement_claim", "行纪三章", op="claim-journey-three").lines == reply.lines
    with pytest.raises(GameError, match="该成就奖励已领取"):
        play("achievement_claim", "行纪三章")

    markers(game, "journey_claims", 7)
    assert "行纪七章 · 可领奖 · 进度：7/7" in play("achievements", "14").text()

    markers(game, "journey_claims", 16)
    page = play("achievements", "14").text()
    assert "行纪全章 · 可领奖 · 进度：16/16" in page
    assert "秘境五通 · 进行中 · 进度：0/5" in page


def test_echo_and_first_clear_achievements_unlock(game, play):
    play("adopt", "青鸾")
    markers(game, "echo_claims", 3)
    markers(game, "first_clear_claims", 5)
    page = play("achievements", "14")
    assert "回响三章 · 可领奖 · 进度：3/3" in page.text()
    assert "回响全章 · 进行中 · 进度：3/21" in page.text()
    assert "秘境五通 · 可领奖 · 进度：5/5" in page.text()

    markers(game, "echo_claims", 21)
    markers(game, "first_clear_claims", 20)
    assert "回响全章 · 可领奖 · 进度：21/21" in play("achievements", "14").text()
    assert "秘境全通 · 可领奖 · 进度：20/20" in play("achievements", "15").text()


def test_top_titles_appear_once_the_systems_are_complete(game, play):
    play("adopt", "青鸾")
    assert "17. 山海尽头 · 进度 0/16" in play("titles", "4").text()

    markers(game, "journey_claims", 16)
    assert "17. 山海尽头 · 已获得 · 走完山海行纪全部十六段章节。" in play("titles", "4").text()

    markers(game, "echo_claims", 21)
    markers(game, "first_clear_claims", 20)
    page = play("titles", "4").text()
    assert "18. 万籁归心 · 已获得" in page
    assert "19. 秘境行家 · 已获得" in page
    assert "当前称号：秘境行家 · 已获得 4/23 项" in page


def test_hub_reports_the_new_achievement(game, play):
    play("adopt", "青鸾")
    markers(game, "journey_claims", 3)
    line = next(text for text in play("objectives").lines if text.startswith("成就："))
    assert "行纪三章" in line


def test_catalog_requires_the_final_milestone(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "achievements.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries = [entry for entry in entries if entry["id"] != "journey_all"]
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="missing final achievement milestone for journey_claims"):
        Catalog.load(target)


def test_achievement_page_links_stay_out_of_the_buttons(game, play):
    play("adopt", "青鸾")
    markers(game, "journey_claims", 3)
    reply = play("achievements", "13")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()
