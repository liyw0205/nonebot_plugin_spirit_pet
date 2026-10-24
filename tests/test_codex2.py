import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

from .support import items, player, sql

NOW = 1_800_000_000
SEQUENCE = __import__("itertools").count()


def snapshot(store):
    """Domain state only — `operations` is the idempotency log and legitimately grows."""
    return [
        sql(store, "SELECT * FROM players"),
        sql(store, "SELECT * FROM pets ORDER BY pet_id"),
        sql(store, "SELECT * FROM inventory"),
        sql(store, "SELECT * FROM quest_progress"),
    ]


def test_counter_lookup_matches_the_battle_engine_for_every_element(game, play):
    from nonebot_plugin_spirit_pet.gameplay.combat import effectiveness

    content = game[0].content
    for element in content.elements.values():
        page = play("catalog_counter", element.name)
        assert page.title == f"图鉴克制 · {element.name}"
        for key in content.elements:
            if effectiveness(element.id, key, content.elements) > 1:
                assert content.elements[key].name in page.lines[1]
            else:
                assert content.elements[key].name not in page.lines[1]
            if effectiveness(key, element.id, content.elements) > 1:
                assert content.elements[key].name in page.lines[2]
            else:
                assert content.elements[key].name not in page.lines[2]


def test_counter_lookup_accepts_ids_and_lists_primary_element_species(game, play):
    page = play("catalog_counter", "ice")
    assert page.title == "图鉴克制 · 冰"
    assert page.lines[0] == "冰属性灵宠：寒翎鹰、雪影狐、玄冰蚕"
    assert page.lines[1] == "克制：火（玄狐、毕方、赤焰虎、熔岩甲）"
    assert page.lines[2] == "被克制：土（负山狮、岩心偶）、雷（雷泽夔、霆光雕）"
    assert "灵宠图鉴" in page.commands and "灵宠帮助" in page.commands


def test_counter_lookup_reports_elements_without_a_matchup(game, play):
    page = play("catalog_counter", "风")
    assert page.title == "图鉴克制 · 风"
    assert page.lines[1] == "克制：土（负山狮、岩心偶）"
    assert page.lines[2] == "被克制：无"
    assert page.lines[3] == "属性加成以主属性结算，副属性不影响克制方向。"


def test_counter_lookup_routes_through_the_plain_catalog_alias(game, play):
    assert play("catalog", "克制 火").lines == play("catalog_counter", "火").lines


def test_drop_lookup_lists_every_source_for_a_common_item(game, play):
    page = play("catalog_drop", "锻灵矿")
    assert page.title == "图鉴掉落 · 锻灵矿"
    assert page.lines[0] == "锻灵矿：装备强化材料，可从秘境和每日任务获得。"
    assert page.lines[1] == "掉落来源（24 处）："
    assert "· 秘境 青岚林" in page.lines
    assert "· 万灵塔 初入塔门" in page.lines
    assert "· 委托 寻锻矿" in page.lines
    # A stage reward would be listed with its own prefix.
    stage_drop = play("catalog_drop", "青岚翎")
    assert "· 关卡 月影追猎" in stage_drop.lines


def test_drop_lookup_accepts_item_ids_and_names_an_item_without_drops(game, play):
    assert play("catalog_drop", "spirit_food").title == "图鉴掉落 · 灵粮"
    page = play("catalog_drop", "同心丹")
    assert page.lines[0].startswith("同心丹：")
    assert page.lines[1] == "暂无掉落来源；可在灵坊购买或从其他系统获得。"
    assert "灵宠秘境" in page.commands and "灵宠委托" in page.commands


def test_drop_lookup_routes_through_the_plain_catalog_alias(game, play):
    assert play("catalog", "掉落 锻灵矿").lines == play("catalog_drop", "锻灵矿").lines


