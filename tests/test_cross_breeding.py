import asyncio
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.content.catalog import Catalog, DATA_DIR
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import family_trial
from nonebot_plugin_spirit_pet.utils.time import beijing_week

from .support import items, player, sql, uid_label
from .test_commands import onebot_event, qq_event

NOW = 1_800_000_000
RECIPE = "wind_flame_to_baize"


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)
    return uid_label(game[1], user)


def add_pet(game, species, *, user="u1", affinity=100, energy=100, realm=0, archived=0):
    with game[1].connect() as conn:
        cursor = conn.execute(
            "INSERT INTO pets(user_id,species_id,name,realm,affinity,energy,energy_updated,archived) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user, species, f"伙伴{species}{affinity}{energy}", realm, affinity, energy, NOW, archived),
        )
        return int(cursor.lastrowid)


def grant(game, *, stones=5000, **materials):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id='u1'", (stones,))
    for item_id, amount in materials.items():
        sql(
            game[1],
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,?) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=excluded.quantity",
            (item_id, amount),
        )


def pair(game, *, first="qingluan", second="xuanhu", affinity=100, energy=100, realm=1):
    return (
        add_pet(game, first, affinity=affinity, energy=energy, realm=realm),
        add_pet(game, second, affinity=affinity, energy=energy, realm=realm),
    )


def test_cross_breeding_catalog_has_fixed_species_and_multiple_routes_to_same_egg(game, play):
    catalog = game[0].content.cross_breeding
    assert len(catalog) == 3
    assert catalog["wind_flame_to_baize"].offspring_species == "baize"
    assert catalog["dragon_wood_to_baize"].offspring_species == "baize"
    assert len({tuple(sorted((r.parent_a_species, r.parent_b_species))) for r in catalog.values()}) == 3
    assert all(game[0].content.items[f"egg_{r.offspring_species}"].species_id == r.offspring_species
               for r in catalog.values())
    listing = play("cross_breeding")
    assert "wind_flame_to_baize" in listing.text()
    assert "dragon_wood_to_baize" in listing.text()
    assert "白泽灵卵" in listing.text()


