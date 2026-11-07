"""灵宠际遇: the daily cost/benefit road choice."""

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import daily_encounters
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import items, player, sql

NOW = 1_800_000_000
DAY = 86400


def context(game, user="u1", now=NOW):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, now, "enc")


def todays(game, user="u1", now=NOW):
    return daily_encounters.todays(context(game, user, now))


def account(play):
    play("adopt", "青鸾", now=NOW)


def grant(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def stones_option(encounter):
    return next(option for option in encounter.options if option.cost.stones)


def item_option(encounter):
    return next(option for option in encounter.options if option.cost.items)


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY item_id"),
        sql(game[1], "SELECT user_id, stones FROM players"),
        sql(game[1], "SELECT user_id, quest_id, progress, claimed FROM quest_progress ORDER BY quest_id"),
        sql(game[1], "SELECT battle_id FROM battle_records"),
    )


def test_the_same_day_is_stable_and_the_next_day_moves_on(game, play):
    account(play)
    first = todays(game)
    assert todays(game) is first
    later = todays(game, now=NOW + DAY)
    assert later.id != first.id


def test_page_lists_every_option_with_its_price(game, play):
    account(play)
    encounter = todays(game)
    page = play("encounters", now=NOW)
    assert page.title == "灵宠际遇"
    for option in encounter.options:
        assert option.label in page.text()
    assert "付出" in page.text()


def test_choose_pays_the_price_and_grants_the_reward(game, play):
    account(play)
    encounter = todays(game)
    option = stones_option(encounter)
    sql(game[1], "UPDATE players SET stones=100000")
    before = player(game[1])["stones"]
    bag_before = items(game[1])

    reply = play("encounters", option.label, now=NOW)
    assert option.text in reply.text()
    assert player(game[1])["stones"] == before - option.cost.stones + option.reward.stones.maximum
    marker = sql(
        game[1], "SELECT progress, claimed FROM quest_progress WHERE quest_id=?",
        (f"enc_{beijing_day(NOW)}",),
    )[0]
    assert marker["progress"] == encounter.options.index(option) + 1
    assert marker["claimed"] == 1
    assert items(game[1]) != bag_before or option.reward.stones.maximum


def test_a_second_choice_on_the_same_day_is_refused(game, play):
    account(play)
    encounter = todays(game)
    option = stones_option(encounter)
    sql(game[1], "UPDATE players SET stones=100000")
    play("encounters", option.label, now=NOW)
    other = next(entry for entry in encounter.options if entry.id != option.id)
    with pytest.raises(GameError, match="今日已了"):
        play("encounters", other.label, now=NOW)


def test_an_unknown_option_is_refused(game, play):
    account(play)
    with pytest.raises(GameError, match="没有这个选项"):
        play("encounters", "不存在", now=NOW)


def test_short_stones_leave_everything_untouched(game, play):
    account(play)
    option = stones_option(todays(game))
    sql(game[1], "UPDATE players SET stones=0")
    before = snapshot(game)
    with pytest.raises(GameError, match="灵石不足"):
        play("encounters", option.label, now=NOW)
    assert snapshot(game) == before


def test_short_items_leave_everything_untouched(game, play):
    account(play)
    option = item_option(todays(game))
    sql(game[1], "UPDATE players SET stones=100000")
    sql(game[1], "DELETE FROM inventory")
    before = snapshot(game)
    with pytest.raises(GameError, match="道具不足"):
        play("encounters", option.label, now=NOW)
    assert snapshot(game) == before


def test_unregistered_caller_gets_a_preview(game, play):
    page = play("encounters", user="u9", now=NOW)
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='u9'") == []


def test_a_replayed_operation_returns_the_cached_reply(game, play):
    account(play)
    option = stones_option(todays(game))
    sql(game[1], "UPDATE players SET stones=100000")
    first = play("encounters", option.label, op="once", now=NOW)
    stones = player(game[1])["stones"]
    again = play("encounters", option.label, op="once", now=NOW)
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones


def test_the_choice_writes_no_battle_record(game, play):
    account(play)
    option = stones_option(todays(game))
    sql(game[1], "UPDATE players SET stones=100000")
    play("encounters", option.label, now=NOW)
    assert sql(game[1], "SELECT * FROM battle_records") == []


def test_alias_parses():
    assert _parse("灵宠际遇") == ("encounters", "")
    assert _parse("灵宠际遇 搬石") == ("encounters", "搬石")


# ------------------------------------------------------------- follow-ups
# Day 0 (NOW) draws `herd`. Day +3 draws `rockslide`, whose 搬石 option
# schedules `quarry_debt` for day +4. That keeps every assertion below on a
# real, shipped trigger without depending on a random rotation.

