"""Daily mentor lessons: one master action per apprentice per Beijing day."""

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.content import MentorLessonRule
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import mentorship

from .support import player, player_uid, sql

NOW = 1_800_000_000
DAY = 86_400
HOUR = 3_600


def pair(game, play, mentor_realm=3):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    sql(game[1], "UPDATE pets SET realm=? WHERE user_id='u1'", (mentor_realm,))
    mentor, apprentice = player_uid(game[1], "u1"), player_uid(game[1], "u2")
    play("mentorship", str(mentor), user="u2")
    play("mentorship", f"同意 {apprentice}", user="u1")
    return mentor, apprentice


def pet_row(game, user="u1"):
    return sql(game[1], "SELECT * FROM pets WHERE user_id=?", (user,))[0]


def lesson_rows(game, mentor="u1", now=NOW):
    from nonebot_plugin_spirit_pet.utils.time import beijing_day
    return sql(
        game[1],
        "SELECT quest_id, progress FROM quest_progress WHERE user_id=? AND quest_id LIKE ? ORDER BY quest_id",
        (mentor, f"{mentorship.LESSON}{beijing_day(now)}_%"),
    )


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, stones FROM players ORDER BY user_id"),
        sql(game[1], "SELECT pet_id, energy, exp FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, quest_id, progress FROM quest_progress ORDER BY user_id, quest_id"),
    )


def test_lesson_rule_is_wired_and_bounded(game):
    lesson = game[0].content.rules.mentor.lesson
    assert (lesson.energy, lesson.exp, lesson.stones, lesson.daily_limit) == (10, 30, 20, 3)
    with pytest.raises(Exception):
        MentorLessonRule.model_validate({"energy": 0, "exp": 1, "stones": 0, "daily_limit": 1})
    with pytest.raises(Exception):
        MentorLessonRule.model_validate({"energy": 1, "exp": 1, "stones": 0, "daily_limit": 0})


def test_lesson_page_is_read_only_before_adoption(game, play):
    page = play("mentorship", "传道", user="ghost")
    assert page.title == "灵宠师徒"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players WHERE user_id='ghost'") == []


def test_mentor_page_links_to_the_lesson_page(game, play):
    mine, _ = pair(game, play)
    page = play("mentorship", user="u1")
    assert "今日传道 0/3 次" in page.text()
    assert any(link.command == "灵宠师徒 传道" for link in page.inline_commands)
    lesson_page = play("mentorship", "传道", user="u1")
    assert "徒弟 1/3 名" in lesson_page.text()
    assert "可传道" in lesson_page.text()
    assert "灵宠师徒 传道 10001" in [link.command for link in lesson_page.inline_commands]


def test_lesson_pays_the_apprentice_exp_and_master_stones(game, play):
    mine, _ = pair(game, play)
    master_pet = pet_row(game, "u1")
    apprentice_pet = pet_row(game, "u2")
    before_master = player(game[1], "u1")["stones"]
    reply = play("mentorship", "传道 10001", user="u1", op="lesson-1")
    assert "修为 +30" in reply.text()
    assert "灵石 +20" in reply.text()
    assert pet_row(game, "u1")["energy"] == master_pet["energy"] - 10
    assert pet_row(game, "u2")["exp"] == apprentice_pet["exp"] + 30
    assert player(game[1], "u1")["stones"] == before_master + 20
    assert lesson_rows(game) == [{
        "quest_id": mentorship.lesson_key(NOW, "u2"),
        "progress": 1,
    }]


def test_same_pair_can_lesson_once_per_day(game, play):
    pair(game, play)
    play("mentorship", "传道 10001", user="u1", op="lesson-a")
    before = snapshot(game)
    with pytest.raises(GameError, match="今日已经传过道"):
        play("mentorship", "传道 10001", user="u1", op="lesson-b")
    assert snapshot(game) == before


def test_master_daily_limit_is_three_across_apprentices(game, play):
    play("adopt", "青鸾", user="u1")
    sql(game[1], "UPDATE pets SET realm=3 WHERE user_id='u1'")
    for index in range(2, 6):
        play("adopt", "玄狐", user=f"u{index}")
    mentor = player_uid(game[1], "u1")
    for index in range(2, 5):
        play("mentorship", str(mentor), user=f"u{index}")
        play("mentorship", f"同意 {player_uid(game[1], f'u{index}')}", user="u1")
    # A fourth relation is impossible through the command (max 3); seed it only to
    # exercise the independent daily cap.
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', 'apprentice_u5', 1, 1)",
    )
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u5', 'mentorlink_u1', 1, 1)",
    )
    for index in range(2, 5):
        play("mentorship", f"传道 {player_uid(game[1], f'u{index}')}", user="u1", op=f"lesson-{index}")
    with pytest.raises(GameError, match="次数已用尽"):
        play("mentorship", f"传道 {player_uid(game[1], 'u5')}", user="u1", op="lesson-over")
    assert len(lesson_rows(game)) == 3


