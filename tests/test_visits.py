"""灵宠串门: friends-only daily visits that pay bond experience to both pets."""

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import bond_levels
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import player_uid, sql

NOW = 1_800_000_000
DAY = 86_400


def snapshot(store):
    return (
        sql(store, "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(store, "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(
            store,
            "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
            " ORDER BY user_id, quest_id",
        ),
    )


def befriend(game, play, first, second):
    uid_first = player_uid(game[1], first)
    uid_second = player_uid(game[1], second)
    play("friends", f"添加 {uid_second}", user=first, op=f"add-{first}-{second}")
    play("friends", f"同意 {uid_first}", user=second, op=f"acc-{first}-{second}")
    return uid_second


def setup_pair(game, play):
    play("adopt", "青鸾", now=NOW, op="vis-adopt-1")
    play("adopt", "青鸾", user="u2", now=NOW, op="vis-adopt-2")
    return befriend(game, play, "u1", "u2")


def bond(game, user="u1"):
    pet_id = sql(
        game[1], "SELECT active_pet_id FROM players WHERE user_id=?", (user,),
    )[0]["active_pet_id"]
    rows = sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE user_id=? AND quest_id=?",
        (user, bond_levels.key(pet_id)),
    )
    return rows[0]["progress"] if rows else 0


def test_page_lists_friends_and_visits_left(game, play):
    setup_pair(game, play)
    page = play("visits", now=NOW, op="vis-page")
    assert "今日串门 0/3 次 · 好友 1 位。" in page.lines[0]
    assert any("可串门" in line for line in page.lines)
    assert [link.command for link in page.inline_commands] == [f"灵宠串门 {player_uid(game[1], 'u2')}"]


def test_visit_pays_bond_to_both_and_stones_to_visitor(game, play):
    uid2 = setup_pair(game, play)
    stones = {row["user_id"]: row["stones"] for row in sql(game[1], "SELECT user_id, stones FROM players")}
    result = play("visits", str(uid2), now=NOW, op="vis-1")
    assert result.title == "灵宠串门"
    assert "羁绊经验 +5" in result.text()
    assert bond(game, "u1") == 5
    assert bond(game, "u2") == 5
    after = {row["user_id"]: row["stones"] for row in sql(game[1], "SELECT user_id, stones FROM players")}
    assert after["u1"] == stones["u1"] + 20
    assert after["u2"] == stones["u2"]
    assert "今日还剩 2 次" in result.text()


def test_same_friend_once_per_day(game, play):
    uid2 = setup_pair(game, play)
    play("visits", str(uid2), now=NOW, op="same-1")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="已经去过这位好友家"):
        play("visits", str(uid2), now=NOW + 1, op="same-2")
    assert snapshot(game[1]) == before
    assert play("visits", str(uid2), now=NOW + DAY, op="same-3").title == "灵宠串门"


def test_three_visits_per_day_cap(game, play):
    setup_pair(game, play)
    for user in ("u3", "u4", "u5"):
        play("adopt", "青鸾", user=user, now=NOW, op=f"cap-adopt-{user}")
        befriend(game, play, "u1", user)
    for index, user in enumerate(("u2", "u3", "u4")):
        play("visits", str(player_uid(game[1], user)), now=NOW + index, op=f"cap-{user}")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="今日串门次数已用完"):
        play("visits", str(player_uid(game[1], "u5")), now=NOW + 10, op="cap-over")
    assert snapshot(game[1]) == before
    assert play(
        "visits", str(player_uid(game[1], "u5")), now=NOW + DAY, op="cap-next",
    ).title == "灵宠串门"


def test_strangers_and_unknown_uids_write_nothing(game, play):
    play("adopt", "青鸾", now=NOW, op="str-adopt-1")
    play("adopt", "青鸾", user="u2", now=NOW, op="str-adopt-2")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="只能去好友家串门"):
        play("visits", str(player_uid(game[1], "u2")), now=NOW, op="stranger")
    with pytest.raises(GameError):
        play("visits", "999999", now=NOW + 1, op="unknown")
    assert snapshot(game[1]) == before


def test_friend_without_active_pet_is_refused(game, play):
    uid2 = setup_pair(game, play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="尚未选择出战伙伴"):
        play("visits", str(uid2), now=NOW, op="no-pet")
    assert snapshot(game[1]) == before


def test_objectives_row_reports_visits(game, play):
    setup_pair(game, play)
    objectives = play("objectives", now=NOW, op="vis-obj")
    assert any(line.startswith("串门：今日 0/3 次") for line in objectives.lines)
    play("visits", str(player_uid(game[1], "u2")), now=NOW + 1, op="vis-obj-1")
    assert beijing_day(NOW) == beijing_day(NOW + 1)
    objectives = play("objectives", now=NOW + 2, op="vis-obj-2")
    assert any(line.startswith("串门：今日 1/3 次") for line in objectives.lines)
