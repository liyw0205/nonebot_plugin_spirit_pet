import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import player, sql

NOW = 1_800_000_000
NEW_ENCOUNTERS = (
    "spring_echo", "valley_vein", "cave_mural", "ember_forge", "ruins_altar", "void_bridge", "cloud_stele",
)
ROUTE_OF = {
    "spirit_spring": "spring_echo",
    "starfall_valley": "valley_vein",
    "ancient_cave": "cave_mural",
    "ember_vein": "ember_forge",
    "primordial_ruins": "ruins_altar",
    "void_frontier": "void_bridge",
    "tribulation_clouds": "cloud_stele",
}


def stones(game):
    return player(game[1])["stones"]


def discover(game, encounter_id, user="u1"):
    sql(
        game[1],
        "INSERT INTO adventure_discoveries(user_id, encounter_id, discovered_at) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, encounter_id) DO NOTHING",
        (user, encounter_id, NOW),
    )


def test_seven_new_encounters_are_in_place(game):
    content = game[0].content
    assert len(content.encounters) == 21
    for encounter_id in NEW_ENCOUNTERS:
        encounter = content.encounters[encounter_id]
        assert encounter.weight > 0
        assert encounter.text
        assert len(encounter.options) == 2
        assert len({option.id for option in encounter.options}) == 2
        assert encounter.reward.stones.minimum <= encounter.reward.stones.maximum
        for option in encounter.options:
            assert option.label and option.text
            assert option.reward.stones.minimum > 0 or option.reward.items
            assert all(item in content.items for item in option.reward.items)


def test_each_route_gained_exactly_one_encounter(game):
    content = game[0].content
    listed = []
    for route in content.exploration_routes.values():
        assert len(route.encounters) == 3
        assert all(encounter_id in content.encounters for encounter_id in route.encounters)
        listed.extend(route.encounters)
    assert sorted(listed) == sorted(content.encounters)
    for route_id, encounter_id in ROUTE_OF.items():
        assert encounter_id in content.exploration_routes[route_id].encounters


def test_new_encounter_rewards_sit_inside_their_route_scale(game):
    content = game[0].content
    for route_id, encounter_id in ROUTE_OF.items():
        route = content.exploration_routes[route_id]
        siblings = [content.encounters[item] for item in route.encounters if item != encounter_id]
        new = content.encounters[encounter_id]
        low = min(entry.reward.stones.minimum for entry in siblings)
        high = max(entry.reward.stones.maximum for entry in siblings)
        assert low - 10 <= new.reward.stones.minimum <= high + 10
        assert low - 10 <= new.reward.stones.maximum <= high + 10


def test_discovering_and_echoing_a_new_encounter_pays_once(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未发现灵泉回响"):
        play("echo_choose", "灵泉回响 汲取")

    discover(game, "spring_echo")
    page = play("echoes")
    assert "灵泉回响" in page.text()
    assert "灵宠回响选择 灵泉回响 汲取" in {link.command for link in page.inline_commands}

    before = stones(game)
    reply = play("echo_choose", "灵泉回响 汲取", op="echo-new")
    assert stones(game) == before + 90
    assert play("echo_choose", "灵泉回响 汲取", op="echo-new").lines == reply.lines
    with pytest.raises(GameError, match="已回响（汲取），其余选项已失效"):
        play("echo_choose", "灵泉回响 静听")


def test_counts_and_ceilings_follow_the_content(game, play):
    content = game[0].content
    assert len(content.encounters) == 21
    targets = {}
    for achievement in content.achievements.values():
        targets.setdefault(achievement.metric, set()).add(achievement.target)
    assert max(targets["adventures_discovered"]) == 21
    assert max(targets["echo_claims"]) == 21
    assert {5, 10} <= targets["adventures_discovered"]
    titles = {title.id: title for title in content.titles.values()}
    assert titles["echo_all"].target == 21
    assert "二十一" in titles["echo_all"].description

    play("adopt", "青鸾")
    assert "已发现 0/21 条奇闻" in play("echoes").text()
    discover(game, "cloud_stele")
    assert "已发现 1/21 条奇闻" in play("echoes").text()
    assert "奇闻发现：1/21" in play("adventure_codex").text()
    hub = next(text for text in play("objectives").lines if text.startswith("回响："))
    assert "已发现 1/21 条奇闻" in hub