@pytest.mark.parametrize(
    "edit",
    [
        lambda recipes, items: recipes[1].update(parent_a_species=recipes[0]["parent_b_species"],
                                                  parent_b_species=recipes[0]["parent_a_species"]),
        lambda recipes, items: recipes[0].update(parent_b_species=recipes[0]["parent_a_species"]),
        lambda recipes, items: recipes[0].update(parent_a_species="unknown_species"),
        lambda recipes, items: recipes[0].update(offspring_species="unknown_species"),
        lambda recipes, items: recipes[0].update(items={}),
        lambda recipes, items: recipes[0].update(items={"spirit_food": 1}),
        lambda recipes, items: recipes[0].update(items={"missing_material": 1}),
        lambda recipes, items: recipes[0].update(items={"forge_ore": 21}),
        lambda recipes, items: recipes[0].update(minimum_realm="unknown_realm"),
        lambda recipes, items: recipes[0].update(text=""),
        lambda recipes, items: recipes[0].update(stones=10_001),
        lambda recipes, items: recipes[0].update(energy=101),
        lambda recipes, items: recipes[0].update(items={"forge_ore": 7}),
        lambda recipes, items: recipes.__setitem__(1, {**recipes[1], "id": recipes[0]["id"]}),
        lambda recipes, items: next(item for item in items if item["id"] == "egg_baize").update(
            species_id="qingluan",
        ),
        lambda recipes, items: next(item for item in items if item["id"] == "egg_baize").update(
            kind="material", species_id=None,
        ),
    ],
)
def test_cross_breeding_content_rejects_invalid_recipes(tmp_path, edit):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    recipe_path = target / "cross_breeding.json"
    recipes = json.loads(recipe_path.read_text(encoding="utf-8"))
    items = json.loads((target / "items.json").read_text(encoding="utf-8"))
    edit(recipes, items)
    recipe_path.write_text(json.dumps(recipes, ensure_ascii=False), encoding="utf-8")
    (target / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        Catalog.load(target)


def test_cross_breeding_spends_resources_and_records_true_parents_then_hatches(game, play):
    account(game, play)
    first, second = pair(game)
    grant(game, stones=5000, forge_ore=2)
    before = player(game[1])["stones"]
    reply = play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-breed-one")
    assert reply.title == "灵宠异族共育成功"
    assert player(game[1])["stones"] == before - 1000
    assert items(game[1])["forge_ore"] == 1
    assert items(game[1])["egg_baize"] == 1
    energy = {row["pet_id"]: row["energy"] for row in sql(game[1], "SELECT pet_id,energy FROM pets")}
    assert energy[first] == energy[second] == 80
    operation = sql(game[1], "SELECT snapshot FROM pet_pedigree_operations WHERE operation_id='cross-breed-one'")[0]
    snapshot = json.loads(operation["snapshot"])
    assert snapshot["parent_a_species"] == "qingluan"
    assert snapshot["parent_b_species"] == "xuanhu"
    assert snapshot["offspring_species"] == "baize"
    assert sql(game[1], "SELECT parent_a_id,parent_b_id FROM pet_lineage_eggs")[0] == {
        "parent_a_id": first, "parent_b_id": second,
    }

    hatched = play("use", "白泽灵卵", op="cross-hatch-one")
    child = sql(game[1], "SELECT child_pet_id FROM pet_lineage_eggs WHERE operation_id='cross-breed-one'")[0]["child_pet_id"]
    assert child is not None and "获得白泽" in hatched.text()
    detail = play("pedigree", str(child))
    parent_names = {row["pet_id"]: row["name"] for row in sql(game[1], "SELECT pet_id,name FROM pets")}
    assert parent_names[first] in detail.text() and "青鸾" in detail.text()
    assert parent_names[second] in detail.text() and "玄狐" in detail.text()
    family_page = play("family_trial")
    assert all(str(pet_id) in family_page.text() for pet_id in (first, second, child))
    duel_pairs = play("family_duel", "亲子")
    outing_pairs = play("family_outing", "亲子 brook_walk")
    assert any(str(first) in line and str(child) in line for line in duel_pairs.lines)
    assert any(str(second) in line and str(child) in line for line in duel_pairs.lines)
    assert any(str(first) in line and str(child) in line for line in outing_pairs.lines)


def test_cross_breeding_pair_week_limits_clock_rollback_and_permanent_replay(game, play):
    account(game, play)
    first, second = pair(game)
    grant(game, forge_ore=3)
    original = play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-permanent")
    original_state = (player(game[1]), items(game[1]), sql(game[1], "SELECT energy FROM pets ORDER BY pet_id"))
    sql(game[1], "DELETE FROM operations WHERE operation_id='cross-permanent'")
    from nonebot_plugin_spirit_pet.application.game import Game

    reopened = Game(game[0].store, game[0].config)
    assert reopened.execute("u1", "cross_breeding", f"{RECIPE} {first} {second}",
                            "cross-permanent", NOW + 1) == original
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT energy FROM pets ORDER BY pet_id")) == original_state
    with pytest.raises(GameError, match="自然周"):
        play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-week-repeat")
    with pytest.raises(GameError, match="时间早于"):
        play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-clock-back", now=NOW - 1)
    with pytest.raises(GameError, match="永久异族共育凭证"):
        play("cross_breeding", f"{RECIPE} {second} {first}", op="cross-pair-repeat", now=NOW + 8 * 86400)
    other_first, other_second = pair(game, first="jiaolong", second="xuanhu")
    grant(game, stones=5000, forge_ore=2, bloodline_essence=2, gem_vital=2)
    assert play("cross_breeding", f"fox_dragon_to_jiaolong {other_first} {other_second}",
                op="cross-next-week", now=NOW + 8 * 86400).title == "灵宠异族共育成功"


def test_cross_breeding_natural_week_boundary_is_beijing_monday(game, play):
    account(game, play)
    first, second = pair(game)
    next_first, next_second = pair(game, first="jiaolong", second="xuanhu")
    grant(game, stones=5000, forge_ore=3, bloodline_essence=1, gem_vital=1)
    from nonebot_plugin_spirit_pet.utils.time import beijing_week

    _, week_end = beijing_week(NOW)
    assert play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-before-monday",
                now=week_end - 1).title == "灵宠异族共育成功"
    assert play("cross_breeding", f"fox_dragon_to_jiaolong {next_first} {next_second}",
                op="cross-at-monday", now=week_end).title == "灵宠异族共育成功"


