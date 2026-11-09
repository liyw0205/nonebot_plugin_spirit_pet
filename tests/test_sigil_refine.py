"""Sigil refinement: ranks raise the flat bonus, costs are all-or-nothing."""

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from .support import sql

NOW = 1_800_000_000


def seed_claims(game, count, user="u1", offset=0):
    for index in range(offset, offset + count):
        sql(
            game[1],
            "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at,"
            " reward_snapshot, reply) VALUES (?, ?, ?, ?, '{}', 'seed')",
            (user, f"seed_{index}", f"seed-op-{user}-{index}", NOW),
        )


def set_stones(game, value, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (value, user))


def grant(game, item_id, amount, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id)"
        " DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


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


def unlock_first(game, play):
    """Adopt, unlock 初光符 (1 achievement claim) and give the rank-2 costs."""
    play("adopt", "青鸾", now=NOW, op="refine-adopt")
    seed_claims(game, 1)
    set_stones(game, 5000)
    grant(game, "forge_ore", 2)


def test_refine_raises_rank_and_bonus(game, play):
    unlock_first(game, play)
    play("sigils", "装备 初光符", now=NOW + 1, op="refine-equip")
    reply = play("sigils", "精炼 初光符", now=NOW + 2, op="refine-1")
    assert reply.title == "符印精炼"
    assert "精炼到 2 阶" in reply.text()
    assert "气血 +48" in reply.text()  # 40 + 20%
    assert sql(
        game[1],
        "SELECT progress FROM quest_progress WHERE quest_id='sigil_rank_first_light'",
    )[0]["progress"] == 2
    # Stones and material were paid exactly once.
    assert sql(game[1], "SELECT stones FROM players WHERE user_id='u1'")[0]["stones"] == 5000 - 400
    assert sql(
        game[1],
        "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'",
    )[0]["quantity"] == 0


def test_refine_caps_at_three(game, play):
    unlock_first(game, play)
    set_stones(game, 5000)
    grant(game, "bloodline_essence", 2)
    play("sigils", "精炼 初光符", now=NOW + 1, op="cap-1")
    play("sigils", "精炼 初光符", now=NOW + 2, op="cap-2")
    with pytest.raises(GameError, match="已精炼到 3 阶"):
        play("sigils", "精炼 初光符", now=NOW + 3, op="cap-3")


def test_refine_without_stones_writes_nothing(game, play):
    unlock_first(game, play)
    set_stones(game, 100)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="灵石不足"):
        play("sigils", "精炼 初光符", now=NOW + 1, op="poor")
    assert snapshot(game[1]) == before


def test_refine_without_materials_writes_nothing(game, play):
    unlock_first(game, play)
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="材料不足"):
        play("sigils", "精炼 初光符", now=NOW + 1, op="no-mat")
    assert snapshot(game[1]) == before


def test_refine_locked_sigil_refuses(game, play):
    play("adopt", "青鸾", now=NOW, op="lock-adopt")
    set_stones(game, 5000)
    grant(game, "forge_ore", 2)
    before = snapshot(game[1])
    with pytest.raises(GameError, match="尚未解锁"):
        play("sigils", "精炼 初光符", now=NOW + 1, op="locked")
    assert snapshot(game[1]) == before


def test_page_shows_rank_and_refine_link(game, play):
    unlock_first(game, play)
    page = play("sigils", now=NOW + 1, op="page")
    assert any("初光符" in line and "精炼 1/3" in line for line in page.lines)
    assert "灵宠符印 精炼 初光符" in [link.command for link in page.inline_commands]
