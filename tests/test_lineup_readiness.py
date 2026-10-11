from dataclasses import replace

import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.utils.time import beijing_day

from .support import sql
from .test_battles import setup_team
from .test_lineup_settlement import roster

NOW = 1_800_000_000
ACTIONS = ("train", "breakthrough", "evolve", "feed", "bond")


def prepared_lineups(game, play):
    setup_team(game, play)
    lineups = {}
    for user in ("u1", "u2"):
        ids = roster(game, play, user)
        play("lineup", " ".join(map(str, ids)), user=user)
        sql(game[1], "INSERT INTO pets(user_id, species_id, name, energy_updated) "
            "VALUES (?, 'jiaolong', '备用蛟龙', ?)", (user, NOW))
        spare = sql(game[1], "SELECT MAX(pet_id) AS id FROM pets WHERE user_id=?", (user,))[0]["id"]
        lineups[user] = [*ids, spare]
        sql(game[1], "UPDATE pets SET exp=10000, energy=90, affinity=10 WHERE user_id=?", (user,))
        for item in ("bloodline_essence", "spirit_food"):
            sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES (?,?,100) "
                "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=100", (user, item))
        play("team_ready", user=user)
    return lineups


def readiness(store):
    return {
        row["user_id"]: row for row in sql(
            store, "SELECT user_id,ready_pet_id,ready_pet_ids FROM team_members ORDER BY user_id",
        )
    }


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("user,slot,invalidated", [
    ("u1", 0, True), ("u1", 1, True), ("u1", 2, True), ("u1", 3, False),
    ("u2", 0, True), ("u2", 1, False), ("u2", 2, False), ("u2", 3, False),
])
def test_numbered_care_invalidates_only_actual_team_participants(game, play, action, user, slot, invalidated):
    lineups = prepared_lineups(game, play)
    before = readiness(game[1])
    pet_id = lineups[user][slot]
    old_pet = sql(game[1], "SELECT * FROM pets WHERE pet_id=?", (pet_id,))[0]

    play(action, str(pet_id), user=user, op="numbered-care")

    new_pet = sql(game[1], "SELECT * FROM pets WHERE pet_id=?", (pet_id,))[0]
    assert new_pet != old_pet
    after = readiness(game[1])
    if invalidated:
        assert after[user] == {"user_id": user, "ready_pet_id": None, "ready_pet_ids": ""}
        with pytest.raises(GameError, match="全体"):
            play("team_challenge", "上古灵殿")
    else:
        assert after[user] == before[user]
    other = "u2" if user == "u1" else "u1"
    assert after[other] == before[other]


@pytest.mark.parametrize("action", ACTIONS)
def test_rejected_numbered_care_preserves_entire_lineup_and_consent(game, play, action):
    lineups = prepared_lineups(game, play)
    pet_id = lineups["u1"][1]
    if action == "train":
        sql(game[1], "UPDATE pets SET energy=0 WHERE pet_id=?", (pet_id,))
    elif action == "breakthrough":
        sql(game[1], "UPDATE pets SET exp=0 WHERE pet_id=?", (pet_id,))
    elif action in {"evolve", "feed"}:
        item = "bloodline_essence" if action == "evolve" else "spirit_food"
        sql(game[1], "UPDATE inventory SET quantity=0 WHERE user_id='u1' AND item_id=?", (item,))
    else:
        sql(game[1], "UPDATE players SET last_bond_day=? WHERE user_id='u1'", (beijing_day(NOW),))
    tables = ("players", "pets", "inventory", "team_members", "quest_progress", "operations")
    before = {table: sql(game[1], f"SELECT * FROM {table} ORDER BY rowid") for table in tables}

    with pytest.raises(GameError):
        play(action, str(pet_id), op="rejected-care")

    assert {table: sql(game[1], f"SELECT * FROM {table} ORDER BY rowid") for table in tables} == before


@pytest.mark.parametrize("action", ["breakthrough", "evolve"])
def test_committed_progression_failure_clears_nonleading_pet_consent(game, play, monkeypatch, action):
    lineups = prepared_lineups(game, play)
    pet_id = lineups["u1"][2]
    if action == "breakthrough":
        sql(game[1], "UPDATE pets SET layer=10 WHERE pet_id=?", (pet_id,))
    else:
        bloodlines = dict(game[0].content.bloodlines)
        first = bloodlines[0]
        bloodlines[0] = first.model_copy(update={
            "evolution": first.evolution.model_copy(update={"chance": 0.5}),
        })
        game[0].content = replace(game[0].content, bloodlines=bloodlines)
    monkeypatch.setattr(game[0].rng, "random", lambda: 0.99)
    old_exp = sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (pet_id,))[0]["exp"]
    other_ready = readiness(game[1])["u2"]

    reply = play(action, str(pet_id))

    assert reply.title in {"破境未成", "进化未成"}
    assert sql(game[1], "SELECT exp FROM pets WHERE pet_id=?", (pet_id,))[0]["exp"] < old_exp
    assert readiness(game[1])["u1"]["ready_pet_ids"] == ""
    assert readiness(game[1])["u2"] == other_ready


@pytest.mark.parametrize("action", ACTIONS)
def test_redelivered_care_does_not_revoke_subsequent_consent(game, play, action):
    lineups = prepared_lineups(game, play)
    pet_id = lineups["u1"][1]
    reply = play(action, str(pet_id), op="original-care")
    play("team_ready")
    before = readiness(game[1])
    pets_before = sql(game[1], "SELECT * FROM pets ORDER BY pet_id")

    assert play(action, str(pet_id), op="original-care") == reply
    assert readiness(game[1]) == before
    assert sql(game[1], "SELECT * FROM pets ORDER BY pet_id") == pets_before


def test_team_status_shows_only_the_teammates_selected_participant(game, play):
    lineups = prepared_lineups(game, play)
    for pet_id, name in zip(lineups["u2"][:3], ("队友首宠", "队友后宠二", "队友后宠三")):
        sql(game[1], "UPDATE pets SET name=? WHERE pet_id=?", (name, pet_id))
    before = sql(game[1], "SELECT * FROM pets ORDER BY pet_id")

    status = play("team_status")
    detail = play("team_status", "赤霄")

    assert "队友首宠" in status.text() + detail.text()
    assert "队友后宠二" not in status.text() + detail.text()
    assert "队友后宠三" not in status.text() + detail.text()
    assert "已准备" in detail.text()
    assert sql(game[1], "SELECT * FROM pets ORDER BY pet_id") == before
