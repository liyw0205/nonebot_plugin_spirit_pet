import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, player, sql

NOW = 1_800_000_000
RICE = 1800
DAY = 86_400
WILT_AFTER = 48 * 3600


def open_and_plant(play, game, seed_name="灵稻种", plot=1, op="f2"):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", str(plot), now=NOW, op=f"{op}-open")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','seed_spirit_rice',5) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+5"
        )
    play("farm_plant", f"{plot} {seed_name}", now=NOW + 1, op=f"{op}-plant")


def test_upgrade_shortens_growth(game, play):
    open_and_plant(play, game, op="up")
    sql(game[1], "UPDATE players SET stones=10000")
    before = player(game[1])["stones"]
    result = play("farm_upgrade", "1", now=NOW + 2, op="up-1")
    assert "升至 1 级" in result.lines[0]
    assert player(game[1])["stones"] == before - 800
    # 灵稻 base 1800 -> tier1: 1530; harvested at +1529 elapsed -> 1s remaining
    with pytest.raises(GameError, match="剩余 1 秒"):
        play("farm_harvest", "1", now=NOW + 1 + 1529, op="up-early")
    result = play("farm_harvest", "1", now=NOW + 1 + 1530, op="up-ok")
    assert "成熟收获" in result.lines[0]


def test_upgrade_second_level_and_cap(game, play):
    open_and_plant(play, game, op="cap")
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_upgrade", "1", now=NOW + 2, op="cap-1")
    result = play("farm_upgrade", "1", now=NOW + 3, op="cap-2")
    assert "升至 2 级" in result.lines[0]
    with pytest.raises(GameError, match="最高等级"):
        play("farm_upgrade", "1", now=NOW + 4, op="cap-3")
    # tier2: 1800*70/100 = 1260
    result = play("farm_harvest", "1", now=NOW + 1 + 1260, op="cap-harvest")
    assert "成熟收获" in result.lines[0]


def test_upgrade_requires_open_plot_and_stones(game, play):
    play("adopt", "青鸾", now=NOW)
    with pytest.raises(GameError, match="尚未开垦"):
        play("farm_upgrade", "1", now=NOW, op="u-req")
    sql(game[1], "UPDATE players SET stones=300")
    play("farm_open", "1", now=NOW, op="u-open")
    sql(game[1], "UPDATE players SET stones=100")
    with pytest.raises(GameError, match="灵石不足"):
        play("farm_upgrade", "1", now=NOW + 1, op="u-poor")



def test_wilt_returns_seed_only(game, play):
    open_and_plant(play, game, op="wilt")
    planted_at = NOW + 1
    wilt_time = planted_at + RICE + 48 * 3600
    before_food = items(game[1])["spirit_food"]
    result = play("farm_harvest", "1", now=wilt_time, op="wilt-clean")
    assert "已枯萎" in result.lines[0]
    assert items(game[1])["seed_spirit_rice"] == 5  # stocked 5, planted 1, returned 1
    assert items(game[1])["spirit_food"] == before_food  # no yield
    page = play("farm", now=wilt_time + 1)
    assert "田位 1 · 待播种" in page.lines


def test_wilt_boundary_not_yet(game, play):
    open_and_plant(play, game, op="wiltb")
    # Exactly mature+48h-1s: still good yield.
    result = play("farm_harvest", "1", now=NOW + 1 + RICE + 48 * 3600 - 1, op="wiltb-ok")
    assert "成熟收获" in result.lines[0]


def test_high_tier_crops_plant_and_harvest(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="hi-open")
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','seed_twin_grain',2) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+2"
        )
    play("farm_plant", "1 双穗麦种", now=NOW + 1, op="hi-plant")
    result = play("farm_harvest", "1", now=NOW + 1 + 10800, op="hi-harvest")
    assert "灵粮 +2" in result.text()
    assert "锻灵矿 +2" in result.text()
    with game[1].connect() as conn:
        conn.execute(
            "INSERT INTO inventory(user_id,item_id,quantity) VALUES ('u1','seed_void_lotus',1)"
        )
    play("farm_plant", "1 虚灵仙葩种", now=NOW + 2 + 10800, op="hi-plant2")
    # void_lotus base 14400 at tier0
    result2 = play("farm_harvest", "1", now=NOW + 2 + 25200, op="hi-harvest2")
    assert "修为 +120" in result2.text()
    assert "灵石 +150" in result2.text()
    assert "血脉精华 +2" in result2.text()


def test_replay_upgrades_once(game, play):
    open_and_plant(play, game, op="rp")
    sql(game[1], "UPDATE players SET stones=10000")
    before = player(game[1])["stones"]
    first = play("farm_upgrade", "1", now=NOW + 2, op="rp-up")
    assert play("farm_upgrade", "1", now=NOW + 3, op="rp-up") == first
    assert player(game[1])["stones"] == before - 800  # charged once


def test_native_clean_and_parse(game, play):
    play("adopt", "青鸾", now=NOW)
    sql(game[1], "UPDATE players SET stones=10000")
    play("farm_open", "1", now=NOW, op="nv-open")
    page = play("farm", now=NOW + 1)
    assert any(link.command == "灵宠升级 1" for link in page.inline_commands)
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = [
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    ]
    assert len(buttons) <= 4
    assert not set(buttons) & {link.command for link in page.inline_commands}
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠升级 1") == ("farm_upgrade", "1")
