"""灵宠借力: lending a companion to a friend, and the bonus it carries."""

import json
import re
import shutil
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import borrow
from nonebot_plugin_spirit_pet.gameplay.combat import pet_stats
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, player, player_uid, sql

NOW = 1_800_000_000
DAY = 86400


def context(game, user="u1", now=NOW):
    service, store = game
    conn = store.connect()
    return Context(Repository(conn), service.content, service.config, service.rng, user, now, f"probe-{user}")


def stats(game, user="u1"):
    with closing(context(game, user).repo.conn) as _:
        return combatant(context(game, user)).stats


def add_pet(game, user, species, name, *, archived=0):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, layer, bloodline, exp, affinity,"
        " energy, energy_updated, archived) VALUES (?, ?, ?, 0, 1, 0, 0, 0, 100, ?, ?)",
        (user, species, name, NOW, archived),
    )
    return sql(game[1], "SELECT MAX(pet_id) AS pet_id FROM pets WHERE user_id=?", (user,))[0]["pet_id"]


def befriend(game, first="u1", second="u2"):
    low, high = sorted((first, second))
    sql(game[1], "INSERT INTO friend_links(user_low, user_high, created_at) VALUES (?, ?, ?)",
        (low, high, NOW))


def unfriend(game, first="u1", second="u2"):
    low, high = sorted((first, second))
    sql(game[1], "DELETE FROM friend_links WHERE user_low=? AND user_high=?", (low, high))


def account(game, play, user="u1", species="青鸾", name=None):
    play("adopt", species, user=user)
    if name:
        sql(game[1], "UPDATE pets SET name=? WHERE user_id=?", (name, user))


def two_players(game, play):
    """Both accounts exist; the tuple is (u2's UID, u1's UID) so `owner` means the lender."""
    account(game, play, "u1", "青鸾", "小青")
    account(game, play, "u2", "玄狐", "小玄")
    return player_uid(game[1], "u2"), player_uid(game[1], "u1")


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones, active_pet_id FROM players ORDER BY user_id"),
        sql(game[1], "SELECT pet_id, species_id, name, realm, layer, energy FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
        sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress"
                     " WHERE quest_id NOT LIKE 'lend_%' AND quest_id NOT LIKE 'borrow%'"
                     " ORDER BY user_id, quest_id"),
    )


def keys(game, user):
    return {row["quest_id"]: row["progress"] for row in sql(
        game[1], "SELECT quest_id, progress FROM quest_progress WHERE user_id=?", (user,),
    )}


# ---------------------------------------------------------------- rules

def test_rule_is_wired_and_bounded(game):
    rule = game[0].content.rules.borrow
    assert 0 < rule.rate <= 0.25
    assert 1 <= rule.keep_days <= 30


def test_rule_model_rejects_out_of_range_values():
    from nonebot_plugin_spirit_pet.domain.content import BorrowRule

    with pytest.raises(ValidationError):
        BorrowRule.model_validate({"rate": 0, "keep_days": 7})
    with pytest.raises(ValidationError):
        BorrowRule.model_validate({"rate": 0.9, "keep_days": 7})
    with pytest.raises(ValidationError):
        BorrowRule.model_validate({"rate": 0.1, "keep_days": 0})


def test_borrowing_may_not_outshine_the_support_roster(tmp_path):
    """One borrowed friend must not be worth more than every bench slot together."""
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    rules = json.loads((target / "rules.json").read_text(encoding="utf-8"))
    rules["borrow"]["rate"] = round(rules["support"]["rate"] * rules["support"]["slots"] + 0.05, 2)
    (target / "rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds the support roster"):
        Catalog.load(target)


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("borrow", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []


# ---------------------------------------------------------------- lending

def test_lending_writes_one_expiring_row(game, play):
    account(game, play)
    pet_id = pet(game[1])["pet_id"]
    reply = play("borrow", f"出借 {pet_id}")
    assert "已挂出" in reply.text()
    stored = keys(game, "u1")
    assert stored[f"lend_{pet_id}"] == NOW + 7 * DAY
    assert len(stored) == 1


def test_lending_refuses_an_archived_pet(game, play):
    account(game, play)
    pet_id = add_pet(game, "u1", "xuanhu", "小玄", archived=1)
    before = keys(game, "u1")
    with pytest.raises(GameError, match="已封存"):
        play("borrow", f"出借 {pet_id}")
    assert keys(game, "u1") == before


def test_lending_refuses_a_pet_on_an_expedition(game, play):
    account(game, play)
    pet_id = pet(game[1])["pet_id"]
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', ?, 'task', '任务', 'lend-op', ?, ?, 'running', '{}', 0)",
        (pet_id, NOW, NOW + 600),
    )
    before = keys(game, "u1")
    with pytest.raises(GameError, match="正在外出派遣"):
        play("borrow", f"出借 {pet_id}")
    assert keys(game, "u1") == before