def test_both_lookups_are_read_only(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    before = snapshot(game[1])
    for action, arg in (
        ("catalog_counter", "火"), ("catalog", "克制 火"),
        ("catalog_drop", "锻灵矿"), ("catalog", "掉落 锻灵矿"),
    ):
        play(action, arg, now=NOW + 1)
    assert snapshot(game[1]) == before


def test_lookups_work_without_an_account(game, play):
    page = play("catalog_counter", "火", user="u9", now=NOW)
    assert page.title == "图鉴克制 · 火"
    drop = play("catalog_drop", "锻灵矿", user="u9", now=NOW)
    assert drop.title == "图鉴掉落 · 锻灵矿"
    assert sql(game[1], "SELECT user_id FROM players") == []


@pytest.mark.parametrize("action, argument, message", [
    ("catalog_counter", "", "格式：灵宠图鉴 克制"),
    ("catalog_drop", "", "格式：灵宠图鉴 掉落"),
    ("catalog_counter", "不存在的属性", "未找到该属性"),
    ("catalog_drop", "不存在的物品", "未找到该物品"),
])
def test_lookups_reject_missing_or_unknown_arguments(play, action, argument, message):
    with pytest.raises(GameError, match=message):
        play(action, argument, now=NOW)


def test_catalog_alias_requires_an_argument_after_the_keyword(game, play):
    with pytest.raises(GameError, match="格式：灵宠图鉴 克制"):
        play("catalog", "克制", now=NOW)
    with pytest.raises(GameError, match="格式：灵宠图鉴 掉落"):
        play("catalog", "掉落", now=NOW)


def test_unknown_names_still_raise_before_any_state_change(game, play):
    play("adopt", "青鸾", now=NOW)
    before = snapshot(game[1])
    with pytest.raises(GameError):
        play("catalog_drop", "不存在的物品", now=NOW + 1)
    with pytest.raises(GameError):
        play("catalog_counter", "不存在的属性", now=NOW + 2)
    assert snapshot(game[1]) == before


def test_native_payload_keeps_buttons_and_no_row_links(game, play):
    play("adopt", "青鸾", now=NOW)
    for reply in (play("catalog_counter", "火", now=NOW + 1), play("catalog_drop", "锻灵矿", now=NOW + 2)):
        _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
        buttons = [
            button.action.data.removeprefix("/")
            for segment in message["keyboard"]
            for row in segment.data["keyboard"].content.rows
            for button in row.buttons
        ]
        assert len(buttons) <= 4
        assert not set(buttons) & {link.command for link in reply.inline_commands}
        assert reply.inline_commands == ()


def test_parse_and_help_contract():
    assert handlers._parse("灵宠图鉴克制 火") == ("catalog_counter", "火")
    assert handlers._parse("灵宠图鉴掉落 锻灵矿") == ("catalog_drop", "锻灵矿")
    assert handlers._parse("灵宠图鉴 克制 火") == ("catalog", "克制 火")
    assert handlers._parse("灵宠图鉴 掉落 锻灵矿") == ("catalog", "掉落 锻灵矿")
    # The bare catalog still parses as the species listing and its detail view.
    assert handlers._parse("灵宠图鉴") == ("catalog", "")
    assert handlers._parse("灵宠图鉴 2") == ("catalog", "2")
    assert handlers._parse("灵宠图鉴 青鸾") == ("catalog", "青鸾")
    entries = _HELP_SECTIONS["血脉与道具"]
    assert ("灵宠图鉴 克制 属性名", "灵宠图鉴克制 ", "查看某属性的克制关系与对应种族。") in entries
    assert (
        "灵宠图鉴 掉落 物品名", "灵宠图鉴掉落 ",
        "查看某件物品在秘境、关卡、万灵塔与委托中的掉落来源。",
    ) in entries


# --- Goal 8 second-order collection: three achievements and one title ---


def _account(game, play, user="u1"):
    play("adopt", "青鸾", user=user, now=NOW)


def _metric(game, user, name):
    import itertools

    from nonebot_plugin_spirit_pet.application.context import Context
    from nonebot_plugin_spirit_pet.domain.models import Reply
    from nonebot_plugin_spirit_pet.gameplay import achievements
    from nonebot_plugin_spirit_pet.storage.repository import Repository

    values = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng, user, NOW, "metric")
        values.append(achievements._metric(ctx, user, name))
        return Reply("metric", ())

    game[1].transact(user, f"metric-{user}-{name}-{next(SEQUENCE)}", NOW, run)
    return values[-1]


