import sqlite3
from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.skill_mastery_rewards import CLAIM_PREFIX, claim_id

from .support import items, pet, player, sql

NOW = 1_800_000_000


def add_pet(game, *, user="u1", species="qingluan", name="备用伙伴"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        (user, species, name, NOW),
    )
    return sql(game[1], "SELECT pet_id FROM pets WHERE user_id=? AND name=?", (user, name))[0]["pet_id"]


def add_skill(game, pet_id, skill_id="wind_slash", *, level=5, proficiency=0):
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level, proficiency) VALUES (?, ?, 0, ?, ?)",
        (pet_id, skill_id, level, proficiency),
    )


def test_routes_and_unregistered_browsing_are_read_only(game, play):
    assert COMMANDS["灵宠灵术赏"] == "skill_mastery_rewards"
    assert COMMANDS["灵宠灵术领奖"] == "skill_mastery_claim"
    assert handlers._parse("灵宠灵术领奖 17 风刃术") == ("skill_mastery_claim", "17 风刃术")

    listing = play("skill_mastery_rewards", user="u9")
    assert listing.title == "灵宠灵术赏 1/1"
    assert listing.inline_commands[0].command == "灵宠领养 "
    assert not sql(game[1], "SELECT * FROM players")
    with pytest.raises(GameError, match="先完成领养"):
        play("skill_mastery_claim", "1 风刃术", user="u9")


def test_catalog_pages_each_owned_pet_skill_and_native_claim_link(game, play):
    play("adopt", "青鸾")
    active_id = pet(game[1])["pet_id"]
    skill_ids = list(game[0].content.skills)[:6]
    for skill_id in skill_ids:
        add_skill(game, active_id, skill_id)

    first = play("skill_mastery_rewards")
    assert first.title == "灵宠灵术赏 1/2"
    assert len(first.inline_commands) == 5
    assert all(link.command.startswith("灵宠灵术领奖 ") for link in first.inline_commands)
    _, message = _qq_segments(first, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert not buttons & {link.command for link in first.inline_commands}

    second = play("skill_mastery_rewards", "2")
    assert second.title == "灵宠灵术赏 2/2"
    assert len(second.inline_commands) == 1
    with pytest.raises(GameError, match="共 2 页"):
        play("skill_mastery_rewards", "3")


def test_archived_pet_mastery_remains_reviewable_and_claimable(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    add_skill(game, pet_id)
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (pet_id,))

    listing = play("skill_mastery_rewards")
    assert any(
        line.startswith(f"灵宠 {pet_id} · 青鸾 · 已封存 · 风刃术 · 五阶精通 · 奖励：")
        and line.endswith("· 可领取")
        for line in listing.lines
    )
    assert [link.command for link in listing.inline_commands] == [
        f"灵宠灵术领奖 {pet_id} 风刃术",
    ]

    before = player(game[1])["stones"]
    result = play("skill_mastery_claim", f"{pet_id} 风刃术")
    assert result.title == "灵术精进奖励"
    assert player(game[1])["stones"] == before + 120


def test_claim_is_specific_to_pet_and_skill_and_drives_master_title(game, play):
    play("adopt", "青鸾")
    first_pet_id = pet(game[1])["pet_id"]
    second_pet_id = add_pet(game, name="第二只青鸾")
    add_skill(game, first_pet_id)
    add_skill(game, second_pet_id)
    for index in range(6):
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
            (claim_id(9000 + index, f"legacy_skill_{index}"),),
        )
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 1)",
        (CLAIM_PREFIX + "noise",))
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES ('u1', ?, 1, 0)",
        (claim_id(9010, "unclaimed_skill"),))

    stones_before = player(game[1])["stones"]
    books_before = items(game[1]).get("book_wind_slash", 0)
    command = f"{first_pet_id} 风刃术"
    link = play("skill_mastery_rewards").inline_commands[0]
    assert link.command == f"灵宠灵术领奖 {command}"
    first = play("skill_mastery_claim", command, op="first-mastery-claim")
    assert first.title == "灵术精进奖励"
    assert player(game[1])["stones"] == stones_before + 120
    assert items(game[1])["book_wind_slash"] == books_before + 1
    assert sql(game[1], "SELECT progress, claimed FROM quest_progress WHERE user_id='u1' AND quest_id=?",
               (claim_id(first_pet_id, "wind_slash"),)) == [{"progress": 1, "claimed": 1}]
    assert play("skill_mastery_claim", command, op="first-mastery-claim") == first
    with pytest.raises(GameError, match="已领取"):
        play("skill_mastery_claim", command)

    second = play("skill_mastery_claim", f"{second_pet_id} 风刃术")
    assert "灵石 +120" in second.text()
    assert sql(game[1], "SELECT COUNT(*) AS total FROM quest_progress WHERE user_id='u1' AND claimed=1 "
                       "AND substr(quest_id, 1, ?) = ?", (len(CLAIM_PREFIX), CLAIM_PREFIX)) == [{"total": 9}]
    title_page = play("titles", "5")
    assert "21. 万法宗师 · 已获得 · 领取八份灵术精进奖励。" in title_page.text()
    assert "当前称号：万法宗师 · 已获得 4/23 项" in title_page.text()