def test_lending_refuses_a_pet_you_do_not_own(game, play):
    account(game, play, "u1")
    account(game, play, "u2")
    other = add_pet(game, "u2", "xuanhu", "小玄")
    with pytest.raises(GameError, match="没有属于你的这只灵宠"):
        play("borrow", f"出借 {other}")


def test_withdrawing_removes_the_offer_and_twice_is_refused(game, play):
    account(game, play)
    pet_id = pet(game[1])["pet_id"]
    play("borrow", f"出借 {pet_id}")
    assert "已收回" in play("borrow", f"收回 {pet_id}").text()
    assert f"lend_{pet_id}" not in keys(game, "u1")
    before = keys(game, "u1")
    with pytest.raises(GameError, match="没有挂出"):
        play("borrow", f"收回 {pet_id}")
    assert keys(game, "u1") == before


# ---------------------------------------------------------------- borrowing

def test_borrowing_needs_friendship(game, play):
    owner, _ = two_players(game, play)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    before = keys(game, "u1")
    with pytest.raises(GameError, match="只能借用好友的伙伴"):
        play("borrow", f"借用 {owner} {target}")
    assert keys(game, "u1") == before


def test_borrowing_your_own_pet_is_refused(game, play):
    account(game, play)
    pet_id = pet(game[1])["pet_id"]
    uid = player_uid(game[1], "u1")
    play("borrow", f"出借 {pet_id}")
    with pytest.raises(GameError, match="不能借用自己"):
        play("borrow", f"借用 {uid} {pet_id}")


