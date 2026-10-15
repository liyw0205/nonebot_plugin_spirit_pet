import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql, uid_label

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)
    return uid_label(game[1], user)


def add_pet(game, species="qingluan", user="u1", affinity=100, energy=100, name=None):
    store = game[1]
    with store.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user, species, name or species, affinity, energy, NOW),
        )
        return cursor.lastrowid


def links(reply):
    return [(link.line, link.label, link.command) for link in reply.inline_commands]


def fund(game, stones=5000):
    sql(game[1], "UPDATE players SET stones=?", (stones,))


def test_every_species_has_an_egg_and_the_rule_is_sane(game):
    content = game[0].content
    eggs = {item.species_id for item in content.items.values() if item.kind == "pet_egg"}
    assert eggs == set(content.species)
    assert all(content.items[f"egg_{species}"].price is None for species in content.species)
    rule = content.rules.breeding
    assert rule.affinity == 100
    assert 0 < rule.energy <= 100
    assert rule.cost.stones > 0
    assert rule.cost.items == {}


def test_list_shows_rules_pairs_and_only_links_ready_pairs(game, play):
    account(game, play)
    fund(game)
    first = add_pet(game, "xuanhu")
    second = add_pet(game, "xuanhu")
    listing = play("breeding")
    assert listing.title == "灵宠培育 1/1"
    assert "亲密满 100" in listing.text() and "800 灵石" in listing.text()
    assert f"玄狐：编号 {first} + {second}" in listing.text()
    assert "可培育" in listing.text()
    assert links(listing) == [(2, "培育这一对", f"灵宠培育 {first} {second}")]
    assert listing.commands == ("灵宠列表",)
    assert not {command for _, _, command in links(listing)} & set(listing.commands)


def test_list_reports_blockers_instead_of_offering_the_pair(game, play):
    account(game, play)
    add_pet(game, "xuanhu", affinity=40)
    add_pet(game, "xuanhu", affinity=60)
    listing = play("breeding")
    assert "亲密不足（40/60）" in listing.text()
    assert links(listing) == []
    assert listing.commands == ("灵宠列表",)

    sql(game[1], "UPDATE pets SET affinity=100, energy=5")
    assert "精力不足" in play("breeding").text()

    sql(game[1], "UPDATE pets SET energy=100")
    sql(game[1], "UPDATE players SET stones=10")
    assert "灵石不足" in play("breeding").text()


def test_unregistered_player_can_read_the_rules_without_an_account(game, play):
    listing = play("breeding")
    assert "尚未结契" in listing.text()
    assert links(listing) == [(2, "开始领养", "灵宠领养 ")]
    assert not sql(game[1], "SELECT * FROM players")


def test_no_same_species_partner_is_reported_with_a_next_step(game, play):
    account(game, play)
    listing = play("breeding")
    assert "还没有同族伙伴" in listing.text()
    assert "灵宠召唤 " in listing.commands


def test_breeding_consumes_resources_and_yields_the_species_egg(game, play):
    account(game, play)
    fund(game)
    first = add_pet(game, "qingluan")
    second = add_pet(game, "qingluan")
    before_stones = player(game[1])["stones"]
    result = play("breeding", f"{first} {second}", op="breed-1")
    assert result.title == "灵宠培育成功"
    assert f"灵石 -800" in result.text()
    assert "获得青鸾灵卵 ×1。" in result.text()
    assert player(game[1])["stones"] == before_stones - 800
    assert items(game[1])["egg_qingluan"] == 1
    energies = {row["pet_id"]: row["energy"] for row in sql(game[1], "SELECT pet_id, energy FROM pets")}
    assert energies[first] == 70 and energies[second] == 70
    assert links(result) == [(2, "孵化灵卵", "灵宠使用 青鸾灵卵")]


