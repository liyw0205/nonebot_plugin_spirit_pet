"""灵宠师徒: request, accept, expel and graduate, with the once-only graduation payout."""

import json
import re
import shutil
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import mentorship

from .support import player, player_uid, sql

NOW = 1_800_000_000
HOUR = 3600
GRADUATE = 2  # 筑基 in the shipped realm ladder


def both(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    return player_uid(game[1], "u1"), player_uid(game[1], "u2")


def set_realm(game, user, index):
    sql(game[1], "UPDATE pets SET realm=? WHERE user_id=?", (index, user))


def links(game, user):
    return {
        row["quest_id"]: row["progress"]
        for row in sql(
            game[1],
            "SELECT quest_id, progress FROM quest_progress WHERE user_id=?"
            " AND (quest_id LIKE 'mentorlink_%' OR quest_id LIKE 'apprentice_%'"
            " OR quest_id LIKE 'mentorreq_%' OR quest_id='graduated')"
            " ORDER BY quest_id",
            (user,),
        )
    }


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT pet_id, realm, exp FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY user_id, quest_id"),
    )


# ---------------------------------------------------------------- rules

def test_the_rule_is_wired_and_bounded(game):
    rule = game[0].content.rules.mentor
    assert 1 <= rule.max_apprentices <= 5
    assert 1 <= rule.request_hours <= 72
    assert rule.graduate_realm in {realm.id for realm in game[0].content.realms}


def test_the_rule_model_rejects_out_of_range_values():
    from nonebot_plugin_spirit_pet.domain.content import MentorRule

    base = {
        "graduate_realm": "zhuji",
        "mentor_reward": {"exp": {"minimum": 0, "maximum": 0}, "stones": {"minimum": 1, "maximum": 1}, "items": {}},
        "apprentice_reward": {"exp": {"minimum": 0, "maximum": 0}, "stones": {"minimum": 1, "maximum": 1}, "items": {}},
    }
    with pytest.raises(ValidationError):
        MentorRule.model_validate({**base, "max_apprentices": 0, "request_hours": 24})
    with pytest.raises(ValidationError):
        MentorRule.model_validate({**base, "max_apprentices": 6, "request_hours": 24})
    with pytest.raises(ValidationError):
        MentorRule.model_validate({**base, "max_apprentices": 3, "request_hours": 0})


