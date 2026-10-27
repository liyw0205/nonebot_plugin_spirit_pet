import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
RICE = 1800  # 灵稻 duration


def row(page, text):
    return next(line for line in page.lines if text in line)


def buy_seed(game, seed_id="seed_spirit_rice"):
    sql(game[1], "UPDATE players SET stones=10000")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1',?,5) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+5",
            (seed_id,),
        )



def test_plot_open_ladder_costs(game, play):
    play("adopt", "青鸾", now=NOW)
    expected = (200, 500, 1200, 2500)
    stones = 10000
    sql(game[1], f"UPDATE players SET stones={stones}")
    for plot in range(1, 5):
        before = player(game[1])["stones"]
        play("farm_open", str(plot), now=NOW + plot, op=f"open-{plot}")
        assert player(game[1])["stones"] == before - expected[plot - 1]
    page = play("farm", now=NOW + 10)
    assert "田位 1 · 待播种" in page.lines
    assert "田位 4 · 待播种" in page.lines
    with pytest.raises(GameError, match="已经开垦"):
        play("farm_open", "1", now=NOW + 11, op="open-again")


def test_plant_grow_harvest_full_cycle(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="cycle-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW + 1, op="cycle-plant")
    with pytest.raises(GameError, match="还在生长"):
        play("farm_harvest", "1", now=NOW + 2, op="cycle-early")
    result = play("farm_harvest", "1", now=NOW + 1 + RICE, op="cycle-harvest")
    assert "灵稻成熟收获" in result.lines[0]
    assert "灵粮 +3" in result.text()  # FixedRandom minimum of 3-5
    # Plot returns to 待播种; crop rows cleared.
    page = play("farm", now=NOW + 2 + RICE)
    assert "田位 1 · 待播种" in page.lines
    assert not sql(game[1], "SELECT quest_id FROM quest_progress WHERE quest_id LIKE 'farm_crop_1_%'")


def test_renew_once_per_growth_and_costs_by_remaining(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="renew-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW, op="renew-plant")
    # At NOW+900: remaining 900s -> cost 90 stones, cut 90s.
    before = player(game[1])["stones"]
    result = play("farm_renew", "1", now=NOW + 900, op="renew-once")
    assert "花费 90 灵石" in result.lines[0]
    assert player(game[1])["stones"] == before - 90
    with pytest.raises(GameError, match="已经翻新过"):
        play("farm_renew", "1", now=NOW + 901, op="renew-twice")
    # Renewed flag persists until harvest, so even a mature plot reports renewed.
    with pytest.raises(GameError, match="已经翻新过"):
        play("farm_renew", "1", now=NOW + RICE, op="renew-mature")


def test_rejection_paths(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="尚未开垦"):
        play("farm_plant", "1 灵稻种", now=NOW, op="rej-plant")
    with pytest.raises(GameError, match="尚未开垦"):
        play("farm_harvest", "1", now=NOW, op="rej-harvest")
    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="数量须为"):
        play("farm_open", "9", now=NOW, op="rej-bound")
    with pytest.raises(GameError, match="灵石不足"):
        play("farm_open", "4", now=NOW, op="rej-open-poor")
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="rej-open")
    with pytest.raises(GameError, match="未找到该作物"):
        play("farm_plant", "1 不存在的种子", now=NOW + 1, op="rej-seed")
    with pytest.raises(GameError, match="不接受参数"):
        play("farm", "1", now=NOW + 1, op="rej-arg")


