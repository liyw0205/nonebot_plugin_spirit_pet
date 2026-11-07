"""灵宠演武: a zero-cost trial fight against a wooden dummy."""

import json
import re
import shutil
from contextlib import closing
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.drill_content import DrillDummy
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import drill
from nonebot_plugin_spirit_pet.gameplay.combat import Fighter, fight
from nonebot_plugin_spirit_pet.gameplay.loadout import combatants
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import player, sql

NOW = 1_800_000_000
DAY = 86400


def account(game, play, user="u1", species="青鸾"):
    play("adopt", species, user=user)


def snapshot(game):
    """Everything a drill must leave byte-identical."""
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT pet_id, energy, exp, affinity FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
        sql(game[1], "SELECT * FROM pve_stage_progress ORDER BY user_id, stage_id"),
        sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress"
                     " WHERE quest_id NOT LIKE 'drill_%' ORDER BY user_id, quest_id"),
    )


def drills(game):
    return sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress"
                        " WHERE quest_id LIKE 'drill_%' ORDER BY quest_id")


def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit(directory, name, change):
    path = directory / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- content

def test_seven_dummies_load_in_realm_order(game):
    dummies = drill.dummies(game[0])
    assert len(dummies) == 7
    assert [dummy.order for dummy in dummies] == [1, 2, 3, 4, 5, 6, 7]
    realms = [realm.id for realm in game[0].content.realms]
    orders = [realms.index(dummy.realm) for dummy in dummies]
    assert orders == sorted(orders), "dummies must be ordered from the lowest realm up"
    assert len({dummy.name for dummy in dummies}) == 7


def test_every_dummy_names_a_known_realm_and_element(game):
    realms = {realm.id for realm in game[0].content.realms}
    elements = set(game[0].content.elements)
    for dummy in drill.dummies(game[0]):
        assert dummy.realm in realms
        assert dummy.primary_element in dummy.elements
        assert set(dummy.elements) <= elements


def test_a_dummy_with_an_unknown_realm_is_rejected(tmp_path):
    directory = content_dir(tmp_path)

    def change(data):
        data[0]["realm"] = "not_a_realm"

    edit(directory, "drills.json", change)
    with pytest.raises(ValueError, match="unknown realm"):
        Catalog.load(directory)


def test_a_dummy_whose_primary_is_not_its_element_is_rejected():
    with pytest.raises(ValidationError, match="primary element must be one of its elements"):
        DrillDummy.model_validate({
            "id": "bad_post", "name": "怪桩", "description": "x", "realm": "qiling",
            "stats": {"hp": 10, "attack": 1, "defense": 0, "speed": 1},
            "elements": ["wood"], "primary_element": "fire", "order": 1,
        })


def test_a_dummy_with_an_unknown_element_is_rejected(tmp_path):
    directory = content_dir(tmp_path)

    def change(data):
        data[0]["elements"] = ["wood", "not_an_element"]
        data[0]["primary_element"] = "wood"

    edit(directory, "drills.json", change)
    with pytest.raises(ValueError, match="unknown element"):
        Catalog.load(directory)


def test_duplicate_order_and_duplicate_name_are_rejected(tmp_path):
    # `_index` rejects duplicate names for every content file, so a repeated name never
    # reaches `_validate_drills`; a repeated `order` is drill-specific and is caught there.
    for mutate, message in (
        (lambda data: data[1].update(order=1), "repeats order"),
        (lambda data: data[1].update(name=data[0]["name"]), "duplicate content"),
    ):
        directory = content_dir(tmp_path / message.replace(" ", "_"))
        edit(directory, "drills.json", mutate)
        with pytest.raises(ValueError, match=message):
            Catalog.load(directory)


def test_a_zero_speed_dummy_is_rejected():
    with pytest.raises(ValidationError):
        DrillDummy.model_validate({
            "id": "slow_post", "name": "死桩", "description": "x", "realm": "qiling",
            "stats": {"hp": 10, "attack": 1, "defense": 0, "speed": 0},
            "elements": ["wood"], "primary_element": "wood", "order": 1,
        })


