from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql


def test_generated_dao_names_unique_across_concurrent_adoptions(game):
    service, store = game
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(
            lambda index: service.execute(f"private-id-{index}", "adopt", "青鸾", f"new-{index}", 1000),
            range(12),
        ))
    names = [row["dao_name"] for row in sql(store, "SELECT dao_name FROM players")]
    assert len(names) == len(set(names)) == 12
    assert all("private-id" not in reply.text() for reply in replies)


def test_name_collision_and_case_insensitive_uniqueness(game, play):
    play("adopt")
    play("adopt", user="u2")
    play("dao_name", "Cloud")
    before = player(game[1], "u2")["dao_name"]
    with pytest.raises(GameError, match="已被使用"):
        play("dao_name", "cloud", user="u2")
    assert player(game[1], "u2")["dao_name"] == before
    play("spar", "CLOUD", user="u2")
    assert play("accept").title == "切磋结算"


def test_internal_ids_never_displayed_or_used_as_interaction_targets(game, play):
    ids = ["private-openid-001", "private-openid-002"]
    for user in ids:
        play("adopt", user=user)
    target_name = player(game[1], ids[1])["dao_name"]
    with pytest.raises(GameError, match="道号不存在"):
        play("spar", ids[1], user=ids[0])
    replies = [play(action, user=ids[0]) for action in ("status", "identity", "rank", "pvp_rank", "help")]
    replies += [play("spar", target_name, user=ids[0]), play("accept", user=ids[1])]
    assert all(not any(user in reply.text() for user in ids) for reply in replies)


def test_rename_does_not_redirect_a_pending_duel(game, play):
    play("adopt")
    play("adopt", user="u2")
    old = player(game[1], "u2")["dao_name"]
    play("spar", old)
    play("dao_name", "听雨散人", user="u2")
    assert "听雨散人" in play("accept", user="u2").text()
    with pytest.raises(GameError):
        play("spar", old)


def test_concurrent_renames_to_same_name_one_wins(game, play):
    play("adopt")
    play("adopt", user="u2")

    def rename(user):
        try:
            game[0].execute(user, "dao_name", "唯一道号", f"rename-{user}", 1800000000)
            return True
        except GameError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(rename, ["u1", "u2"])) == 1


def test_exhausted_base_name_pool_gets_unique_numeric_suffix(game, play):
    from dataclasses import replace
    from nonebot_plugin_spirit_pet.domain.battle_content import DaoNames

    game[0].content = replace(game[0].content, dao_names=DaoNames(
        prefixes=["青", "白"], suffixes=["云", "月"],
    ))
    for index in range(5):
        play("adopt", "青鸾", user=f"private-{index}")
    names = [row["dao_name"] for row in sql(game[1], "SELECT dao_name FROM players")]
    assert len(set(names)) == 5
    assert any(name[-4:].isdigit() for name in names)


def test_join_team_by_leader_name_and_hide_internal_ids(game, play):
    play("adopt")
    play("adopt", user="u2")
    leader_name = player(game[1])["dao_name"]
    play("team_create")
    play("team_join", leader_name, user="u2")
    text = play("team_status").text()
    assert leader_name in text and player(game[1], "u2")["dao_name"] in text
    assert "u1" not in text and "u2" not in text


@pytest.mark.parametrize("name", ["a", "空 格", "[链接]", "名字太长1234567890"])
def test_invalid_name_does_not_modify_identity(game, play, name):
    play("adopt")
    before = player(game[1])
    with pytest.raises(GameError):
        play("dao_name", name)
    assert player(game[1]) == before
