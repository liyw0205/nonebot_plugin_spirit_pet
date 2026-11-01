"""New systems feed achievements and titles through monotonic counters."""

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.gameplay import alchemy, counters, hybrid
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def grant(game, item_id, amount=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def ready(game, play, *, stones=5000):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (stones,))
    sql(game[1], "DELETE FROM inventory WHERE user_id='u1'")
    for entry in game[0].content.hybrids.values():
        for seed in entry.seeds:
            grant(game, seed, 2)
    for entry in game[0].content.alchemy.values():
        for item_id in entry.materials:
            grant(game, item_id, 4)


def find_row(play, command, label, *, pages=20):
    """Search paginated listings for a row mentioning *label*."""
    for page in range(1, pages + 1):
        reply = play(command, str(page))
        for line in reply.text().splitlines():
            if label in line:
                return line
    raise AssertionError(f"{label} not found in {command}")


def achievement_ids(game):
    return {entry.id: entry for entry in game[0].content.achievements.values()}


def title_ids(game):
    return {entry.id: entry for entry in game[0].content.titles.values()}


def test_content_declares_the_new_achievements_and_titles(game):
    achievements = achievement_ids(game)
    for key in ("hybrid_first", "hybrid_adept", "alchemy_first", "alchemy_adept",
                "contract_first", "desperate_first", "release_first"):
        assert key in achievements
    titles = title_ids(game)
    assert titles["alchemy_master"].metric == "alchemy_brews"
    assert titles["desperate_walker"].metric == "hard_clears"


def test_counters_start_at_zero_and_only_rise(game, play):
    ready(game, play)
    ctx = ctx_of(game)
    assert counters.value(ctx, "alchemy_brews") == 0
    counters.bump(ctx, "alchemy_brews")
    counters.bump(ctx, "alchemy_brews", 2)
    assert counters.value(ctx, "alchemy_brews") == 3
    with pytest.raises(ValueError, match="positive"):
        counters.bump(ctx, "alchemy_brews", 0)


def test_a_brew_increments_its_counter_once(game, play):
    ready(game, play)
    first = sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)[0]
    play("alchemy", first.name, op="brew")
    assert counters.value(ctx_of(game), "alchemy_brews") == 1
    play("alchemy", first.name, op="brew-2")
    assert counters.value(ctx_of(game), "alchemy_brews") == 2


def test_a_refused_brew_does_not_count(game, play):
    ready(game, play, stones=0)
    first = sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)[0]
    from nonebot_plugin_spirit_pet.domain.models import GameError

    with pytest.raises(GameError):
        play("alchemy", first.name)
    assert counters.value(ctx_of(game), "alchemy_brews") == 0


def test_replaying_a_brew_does_not_double_count(game, play):
    ready(game, play)
    first = sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)[0]
    play("alchemy", first.name, op="replay")
    play("alchemy", first.name, op="replay")
    assert counters.value(ctx_of(game), "alchemy_brews") == 1


def test_hybridisation_counts_its_own_metric(game, play):
    ready(game, play)
    entry = sorted(game[0].content.hybrids.values(), key=lambda row: row.stones)[0]
    play("hybrid", entry.name, op="hyb")
    assert counters.value(ctx_of(game), "hybrid_brews") == 1
    assert counters.value(ctx_of(game), "alchemy_brews") == 0


def test_the_first_brew_unlocks_its_achievement(game, play):
    ready(game, play)
    first = sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)[0]
    play("alchemy", first.name, op="unlock")
    row = find_row(play, "achievements", "开炉初成")
    assert "可领奖" in row


def test_claiming_the_new_achievement_pays_once(game, play):
    ready(game, play)
    first = sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)[0]
    play("alchemy", first.name, op="claim-brew")
    stones = player(game[1])["stones"]
    play("achievement_claim", "开炉初成", op="claim")
    assert player(game[1])["stones"] == stones + 150
    with pytest.raises(Exception):
        play("achievement_claim", "开炉初成", op="claim-2")


def test_the_alchemy_title_unlocks_at_its_target(game, play):
    ready(game, play)
    ctx = ctx_of(game)
    counters.bump(ctx, "alchemy_brews", 10)
    row = find_row(play, "titles", "丹道初窥")
    assert "已获得" in row


def test_release_counts_from_the_dedication_marker(game, play):
    play("adopt", "青鸾")
    sql(game[1], "INSERT INTO pets(user_id, species_id, name, affinity, energy_updated)"
                 " VALUES ('u1','xuanhu','玄狐甲', 0, ?)", (NOW,))
    spare = sql(game[1], "SELECT MAX(pet_id) AS m FROM pets WHERE user_id='u1'")[0]["m"]
    play("pet_release", f"确认 {spare}", op="release")
    row = find_row(play, "achievements", "送别与重逢")
    assert "可领奖" in row


def test_counters_survive_a_restart(game, play):
    ready(game, play)
    first = sorted(game[0].content.alchemy.values(), key=lambda entry: entry.stones)[0]
    play("alchemy", first.name, op="persist")
    assert counters.value(ctx_of(game), "alchemy_brews") == 1
    rows = sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='u1' AND quest_id='stat_alchemy_brews'")
    assert rows and rows[0]["progress"] == 1