def _clear(game, play, dungeon_id, side=0, winner_side=None, user="u2"):
    """Seed a battle record for `user`; by default that participant wins."""
    if not sql(game[1], "SELECT 1 FROM players WHERE user_id=?", (user,)):
        play("adopt", "青鸾", user=user, now=NOW)
    ops = f"seed-{next(SEQUENCE)}-{user}-{dungeon_id}-{side}-{winner_side}"
    with game[1].connect() as conn:
        battle = conn.execute(
            "INSERT INTO battle_records(operation_id, initiator_id, kind, battle_key, title,"
            " winner_side, rounds, played_at, reply, snapshot, battle_log)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ops, user, "pve", dungeon_id, dungeon_id,
             side if winner_side is None else winner_side, 3, NOW, "", "{}", "[]"),
        ).lastrowid
        conn.execute(
            "INSERT INTO battle_participants(battle_id, user_id, side, permission) VALUES (?,?,?,?)",
            (battle, user, side, "participant"),
        )


def test_content_defines_the_second_order_collection_goals(game):
    content = game[0].content
    assert len(content.achievements) == 77
    assert len(content.titles) == 22
    goals = {
        "lineage_all": ("lineage_branches", len(content.lineages)),
        "skill_codex_all": ("skills_learned", len(content.skills)),
        "dungeon_clear_all": ("dungeon_clears", len(content.dungeons)),
    }
    for entry_id, (metric, target) in goals.items():
        entry = content.achievements[entry_id]
        assert (entry.metric, entry.target) == (metric, target)
        assert all(item in content.items for item in entry.reward.items)
    assert (len(content.lineages), len(content.skills), len(content.dungeons)) == (54, 24, 20)
    title = content.titles["lineage_grandmaster"]
    assert (title.name, title.metric, title.target) == ("万脉宗师", "lineage_branches", 54)


def test_lineage_and_skill_metrics_are_derived_from_saved_progress(game, play):
    _account(game, play)
    assert _metric(game, "u1", "lineage_branches") == 0
    assert _metric(game, "u1", "skills_learned") == 0
    lineage = next(iter(game[0].content.lineages.values()))
    sql(game[1], "UPDATE pets SET lineage_id=? WHERE user_id='u1'", (lineage.id,))
    assert _metric(game, "u1", "lineage_branches") == 1
    skill = next(iter(game[0].content.skills))
    sql(
        game[1],
        "INSERT INTO learned_skills(pet_id, skill_id, equipped, level) SELECT pet_id, ?, 0, 1 FROM pets WHERE user_id='u1'",
        (skill,),
    )
    assert _metric(game, "u1", "skills_learned") == 1


def test_dungeon_clears_count_wins_only_and_ignore_retired_keys(game, play):
    _account(game, play)
    assert _metric(game, "u2", "dungeon_clears") == 0
    first, second = list(game[0].content.dungeons)[:2]
    _clear(game, play, first)
    assert _metric(game, "u2", "dungeon_clears") == 1
    # A defeat and a draw are not clears.
    _clear(game, play, second, winner_side=1)
    assert _metric(game, "u2", "dungeon_clears") == 1
    _clear(game, play, second, winner_side=-1)
    assert _metric(game, "u2", "dungeon_clears") == 1
    # A winning row whose participant sat on the losing side is not a clear either.
    _clear(game, play, second, side=1, winner_side=0)
    assert _metric(game, "u2", "dungeon_clears") == 1
    # Re-winning the same dungeon still counts once.
    _clear(game, play, first)
    assert _metric(game, "u2", "dungeon_clears") == 1


