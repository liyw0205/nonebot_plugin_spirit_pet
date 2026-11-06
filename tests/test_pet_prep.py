"""Per-pet preparation: the 伙伴 selector, 灵宠整备 page and roster-preserving switch."""

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _action_items
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import pet, player, sql

NOW = 1_800_000_000


def account(play, user="u1"):
    play("adopt", "青鸾", user=user)


def add_pet(store, species="xuanhu", name="玄狐二号", user="u1"):
    sql(
        store,
        "INSERT INTO pets(user_id, species_id, name, energy_updated) VALUES (?, ?, ?, ?)",
        (user, species, name, NOW),
    )
    return sql(store, "SELECT pet_id FROM pets WHERE user_id=? AND name=?", (user, name))[0]["pet_id"]


def give(store, item_id, amount=1, user="u1"):
    sql(
        store,
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, item_id, amount),
    )


def worn(store, target):
    return {
        row["slot"]: (row["item_id"], row["enhancement"])
        for row in sql(store, "SELECT slot, item_id, enhancement FROM equipment WHERE pet_id=?", (target,))
    }


def roster(store, user="u1"):
    return [row["pet_id"] for row in sql(
        store, "SELECT pet_id FROM active_pet_slots WHERE user_id=? ORDER BY slot", (user,),
    )]


def state(store):
    return {
        table: sql(store, f"SELECT * FROM {table} ORDER BY 1")
        for table in ("players", "pets", "equipment", "learned_skills", "quest_progress",
                      "inventory", "active_pet_slots")
    }


def unlock_sigil(store, user="u1"):
    sql(
        store,
        "INSERT INTO achievement_claims(user_id, achievement_id, operation_id, claimed_at,"
        " reward_snapshot, reply) VALUES (?, 'test_marker', 'test-achievement', ?, '{}', '{}')",
        (user, NOW),
    )


def test_equip_and_unequip_a_backup_pet_without_switching(game, play):
    account(play)
    active = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    give(game[1], "spirit_bell")
    before_bag = sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_bell'")[0]["quantity"]

    reply = play("equipment", "灵心铃 伙伴 玄狐二号", now=NOW)
    assert "玄狐二号" in reply.text() and "灵心铃" in reply.text()
    assert worn(game[1], second)["charm"][0] == "spirit_bell"
    assert worn(game[1], active) == {}
    assert pet(game[1])["pet_id"] == active
    assert roster(game[1]) == [active]
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_bell'")[0]["quantity"] == before_bag - 1

    play("unequip", "饰品 伙伴 玄狐二号", now=NOW)
    assert worn(game[1], second) == {}
    assert sql(game[1], "SELECT quantity FROM inventory WHERE item_id='spirit_bell'")[0]["quantity"] == before_bag
    assert pet(game[1])["pet_id"] == active


def test_equip_accepts_the_pet_number(game, play):
    account(play)
    second = add_pet(game[1])
    give(game[1], "spirit_bell")
    play("equipment", f"灵心铃 伙伴 {second}", now=NOW)
    assert worn(game[1], second)["charm"][0] == "spirit_bell"


def test_skill_commands_target_a_backup_pet(game, play):
    account(play)
    active = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    give(game[1], "book_fireball")

    play("learn", "赤焰术 伙伴 玄狐二号", now=NOW)
    rows = {row["pet_id"]: row["equipped"] for row in sql(game[1], "SELECT * FROM learned_skills")}
    assert rows == {second: 1}
    assert "赤焰术" in play("skills", "伙伴 玄狐二号", now=NOW).text()
    assert "尚未学习灵术" in play("skills", now=NOW).text()

    play("unequip_skill", "赤焰术 伙伴 玄狐二号", now=NOW)
    assert sql(game[1], "SELECT equipped FROM learned_skills WHERE pet_id=?", (second,))[0]["equipped"] == 0
    play("equip_skill", "赤焰术 伙伴 玄狐二号", now=NOW)
    assert sql(game[1], "SELECT equipped FROM learned_skills WHERE pet_id=?", (second,))[0]["equipped"] == 1
    assert sql(game[1], "SELECT * FROM learned_skills WHERE pet_id=?", (active,)) == []


def test_enhance_targets_the_worn_item_of_a_backup_pet(game, play):
    account(play)
    active = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    give(game[1], "spirit_bell")
    give(game[1], "forge_ore", 10)
    play("equipment", "灵心铃 伙伴 玄狐二号", now=NOW)
    sql(game[1], "UPDATE players SET stones=100000")

    reply = play("enhance", "饰品 伙伴 玄狐二号", now=NOW)
    assert "玄狐二号" in reply.text() and "+1" in reply.text()
    assert worn(game[1], second)["charm"][1] == 1
    assert worn(game[1], active) == {}