@pytest.mark.parametrize("blocker", ["affinity", "energy", "realm", "stones", "material", "foster", "expedition"])
def test_cross_breeding_rejections_leave_resources_and_receipts_untouched(game, play, blocker):
    account(game, play)
    affinity = 20 if blocker == "affinity" else 100
    energy = 5 if blocker == "energy" else 100
    realm = 0 if blocker == "realm" else 1
    first, second = pair(game, affinity=affinity, energy=energy, realm=realm)
    grant(game, stones=100 if blocker == "stones" else 5000,
          forge_ore=0 if blocker == "material" else 1)
    if blocker == "foster":
        sql(game[1], "INSERT INTO quest_progress(user_id,quest_id,progress,claimed) VALUES ('u1',?,?,1)",
            (f"foster_{second}", 10001))
    if blocker == "expedition":
        sql(game[1], "INSERT INTO expeditions(user_id,pet_id,task_id,task_name,source_operation_id,started_at,"
                     "finishes_at,state,reward_snapshot) VALUES ('u1',?,'job','行程','cross-expedition',?,?,"
                     "'running','{}')", (second, NOW - 10, NOW + 600))
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id,energy FROM pets ORDER BY pet_id"))
    with pytest.raises(GameError):
        play("cross_breeding", f"{RECIPE} {first} {second}", op=f"reject-{blocker}")
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id,energy FROM pets ORDER BY pet_id")) == before
    assert not sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE operation_id=?", (f"reject-{blocker}",))
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'cross_breeding_%'")


@pytest.mark.parametrize("violation", ["same_species", "wrong_recipe", "foreign_parent", "not_adopted"])
def test_cross_breeding_rejects_invalid_parent_identity_or_recipe(game, play, violation):
    account(game, play)
    first, second = pair(game)
    recipe = RECIPE
    actor = "u1"
    if violation == "same_species":
        second = add_pet(game, "qingluan", energy=100, realm=1)
    elif violation == "wrong_recipe":
        recipe = "fox_dragon_to_jiaolong"
    elif violation == "foreign_parent":
        play("adopt", "玄狐", user="u2")
        second = add_pet(game, "xuanhu", user="u2", energy=100, realm=1)
    elif violation == "not_adopted":
        actor = "ghost"
    grant(game, stones=5000, forge_ore=1)
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id,energy FROM pets ORDER BY pet_id"))
    with pytest.raises(GameError):
        play("cross_breeding", f"{recipe} {first} {second}", user=actor, op=f"reject-{violation}")
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id,energy FROM pets ORDER BY pet_id")) == before
    assert not sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE operation_id=?", (f"reject-{violation}",))


def test_cross_breeding_rolls_every_write_back_on_lineage_failure(game, play):
    account(game, play)
    first, second = pair(game)
    grant(game, forge_ore=1)
    before = (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id,energy FROM pets ORDER BY pet_id"))
    sql(game[1], "CREATE TRIGGER fail_cross_lineage BEFORE INSERT ON pet_lineage_eggs "
                 "BEGIN SELECT RAISE(ABORT,'injected cross lineage failure'); END")
    with pytest.raises(Exception, match="injected cross lineage failure"):
        play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-lineage-retry")
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id,energy FROM pets ORDER BY pet_id")) == before
    assert not sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE operation_id='cross-lineage-retry'")
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'cross_breeding_%'")
    sql(game[1], "DROP TRIGGER fail_cross_lineage")
    assert play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-lineage-retry").title == "灵宠异族共育成功"


@pytest.mark.parametrize("trigger", [
    "CREATE TRIGGER fail_cross BEFORE UPDATE ON players WHEN NEW.stones < OLD.stones "
    "BEGIN SELECT RAISE(ABORT,'injected player failure'); END",
    "CREATE TRIGGER fail_cross BEFORE UPDATE ON pets WHEN NEW.energy < OLD.energy "
    "BEGIN SELECT RAISE(ABORT,'injected pet failure'); END",
    "CREATE TRIGGER fail_cross BEFORE UPDATE ON inventory WHEN OLD.item_id='forge_ore' "
    "BEGIN SELECT RAISE(ABORT,'injected material failure'); END",
    "CREATE TRIGGER fail_cross BEFORE INSERT ON inventory WHEN NEW.item_id='egg_baize' "
    "BEGIN SELECT RAISE(ABORT,'injected egg failure'); END",
    "CREATE TRIGGER fail_cross BEFORE INSERT ON quest_progress "
    "BEGIN SELECT RAISE(ABORT,'injected weekly receipt failure'); END",
    "CREATE TRIGGER fail_cross BEFORE INSERT ON pet_pedigree_operations "
    "BEGIN SELECT RAISE(ABORT,'injected operation failure'); END",
    "CREATE TRIGGER fail_cross BEFORE INSERT ON operations "
    "BEGIN SELECT RAISE(ABORT,'injected replay operation failure'); END",
    "CREATE TRIGGER fail_cross BEFORE INSERT ON pet_lineage_eggs "
    "BEGIN SELECT RAISE(ABORT,'injected lineage failure'); END",
])
def test_cross_breeding_failures_at_each_write_boundary_are_atomic(game, play, trigger):
    account(game, play)
    first, second = pair(game)
    grant(game, forge_ore=1)
    before = (
        player(game[1]), items(game[1]),
        sql(game[1], "SELECT pet_id,energy,energy_updated FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'cross_breeding_%'"),
        sql(game[1], "SELECT * FROM operations WHERE operation_id='cross-write-failure'"),
        sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE operation_id='cross-write-failure'"),
        sql(game[1], "SELECT * FROM pet_lineage_eggs"),
    )
    sql(game[1], trigger)
    with pytest.raises(Exception, match="injected"):
        play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-write-failure")
    after = (
        player(game[1]), items(game[1]),
        sql(game[1], "SELECT pet_id,energy,energy_updated FROM pets ORDER BY pet_id"),
        sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'cross_breeding_%'"),
        sql(game[1], "SELECT * FROM operations WHERE operation_id='cross-write-failure'"),
        sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE operation_id='cross-write-failure'"),
        sql(game[1], "SELECT * FROM pet_lineage_eggs"),
    )
    assert after == before
    sql(game[1], "DROP TRIGGER fail_cross")
    assert play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-write-failure").title == "灵宠异族共育成功"


def test_cross_breeding_concurrent_pairs_share_one_weekly_slot(game, play):
    account(game, play)
    first, second = pair(game)
    other_first, other_second = pair(game, first="jiaolong", second="xuanhu")
    grant(game, stones=5000, forge_ore=3, bloodline_essence=1, gem_vital=1)

    def attempt(recipe, left, right, op):
        try:
            return play("cross_breeding", f"{recipe} {left} {right}", op=op).title
        except GameError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: attempt(*args), [
            (RECIPE, first, second, "cross-race-a"),
            ("fox_dragon_to_jiaolong", other_first, other_second, "cross-race-b"),
        ]))
    assert results.count("灵宠异族共育成功") == 1
    assert results.count("rejected") == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM pet_lineage_eggs")[0]["n"] == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM quest_progress WHERE user_id='u1' "
                       "AND quest_id LIKE 'cross_breeding_week_%' AND claimed=1")[0]["n"] == 1


