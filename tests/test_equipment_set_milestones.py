import itertools

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import Reply
from nonebot_plugin_spirit_pet.gameplay import achievements
from nonebot_plugin_spirit_pet.gameplay.equipment_set_rewards import SET_REWARDS, claim_id
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, player, sql

NOW = 1_800_000_000
_METRIC_CALLS = itertools.count()


def account(play):
    play("adopt", "青鸾")


def metric(game, user="u1"):
    call = next(_METRIC_CALLS)
    values = []

    def run(conn):
        ctx = Context(Repository(conn), game[0].content, game[0].config, game[0].rng,
                      user, NOW, f"set-metric-{call}")
        values.append(achievements._metric(ctx, user, "equipment_set_claims"))
        return Reply("metric", ())

    game[1].transact(user, f"set-metric-{call}", NOW, run)
    return values[0]


def mark(game, set_id, claimed=1, user="u1"):
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, ?) "
        "ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=excluded.claimed",
        (user, claim_id(set_id), claimed),
    )


def test_metric_counts_only_configured_claimed_set_credentials(game, play):
    account(play)
    mark(game, "sky_wind")
    mark(game, "sky_wind")
    mark(game, "stone_guard", claimed=0)
    sql(game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) "
        "VALUES ('u1', 'equipment_set_reward_unconfigured', 1, 1)")

    assert metric(game) == 1
    assert metric(game, "stranger") == 0

    mark(game, "stone_guard")
    assert metric(game) == 2


def test_set_achievement_rewards_and_master_title_follow_claimed_milestones(game, play):
    account(play)
    mark(game, "sky_wind")
    mark(game, "stone_guard", claimed=0)
    sql(game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) "
        "VALUES ('u1', 'equipment_set_reward_unconfigured', 1, 1)")
    assert metric(game) == 1
    first_page = play("achievements", "15")
    assert "套装初成 · 可领奖 · 进度：1/1" in first_page.text()
    assert "灵宠成就领奖 套装初成" in first_page.commands
    assert "套装兼收 · 进行中 · 进度：1/2" in first_page.text()

    before_stones = player(game[1])["stones"]
    before_food = items(game[1]).get("spirit_food", 0)
    first = play("achievement_claim", "套装初成", op="set-achievement-first")
    assert first.title == "成就奖励已领取"
    assert player(game[1])["stones"] == before_stones + 200
    assert items(game[1])["spirit_food"] == before_food + 1
    assert play("achievement_claim", "套装初成", op="set-achievement-first").lines == first.lines
    assert player(game[1])["stones"] == before_stones + 200

    mark(game, "stone_guard")
    assert metric(game) == 2
    second_page = play("achievements", "15")
    assert "套装兼收 · 可领奖 · 进度：2/2" in second_page.text()
    play("achievement_claim", "套装兼收", op="set-achievement-pair")

    mark(game, "venom_edge")
    mark(game, "root_silk")
    assert metric(game) == 4
    last_page = play("achievements", "15")
    assert "套装全收 · 可领奖 · 进度：4/4" in last_page.text()
    assert "灵宠成就领奖 套装全收" in last_page.commands

    title_page = play("titles", "4")
    assert "20. 套装宗师 · 已获得 · 领取全部四套装备的完成奖励。" in title_page.text()
    assert "当前称号：套装宗师 · 已获得 2/20 项" in title_page.text()

    before_stones = player(game[1])["stones"]
    before_essence = items(game[1]).get("bloodline_essence", 0)
    final = play("achievement_claim", "套装全收", op="set-achievement-all")
    assert final.title == "成就奖励已领取"
    assert player(game[1])["stones"] == before_stones + 1200
    assert items(game[1])["bloodline_essence"] == before_essence + 3


def test_content_requires_set_milestone_targets_and_top_title(game):
    content = Catalog.load()
    targets = {
        entry.target for entry in content.achievements.values()
        if entry.metric == "equipment_set_claims"
    }
    assert targets == {1, 2, len(SET_REWARDS)}
    title = content.titles["equipment_set_master"]
    assert (title.metric, title.target, title.order) == (
        "equipment_set_claims", len(SET_REWARDS), len(content.titles),
    )


def test_help_and_native_achievement_link_expose_the_new_progress(game, play):
    assert "完成奖励与收藏进度" in play("help", "灵物与灵术").text()
    account(play)
    mark(game, "sky_wind")
    reply = play("achievements", "15")
    expected = {"灵宠成就领奖 套装初成"}
    assert {link.command for link in reply.inline_commands} == expected

    _, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in native
        if segment.type == "keyboard"
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons & expected == set()
