import itertools
import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError, Reply
from nonebot_plugin_spirit_pet.gameplay import achievements
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import pet, player, sql
from .test_arena_matching import NOW, register, uid

WEAPON = "青岚翎"
NEW_METRICS = (
    "max_enhancement", "spar_wins", "battles_fought",
    "equipment_owned", "achievements_claimed", "resonances_enabled",
)


COUNTER = itertools.count()


def metric(game, user, name):
    values = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "metric")
        values.append(achievements._metric(ctx, user, name))
        return Reply("metric", ())

    game[1].transact(user, f"metric-{user}-{name}-{next(COUNTER)}", NOW, run)
    return values[-1]


def forge(game, play, target=None):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=1000000")
    play("buy", WEAPON)
    play("equipment", WEAPON)
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'forge_ore', 100)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=100")
    if target is not None:
        play("enhance", f"灵器 {target}")


def stones(game):
    return player(game[1])["stones"]


def ore(game):
    rows = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='forge_ore'")
    return rows[0]["quantity"] if rows else 0


def test_new_metrics_start_at_zero_without_writing_anything(game, play):
    play("adopt", "青鸾")
    before = {table: sql(game[1], f"SELECT * FROM {table}") for table in
              ("equipment", "unequipped_equipment", "battle_records", "achievement_claims", "player_resonance")}
    assert {name: metric(game, "u1", name) for name in NEW_METRICS} == dict.fromkeys(NEW_METRICS, 0)
    assert {name: metric(game, "stranger", name) for name in NEW_METRICS} == dict.fromkeys(NEW_METRICS, 0)
    after = {table: sql(game[1], f"SELECT * FROM {table}") for table in before}
    assert after == before
    assert sql(game[1], "SELECT user_id FROM players") == [{"user_id": "u1"}]


def test_max_enhancement_counts_equipped_and_stored_items(game, play):
    forge(game, play, target=3)
    assert metric(game, "u1", "max_enhancement") == 3
    play("unequip", "灵器")
    assert sql(game[1], "SELECT enhancement FROM equipment") == []
    assert metric(game, "u1", "max_enhancement") == 3


def test_equipment_owned_adds_both_tables(game, play):
    forge(game, play, target=3)
    assert metric(game, "u1", "equipment_owned") == 1
    play("unequip", "灵器")
    assert metric(game, "u1", "equipment_owned") == 1


def test_spar_and_battle_counts_follow_the_permanent_record(game, play):
    register(game, play)
    play("spar", uid(1), user="private-0", now=NOW)
    record = sql(game[1], "SELECT battle_id, winner_side FROM battle_records WHERE kind='spar'")[0]
    sides = {row["user_id"]: row["side"] for row in sql(
        game[1], "SELECT user_id, side FROM battle_participants WHERE battle_id=?", (record["battle_id"],))}
    winner = next(user for user, side in sides.items() if side == record["winner_side"])
    loser = next(user for user in sides if user != winner)
    assert metric(game, winner, "spar_wins") == 1
    assert metric(game, loser, "spar_wins") == 0
    assert metric(game, winner, "battles_fought") == 1
    assert metric(game, loser, "battles_fought") == 1
    assert metric(game, "private-2", "battles_fought") == 0


def test_achievements_claimed_counts_claims(game, play):
    play("adopt", "青鸾")
    assert metric(game, "u1", "achievements_claimed") == 0
    play("achievement_claim", "初结灵契")
    assert metric(game, "u1", "achievements_claimed") == 1


def test_resonances_enabled_counts_the_selected_pair(game, play):
    play("adopt", "青鸾")
    sql(game[1], "INSERT INTO pets(user_id, species_id, name, energy_updated) "
        "VALUES ('u1','hanying','寒翎鹰二号',1800000000)")
    sql(game[1], "UPDATE players SET stones=100000")
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'bloodline_essence', 1)")
    assert metric(game, "u1", "resonances_enabled") == 0
    play("resonance", "激活 青岚双翼")
    assert metric(game, "u1", "resonances_enabled") == 1


def test_new_achievements_appear_on_the_last_page_and_claim_once(game, play):
    forge(game, play, target=3)
    page = play("achievements", "11")
    assert "初试锋芒 · 可领奖 · 进度：+3 / +3" in page.text()
    assert "灵宠成就领奖 初试锋芒" in page.commands

    before = stones(game), ore(game)
    reply = play("achievement_claim", "初试锋芒", op="claim-forge-first")
    assert reply.title == "成就奖励已领取"
    assert (stones(game), ore(game)) == (before[0] + 200, before[1] + 1)
    assert play("achievement_claim", "初试锋芒", op="claim-forge-first").lines == reply.lines
    with pytest.raises(GameError, match="该成就奖励已领取"):
        play("achievement_claim", "初试锋芒")


def test_hub_reports_the_new_claimable_achievement(game, play):
    forge(game, play, target=3)
    line = next(text for text in play("objectives").lines if text.startswith("成就："))
    assert "初试锋芒" in line


def test_catalog_requires_the_new_metrics_and_the_top_enhancement_milestone():
    content = Catalog.load()
    metrics = {entry.metric for entry in content.achievements.values()}
    assert set(NEW_METRICS) <= metrics
    assert 10 in {entry.target for entry in content.achievements.values() if entry.metric == "max_enhancement"}
    for name in NEW_METRICS:
        assert any(entry.metric == name for entry in content.achievements.values())


def test_enhancement_achievement_cannot_exceed_the_forge_ladder(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    path = target / "achievements.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    beyond = dict(next(entry for entry in entries if entry["id"] == "forge_ten"))
    beyond.update(id="forge_eleven", name="超限淬炼", target=11)
    entries.append(beyond)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds available max_enhancement"):
        Catalog.load(target)


def test_achievement_page_links_stay_out_of_the_buttons(game, play):
    forge(game, play, target=3)
    reply = play("achievements", "11")
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons & {link.command for link in reply.inline_commands} == set()
