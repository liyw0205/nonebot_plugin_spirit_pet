import itertools

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import daily_assignment
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
DAY = 86400
COUNTER = itertools.count()


def context(game, user="u1", now=NOW):
    return Context(
        Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now,
        f"assign-{next(COUNTER)}",
    )


def offered(game, now=NOW):
    return [entry.id for entry in daily_assignment.todays(context(game, now=now))]


def stones(game):
    return player(game[1])["stones"]


def test_pool_doubles_with_a_harder_variant_per_metric(game):
    content = game[0].content
    assert len(content.daily_assignments) == 12
    by_metric = {}
    for assignment in content.daily_assignments.values():
        by_metric.setdefault(assignment.metric, []).append(assignment)
    assert set(by_metric) == {
        "daily_pve", "daily_pvp", "daily_discovery", "daily_expedition", "daily_claim", "daily_training",
    }
    for metric, entries in by_metric.items():
        assert len({entry.target for entry in entries}) == len(entries)
        if metric == "daily_training":
            # The training metric is a boolean (did the player train today), so it stays single-step.
            assert [entry.target for entry in entries] == [1]
        else:
            assert len(entries) >= 2
            assert max(entry.target for entry in entries) > 1


def test_harder_variants_pay_more_than_their_light_counterpart(game):
    content = game[0].content
    by_metric = {}
    for assignment in content.daily_assignments.values():
        by_metric.setdefault(assignment.metric, []).append(assignment)
    for metric, entries in by_metric.items():
        if len(entries) < 2:
            continue
        ordered = sorted(entries, key=lambda entry: entry.target)
        for lighter, heavier in zip(ordered, ordered[1:]):
            assert heavier.reward.stones.minimum > lighter.reward.stones.minimum


def test_rotation_reaches_the_whole_pool_within_four_days(game):
    seen = []
    for offset in range(4):
        seen.extend(offered(game, NOW + offset * DAY))
    assert len(seen) == 12
    assert len(set(seen)) == 12
    assert set(seen) == set(game[0].content.daily_assignments)


def test_hard_variant_requires_its_target_and_claims_once(game, play):
    play("adopt", "青鸾")
    # Walk forward until a hard variant is on offer, then satisfy it.
    day = None
    target = None
    for offset in range(4):
        moment = NOW + offset * DAY
        for assignment in daily_assignment.todays(context(game, now=moment)):
            if assignment.metric == "daily_pve" and assignment.target > 1:
                day, target = moment, assignment
                break
        if day is not None:
            break
    assert day is not None and target is not None

    with pytest.raises(GameError, match="今日尚未完成"):
        play("daily_assignment_claim", target.name, now=day)

    for index in range(target.target):
        sql(game[1], "UPDATE players SET last_pve=NULL")
        sql(game[1], "UPDATE pets SET energy=100")
        play("challenge", "青岚林", now=day + index * 601)

    before = stones(game)
    reply = play("daily_assignment_claim", target.name, now=day, op="assign-hard")
    assert stones(game) == before + target.reward.stones.minimum
    assert play("daily_assignment_claim", target.name, now=day, op="assign-hard").lines == reply.lines

    page = play("daily_assignment", now=day)
    assert any(text.startswith(target.name + " ·") and "今日已选" in text for text in page.lines)
    for other in daily_assignment.todays(context(game, now=day)):
        if other.id != target.id:
            assert any(text.startswith(other.name + " ·") and "今日已错过" in text for text in page.lines)