def test_drill_rule_is_wired_and_bounded(game):
    rule = game[0].content.rules.drill
    assert 1 <= rule.daily_attempts <= 10


def test_rule_model_enforces_bounds():
    from nonebot_plugin_spirit_pet.domain.content import DrillRule

    with pytest.raises(ValidationError):
        DrillRule.model_validate({"daily_attempts": 0})
    with pytest.raises(ValidationError):
        DrillRule.model_validate({"daily_attempts": 11})


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("drill", user="ghost")
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert drills(game) == []


# ---------------------------------------------------------------- catalog

def test_catalog_lists_dummies_and_remaining_attempts(game, play):
    account(game, play)
    entries = drill.dummies(game[0])
    pages = max(1, (len(entries) + drill.PAGE_SIZE - 1) // drill.PAGE_SIZE)
    page = play("drill")
    assert "今日演武 0/5 次" in page.text()
    assert f"第 1/{pages} 页" in page.text()
    # A page shows PAGE_SIZE dummies; every dummy is reachable across the pages.
    for dummy in entries:
        assert dummy.name in page.text() or pages > 1
    assert len(page.inline_commands) == min(len(entries), drill.PAGE_SIZE)
    assert page.inline_commands[0].command == "灵宠演武 柴木桩"


def test_catalog_hides_the_entry_once_the_day_is_spent(game, play):
    account(game, play)
    for _ in range(game[0].content.rules.drill.daily_attempts):
        play("drill", "柴木桩")
    page = play("drill")
    assert "今日演武次数已用完" in page.text()
    assert page.inline_commands == ()


# ---------------------------------------------------------------- running

def test_a_drill_charges_nothing_and_records_nothing(game, play):
    account(game, play)
    before = snapshot(game)
    reply = play("drill", "柴木桩")
    assert reply.title == "演武 · 柴木桩"
    assert "回合" in reply.text()
    assert snapshot(game) == before, "a drill must not touch energy, purse, bag or any counter"
    stored = drills(game)
    assert len(stored) == 1
    assert stored[0]["quest_id"] == f"{drill.DRILL_PREFIX}{beijing_day(NOW)}"
    assert stored[0]["progress"] == 1


def test_the_drill_reports_each_pet_remaining_health(game, play):
    account(game, play)
    reply = play("drill", "柴木桩")
    line = next(line for line in reply.lines if line.startswith("青鸾"))
    match = re.search(r"气血 (\d+)/(\d+) · 承伤 (\d+)", line)
    assert match is not None, line
    left, total, taken = (int(group) for group in match.groups())
    assert left + taken == total


def test_name_and_order_select_the_same_dummy(game, play):
    account(game, play)
    by_name = play("drill", "柴木桩")
    by_order = play("drill", "1")
    assert by_name.title == by_order.title == "演武 · 柴木桩"


def test_the_drill_uses_the_real_lineup_and_the_real_engine(game, play, tmp_path):
    """The drill must fight with the lineup's own fighters, not a stripped copy."""
    from nonebot_plugin_spirit_pet.storage.database import Store

    account(game, play)
    reply = play("drill", "柴木桩")
    expected_rounds = int(re.search(r"(\d+) 回合", reply.text()).group(1))

    # Rebuild the same starting state and ask the engine directly.
    fresh = Store(tmp_path / "replay" / "spirit.db")
    fresh.initialize()
    replay = Game(fresh, Config(), game[0].rng)
    replay.execute("u1", "adopt", "青鸾", "replay-adopt", NOW)
    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    context = Context(
        Repository(fresh.connect()), replay.content, Config(), replay.rng, "u1", NOW, "probe",
    )
    battle = fight(
        combatants(context, recover_energy=False),
        [drill._dummy_fighter(context, drill.dummies(game[0])[0])],
        replay.rng, replay.content.elements,
    )
    assert battle.rounds == expected_rounds


def test_the_daily_cap_refuses_without_writing(game, play):
    account(game, play)
    rule = game[0].content.rules.drill
    for _ in range(rule.daily_attempts):
        play("drill", "柴木桩")
    before = snapshot(game)
    stored = drills(game)
    with pytest.raises(GameError, match=f"今日演武已达 {rule.daily_attempts} 次"):
        play("drill", "柴木桩")
    assert snapshot(game) == before
    assert drills(game) == stored


def test_the_cap_resets_the_next_day(game, play):
    account(game, play)
    rule = game[0].content.rules.drill
    for _ in range(rule.daily_attempts):
        play("drill", "柴木桩")
    assert play("drill", "柴木桩", now=NOW + DAY).title == "演武 · 柴木桩"
    assert len(drills(game)) == 2


def test_refusals_leave_no_trace(game, play):
    account(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="没有这座木人桩"):
        play("drill", "不存在之桩")
    with pytest.raises(GameError, match="演武场只有"):
        play("drill", "99")
    # A player who never adopted is refused before anything is written.
    with pytest.raises(GameError, match="还没有灵宠伙伴"):
        play("drill", "柴木桩", user="u2")
    assert snapshot(game) == before
    assert drills(game) == []
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='u2'") == []


def test_a_pet_on_an_expedition_cannot_drill(game, play):
    account(game, play)
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', ?, 'task', '任务', 'drill-op', ?, ?, 'running', '{}', 0)",
        (pet_id, NOW, NOW + 600),
    )
    before = snapshot(game)
    with pytest.raises(GameError, match="正在外出派遣"):
        play("drill", "柴木桩")
    assert drills(game) == []
    assert snapshot(game) == before