def test_sigils_can_be_placed_on_a_backup_pet(game, play):
    account(play)
    active = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    unlock_sigil(game[1])

    reply = play("sigils", "装备 初光符 伙伴 玄狐二号", now=NOW)
    assert "玄狐二号" in reply.text()
    rows = sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'sigil_%'")
    assert rows == [{"quest_id": f"sigil_{second}_1_first_light"}]
    assert "初光符" in play("sigils", "伙伴 玄狐二号", now=NOW).text()

    play("sigils", "卸下 初光符 伙伴 玄狐二号", now=NOW)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'sigil_%'") == []
    assert pet(game[1])["pet_id"] == active


def test_selector_guards_are_stable(game, play):
    account(play)
    add_pet(game[1], name="无名一号")
    add_pet(game[1], species="baize", name="无名一号")
    sealed = add_pet(game[1], species="jiaolong", name="封存者")
    give(game[1], "spirit_bell")
    with pytest.raises(GameError, match="都叫无名一号"):
        play("equipment", "灵心铃 伙伴 无名一号", now=NOW)
    with pytest.raises(GameError, match="没有找到名为"):
        play("equipment", "灵心铃 伙伴 不存在", now=NOW)
    with pytest.raises(GameError, match="请填写伙伴名字或编号"):
        play("equipment", "灵心铃 伙伴", now=NOW)
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (sealed,))
    with pytest.raises(GameError, match="已封存"):
        play("equipment", "灵心铃 伙伴 封存者", now=NOW)


def test_switch_promotes_a_member_and_keeps_the_roster(game, play):
    account(play)
    first = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    third = add_pet(game[1], species="baize", name="白泽三号")
    play("lineup", f"{first} {second} {third}", now=NOW)
    assert roster(game[1]) == [first, second, third]

    reply = play("switch", str(second), now=NOW)
    assert "阵容共 3 只" in reply.text()
    assert roster(game[1]) == [second, first, third]
    assert pet(game[1])["pet_id"] == second

    play("switch", str(third), now=NOW)
    assert roster(game[1]) == [third, second, first]


def test_switch_to_a_new_pet_replaces_only_the_lead(game, play):
    account(play)
    first = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    play("lineup", f"{first} {second}", now=NOW)
    fourth = add_pet(game[1], species="jiaolong", name="蛟龙四号")

    play("switch", str(fourth), now=NOW)
    assert roster(game[1]) == [fourth, second]


def test_switch_refuses_a_duplicate_species_lead(game, play):
    account(play)
    first = pet(game[1])["pet_id"]
    second = add_pet(game[1])
    play("lineup", f"{first} {second}", now=NOW)
    clone = add_pet(game[1], name="玄狐分身")

    with pytest.raises(GameError, match="同族"):
        play("switch", str(clone), now=NOW)
    assert roster(game[1]) == [first, second]


def test_prep_page_lists_gear_skills_and_sigils(game, play):
    account(play)
    second = add_pet(game[1])
    give(game[1], "spirit_bell")
    play("equipment", "灵心铃 伙伴 玄狐二号", now=NOW)
    give(game[1], "book_fireball")
    play("learn", "赤焰术 伙伴 玄狐二号", now=NOW)
    unlock_sigil(game[1])
    play("sigils", "装备 初光符 伙伴 玄狐二号", now=NOW)

    page = play("pet_prep", "玄狐二号", now=NOW)
    assert page.title == "灵宠整备"
    text = page.text()
    assert "玄狐二号" in text and "灵心铃" in text
    assert "赤焰术" in text and "初光符" in text
    assert "整备只读" in text
    linked = {link.command for link in page.inline_commands}
    assert f"伙伴 {second}" in " ".join(linked)
    assert len(page.commands) <= 4
    assert len(set(page.commands)) == len(page.commands)


def test_prep_page_is_read_only(game, play):
    account(play)
    add_pet(game[1])
    before = state(game[1])
    play("pet_prep", "玄狐二号", now=NOW)
    assert state(game[1]) == before


def test_prep_page_without_a_target_uses_the_active_pet(game, play):
    account(play)
    page = play("pet_prep", "", now=NOW)
    assert "青鸾" in page.text() and "当前出战" in page.text()


def test_unregistered_prep_never_creates_an_account(game, play):
    page = play("pet_prep", "", user="u9", now=NOW)
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT * FROM players WHERE user_id='u9'") == []


def test_alias_parses_and_help_mentions_it():
    assert _parse("灵宠整备 3") == ("pet_prep", "3")
    assert _parse("灵宠整备") == ("pet_prep", "")


def test_action_items_dedupe_links_from_buttons(game, play):
    account(play)
    add_pet(game[1])
    reply = play("pet_prep", "玄狐二号", now=NOW)
    pairs = _action_items(reply)
    assert len(pairs) <= 4
    buttons = {command for _, command in pairs}
    links = {link.command for link in reply.inline_commands}
    assert buttons & links == set()
