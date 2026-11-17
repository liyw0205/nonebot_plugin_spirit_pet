from concurrent.futures import ThreadPoolExecutor

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import loadout, pair_bond
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, sql
from .test_pair_bond import NOW, ctx_of, grant_items, make_pair
from .test_targeted_care import snapshot
from .test_targeted_training import add_pet


def prepare(game, play):
    left, right, _ = make_pair(game, play)
    grant_items(game, "forge_ore", 5)
    grant_items(game, "spirit_food", 5)
    sql(game[1], "UPDATE pets SET realm=3,layer=5")
    return left, right


def command(play, left, right, trial="双傀协守", now=NOW):
    page = play("pair_bond", f"合练 {left} {right}", now=now)
    return next(link.command for link in page.inline_commands if link.label == "开始" + trial)


def stats(game, pet_id):
    ctx = ctx_of(game)
    try:
        return loadout.combatant(ctx, pet_id=pet_id, recover_energy=False).stats.model_dump()
    finally:
        ctx.repo.conn.close()


def test_real_two_pet_battle_advances_pair_and_only_deployed_pair_gets_growth(game, play):
    left, right = prepare(game, play)
    before = stats(game, left)
    food, ore = items(game[1])["spirit_food"], items(game[1])["forge_ore"]
    result = play(*handlers._parse(command(play, left, right)), op="pair-win")
    assert result.title == "同心合练胜利"
    assert "0 → 1/6" in result.text()
    assert items(game[1])["spirit_food"] == food - 1
    assert items(game[1])["forge_ore"] == ore - 1
    assert sql(game[1], "SELECT energy FROM pets") == [{"energy": 88}, {"energy": 88}]
    after = stats(game, left)
    assert after["attack"] > before["attack"]
    assert after["defense"] > before["defense"]
    sql(game[1], "DELETE FROM operations")
    restarted = Game(game[0].store, game[0].config, game[0].rng, game[0].content)
    before_replay = snapshot(game[1])
    assert restarted.execute("u1", "pair_bond", "合练 1 2", "pair-win", NOW + 86400) == result
    assert snapshot(game[1]) == before_replay
    play("lineup", str(left))
    ctx = ctx_of(game)
    try:
        assert pair_bond.rate_of(ctx, left) == {}
    finally:
        ctx.repo.conn.close()
    assert stats(game, left)["attack"] < before["attack"]


def test_harder_formation_different_opponents_gives_two_progress_and_caps_at_three_ranks(game, play):
    left, right = prepare(game, play)
    for day in range(3):
        now = NOW + day * 86400
        link = command(play, left, right, "殿卫狼阵", now)
        result = play(*handlers._parse(link), now=now)
        assert result.title == "同心合练胜利"
    ctx = ctx_of(game)
    try:
        assert pair_bond.practice_progress(ctx, left, right) == 6
        assert pair_bond.practice_rank(ctx, left, right) == 3
        assert pair_bond.rate_of(ctx, left)["attack"] == pytest.approx(0.11)
    finally:
        ctx.repo.conn.close()
    assert "开始殿卫狼阵" not in {link.label for link in play("pair_bond", f"合练 {left} {right}", now=NOW + 4 * 86400).inline_commands}
    records = sql(game[1], "SELECT snapshot FROM battle_records")
    assert len(records) == 3
    assert "古殿守卫" in records[0]["snapshot"] and "月影狼王" in records[0]["snapshot"]


def test_failed_battle_spends_resources_without_advancing_and_repeat_day_is_rejected(game, play):
    left, right = prepare(game, play)
    sql(game[1], "UPDATE pets SET realm=0,layer=1,affinity=60")
    result = play(*handlers._parse(command(play, left, right, "殿卫狼阵")))
    assert result.title == "同心合练未通过"
    assert "0 → 0/6" in result.text()
    assert sql(game[1], "SELECT energy FROM pets") == [{"energy": 88}, {"energy": 88}]
    assert not any(link.label.startswith("开始") for link in play("pair_bond", f"合练 {left} {right}").inline_commands)


def test_old_numbered_bond_links_and_permanent_dissolve_cannot_break_new_pair(game, play):
    left, right = prepare(game, play)
    page = play("pair_bond")
    dissolve = next(link.command for link in page.inline_commands if link.label == "解契")
    result = play(*handlers._parse(dissolve), op="pair-dissolve")
    play("pair_bond", f"结契 {left} {right}")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="契约已变更"):
        play(*handlers._parse(dissolve), op="stale-pair")
    sql(game[1], "DELETE FROM operations")
    assert play(*handlers._parse(dissolve), op="pair-dissolve", now=NOW + 86400) == result
    assert snapshot(game[1]) == before
    assert all(link.command.split()[2].isdecimal() for link in play("pair_bond").inline_commands if link.label == "解契")