def test_second_order_achievements_unlock_and_claim_once(game, play):
    _account(game, play)
    content = game[0].content
    lineage_ids = [entry.id for entry in content.lineages.values()]
    skill_ids = list(content.skills)
    dungeon_ids = list(content.dungeons)
    assert (len(lineage_ids), len(skill_ids), len(dungeon_ids)) == (54, 24, 20)

    before = player(game[1])["stones"]

    def page(name):
        return play("achievement_detail", name, now=NOW + 1)

    assert "可领奖" not in page("万脉同归").text()
    assert "可领奖" not in page("万法通鉴").text()
    assert "可领奖" not in page("秘境踏遍").text()

    # Only the LAST branch/skill/dungeon is missing: the gates must still be closed.
    with game[1].connect() as conn:
        for index, lineage in enumerate(lineage_ids[:-1]):
            conn.execute(
                "INSERT INTO pets(user_id, species_id, name, lineage_id, energy_updated)"
                " VALUES ('u1', ?, ?, ?, ?)",
                (content.lineages[lineage].species_id, f"p{index}", lineage, NOW),
            )
        for skill in skill_ids[:-1]:
            conn.execute(
                "INSERT INTO learned_skills(pet_id, skill_id, equipped, level)"
                " SELECT pet_id, ?, 0, 1 FROM pets WHERE user_id='u1' LIMIT 1",
                (skill,),
            )
    for dungeon in dungeon_ids[:-1]:
        _clear(game, play, dungeon, user="u1")

    assert _metric(game, "u1", "lineage_branches") == 53
    assert _metric(game, "u1", "skills_learned") == 23
    assert _metric(game, "u1", "dungeon_clears") == 19
    assert "可领奖" not in page("万脉同归").text()

    # Close the last gap of each collection.
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO pets(user_id, species_id, name, lineage_id, energy_updated)"
            " VALUES ('u1', ?, 'plast', ?, ?)",
            (content.lineages[lineage_ids[-1]].species_id, lineage_ids[-1], NOW),
        )
        conn.execute(
            "INSERT INTO learned_skills(pet_id, skill_id, equipped, level)"
            " SELECT pet_id, ?, 0, 1 FROM pets WHERE user_id='u1' LIMIT 1",
            (skill_ids[-1],),
        )
    _clear(game, play, dungeon_ids[-1], user="u1")

    for name in ("万脉同归", "万法通鉴", "秘境踏遍"):
        assert "可领奖" in page(name).text()

    for name, stones, item, count in (
        ("万脉同归", 3000, "bloodline_essence", 8),
        ("万法通鉴", 2500, "book_spirit_wave", 2),
        ("秘境踏遍", 3500, "bloodline_essence", 6),
    ):
        before = player(game[1])["stones"]
        before_item = items(game[1]).get(item, 0)
        play("achievement_claim", name, now=NOW + 2)
        assert player(game[1])["stones"] == before + stones
        assert items(game[1]).get(item, 0) == before_item + count
        # Idempotent: a second claim pays nothing.
        with pytest.raises(GameError):
            play("achievement_claim", name, now=NOW + 3)


def test_species_detail_is_an_encyclopedia(game, play):
    from nonebot_plugin_spirit_pet.gameplay.combat import effectiveness

    content = game[0].content
    species = content.species["qingluan"]
    detail = play("catalog", "青鸾")
    assert detail.title == "万灵图鉴 · 青鸾"
    assert detail.lines[5].startswith("获取：")

    beats = [content.elements[key].name for key in content.elements
             if effectiveness(species.primary_element, key, content.elements) > 1]
    beaten = [content.elements[key].name for key in content.elements
              if effectiveness(key, species.primary_element, content.elements) > 1]
    line = detail.lines[6]
    for name in beats:
        assert f"克制{name}" in line or f"、{name}" in line.split("·")[0]
    for name in beaten:
        assert name in line.split("·", 1)[1]
    assert line.endswith("以主属性结算，副属性不影响克制方向。")

    branches = [b for b in content.lineages.values() if b.species_id == species.id]
    assert len(branches) == 2
    assert detail.lines[7].startswith("血脉分支预览：")
    for branch in branches:
        assert branch.name in detail.lines[7]

    egg = next(item for item in content.items.values()
               if item.kind == "pet_egg" and item.species_id == species.id)
    homes = [d.name for d in content.dungeons.values()
             if egg.id in d.reward.items and d.reward.items[egg.id].maximum > 0]
    drop_line = detail.lines[8]
    assert drop_line == f"灵卵掉落秘境：{'、'.join(homes) if homes else '无秘境掉落'}"

    labels = [(link.label, link.command) for link in detail.inline_commands]
    assert ("查看掉落秘境", "灵宠秘境") in labels
    # Every derived name in the matchup line must be an element that really exists.
    assert all(name in {e.name for e in content.elements.values()} for name in beats + beaten)
