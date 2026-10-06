from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import SCHEMA_VERSION, Store

from .support import items, pet, player, sql


def test_exact_ids_share_database_but_different_ids_do_not(game, play):
    play("adopt", "青鸾", user="123")
    fresh = Store(game[1].path)
    fresh.initialize()
    entry = Game(fresh, Config())
    assert entry.execute("123", "status", "", "qq-status").title == "青鸾"
    with pytest.raises(GameError, match="尚未结契"):
        play("status", user="openid-123")
    assert len(sql(fresh, "SELECT * FROM players")) == 1


def test_adoption_inventory_and_initial_species_values(game, play):
    with pytest.raises(GameError):
        play("adopt", "毕方")
    play("adopt", "玄狐")
    assert pet(game[1])["affinity"] == 10
    assert pet(game[1])["layer"] == 1
    assert items(game[1]) == {"spirit_food": 3}
    with pytest.raises(GameError):
        play("adopt", "青鸾")


def test_sign_replay_daily_boundary_and_clock_rollback(game, play):
    midnight = int(datetime(2026, 10, 7, 16, tzinfo=timezone.utc).timestamp())
    play("adopt", now=midnight - 100)
    first = play("sign", now=midnight - 1, op="same")
    assert play("sign", now=midnight - 1, op="same") == first
    assert player(game[1])["stones"] == 300
    play("sign", now=midnight)
    assert player(game[1])["stones"] == 500
    with pytest.raises(GameError, match="今日已领取"):
        play("sign", now=midnight - 1)


def test_cooldown_error_rolls_back_restoration(game, play):
    play("adopt", now=1000)
    play("train", now=1000)
    before = pet(game[1])
    with pytest.raises(GameError, match="调息"):
        play("train", now=1030)
    assert pet(game[1]) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='rejected'")


def test_energy_fractional_restore_cap_and_clock_rollback(game, play):
    play("adopt", now=1000)
    play("train", now=1000)
    play("status", now=1299)
    assert pet(game[1])["energy"] == 85
    play("status", now=1301)
    assert (pet(game[1])["energy"], pet(game[1])["energy_updated"]) == (86, 1300)
    play("status", now=100000)
    play("status", now=500)
    assert (pet(game[1])["energy"], pet(game[1])["energy_updated"]) == (100, 100000)


def test_summon_switch_and_player_level_cooldown(game, play):
    play("adopt", "玄狐")
    play("train")
    original = pet(game[1])
    play("summon", op="draw")
    assert play("summon", op="draw").title == "山海召唤"
    assert len(sql(game[1], "SELECT * FROM pets")) == 2
    assert player(game[1])["stones"] == 0
    other = sql(game[1], "SELECT pet_id FROM pets ORDER BY pet_id DESC")[0]["pet_id"]
    play("switch", str(other))
    with pytest.raises(GameError, match="调息"):
        play("train")
    play("switch", str(original["pet_id"]))
    assert pet(game[1])["exp"] == original["exp"]
    assert "1/1" in play("pet_list").title


def test_pet_cap_and_ambiguous_names(game, play):
    play("adopt", "青鸾")
    play("summon")
    with pytest.raises(GameError, match="名字重复"):
        play("switch", "青鸾")
    game[0].config.spirit_pet_max_pets = 2
    with pytest.raises(GameError, match="上限"):
        play("summon")


def test_inventory_consumables_and_materials(game, play):
    play("adopt")
    play("sign")
    play("buy", "回元丹 2")
    with pytest.raises(GameError, match="已满"):
        play("use", "回元丹")
    play("train")
    result = play("use", "回元丹 2")
    assert "精力 +15" in result.text()
    assert items(game[1])["energy_pill"] == 0
    before = pet(game[1])["exp"]
    play("feed")
    assert pet(game[1])["exp"] == before + 10
    assert items(game[1])["spirit_food"] == 5
    with pytest.raises(GameError, match="材料"):
        play("use", "血脉精华")
    assert "灵粮：5" in play("bag").text()


@pytest.mark.parametrize("amount", ["0", "-1", "100", "1.5", "1; DROP TABLE players"])
def test_invalid_quantities_rollback(game, play, amount):
    play("adopt")
    before = player(game[1])
    with pytest.raises(GameError):
        play("buy", f"灵粮 {amount}")
    assert player(game[1]) == before


def test_concurrent_adoptions_and_redelivery(game):
    service, store = game

    def adopt(index):
        try:
            service.execute("u1", "adopt", "", f"adopt-{index}", 1000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(adopt, range(8))) == 1
        replies = list(pool.map(lambda _: service.execute("u1", "sign", "", "same-sign", 1000), range(8)))
    assert all(reply == replies[0] for reply in replies)
    assert player(store)["stones"] == 300
    assert len(sql(store, "SELECT * FROM pets")) == 1


def test_foreign_pet_switch_and_nickname_validation(game, play):
    play("adopt", "青鸾")
    play("adopt", "玄狐", user="u2")
    with pytest.raises(GameError):
        play("switch", str(pet(game[1], "u2")["pet_id"]))
    with pytest.raises(GameError):
        play("rename", "[bad](url)")
    play("rename", "小青")
    assert play("status").title == "小青"
    assert "小青" in play("rank").text()


@pytest.mark.parametrize("version", [*range(1, SCHEMA_VERSION), SCHEMA_VERSION + 1, 99])
def test_unreleased_old_or_future_schema_is_never_modified(tmp_path, version):
    store = Store(tmp_path / "old.db")
    sql(store, f"PRAGMA user_version={version}")
    sql(store, "CREATE TABLE sentinel(value TEXT)")
    sql(store, "INSERT INTO sentinel VALUES ('keep')")
    with pytest.raises(RuntimeError, match=str(version)):
        store.initialize()
    assert sql(store, "SELECT * FROM sentinel") == [{"value": "keep"}]
    assert sql(store, "PRAGMA user_version")[0]["user_version"] == version


def test_unknown_unversioned_database_is_not_adopted(tmp_path):
    store = Store(tmp_path / "unknown.db")
    sql(store, "CREATE TABLE sentinel(value TEXT)")
    with pytest.raises(RuntimeError):
        store.initialize()


def test_operation_id_cannot_be_reused_by_another_player(game, play):
    play("identity", op="shared-event")
    with pytest.raises(ValueError, match="different user"):
        play("identity", user="u2", op="shared-event")


def test_unexpected_failure_rolls_back_inventory_player_pet_and_cache(game, play, monkeypatch):
    from nonebot_plugin_spirit_pet.application.commands import ACTIONS, Command

    play("adopt")
    before = player(game[1]), pet(game[1]), items(game[1])

    def fail(ctx, arg):
        ctx.player().stones += 100
        ctx.pet().exp += 200
        ctx.repo.consume_item(ctx.user_id, "spirit_food", 1)
        raise RuntimeError("test failure after writes")

    monkeypatch.setitem(ACTIONS, "test_failure", Command(fail))
    with pytest.raises(RuntimeError, match="after writes"):
        play("test_failure", op="failed-event")
    assert (player(game[1]), pet(game[1]), items(game[1])) == before
    assert not sql(game[1], "SELECT * FROM operations WHERE operation_id='failed-event'")