def test_cross_breeding_concurrent_reuse_of_same_pair_has_one_success(game, play):
    account(game, play)
    first, second = pair(game)
    grant(game, forge_ore=2)

    def attempt(op):
        try:
            return play("cross_breeding", f"{RECIPE} {first} {second}", op=op).title
        except GameError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("cross-pair-race-a", "cross-pair-race-b")))
    assert results.count("灵宠异族共育成功") == 1
    assert results.count("rejected") == 1
    assert items(game[1])["egg_baize"] == 1
    assert sql(game[1], "SELECT COUNT(*) AS n FROM pet_lineage_eggs")[0]["n"] == 1


def test_cross_breeding_help_objectives_and_today_are_actionable(game, play):
    account(game, play)
    pair(game)
    grant(game, forge_ore=1)
    help_reply = play("help", "成长")
    assert "灵宠异族共育" in help_reply.text()
    assert "灵宠异族共育：" in help_reply.text()
    assert "灵宠异族共育" in play("objectives").text()
    today = play("today")
    assert "本周可按固定配方完成一次异族共育" in today.text()
    assert any(command == "灵宠异族共育" for command in today.commands) or any(
        link.command == "灵宠异族共育" for link in today.inline_commands
    )
    assert "还没有异族共育记录" in play("cross_breeding", "记录").text()


@pytest.mark.parametrize("adapter", ["QQ", "OneBot V11"])
def test_cross_breeding_command_uses_shared_adapter_handler(game, play, monkeypatch, adapter):
    play("adopt", "青鸾", user="12345")
    first = add_pet(game, "qingluan", user="12345", affinity=100, energy=100, realm=1)
    second = add_pet(game, "xuanhu", user="12345", affinity=100, energy=100, realm=1)
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='12345'")
    sql(game[1], "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('12345','forge_ore',1)")
    monkeypatch.setattr(handlers, "game", game[0])
    monkeypatch.setattr(handlers, "config", Config(spirit_pet_qq_mode="native"))
    monkeypatch.setattr("nonebot_plugin_spirit_pet.application.game.time.time", lambda: NOW)
    text = f"灵宠异族共育 {RECIPE} {first} {second}"
    event = qq_event(text=text, message_id=f"cross-{adapter}") if adapter == "QQ" else onebot_event(text)
    bot = SimpleNamespace(self_id="9000", adapter=SimpleNamespace(get_name=lambda: adapter), send=AsyncMock())

    asyncio.run(handlers.handle_command(bot, event, event.get_message()))

    assert handlers._parse(text) == ("cross_breeding", f"{RECIPE} {first} {second}")
    assert bot.send.await_count == 1
    assert "灵宠异族共育成功" in str(bot.send.call_args.args[1])
    assert sql(game[1], "SELECT COUNT(*) AS n FROM pet_lineage_eggs")[0]["n"] == 1


