import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.database import Store
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql
from .test_explore_ambush import skip_ambush
from .test_targeted_care import create_ready_team, snapshot
from .test_targeted_training import NOW, add_pet


@pytest.mark.parametrize("ambush", [False, True])
def test_exploring_backup_pays_and_earns_on_original_pet_and_replays_after_restart(game, play, ambush):
    play("adopt", "青鸾")
    create_ready_team(play, game[1])
    target = add_pet(game[1])
    sql(game[1], "UPDATE pets SET realm=6 WHERE pet_id=?", (target,))
    if not ambush:
        skip_ambush(game)
    before_active = sql(game[1], "SELECT * FROM pets WHERE pet_id=1")
    reply = play("explore", f"灵泉修行 伙伴 {target}", op="bound-explore")
    assert sql(game[1], "SELECT * FROM pets WHERE pet_id=1") == before_active
    result = sql(game[1], "SELECT energy,exp FROM pets WHERE pet_id=?", (target,))[0]
    assert result["energy"] == 75 and result["exp"] > 0
    assert player(game[1])["active_pet_id"] == 1
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": 1}]
    assert any(link.command == f"灵宠整备 {target}" for link in reply.inline_commands)
    assert f"灵宠历练 伙伴 {target}" in reply.commands
    if ambush:
        assert sql(game[1], "SELECT battle_key FROM battle_records") == [{"battle_key": "ambush_spirit_spring"}]
    else:
        assert len(sql(game[1], "SELECT * FROM adventure_discoveries")) == 1
    with pytest.raises(GameError, match="调息"):
        play("explore", "灵泉修行", now=NOW + 1)
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    reopened = Game(Store(game[1].path), game[0].config, game[0].rng, content=game[0].content)
    assert reopened.execute("u1", "explore", f"灵泉修行 伙伴 {target}", "bound-explore", NOW + 86400) == reply
    assert snapshot(game[1]) == before


def test_route_selection_stays_bound_after_switch_and_recovers_without_active_pet(game, play):
    play("adopt", "青鸾")
    target = add_pet(game[1])
    page = play("explore", f"伙伴 {target}")
    command = next(command for command in page.commands if command == f"灵宠历练 灵泉修行 伙伴 {target}")
    play("switch", str(target))
    sql(game[1], "DELETE FROM active_pet_slots")
    sql(game[1], "UPDATE players SET active_pet_id=NULL")
    skip_ambush(game)
    play(*handlers._parse(command))
    assert sql(game[1], "SELECT energy FROM pets ORDER BY pet_id") == [{"energy": 100}, {"energy": 75}]
    with pytest.raises(GameError) as error:
        play("explore", "灵泉修行", now=NOW + 900)
    assert error.value.reply.title == "选择伙伴"


@pytest.mark.parametrize("blocked", ["archived", "trip", "energy", "realm", "foreign", "travel"])
def test_stale_explore_revalidates_every_target_gate_without_cost(game, play, blocked):
    play("adopt", "青鸾")
    target = add_pet(game[1])
    command = next(command for command in play("explore", f"伙伴 {target}").commands
                   if command == f"灵宠历练 灵泉修行 伙伴 {target}")
    if blocked == "archived":
        play("pet_archive", str(target))
    elif blocked == "trip":
        play("switch", str(target))
        play("expedition_start", "采灵药")
        play("switch", "1")
    elif blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=?", (target,))
    elif blocked == "realm":
        command = f"灵宠历练 古洞寻珍 伙伴 {target}"
    elif blocked == "foreign":
        play("adopt", user="other")
        sql(game[1], "UPDATE pets SET user_id='other' WHERE pet_id=?", (target,))
    else:
        play("adventure_travel", "启程 灵泉修行")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play(*handlers._parse(command))
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("ambush", [False, True])
def test_explore_failed_commit_rolls_back_rewards_discovery_battle_and_receipt(game, play, monkeypatch, ambush):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE pets SET realm=6")
    if not ambush:
        skip_ambush(game)
    before = snapshot(game[1])
    original = Repository.save

    def fail(repo):
        original(repo)
        raise RuntimeError("explore settlement failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "save", fail)
        with pytest.raises(RuntimeError, match="explore settlement failure"):
            play("explore", "灵泉修行 伙伴 1", op="retry-explore")
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT * FROM adventure_discoveries") == []
    assert sql(game[1], "SELECT * FROM battle_records") == []
    assert sql(game[1], "SELECT * FROM duel_actions WHERE operation_id='retry-explore'") == []
    assert play("explore", "灵泉修行 伙伴 1", op="retry-explore").title == "山海历练 · 灵泉修行"


@pytest.mark.parametrize("argument", ["伙伴", "灵泉修行 伙伴", "灵泉修行 伙伴 0",
                                     "灵泉修行 伙伴 9223372036854775808", "missing 伙伴 1"])
def test_bad_explore_arguments_preserve_state(game, play, argument):
    play("adopt")
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("explore", argument)
    assert snapshot(game[1]) == before


def test_exploring_active_pet_invalidates_team_readiness(game, play):
    play("adopt")
    create_ready_team(play, game[1])
    skip_ambush(game)
    play("explore", "灵泉修行 伙伴 1")
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": None}]
