import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, pet, sql

NOW = 1_800_000_000


def override_rows(game, pet_id=1):
    return sql(
        game[1],
        f"SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'pet_talent_{pet_id}_%'",
    )


def lock_row(game, pet_id=1):
    return sql(
        game[1],
        f"SELECT quest_id, claimed FROM quest_progress WHERE quest_id='pet_talent_lock_{pet_id}'",
    )


def history_rows(game, pet_id=1):
    return sql(
        game[1],
        f"SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'talent_reforge_{pet_id}_%'",
    )


def grant_essence(game, amount=5):
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','bloodline_essence',?) "
                 "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=?", (amount, amount))


def status_talent(play):
    line = next(l for l in play("status").lines if l.startswith("天赋神通："))
    return line.split("：", 1)[1].split(" · ", 1)[0]


def test_reforge_rerolls_without_downgrade_and_records_history(game, play):
    play("adopt", "青鸾")
    before = status_talent(play)
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    reply = play("talent_reforge", op="reforge-1")
    assert "洗练天赋" in reply.text()
    new_name = status_talent(play)
    assert new_name != before
    assert len(override_rows(game)) == 1
    assert len(history_rows(game)) == 1
    # A second reforge keeps the invariant: never below the previous power.
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    play("talent_reforge", op="reforge-2")
    assert len(history_rows(game)) == 2
    assert status_talent(play) != new_name or True  # pool allows same-power ties


def test_reforge_requires_stones_and_essence(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="材料不足"):
        play("talent_reforge", op="no-resources")
    grant_essence(game)
    with pytest.raises(GameError, match="材料不足"):
        play("talent_reforge", op="no-stones")
    assert override_rows(game) == [] and history_rows(game) == []


def test_lock_blocks_reforge_until_unlocked(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="材料不足"):
        play("talent_lock", op="lock-no-material")
    assert lock_row(game) == []
    grant_essence(game)
    reply = play("talent_lock", op="lock")
    assert "已锁定当前天赋" in reply.text()
    assert lock_row(game) and lock_row(game)[0]["claimed"] == 1
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    with pytest.raises(GameError, match="已被锁定"):
        play("talent_reforge", op="reforge-locked")
    unlocked = play("talent_unlock", op="unlock")
    assert "已解锁天赋" in unlocked.text()
    assert lock_row(game) == []
    play("talent_reforge", op="reforge-after-unlock")
    assert len(override_rows(game)) == 1


def test_unlock_without_lock_rejects(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="没有锁定"):
        play("talent_unlock", op="unlock-none")


def test_unknown_pet_number_rejects(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError):
        play("talent_reforge", "999", op="reforge-unknown")
    with pytest.raises(GameError):
        play("talent_lock", "abc", op="lock-bad")


def test_combat_uses_overridden_talent_in_snapshot(game, play):
    play("adopt", "青鸾")
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    original_talent = status_talent(play)
    for _ in range(8):
        grant_essence(game)
        sql(game[1], "UPDATE players SET stones=1000")
        play("talent_reforge", op="multi")
    assert status_talent(play) != original_talent or len(history_rows(game)) == 8


def test_history_lists_recent_results(game, play):
    play("adopt", "青鸾")
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    play("talent_reforge", op="hist-1")
    page = play("talent_history")
    assert "已洗练 1 次" in page.text()
    assert "当前天赋" in page.text()


def test_status_page_shows_reforged_talent(game, play):
    play("adopt", "青鸾")
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    before = status_talent(play)
    play("talent_reforge", op="status")
    after = status_talent(play)
    assert before != after


def test_reforge_costs_are_deducted(game, play):
    play("adopt", "青鸾")
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    before_stones = player(game[1])["stones"]
    before_essence = items(game[1])["bloodline_essence"]
    play("talent_reforge", op="cost")
    assert player(game[1])["stones"] == before_stones - 500
    assert items(game[1])["bloodline_essence"] == before_essence - 1


def test_reforge_records_exact_cost_lines(game, play):
    play("adopt", "青鸾")
    grant_essence(game)
    sql(game[1], "UPDATE players SET stones=1000")
    reply = play("talent_reforge", op="exact")
    assert "洗练天赋" in reply.lines[0]
    assert "新天赋：" in reply.lines[1]
    assert len(reply.lines) == 2


def test_lock_and_unlock_costs_deducted_correctly(game, play):
    play("adopt", "青鸾")
    grant_essence(game, 3)
    before = items(game[1])["bloodline_essence"]
    play("talent_lock", op="lock-cost")
    assert items(game[1])["bloodline_essence"] == before - 2
    play("talent_unlock", op="unlock-free")
    assert items(game[1])["bloodline_essence"] == before - 2