def test_replaying_one_operation_runs_one_drill(game, play):
    account(game, play)
    first = play("drill", "柴木桩", op="once")
    second = play("drill", "柴木桩", op="once")
    assert first.text() == second.text()
    assert drills(game)[0]["progress"] == 1


def test_a_drill_is_invisible_to_objectives_except_its_own_line(game, play):
    account(game, play)
    before = [line for line in play("objectives").lines if not line.startswith("演武")]
    play("drill", "柴木桩")
    after = [line for line in play("objectives").lines if not line.startswith("演武")]
    assert after == before


def test_objectives_row_reports_the_drill_quota(game, play):
    account(game, play)
    line = next(line for line in play("objectives").lines if line.startswith("演武："))
    assert line == "演武：今日 0/5 次"
    play("drill", "柴木桩")
    line = next(line for line in play("objectives").lines if line.startswith("演武："))
    assert line == "演武：今日 1/5 次"


# ---------------------------------------------------------------- surfaces

def test_help_and_parser_cover_the_drill(game, play):
    account(game, play)
    assert _parse("灵宠演武") == ("drill", "")
    assert _parse("灵宠演武 柴木桩") == ("drill", "柴木桩")
    assert _parse("灵宠演武 1") == ("drill", "1")
    assert _parse("灵宠演武 名单") == ("drill", "名单")
    assert _parse("灵宠演武 名单 2") == ("drill", "名单 2")
    assert _parse("灵宠演武之后聊天") is None

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["秘境与关卡"]}
    assert "灵宠演武" in rows and "灵宠演武 木人桩" in rows and "灵宠演武 名单" in rows


def test_every_rendered_link_reparses(game, play):
    account(game, play)
    for argument in ("", "名单"):
        page = play("drill", argument)
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None
    # A page beyond the ladder is refused rather than rendered empty.
    entries = drill.dummies(game[0])
    pages = max(1, (len(entries) + drill.PAGE_SIZE - 1) // drill.PAGE_SIZE)
    with pytest.raises(GameError, match=f"共 {pages} 页"):
        play("drill", f"名单 {pages + 1}")


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    account(game, play)
    page = play("drill")
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
    rendered = _qq_segments(page, Config(spirit_pet_qq_mode="text"))[0]
    assert "演武（/灵宠演武 柴木桩）" in rendered


def test_the_onebot_text_page_spells_the_dummy_name(game, play):
    account(game, play)
    reply = play("drill", "柴木桩")
    rendered = _qq_segments(reply, Config(spirit_pet_qq_mode="text"))[0]
    assert "【演武 · 柴木桩】" in rendered
    assert "不耗精力" in rendered