def test_borrowing_a_pet_that_is_not_on_offer_is_refused(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    before = snapshot(game)
    with pytest.raises(GameError, match="没有被挂出"):
        play("borrow", f"借用 {owner} {target}")
    assert snapshot(game) == before


def test_an_expired_offer_cannot_be_borrowed(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    later = NOW + 8 * DAY
    with pytest.raises(GameError, match="已经到期"):
        play("borrow", f"借用 {owner} {target}", now=later)


def test_borrowing_an_archived_pet_is_refused(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = add_pet(game, "u2", "baize", "小白")
    play("borrow", f"出借 {target}", user="u2")
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (target,))
    with pytest.raises(GameError, match="已封存"):
        play("borrow", f"借用 {owner} {target}")


def test_borrowing_without_an_active_pet_is_refused(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    with pytest.raises(GameError, match="请先选择出战伙伴"):
        play("borrow", f"借用 {owner} {target}")


def test_a_successful_borrow_writes_two_rows_and_grants_the_rate(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    without = stats(game)
    reply = play("borrow", f"借用 {owner} {target}")
    assert "已借来" in reply.text()
    stored = keys(game, "u1")
    assert stored[borrow.BORROW_PET] == target
    assert stored[borrow.BORROW_UNTIL] == NOW + 7 * DAY

    with closing(context(game).repo.conn):
        base = pet_stats(context(game).repo.pet(target), game[0].content)
    rate = game[0].content.rules.borrow.rate
    after = stats(game)
    for key in ("hp", "attack", "defense", "speed"):
        assert getattr(after, key) == getattr(without, key) + int(getattr(base, key) * rate)


def test_the_bonus_only_touches_the_active_pet(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    bench = add_pet(game, "u1", "baize", "小白")
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    with closing(context(game).repo.conn):
        before_bench = combatant(context(game), pet_id=bench).stats
    before_active = stats(game)
    play("borrow", f"借用 {owner} {target}")
    with closing(context(game).repo.conn):
        after_bench = combatant(context(game), pet_id=bench).stats
        boost = borrow.bonus(context(game))
    assert any(boost.values())
    assert after_bench == before_bench, "a benched pet must not receive a borrowed bonus"
    assert stats(game).hp > before_active.hp


def test_no_borrow_means_no_bonus(game, play):
    account(game, play)
    with closing(context(game).repo.conn):
        assert borrow.bonus(context(game)) == {"hp": 0, "attack": 0, "defense": 0, "speed": 0}
        assert borrow.current(context(game)) is None


# ---------------------------------------------------------------- invalidation

def test_unfriending_kills_the_bonus_without_cleanup(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    assert stats(game).hp > 0
    boosted = stats(game)
    unfriend(game)
    with closing(context(game).repo.conn):
        assert borrow.current(context(game)) is None
    assert stats(game).hp < boosted.hp
    # The intent rows are still there; only the derived validity changed.
    assert keys(game, "u1")[borrow.BORROW_PET] == target


def test_refriending_restores_the_bonus_while_the_offer_stands(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    boosted = stats(game)
    unfriend(game)
    befriend(game)
    assert stats(game) == boosted


def test_the_offer_expiring_kills_the_bonus(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    later = NOW + 7 * DAY + 1
    with closing(context(game, now=later).repo.conn):
        assert borrow.current(context(game, now=later)) is None


def test_the_lender_withdrawing_kills_the_bonus(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    play("borrow", f"收回 {target}", user="u2")
    with closing(context(game).repo.conn):
        assert borrow.current(context(game)) is None


def test_sending_the_lent_pet_away_kills_the_bonus(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u2', ?, 'task', '任务', 'away-op', ?, ?, 'running', '{}', 0)",
        (target, NOW, NOW + 600),
    )
    with closing(context(game).repo.conn):
        assert borrow.current(context(game)) is None


def test_returning_clears_both_rows_and_twice_is_refused(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    assert "已归还" in play("borrow", "归还").text()
    stored = keys(game, "u1")
    assert borrow.BORROW_PET not in stored and borrow.BORROW_UNTIL not in stored
    with pytest.raises(GameError, match="没有借来"):
        play("borrow", "归还")


def test_borrowing_a_second_pet_replaces_the_first_and_says_so(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    first = pet(game[1], "u2")["pet_id"]
    second = add_pet(game, "u2", "baize", "小白")
    play("borrow", f"出借 {first}", user="u2")
    play("borrow", f"出借 {second}", user="u2")
    play("borrow", f"借用 {owner} {first}")
    reply = play("borrow", f"借用 {owner} {second}")
    assert "已替换" in reply.text()
    assert keys(game, "u1")[borrow.BORROW_PET] == second


# ---------------------------------------------------------------- no side effects

def test_borrowing_writes_no_rewards_records_or_progress(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    before = snapshot(game)
    play("borrow", f"借用 {owner} {target}")
    assert snapshot(game) == before
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"] == 0


def test_state_survives_a_restart(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    play("borrow", f"借用 {owner} {target}")
    boosted = stats(game)
    Store(game[1].path).initialize()
    assert stats(game) == boosted
    assert "已借来" not in play("borrow").text()


# ---------------------------------------------------------------- surfaces

def test_page_shows_offers_borrowed_pet_and_friends_stock(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = add_pet(game, "u2", "baize", "小白")
    play("borrow", f"出借 {target}", user="u2")
    page = play("borrow")
    assert "好友挂出的伙伴" in page.text()
    assert "小白" in page.text()
    borrow_links = [link for link in page.inline_commands if link.label == "借用"]
    assert borrow_links and borrow_links[0].command == f"灵宠借力 借用 {owner} {target}"

    play("borrow", f"借用 {owner} {target}")
    page = play("borrow")
    assert "当前借来" in page.text()
    assert any(link.label == "归还" for link in page.inline_commands)


def test_page_empty_states_are_honest(game, play):
    account(game, play)
    page = play("borrow")
    assert "当前没有借来的伙伴" in page.text()
    assert "还没有挂出伙伴" in page.text()
    assert "没有可借的好友伙伴" in page.text()


def test_objectives_row_reports_lends_and_borrows(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = pet(game[1], "u2")["pet_id"]
    play("borrow", f"出借 {target}", user="u2")
    line = next(row for row in play("objectives").lines if row.startswith("借力："))
    assert "挂出 0 只 · 未借入" in line
    play("borrow", f"借用 {owner} {target}")
    line = next(row for row in play("objectives").lines if row.startswith("借力："))
    assert "借入" in line and f"挂出 0 只" in line


def test_help_and_parser_cover_the_command(game, play):
    account(game, play)
    assert _parse("灵宠借力") == ("borrow", "")
    assert _parse("灵宠借力 出借 3") == ("borrow", "出借 3")
    assert _parse("灵宠借力 借用 10001 3") == ("borrow", "借用 10001 3")
    # The parser forwards any argument; an unknown sub-verb is refused by the dispatcher.
    with pytest.raises(GameError, match="格式：灵宠借力"):
        play("borrow", "之后聊天")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["成长"]}
    assert "灵宠借力" in rows
    assert "灵宠借力 借用 UID 编号" in rows


def test_every_rendered_link_reparses(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = add_pet(game, "u2", "baize", "小白")
    play("borrow", f"出借 {target}", user="u2")
    for action, arg in (("borrow", ""), ("borrow", f"借用 {owner} {target}")):
        page = play(action, arg)
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    owner, _ = two_players(game, play)
    befriend(game)
    target = add_pet(game, "u2", "baize", "小白")
    play("borrow", f"出借 {target}", user="u2")
    page = play("borrow")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_the_onebot_text_page_spells_the_command(game, play):
    account(game, play)
    rendered = _qq_segments(play("borrow"), Config(spirit_pet_qq_mode="text"))[0]
    assert "借力（/灵宠借力）" in rendered