def test_next_beijing_day_resets_both_limits(game, play):
    pair(game, play)
    play("mentorship", "传道 10001", user="u1", op="lesson-day1")
    with pytest.raises(GameError, match="今日已经传过道"):
        play("mentorship", "传道 10001", user="u1", op="lesson-day1b", now=NOW + HOUR)
    play("mentorship", "传道 10001", user="u1", op="lesson-day2", now=NOW + DAY)
    assert len(lesson_rows(game, now=NOW + DAY)) == 1


def test_non_apprentice_self_unknown_and_graduated_are_refused(game, play):
    pair(game, play)
    play("adopt", "白泽", user="u3")
    before = snapshot(game)
    for argument in ("10002", "10000", "999999"):
        with pytest.raises(GameError, match="不是你的徒弟|不能与自己|没有找到"):
            play("mentorship", f"传道 {argument}", user="u1", op=f"bad-{argument}")
    assert snapshot(game) == before
    assert "门下暂无徒弟" not in play("mentorship", "传道", user="u1").text()


def test_no_active_pet_or_expedition_refuses_without_writing(game, play):
    pair(game, play)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    before = snapshot(game)
    with pytest.raises(GameError, match="出战伙伴|出战灵宠|没有出战"):
        play("mentorship", "传道 10001", user="u1", op="lesson-no-pet")
    assert snapshot(game) == before
    sql(game[1], "UPDATE players SET active_pet_id=(SELECT pet_id FROM pets WHERE user_id='u2') WHERE user_id='u2'")
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u2', (SELECT pet_id FROM pets WHERE user_id='u2'), 't', '任务', 'mentor-expedition',"
        " ?, ?, 'running', '{}', 0)",
        (NOW, NOW + 600),
    )
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣"):
        play("mentorship", "传道 10001", user="u1", op="lesson-trip")
    assert snapshot(game) == before


def test_master_energy_and_pet_expedition_refuse_without_writing(game, play):
    pair(game, play)
    sql(game[1], "UPDATE pets SET energy=5, energy_updated=? WHERE user_id='u1'", (NOW,))
    before = snapshot(game)
    with pytest.raises(GameError, match="精力不足"):
        play("mentorship", "传道 10001", user="u1", op="lesson-tired")
    assert snapshot(game) == before
    sql(game[1], "UPDATE pets SET energy=100 WHERE user_id='u1'")
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id,"
        " started_at, finishes_at, state, reward_snapshot, slot)"
        " VALUES ('u1', (SELECT pet_id FROM pets WHERE user_id='u1'), 't', '任务', 'mentor-master-trip',"
        " ?, ?, 'running', '{}', 0)",
        (NOW, NOW + 600),
    )
    before = snapshot(game)
    with pytest.raises(GameError, match="外出|派遣"):
        play("mentorship", "传道 10001", user="u1", op="lesson-master-trip")
    assert snapshot(game) == before


def test_lesson_is_idempotent_for_the_same_operation(game, play):
    pair(game, play)
    first = play("mentorship", "传道 10001", user="u1", op="lesson-same")
    before = snapshot(game)
    again = play("mentorship", "传道 10001", user="u1", op="lesson-same")
    assert again.text() == first.text()
    assert snapshot(game) == before


def test_lesson_survives_restart_and_resets_next_day(game, play):
    pair(game, play)
    play("mentorship", "传道 10001", user="u1", op="lesson-persist")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store
    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    page = restarted.execute("u1", "mentorship", "传道", "restart-lesson", NOW + HOUR)
    assert "今日传道 1/3 次" in page.text()
    with pytest.raises(GameError, match="今日已经传过道"):
        restarted.execute("u1", "mentorship", "传道 10001", "restart-lesson-2", NOW + HOUR)
    restarted.execute("u1", "mentorship", "传道 10001", "restart-lesson-3", NOW + DAY)


def test_lesson_page_is_read_only(game, play):
    pair(game, play)
    before = snapshot(game)
    play("mentorship", "传道", user="u1")
    assert snapshot(game) == before


def test_help_and_parse_cover_lesson(game, play):
    pair(game, play)
    assert _parse("灵宠师徒 传道") == ("mentorship", "传道")
    assert _parse("灵宠师徒 传道 10001") == ("mentorship", "传道 10001")
    guide = play("help", "组队与派遣")
    assert "灵宠师徒 传道" in guide.text()
    assert "灵宠师徒 传道 徒弟UID" in guide.text()


def test_native_payload_has_no_button_link_overlap(game, play):
    pair(game, play)
    page = play("mentorship", "传道", user="u1")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert not buttons & {link.command for link in page.inline_commands}