def test_bred_egg_hatches_into_a_new_partner(game, play):
    account(game, play)
    fund(game)
    first = add_pet(game, "qingluan")
    second = add_pet(game, "qingluan")
    play("breeding", f"{first} {second}", op="breed-hatch")
    hatched = play("use", "青鸾灵卵 1", op="hatch-bred")
    assert hatched.title == "灵卵孵化"
    assert "获得青鸾" in hatched.text()
    assert items(game[1]).get("egg_qingluan", 0) == 0
    assert len(sql(game[1], "SELECT * FROM pets WHERE user_id='u1'")) == 4


def test_breeding_rejects_bad_pairs_and_insufficient_resources(game, play):
    account(game, play)
    first = add_pet(game, "qingluan")
    second = add_pet(game, "qingluan")
    other = add_pet(game, "xuanhu")
    with pytest.raises(GameError, match="格式"):
        play("breeding", str(first))
    with pytest.raises(GameError, match="两只不同"):
        play("breeding", f"{first} {first}")
    with pytest.raises(GameError, match="没有属于你的在册灵宠"):
        play("breeding", f"{first} 999999")
    with pytest.raises(GameError, match="同一种族"):
        play("breeding", f"{first} {other}")
    sql(game[1], "UPDATE pets SET affinity=99 WHERE pet_id=?", (second,))
    with pytest.raises(GameError, match="亲密达到 100"):
        play("breeding", f"{first} {second}")
    sql(game[1], "UPDATE pets SET affinity=100, energy=10 WHERE pet_id=?", (second,))
    with pytest.raises(GameError, match="各有 30 精力"):
        play("breeding", f"{first} {second}")
    sql(game[1], "UPDATE pets SET energy=100")
    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="需要 800 灵石"):
        play("breeding", f"{first} {second}")
    assert items(game[1]).get("egg_qingluan") is None


def test_archived_and_departed_pets_cannot_breed(game, play):
    account(game, play)
    fund(game)
    first = add_pet(game, "qingluan")
    second = add_pet(game, "qingluan")
    sql(game[1], "UPDATE pets SET archived=1 WHERE pet_id=?", (second,))
    with pytest.raises(GameError, match="已封存"):
        play("breeding", f"{first} {second}")
    sql(game[1], "UPDATE pets SET archived=0 WHERE pet_id=?", (second,))
    sql(
        game[1],
        "INSERT INTO expeditions(user_id, pet_id, task_id, task_name, source_operation_id, started_at,"
        " finishes_at, state, reward_snapshot) VALUES ('u1', ?, 'job', '任务', 'op-exp', ?, ?, 'running', '{}')",
        (second, NOW - 10, NOW + 600),
    )
    with pytest.raises(GameError, match="外出派遣"):
        play("breeding", f"{first} {second}")
    assert items(game[1]).get("egg_qingluan") is None


def test_same_operation_replays_without_charging_twice(game, play):
    account(game, play)
    fund(game)
    first = add_pet(game, "qingluan")
    second = add_pet(game, "qingluan")
    first_reply = play("breeding", f"{first} {second}", op="breed-replay")
    # Non-battle actions are guarded by the operation cache, not a durable battle record.
    state = (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id"))
    assert play("breeding", f"{first} {second}", op="breed-replay", now=NOW + 1) == first_reply
    assert (player(game[1]), items(game[1]), sql(game[1], "SELECT pet_id, energy FROM pets ORDER BY pet_id")) == state
    assert items(game[1])["egg_qingluan"] == 1


def test_help_lists_the_breeding_entries(game, play):
    guide = play("help", "成长")
    assert "灵宠培育" in guide.text()
    assert "灵宠培育 编号A 编号B" in guide.text()


def test_native_payload_keeps_links_and_buttons_disjoint(game, play):
    account(game, play)
    fund(game)
    add_pet(game, "qingluan")
    add_pet(game, "qingluan")
    listing = play("breeding")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in listing.inline_commands}
    assert not linked & buttons