def test_cross_breeding_pages_render_native_actions_without_duplicate_buttons(game, play):
    account(game, play)
    first, second = pair(game)
    grant(game, forge_ore=1)
    replies = [play("cross_breeding"), play("cross_breeding", RECIPE),
               play("cross_breeding", f"{RECIPE} {first} {second}", op="cross-ui")]
    for reply in replies:
        _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
        markdown = message["markdown"][0].data["markdown"].content
        links = {parse_qs(urlparse(url).query)["command"][0].removeprefix("/")
                 for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)}
        buttons = {button.action.data.removeprefix("/") for segment in message["keyboard"]
                   for row in segment.data["keyboard"].content.rows for button in row.buttons}
        assert len(buttons) <= 4
        assert not links & buttons
        assert all(handlers._parse(command) is not None for command in links | buttons)
        assert links == {action.command for action in reply.inline_commands}


def test_cross_breeding_queries_do_not_write_state(game, play):
    account(game, play)
    first, second = pair(game)
    grant(game, forge_ore=1)
    def gameplay_state():
        return (
            player(game[1]), items(game[1]),
            sql(game[1], "SELECT pet_id,energy,energy_updated FROM pets ORDER BY pet_id"),
            sql(game[1], "SELECT * FROM quest_progress WHERE user_id='u1' AND quest_id LIKE 'cross_breeding_%'"),
            sql(game[1], "SELECT * FROM pet_pedigree_operations WHERE user_id='u1'"),
            sql(game[1], "SELECT * FROM pet_lineage_eggs WHERE user_id='u1'"),
        )

    before = gameplay_state()
    for action, argument in (
        ("cross_breeding", ""), ("cross_breeding", RECIPE), ("cross_breeding", "记录"),
        ("objectives", ""), ("today", ""), ("help", "成长"), ("pedigree", ""),
    ):
        play(action, argument)
    assert gameplay_state() == before


def test_cross_bred_child_is_eligible_for_existing_family_activities(game, play):
    account(game, play)
    parent, other = pair(game, first="jiaolong", second="xuanhu", realm=1)
    grant(game, stones=5000, forge_ore=1, gem_vital=1)
    play("cross_breeding", f"fox_dragon_to_jiaolong {parent} {other}", op="cross-family-egg")
    play("use", "蛟龙灵卵", op="cross-family-hatch")
    child = sql(game[1], "SELECT child_pet_id FROM pet_lineage_eggs WHERE operation_id='cross-family-egg'")[0][
        "child_pet_id"
    ]
    sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'water_arrow',1)", (parent,))
    sql(game[1], "INSERT INTO learned_skills(pet_id,skill_id,equipped) VALUES (?,'water_arrow',1)", (child,))
    sql(game[1], "UPDATE learned_skills SET level=2 WHERE pet_id=? AND skill_id='water_arrow'", (parent,))

    lesson_pairs = play("family_tutelage", "亲子 water_lesson 1 " + str(child))
    assert any(f"#{parent}" in line and f"#{child}" in line for line in lesson_pairs.lines), lesson_pairs.text()
    duel_pairs = play("family_duel", "亲子")
    outing_pairs = play("family_outing", "亲子 brook_walk")
    assert any(f"#{parent}" in line and f"#{child}" in line for line in duel_pairs.lines)
    assert any(f"#{parent}" in line and f"#{child}" in line for line in outing_pairs.lines)

    family_page = play("family_trial")
    assert all(f"#{pet_id}" in family_page.text() for pet_id in (parent, other, child))
    week_start, _ = beijing_week(NOW)
    trial = family_trial.current_trial(SimpleNamespace(content=game[0].content, now=NOW))
    run_reply = play("family_trial", f"开始 {week_start}:{trial.id} {parent} {child}", op="cross-family-trial")
    assert "已开局" in run_reply.text()
    assert sql(game[1], "SELECT pet_id FROM family_trial_members ORDER BY slot") == [
        {"pet_id": parent}, {"pet_id": child},
    ]
