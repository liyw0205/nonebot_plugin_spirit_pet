from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql


def test_concurrent_adoptions_allocate_unique_stable_uids(game):
    service, store = game
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(
            lambda index: service.execute(
                f"opaque-platform-id-{index}", "adopt", "青鸾", f"adopt-{index}", 1_800_000_000,
            ),
            range(12),
        ))

    ids = [row["id"] for row in sql(store, "SELECT id FROM player_identity ORDER BY id")]
    assert ids == list(range(1, 13))
    assert {int(line.split("：", 1)[1]) for reply in replies for line in reply.lines if line.startswith("UID：")} == set(
        range(10000, 10012)
    )
    assert all("opaque-platform-id" not in reply.text() for reply in replies)


def test_concurrent_duplicate_adoption_allocates_one_uid_and_one_pet(game):
    service, store = game

    def adopt(index):
        try:
            return service.execute("same-platform-user", "adopt", "青鸾", f"duplicate-{index}", 1_800_000_000)
        except GameError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(adopt, range(8)))
    assert sum(reply is not None for reply in replies) == 1
    assert len(sql(store, "SELECT * FROM players")) == 1
    assert len(sql(store, "SELECT * FROM player_identity")) == 1
    assert len(sql(store, "SELECT * FROM pets")) == 1


def test_uid_lookup_drives_team_and_duel_interactions_without_platform_ids(game, play):
    play("adopt", "青鸾", user="platform-one")
    play("adopt", "玄狐", user="platform-two")
    play("team_create", user="platform-one")

    request = play("team_join", "UID 10000", user="platform-two")
    assert "UID 10001申请加入UID 10000" in request.text()
    play("team_accept", "10001", user="platform-one")
    roster = play("team_status", user="platform-one").text()
    assert "UID 10000" in roster and "UID 10001" in roster
    assert "platform-one" not in roster and "platform-two" not in roster

    duel = play("spar", "UID 10001", user="platform-one")
    assert duel.title == "切磋结算"
    assert "UID 10000" in duel.text() and "UID 10001" in duel.text()

    with pytest.raises(GameError, match="有效的 UID"):
        play("spar", "platform-two", user="platform-one")


def test_uid_mapping_is_internal_and_first_adoption_is_idempotent(game, play):
    service, store = game
    adopted = play("adopt", "青鸾", user="opaque-openid", now=1234567890, op="first-adoption")
    assert "UID：10000" in adopted.text()
    assert "初始灵宠：青鸾" in adopted.text()
    assert "道号" not in adopted.text()
    assert play("adopt", "青鸾", user="opaque-openid", now=1234567999, op="first-adoption") == adopted

    info = play("identity", user="opaque-openid")
    assert "UID：10000" in info.text()
    assert "注册时间：2009-02-14 07:31:30（UTC+8）" in info.text()
    assert "opaque-openid" not in info.text()
    with pytest.raises(GameError, match="已与灵宠结契"):
        play("adopt", "青鸾", user="opaque-openid", now=1234568000)
    assert player(store, "opaque-openid")["registered_at"] == 1234567890
    assert sql(store, "SELECT COUNT(*) AS count FROM player_identity")[0]["count"] == 1

    from contextlib import closing

    with closing(store.connect()) as conn:
        repo = Repository(conn)
        assert repo.player_by_uid(10000).user_id == "opaque-openid"
        assert repo.player_by_uid("UID 10000").uid == 10000
        assert repo.player_by_uid("opaque-openid") is None
        assert repo.player_by_uid("9999") is None