def test_clock_rollback_rejected(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW + 100, op="clk-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW + 200, op="clk-plant")
    with pytest.raises(GameError, match="早于种植时间"):
        play("farm_harvest", "1", now=NOW + 100, op="clk-harvest")
    with pytest.raises(GameError, match="早于种植时间"):
        play("farm_renew", "1", now=NOW + 100, op="clk-renew")


def test_unregistered_read_only(game, play):
    page = play("farm", user="u9", now=NOW)
    assert page.title == "灵宠灵田"
    assert "尚未结契" in page.text()
    assert page.inline_commands[0].command == "灵宠领养 "
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_replay_returns_original_reply(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    first = play("farm_open", "1", now=NOW, op="rep-open")
    assert play("farm_open", "1", now=NOW + 1, op="rep-open") == first
    buy_seed(game)
    planted = play("farm_plant", "1 灵稻种", now=NOW + 2, op="rep-plant")
    assert play("farm_plant", "1 灵稻种", now=NOW + 3, op="rep-plant") == planted
    harvested = play("farm_harvest", "1", now=NOW + 2 + RICE, op="rep-harvest")
    assert play("farm_harvest", "1", now=NOW + 3 + RICE, op="rep-harvest") == harvested
    assert items(game[1])["spirit_food"] == 3 + 3  # starter 3 + FixedRandom minimum 3


def test_renew_replay_is_idempotent(game, play):
    """The card requires 翻新 to replay without charging twice."""
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="rn-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW, op="rn-plant")
    charged = play("farm_renew", "1", now=NOW + 900, op="rn-renew")
    stones = player(game[1])["stones"]
    assert play("farm_renew", "1", now=NOW + 901, op="rn-renew") == charged
    assert player(game[1])["stones"] == stones
    with pytest.raises(GameError, match="已经翻新过"):
        play("farm_renew", "1", now=NOW + 902, op="rn-renew-again")


def test_renew_shortens_the_growth_the_harvest_uses(game, play):
    """The 10% cut must reach harvest, not just the reply text.

    1800s crop renewed immediately: 180s comes off, so it matures at 1620s and
    a harvest at 1619s is still refused.
    """
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="rc-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW, op="rc-plant")
    play("farm_renew", "1", now=NOW, op="rc-renew")
    # Without the cut this plot would still need the full 1800s.
    with pytest.raises(GameError, match="还在生长，剩余 1 秒"):
        play("farm_harvest", "1", now=NOW + 1619, op="rc-early")
    assert "灵稻成熟收获" in play("farm_harvest", "1", now=NOW + 1620, op="rc-ok").lines[0]


def test_renew_cut_clears_with_the_harvest(game, play):
    """A replanted plot must not inherit the previous growth's shortcut."""
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="rcc-open")
    buy_seed(game, seed_id="seed_spirit_rice")
    play("farm_plant", "1 灵稻种", now=NOW, op="rcc-plant")
    play("farm_renew", "1", now=NOW, op="rcc-renew")
    play("farm_harvest", "1 灵稻种", now=NOW + 1620, op="rcc-harvest")
    # The replanted crop starts fresh: the full 1800s is required again.
    with pytest.raises(GameError, match="还在生长，剩余 1 秒"):
        play("farm_harvest", "1", now=NOW + 1620 + 1799, op="rcc-early")
    assert "灵稻成熟收获" in play(
        "farm_harvest", "1", now=NOW + 1620 + 1800, op="rcc-ok"
    ).lines[0]


def test_objectives_hub_and_help_contract(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="hub-open")
    buy_seed(game)
    play("farm_plant", "1 灵稻种", now=NOW, op="hub-plant")
    # Mature the crop by time travel.
    result = play("farm_harvest", "1", now=NOW + RICE, op="hub-harvest")
    hub = play("objectives", now=NOW + RICE + 1)
    assert "灵田：1 块可收获" in hub.text() or "灵田" in hub.text()
    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    growth = _HELP_SECTIONS["血脉与道具"]
    assert ("灵宠灵田", "灵宠灵田", "查看灵田状态，开垦、播种与收获。") in growth
    assert ("灵宠收获 田位 补种种子名", "灵宠收获 ", "收获产出；带上种子名可原地补种。") in growth


def test_native_keyboard_stays_clean(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    page = play("farm", now=NOW)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}


def test_parse_routes_farming():
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠灵田") == ("farm", "")
    assert handlers._parse("灵宠开垦 1") == ("farm_open", "1")
    assert handlers._parse("灵宠播种 1 灵稻种") == ("farm_plant", "1 灵稻种")
    assert handlers._parse("灵宠收获 1") == ("farm_harvest", "1")
    assert handlers._parse("灵宠翻新 1") == ("farm_renew", "1")
