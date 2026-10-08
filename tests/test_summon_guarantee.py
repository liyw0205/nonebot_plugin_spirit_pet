from .support import player, sql


NOW = 1_800_000_000
RARE_SPECIES = {"xuanwu", "sanlinglu", "bingcan", "leize", "leitingdiao"}


def test_ten_pull_forces_rare_species_after_nine_misses_and_is_idempotent(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    monkeypatch.setattr(game[0].rng, "random", lambda: 0.0)

    reply = play("summon", "10", now=NOW, op="guaranteed-ten-pull")

    assert reply.title == "山海召唤"
    assert "十连珍稀保底触发" in reply.text()
    pulled = sql(game[1], "SELECT species_id FROM pets WHERE pet_id>1 ORDER BY pet_id")
    assert len(pulled) == 10
    assert sum(row["species_id"] in RARE_SPECIES for row in pulled) == 1
    assert pulled[-1]["species_id"] == "xuanwu"
    assert player(game[1])["stones"] == 0
    assert play("summon", "10", now=NOW, op="guaranteed-ten-pull") == reply
    assert sql(game[1], "SELECT COUNT(*) AS count FROM pets")[0]["count"] == 11


def test_ten_pull_does_not_replace_an_early_rare_result(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=1000 WHERE user_id='u1'")
    draws = iter([0.33, *([0.0] * 9)])
    monkeypatch.setattr(game[0].rng, "random", lambda: next(draws))

    reply = play("summon", "10", now=NOW)

    assert "本次十连已提前抽得珍稀灵宠，保底不追加" in reply.text()
    pulled = sql(game[1], "SELECT species_id FROM pets WHERE pet_id>1 ORDER BY pet_id")
    assert [row["species_id"] for row in pulled] == ["xuanwu", *(["qingluan"] * 9)]


def test_short_batch_has_no_guarantee(game, play, monkeypatch):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=900 WHERE user_id='u1'")
    monkeypatch.setattr(game[0].rng, "random", lambda: 0.0)

    reply = play("summon", "9", now=NOW)

    assert "珍稀保底" not in reply.text()
    assert sql(game[1], "SELECT DISTINCT species_id FROM pets WHERE pet_id>1") == [
        {"species_id": "qingluan"},
    ]
    assert player(game[1])["stones"] == 0