def test_the_catalog_rejects_an_unreachable_graduation_realm(tmp_path):
    for mutate, message in (
        (lambda data: data.update(graduate_realm="not_a_realm"), "does not exist"),
        (lambda data: data.update(graduate_realm="qiling"), "must not be the starting realm"),
    ):
        target = tmp_path / message.replace(" ", "_")
        shutil.copytree(DATA_DIR, target)
        rules = json.loads((target / "rules.json").read_text(encoding="utf-8"))
        mutate(rules["mentor"])
        (target / "rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            Catalog.load(target)


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("mentorship", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []


def test_opening_the_page_writes_nothing(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    before = snapshot(game)
    play("mentorship")
    play("mentorship", user="u2")
    assert snapshot(game) == before


# ---------------------------------------------------------------- asking

def test_an_apprentice_asks_a_stronger_mentor_and_gets_an_expiring_row(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    reply = play("mentorship", str(mine), user="u2")
    assert "拜师帖" in reply.text()
    rows = links(game, "u1")
    assert rows[f"{mentorship.REQUEST}u2"] == NOW + 24 * HOUR


def test_asking_a_peer_is_refused(game, play):
    mine, target = both(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="境界不高过你"):
        play("mentorship", str(mine), user="u2")
    assert snapshot(game) == before


def test_asking_yourself_or_a_stranger_is_refused(game, play):
    _, mine = both(game, play)
    with pytest.raises(GameError, match="不能与自己结为师徒"):
        play("mentorship", str(mine), user="u2")
    before = snapshot(game)
    with pytest.raises(GameError, match="没有找到这位玩家"):
        play("mentorship", "999999", user="u2")
    assert snapshot(game) == before


def test_a_player_who_already_reached_the_line_cannot_ask(game, play):
    mine, _ = both(game, play)
    set_realm(game, "u1", 3)
    set_realm(game, "u2", GRADUATE)
    with pytest.raises(GameError, match="无需再拜师"):
        play("mentorship", str(mine), user="u2")
    assert links(game, "u1") == {}


def test_a_full_mentor_cannot_take_another_apprentice(game, play):
    mine, _ = both(game, play)
    set_realm(game, "u1", 3)
    for index in range(game[0].content.rules.mentor.max_apprentices):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
            (f"{mentorship.APPRENTICE}ghost{index}",),
        )
    with pytest.raises(GameError, match="已收满"):
        play("mentorship", str(mine), user="u2")


def test_asking_twice_keeps_one_row(game, play):
    mine, _ = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2", now=NOW)
    play("mentorship", str(mine), user="u2", now=NOW + HOUR)
    rows = links(game, "u1")
    assert len(rows) == 1
    assert rows[f"{mentorship.REQUEST}u2"] == NOW + HOUR + 24 * HOUR


# ---------------------------------------------------------------- accepting

def test_accepting_writes_both_halves_and_drops_the_request(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    reply = play("mentorship", f"同意 {target}", user="u1")
    assert "师徒关系已成立" in reply.text()
    assert links(game, "u1") == {f"{mentorship.APPRENTICE}u2": 1}
    assert links(game, "u2") == {f"{mentorship.LINK}u1": 1}


def test_accepting_without_a_request_is_refused(game, play):
    mine, target = both(game, play)
    before = snapshot(game)
    with pytest.raises(GameError, match="没有来自该修士的拜师帖"):
        play("mentorship", f"同意 {target}", user="u1")
    assert snapshot(game) == before


def test_an_expired_request_cannot_be_accepted(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    before = snapshot(game)
    with pytest.raises(GameError, match="已经过期"):
        play("mentorship", f"同意 {target}", user="u1", now=NOW + 25 * HOUR)
    assert snapshot(game) == before


def test_rejecting_drops_the_request_only(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    assert "已退回" in play("mentorship", f"拒绝 {target}", user="u1").text()
    assert links(game, "u1") == {}
    assert links(game, "u2") == {}


def test_expelling_removes_both_halves(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    play("mentorship", f"同意 {target}", user="u1")
    assert "已解除" in play("mentorship", f"逐出 {target}", user="u1").text()
    assert links(game, "u1") == {}
    assert links(game, "u2") == {}


# ---------------------------------------------------------------- graduating

def test_graduating_below_the_line_is_refused_without_writing(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    play("mentorship", f"同意 {target}", user="u1")
    before = snapshot(game)
    with pytest.raises(GameError, match="需先到达筑基境"):
        play("mentorship", "出师", user="u2")
    assert snapshot(game) == before


def test_graduating_pays_both_sides_and_clears_the_relation(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    play("mentorship", f"同意 {target}", user="u1")
    set_realm(game, "u2", GRADUATE)
    before_mentor = player(game[1], "u1")["stones"]
    before_apprentice = player(game[1], "u2")["stones"]
    reply = play("mentorship", "出师", user="u2")
    assert "已出师" in reply.text()
    assert player(game[1], "u1")["stones"] == before_mentor + 300
    assert player(game[1], "u2")["stones"] == before_apprentice + 150
    assert links(game, "u1") == {}
    assert links(game, "u2") == {mentorship.GRADUATED: 1}


def test_a_graduated_player_cannot_ask_again(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    play("mentorship", f"同意 {target}", user="u1")
    set_realm(game, "u2", GRADUATE)
    play("mentorship", "出师", user="u2")
    set_realm(game, "u1", 4)
    with pytest.raises(GameError, match="已经出师"):
        play("mentorship", str(mine), user="u2")
    with pytest.raises(GameError, match="还没有师父"):
        play("mentorship", "出师", user="u2")


def test_graduating_does_not_need_the_other_side_online_or_idle(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    play("mentorship", f"同意 {target}", user="u1")
    set_realm(game, "u2", GRADUATE)
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1'")[0]["pet_id"]
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', ?, 'task', '任务', 'mentor-op', ?, ?, 'running', '{}', 0)",
        (pet_id, NOW, NOW + 600),
    )
    assert "已出师" in play("mentorship", "出师", user="u2").text()


# ---------------------------------------------------------------- surfaces

def test_the_page_lists_mentor_apprentices_and_requests(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    mentor_view = play("mentorship", user="u1")
    assert "待我处理的拜师帖" in mentor_view.text()
    labels = {link.label for link in mentor_view.inline_commands}
    assert {"同意", "拒绝"} <= labels
    play("mentorship", f"同意 {target}", user="u1")
    apprentice_view = play("mentorship", user="u2")
    assert "师父：" in apprentice_view.text()
    assert "徒弟 1/3 名" in play("mentorship", user="u1").text()


def test_every_rendered_link_reparses(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    for user in ("u1", "u2"):
        page = play("mentorship", user=user)
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None


def test_the_objectives_line_reports_the_relation(game, play):
    mine, target = both(game, play)
    set_realm(game, "u1", 3)
    line = next(row for row in play("objectives", user="u2").lines if row.startswith("师徒"))
    assert line == "师徒：尚未拜师"
    play("mentorship", str(mine), user="u2")
    play("mentorship", f"同意 {target}", user="u1")
    line = next(row for row in play("objectives", user="u2").lines if row.startswith("师徒"))
    assert line == "师徒：在 UID 10000 门下"
    line = next(row for row in play("objectives", user="u1").lines if row.startswith("师徒"))
    assert line == "师徒：门下 1/3 名徒弟"


def test_help_and_parser_cover_the_command(game, play):
    both(game, play)
    assert _parse("灵宠师徒") == ("mentorship", "")
    assert _parse("灵宠师徒 10000") == ("mentorship", "10000")
    assert _parse("灵宠师徒 出师") == ("mentorship", "出师")
    assert _parse("灵宠师徒 同意 10001") == ("mentorship", "同意 10001")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["组队与派遣"]}
    assert "灵宠师徒" in rows
    assert "灵宠师徒 出师" in rows


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    mine, _ = both(game, play)
    set_realm(game, "u1", 3)
    play("mentorship", str(mine), user="u2")
    page = play("mentorship", user="u1")
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
    both(game, play)
    rendered = _qq_segments(play("mentorship"), Config(spirit_pet_qq_mode="text"))[0]
    assert "【灵宠师徒】" in rendered
