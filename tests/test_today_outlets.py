"""灵宠今日: the daily outlets added after the first digest.

Every new row must disappear when the player has nothing left to do, must never
appear for an untouched account, and opening the page must still write nothing.
"""

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day
from nonebot_plugin_spirit_pet.gameplay import bounty, cave, counters, daily_shop, sects, today

from .support import sql

NOW = 1_800_000_000


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "today")


def collect(game, user="u1"):
    claimable, pending = today.collect(context(game, user))
    return [entry["label"] for entry in claimable], [entry["label"] for entry in pending]


def snapshot(game, user="u1"):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory WHERE user_id=?", (user,)),
        sql(game[1], "SELECT user_id, stones, active_pet_id FROM players WHERE user_id=?", (user,)),
        sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
                     " WHERE user_id=? ORDER BY quest_id", (user,)),
    )


def account(play):
    play("adopt", "青鸾", now=NOW)


def test_shop_outlet_disappears_once_the_stock_is_gone(game, play):
    account(play)
    entry = "今日特供剩 3 件"
    assert entry in collect(game)[1]
    for offer in daily_shop.offers(context(game)):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, ?, 1)",
            (daily_shop.offer_key(NOW, offer), offer.stock),
        )
    assert entry not in collect(game)[1]


def test_cave_outlet_counts_the_remaining_actions(game, play):
    account(play)
    facilities = cave.facilities(context(game))
    assert "洞府还剩 3 次行动" in collect(game)[1]
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
        (f"cave_{facilities[0].id}_day_{beijing_day(NOW)}",),
    )
    assert "洞府还剩 2 次行动" in collect(game)[1]
    for facility in facilities:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO NOTHING",
            (f"cave_{facility.id}_day_{beijing_day(NOW)}",),
        )
    assert not any(label.startswith("洞府还剩") for label in collect(game)[1])


def test_race_and_research_outlets_follow_their_daily_limits(game, play):
    account(play)
    _, pending = collect(game)
    assert any(label.startswith("竞速还剩") for label in pending)
    assert any(label.startswith("研习还剩") for label in pending)


def test_claim_outlets_stay_silent_on_an_untouched_account(game, play):
    account(play)
    claimable, _ = collect(game)
    for prefix in ("今日秘境", "赏金", "周常", "有阶位奖励可领"):
        assert not any(prefix in label for label in claimable), claimable


def test_bounty_outlet_appears_when_the_daily_counter_reaches_the_target(game, play):
    account(play)
    target = bounty.todays(context(game))[0]
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, ?, 0)",
        (counters.day_key(target.metric, NOW), target.target),
    )
    claimable, _ = collect(game)
    assert any(label.startswith("赏金 1 份已达") for label in claimable)


def test_sect_outlets_require_membership_and_track_daily_practice(game, play):
    account(play)
    sect = sects.sects(context(game))[0]
    assert not any("尚未修行" in label for label in collect(game)[1])

    sects._set(context(game), f"sect_current_{sect.id}", 1)
    assert any(f"{sect.name}今日尚未修行" in label for label in collect(game)[1])
    assert any("有阶位奖励可领" in label for label in collect(game)[0])

    sects._set(context(game), f"sect_day_{beijing_day(NOW)}", 1)
    assert not any("尚未修行" in label for label in collect(game)[1])


def test_page_stays_read_only_with_the_new_outlets(game, play):
    account(play)
    before = snapshot(game)
    play("today", now=NOW)
    assert snapshot(game) == before