@pytest.mark.parametrize("blocked", ["archived", "trip", "lineup", "energy", "food", "ore", "foreign"])
def test_stale_practice_checks_both_fixed_pets_and_costs(game, play, blocked):
    left, right = prepare(game, play)
    link = command(play, left, right)
    if blocked in {"archived", "trip", "lineup"}:
        play("lineup", str(left))
        if blocked == "archived":
            play("pet_archive", str(right))
        elif blocked == "trip":
            play("switch", str(right))
            play("expedition_start", "采灵药")
    elif blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=?", (right,))
    elif blocked == "foreign":
        play("adopt", user="u2")
        foreign = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
        link = link.replace(f"合练 {left} {right}", f"合练 {left} {foreign}")
    else:
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE item_id=?", ("spirit_food" if blocked == "food" else "forge_ore",))
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play(*handlers._parse(link))
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT * FROM battle_records") == []


def test_practice_concurrency_day_rollback_and_write_failure_are_atomic(game, play, monkeypatch):
    left, right = prepare(game, play)
    link = command(play, left, right)
    before = snapshot(game[1])
    original = Repository.record_duel_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("pair receipt failure")
    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_duel_action", fail)
        with pytest.raises(RuntimeError):
            play(*handlers._parse(link))
    assert snapshot(game[1]) == before
    assert sql(game[1], "SELECT * FROM battle_records") == []
    def attempt(index):
        try:
            return play(*handlers._parse(link), op=f"pair-race-{index}")
        except GameError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(isinstance(result, GameError) for result in results) == 1
    with pytest.raises(GameError, match="过期"):
        play(*handlers._parse(link), now=NOW + 86400)
    page = play("pair_bond", f"合练 {left} {right}", now=NOW - 86400)
    assert "系统日期" in page.text()


def test_duplicate_names_require_numbers_and_unknown_player_can_preview(game, play):
    assert "尚未结契" in play("pair_bond").text()
    left, right = prepare(game, play)
    play("pair_bond", f"解契 {left}")
    add_pet(game[1], name="青鸾")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="编号"):
        play("pair_bond", "结契 青鸾 玄狐二号")
    assert snapshot(game[1]) == before
    assert play("pair_bond", f"结契 {left} {right}").title == "同心结契"


def test_pair_growth_does_not_transfer_to_new_partner_or_old_dissolve_link(game, play):
    left, right = prepare(game, play)
    play(*handlers._parse(command(play, left, right)))
    old = next(link.command for link in play("pair_bond").inline_commands if link.label == "解契")
    play("pair_bond", f"解契 {left}")
    third = add_pet(game[1], species_id="baize", name="白泽")
    sql(game[1], "UPDATE pets SET affinity=100")
    play("lineup", f"{left} {third}")
    play("pair_bond", f"结契 {left} {third}")
    ctx = ctx_of(game)
    try:
        assert pair_bond.practice_progress(ctx, left, third) == 0
        assert pair_bond.rate_of(ctx, left)["attack"] == 0.08
        assert pair_bond.practice_progress(ctx, left, right) == 1
    finally:
        ctx.repo.conn.close()
    with pytest.raises(GameError, match="契约已变更"):
        play(*handlers._parse(old))


@pytest.mark.parametrize("action", ["结契", "解契"])
def test_bond_changes_and_permanent_reply_fail_atomically(game, play, monkeypatch, action):
    left, right = prepare(game, play)
    if action == "结契":
        play("pair_bond", f"解契 {left}")
    argument = f"结契 {left} {right}" if action == "结契" else f"解契 {left}"
    before = snapshot(game[1])
    original = Repository.record_duel_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("bond receipt")
    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_duel_action", fail)
        with pytest.raises(RuntimeError):
            play("pair_bond", argument, op="retry-bond")
    assert snapshot(game[1]) == before
    assert play("pair_bond", argument, op="retry-bond").title


def test_practice_and_contract_links_keep_small_disjoint_native_actions(game, play):
    from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
    from nonebot_plugin_spirit_pet.core.config import Config
    left, right = prepare(game, play)
    for page in (play("pair_bond"), play("pair_bond", f"合练 {left} {right}")):
        _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix="!"))
        buttons = {button.action.data for segment in message["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert len(buttons) <= 4
        assert not buttons & {"!" + link.command for link in page.inline_commands}
        assert all(handlers._parse(link.command) for link in page.inline_commands)