TRIGGER_DAY = NOW + 3 * DAY
FOLLOW_DAY = TRIGGER_DAY + DAY
AFTER_DAY = FOLLOW_DAY + DAY


def trigger_option(game):
    encounter = todays(game, now=TRIGGER_DAY)
    assert encounter.id == "rockslide", encounter.id
    return next(option for option in encounter.options if option.next)


def affordable(game, option):
    sql(game[1], "UPDATE players SET stones=100000")
    for item_id, amount in option.cost.items.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', ?, ?)"
            " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
            (item_id, amount),
        )


def follow_rows(game):
    return sql(
        game[1],
        "SELECT quest_id, claimed FROM quest_progress WHERE quest_id LIKE 'encfollow_%'",
    )


def test_a_trigger_choice_schedules_the_next_days_followup(game, play):
    account(play)
    option = trigger_option(game)
    affordable(game, option)
    reply = play("encounters", option.label, now=TRIGGER_DAY)
    assert "留待明日" in reply.text()
    rows = follow_rows(game)
    assert len(rows) == 1
    assert rows[0]["quest_id"] == f"encfollow_{beijing_day(FOLLOW_DAY)}_{option.next}"
    assert rows[0]["claimed"] == 0


def test_the_followup_is_todays_encounter_on_the_next_day(game, play):
    account(play)
    option = trigger_option(game)
    affordable(game, option)
    play("encounters", option.label, now=TRIGGER_DAY)
    follow = todays(game, now=FOLLOW_DAY)
    assert follow.id == option.next
    assert follow.trigger == "rockslide"
    page = play("encounters", now=FOLLOW_DAY)
    assert "承接昨日" in page.text()
    assert follow.name in page.text()


def test_a_followup_never_fires_twice(game, play):
    account(play)
    option = trigger_option(game)
    affordable(game, option)
    play("encounters", option.label, now=TRIGGER_DAY)
    # Resolve it on its day; that claims the schedule row.
    follow = todays(game, now=FOLLOW_DAY)
    resolve = next(o for o in follow.options if o.cost.stones)
    affordable(game, resolve)
    play("encounters", resolve.label, now=FOLLOW_DAY)
    assert follow_rows(game)[0]["claimed"] == 1
    # The day after, the rotation is back and no follow-up is surfaced.
    assert todays(game, now=AFTER_DAY).id == "stele"
    assert "承接昨日" not in play("encounters", now=AFTER_DAY).text()


def test_ignoring_a_followup_leaves_no_residue(game, play):
    account(play)
    option = trigger_option(game)
    affordable(game, option)
    play("encounters", option.label, now=TRIGGER_DAY)
    # Never open 灵宠际遇 on FOLLOW_DAY at all. On the day after, the rotation
    # resumes with no follow-up banner and the dormant row never reappears.
    assert todays(game, now=AFTER_DAY).id == "stele"
    page = play("encounters", now=AFTER_DAY)
    assert "承接昨日" not in page.text()
    assert "采石赊账" not in page.text()


def test_the_one_choice_rule_holds_on_a_followup(game, play):
    account(play)
    option = trigger_option(game)
    affordable(game, option)
    play("encounters", option.label, now=TRIGGER_DAY)
    follow = todays(game, now=FOLLOW_DAY)
    first, second = follow.options[0], follow.options[1]
    affordable(game, first)
    affordable(game, second)
    play("encounters", first.label, now=FOLLOW_DAY)
    with pytest.raises(GameError, match="今日已了"):
        play("encounters", second.label, now=FOLLOW_DAY)
    # The 今日已了 page still describes the follow-up that was actually chosen.
    page = play("encounters", now=FOLLOW_DAY)
    assert follow.name in page.text() and "承接昨日" in page.text()


def test_a_refused_trigger_does_not_schedule(game, play):
    account(play)
    option = trigger_option(game)
    sql(game[1], "UPDATE players SET stones=0")  # 搬石 needs 60 stones
    with pytest.raises(GameError, match="灵石不足"):
        play("encounters", option.label, now=TRIGGER_DAY)
    assert follow_rows(game) == []
    assert todays(game, now=FOLLOW_DAY).id == "spring"  # ordinary rotation


def test_the_followup_page_is_read_only(game, play):
    account(play)
    option = trigger_option(game)
    affordable(game, option)
    play("encounters", option.label, now=TRIGGER_DAY)
    before = snapshot(game)
    play("encounters", now=FOLLOW_DAY)
    play("encounters", now=FOLLOW_DAY)
    assert snapshot(game) == before


def test_an_unregistered_player_sees_no_followup(game, play):
    # A follow-up only exists after a trigger choice; an unregistered caller
    # always gets the read-only preview, never a scheduled encounter.
    page = play("encounters", user="u9", now=FOLLOW_DAY)
    assert "尚未结契" in page.text()
    assert follow_rows(game) == []