def test_unlearned_unmastered_foreign_and_stale_entries_are_rejected(game, play):
    play("adopt", "青鸾")
    owner_pet = pet(game[1])["pet_id"]
    play("adopt", "玄狐", user="u2")
    other_pet = pet(game[1], "u2")["pet_id"]
    with pytest.raises(GameError, match="没有这只属于你的已学灵术的灵宠"):
        play("skill_mastery_claim", f"{owner_pet} 风刃术")
    add_skill(game, owner_pet, level=4, proficiency=0)
    stale = play("skill_mastery_rewards").inline_commands
    assert stale == ()
    with pytest.raises(GameError, match="尚未达到五阶精通"):
        play("skill_mastery_claim", f"{owner_pet} 风刃术")

    add_skill(game, other_pet)
    with pytest.raises(GameError, match="没有这只属于你的已学灵术的灵宠"):
        play("skill_mastery_claim", f"{other_pet} 风刃术")
    with pytest.raises(GameError, match="格式"):
        play("skill_mastery_claim", str(owner_pet))


def test_missing_book_definition_and_bad_level_do_not_offer_or_grant(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    add_skill(game, pet_id)
    original = game[0].content
    missing_items = dict(original.items)
    missing_items.pop("book_wind_slash")
    game[0].content = replace(original, items=missing_items)
    assert play("skill_mastery_rewards").inline_commands == ()
    with pytest.raises(GameError, match="秘笈定义缺失"):
        play("skill_mastery_claim", f"{pet_id} 风刃术")
    game[0].content = original

    sql(game[1], "UPDATE learned_skills SET level=99 WHERE pet_id=? AND skill_id='wind_slash'", (pet_id,))
    assert "需检查存档" in play("skill_mastery_rewards").text()
    with pytest.raises(GameError, match="等级记录异常"):
        play("skill_mastery_claim", f"{pet_id} 风刃术")


def test_claim_persistence_failure_rolls_back_resources_and_allows_retry(game, play):
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    add_skill(game, pet_id)
    before_player, before_items = player(game[1]), items(game[1])
    marker = claim_id(pet_id, "wind_slash")
    sql(game[1],
        "CREATE TRIGGER reject_skill_mastery_claim BEFORE INSERT ON quest_progress "
        f"WHEN NEW.quest_id='{marker}' BEGIN SELECT RAISE(ABORT, 'injected mastery reward failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected mastery reward failure"):
        play("skill_mastery_claim", f"{pet_id} 风刃术", op="mastery-retry")
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id=?", (marker,)) == []
    assert player(game[1]) == before_player
    assert items(game[1]) == before_items

    sql(game[1], "DROP TRIGGER reject_skill_mastery_claim")
    result = play("skill_mastery_claim", f"{pet_id} 风刃术", op="mastery-retry")
    assert result.title == "灵术精进奖励"
    assert player(game[1])["stones"] == before_player["stones"] + 120


def test_help_and_objectives_expose_mastery_rewards(game, play):
    assert "灵宠灵术赏 页码" in play("help", "灵物与灵术").text()
    assert "灵宠灵术领奖 宠物编号 技能名" in play("help", "灵物与灵术").text()
    play("adopt", "青鸾")
    pet_id = pet(game[1])["pet_id"]
    add_skill(game, pet_id)
    hub = play("objectives")
    assert "灵术精进奖励：可领 1 项（青鸾·风刃术）· 五阶精通 1 项" in hub.text()
    assert hub.inline_commands[-3].command == "灵宠灵术赏"
    assert hub.inline_commands[-2].command == "灵宠亲密赏"
    assert hub.inline_commands[-1].command == "灵宠境界赏"
    play("skill_mastery_claim", f"{pet_id} 风刃术")
    assert "灵术精进奖励：暂无可领 · 五阶精通 1 项" in play("objectives").text()
