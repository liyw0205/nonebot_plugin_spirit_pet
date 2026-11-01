"""Crop rotation: changing the crop on a plot pays a yield bonus; repeating it pays nothing."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import farming
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000
DAY = 86400


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def crops(game):
    return sorted(game[0].content.crops.values(), key=lambda crop: crop.id)


def seed_of(game, crop):
    return game[0].content.items[crop.seed_item].name


def grant_seeds(game, crop, amount=4, user="u1"):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, crop.seed_item, amount),
    )


def ready(game, play):
    play("adopt", "青鸾")
    sql(game[1], "UPDATE players SET stones=20000 WHERE user_id='u1'")
    play("farm_open", "1", op="open")
    first, second = crops(game)[0], crops(game)[1]
    grant_seeds(game, first)
    grant_seeds(game, second)
    return first, second


def plant(game, play, crop, *, op, plot=1, now=NOW):
    play("farm_plant", f"{plot} {seed_of(game, crop)}", op=op, now=now)


def harvest_at(game, play, crop, *, op, plot=1, now):
    return play("farm_harvest", str(plot), op=op, now=now)


def duration_of(game, plot, crop):
    return farming._growth_seconds(ctx_of(game), plot, crop)


def test_rule_is_wired_and_bounded(game):
    rule = game[0].content.rules.farm_rotation
    assert 1 <= rule.rate_percent <= 100
    from nonebot_plugin_spirit_pet.domain.content import FarmRotationRule

    assert FarmRotationRule.model_validate({"rate_percent": 20}).rate_percent == 20
    with pytest.raises(ValidationError):
        FarmRotationRule.model_validate({"rate_percent": 0})
    with pytest.raises(ValidationError):
        FarmRotationRule.model_validate({"rate_percent": 101})


def test_the_first_planting_has_no_previous_crop(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="first")
    ctx = ctx_of(game)
    assert farming.last_crop(ctx, 1) is None
    assert not farming.rotated(ctx, 1)
    assert farming.reward_multiplier(ctx, 1) == 1.0


def test_changing_the_crop_grants_the_bonus(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="season-1")
    harvest_at(game, play, first, op="h1", now=NOW + duration_of(game, 1, first))
    plant(game, play, second, op="season-2")
    assert farming.rotated(ctx_of(game), 1)
    assert farming.reward_multiplier(ctx_of(game), 1) == 1 + game[0].content.rules.farm_rotation.rate_percent / 100


def test_the_bonus_raises_the_actual_payout(game, play):
    first, _ = ready(game, play)
    rate = game[0].content.rules.farm_rotation.rate_percent
    exp_crop = next(crop for crop in crops(game) if crop.reward_exp and crop.id != first.id)
    grant_seeds(game, exp_crop)

    plant(game, play, first, op="plain-1")
    harvest_at(game, play, first, op="plain-h", now=NOW + duration_of(game, 1, first))

    plant(game, play, exp_crop, op="rot-1")
    exp_before = sql(game[1], "SELECT exp FROM pets WHERE user_id='u1'")[0]["exp"]
    reply = harvest_at(
        game, play, exp_crop, op="rot-h",
        now=NOW + duration_of(game, 1, first) + duration_of(game, 1, exp_crop),
    )
    gained = sql(game[1], "SELECT exp FROM pets WHERE user_id='u1'")[0]["exp"] - exp_before
    assert f"轮作加成 +{rate}%" in reply.text()
    assert gained == int(exp_crop.reward_exp * (1 + rate / 100))


def test_repeating_the_same_crop_earns_nothing(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="rep-1")
    harvest_at(game, play, first, op="rep-h1", now=NOW + duration_of(game, 1, first))
    plant(game, play, first, op="rep-2")
    ctx = ctx_of(game)
    assert not farming.rotated(ctx, 1)
    assert farming.reward_multiplier(ctx, 1) == 1.0
    reply = harvest_at(game, play, first, op="rep-h2", now=NOW + duration_of(game, 1, first) * 3)
    assert "轮作加成" not in reply.text()


def test_a_wilted_season_still_counts_as_the_previous_crop(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="wilt-1")
    harvest_at(game, play, first, op="wilt-h", now=NOW + duration_of(game, 1, first) + farming.WILT_AFTER + 60)
    ctx = ctx_of(game)
    assert farming.last_crop(ctx, 1) == first.id
    plant(game, play, second, op="wilt-2")
    assert farming.rotated(ctx_of(game), 1)


def test_replanting_in_the_same_command_opens_a_new_season(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="re-1")
    play(
        "farm_harvest", f"1 {seed_of(game, second)}", op="re-h",
        now=NOW + duration_of(game, 1, first),
    )
    ctx = ctx_of(game)
    assert farming.last_crop(ctx, 1) == first.id
    assert farming.rotated(ctx, 1)


def test_the_page_shows_the_rotation_state(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="page-1")
    harvest_at(game, play, first, op="page-h", now=NOW + duration_of(game, 1, first))
    page = play("farm")
    assert first.name in page.text()
    assert "上一季" in page.text()
    plant(game, play, second, op="page-2")
    assert "轮作加成" in play("farm").text()


def test_the_rotation_window_closes_after_harvest(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="close-1")
    harvest_at(game, play, first, op="close-h", now=NOW + duration_of(game, 1, first))
    plant(game, play, second, op="close-2")
    harvest_at(game, play, second, op="close-h2", now=NOW + duration_of(game, 1, first) * 3)
    ctx = ctx_of(game)
    assert farming.last_crop(ctx, 1) == second.id
    assert not farming.rotated(ctx, 1)


def test_rotation_is_per_plot(game, play):
    first, second = ready(game, play)
    play("farm_open", "2", op="open-2")
    plant(game, play, first, op="plot1-1", plot=1)
    harvest_at(game, play, first, op="plot1-h", plot=1, now=NOW + duration_of(game, 1, first))
    plant(game, play, second, op="plot1-2", plot=1)
    plant(game, play, first, op="plot2-1", plot=2)
    ctx = ctx_of(game)
    assert farming.rotated(ctx, 1)
    assert not farming.rotated(ctx, 2)


def test_state_survives_a_restart(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="persist-1")
    harvest_at(game, play, first, op="persist-h", now=NOW + duration_of(game, 1, first))
    plant(game, play, second, op="persist-2")
    assert farming.rotated(ctx_of(game), 1)
    assert "轮作加成" in play("farm").text()


def test_objective_help_and_parse_still_work(game, play):
    ready(game, play)
    assert "灵宠灵田" in play("help", "血脉与道具").text()
    assert handlers._parse("灵宠灵田") == ("farm", "")
    assert handlers._parse("灵宠播种 1 灵稻种") == ("farm_plant", "1 灵稻种")


def test_same_operation_replays_identically(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="replay-1")
    harvest_at(game, play, first, op="replay-h", now=NOW + duration_of(game, 1, first))
    plant(game, play, second, op="replay-2")
    first_reply = harvest_at(game, play, second, op="replay-h2", now=NOW + duration_of(game, 1, first) * 3)
    stones = player(game[1])["stones"]
    again = play("farm_harvest", "1", op="replay-h2", now=NOW + duration_of(game, 1, first) * 3)
    assert again.text() == first_reply.text()
    assert player(game[1])["stones"] == stones


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    first, second = ready(game, play)
    plant(game, play, first, op="qq-1")
    harvest_at(game, play, first, op="qq-h", now=NOW + duration_of(game, 1, first))
    plant(game, play, second, op="qq-2")
    page = play("farm")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons
    assert len(page.commands) <= 4
