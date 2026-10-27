"""Team farm-help contracts: watering is a real cross-player daily action."""

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import farming

from .support import player, player_uid, sql

NOW = 1_800_000_000
DAY = 86400


def setup_team(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    sql(game[1], "UPDATE players SET stones=10000")
    with game[1].connect() as conn:
        team = conn.execute("INSERT INTO teams(leader_id) VALUES ('u1')").lastrowid
        conn.execute("INSERT INTO team_members(user_id, team_id) VALUES ('u1', ?)", (team,))
        conn.execute("INSERT INTO team_members(user_id, team_id) VALUES ('u2', ?)", (team,))
    return team, player_uid(game[1], "u2")


def seed(game, user="u2", amount=4):
    sql(
        game[1],
        "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, 'seed_spirit_rice', ?)"
        " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
        (user, amount),
    )


def open_plant(game, play, user="u2", plot=1, seed_name="灵稻种"):
    seed(game, user)
    play("farm_open", str(plot), user=user)
    play("farm_plant", f"{plot} {seed_name}", user=user)


def rice(game):
    return game[0].content.crops["spirit_rice"].duration


def water_rows(game):
    return sql(
        game[1],
        "SELECT user_id, quest_id, progress, claimed FROM quest_progress"
        " WHERE quest_id LIKE 'farm_water%' ORDER BY user_id, quest_id",
    )


def test_rule_defaults_are_content_driven(game):
    rule = game[0].content.rules.farm_water
    assert (rule.seconds, rule.daily_limit, rule.stones) == (60, 3, 10)


def test_unregistered_preview_is_read_only(game, play):
    page = play("farm_water", user="u9")
    assert page.title == "灵田互助"
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert [link.command for link in page.inline_commands] == ["灵宠领养 "]
    assert sql(game[1], "SELECT user_id FROM players") == []


def test_without_a_team_the_command_explains_the_requirement(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="尚未加入队伍"):
        play("farm_water")
    with pytest.raises(GameError, match="尚未加入队伍"):
        play("farm_water", "10001")


def test_team_page_lists_each_teammate_and_their_farm(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    page = play("farm_water")
    assert page.title == "灵田互助"
    assert "今日互助：0/3 次" in page.text()
    assert f"UID {uid2} · 生长 1 块 · 已成熟 0 块 · 今日可浇水 1 块" in page.text()
    assert [link.command for link in page.inline_commands] == [f"灵宠浇水 {uid2}"]
    assert page.commands == ("灵宠队伍", "灵宠灵田", "灵宠帮助 组队与派遣")


def test_target_page_lists_plots_and_only_links_growing_ones(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    page = play("farm_water", str(uid2))
    assert page.title == f"灵田互助 · UID {uid2}"
    assert play("farm_water", f"UID {uid2}").title == page.title
    assert f"田位 1 · 灵稻 · 剩余 {rice(game)} 秒" in page.text()
    assert "田位 2 · 待开垦" in page.text()
    assert [link.command for link in page.inline_commands] == [f"灵宠浇水 {uid2} 1"]


def test_watering_shortens_the_owner_crop_and_pays_the_helper(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    reply = play("farm_water", f"{uid2} 1")
    assert reply.title == "灵田互助"
    assert "成熟时间缩短 60 秒" in reply.text()
    assert "剩余 1740 秒" in reply.text()
    assert player(game[1], "u1")["stones"] == 10010
    assert f"剩余 1740 秒" in play("farm_water", str(uid2)).text()
    rows = {row["quest_id"]: row for row in water_rows(game)}
    assert rows["farm_water_cut_1"]["progress"] == 60
    assert rows[f"farm_water_day_2027-01-15_u2_1"]["claimed"] == 1
    assert rows["farm_water_daily_2027-01-15"]["progress"] == 1
    with pytest.raises(GameError, match="今天已经为"):
        play("farm_water", f"{uid2} 1")
    assert player(game[1], "u1")["stones"] == 10010


def test_one_plot_once_per_day_and_three_plots_per_helper(game, play):
    _, uid2 = setup_team(game, play)
    for plot in range(1, 5):
        open_plant(game, play, plot=plot)
    for plot in (1, 2, 3):
        assert play("farm_water", f"{uid2} {plot}").title == "灵田互助"
    with pytest.raises(GameError, match="今日互助次数已用完"):
        play("farm_water", f"{uid2} 4")
    page = play("farm_water", str(uid2))
    assert "今日互助 3/3 次" in page.text()
    assert "今日次数已用完" in page.text()
    assert page.inline_commands == ()


def test_harvest_uses_the_shortened_growth_and_clears_the_cut(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    play("farm_water", f"{uid2} 1")
    with pytest.raises(GameError, match="还在生长"):
        play("farm_harvest", "1", user="u2", now=NOW + rice(game) - 61)
    assert play("farm_harvest", "1", user="u2", now=NOW + rice(game) - 59).title == "灵田收获"
    assert sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE quest_id='farm_water_cut_1'"
    ) == []


def test_replant_does_not_inherit_the_previous_watering_cut(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    play("farm_water", f"{uid2} 1")
    seed(game, "u2")
    play("farm_harvest", "1 灵稻种", user="u2", now=NOW + rice(game) - 59)
    page = play("farm_water", str(uid2), now=NOW + rice(game) - 59)
    assert f"田位 1 · 灵稻 · 剩余 {rice(game)} 秒" in page.text()
    with pytest.raises(GameError, match="还在生长"):
        play("farm_harvest", "1", user="u2", now=NOW + rice(game) - 59 + rice(game) - 1)


def test_next_day_restores_the_helper_quota_and_plot_mark(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    play("farm_water", f"{uid2} 1")
    play("farm_open", "2", user="u2", now=NOW + DAY)
    play("farm_plant", "2 灵稻种", user="u2", now=NOW + DAY)
    page = play("farm_water", str(uid2), now=NOW + DAY)
    assert "今日互助 0/3 次" in page.text()
    assert "今日已浇水" not in page.text()
    assert play("farm_water", f"{uid2} 2", now=NOW + DAY).title == "灵田互助"
    assert player(game[1], "u1")["stones"] == 10020


def test_state_persists_across_restart(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    play("farm_water", f"{uid2} 1")
    from nonebot_plugin_spirit_pet.application.game import Game
    from nonebot_plugin_spirit_pet.storage.database import Store

    reopened = Store(game[1].path)
    reopened.initialize()
    restarted = Game(reopened, game[0].config, game[0].rng, content=game[0].content)
    target = restarted.execute("u1", "farm_water", str(uid2), "restart-farm", NOW)
    assert "今日已浇水" in target.text()
    page = restarted.execute("u1", "farm_water", "", "restart-farm-list", NOW)
    assert "今日互助：1/3 次" in page.text()


def test_same_operation_replays_without_a_second_reward(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    first = play("farm_water", f"{uid2} 1", op="water-once")
    again = play("farm_water", f"{uid2} 1", op="water-once")
    assert again.title == first.title and again.lines == first.lines
    assert player(game[1], "u1")["stones"] == 10010
    assert [row["progress"] for row in water_rows(game) if row["quest_id"] == "farm_water_daily_2027-01-15"] == [1]


def test_mature_empty_and_wilted_plots_are_rejected(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    with pytest.raises(GameError, match="已经成熟"):
        play("farm_water", f"{uid2} 1", now=NOW + rice(game))
    with pytest.raises(GameError, match="已经枯萎"):
        play("farm_water", f"{uid2} 1", now=NOW + rice(game) + 48 * 3600)
    play("farm_open", "2", user="u2")
    with pytest.raises(GameError, match="还没有播种"):
        play("farm_water", f"{uid2} 2")
    with pytest.raises(GameError, match="尚未开垦"):
        play("farm_water", f"{uid2} 3")


def test_non_teammate_self_and_unknown_targets_are_rejected(game, play):
    _, uid2 = setup_team(game, play)
    play("adopt", "白泽", user="u3")
    uid1 = player_uid(game[1], "u1")
    uid3 = player_uid(game[1], "u3")
    with pytest.raises(GameError, match="不能为自己的灵田浇水"):
        play("farm_water", str(uid1))
    with pytest.raises(GameError, match="只能帮助同一队伍的队友"):
        play("farm_water", str(uid3))
    with pytest.raises(GameError, match="没有找到这位玩家"):
        play("farm_water", "99999")
    assert player(game[1], "u1")["stones"] == 10000


def test_native_payload_keeps_buttons_and_links_separate(game, play):
    _, uid2 = setup_team(game, play)
    open_plant(game, play)
    page = play("farm_water")
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    links = {link.command for link in page.inline_commands}
    assert buttons == set(page.commands)
    assert buttons & links == set()
    assert links == {f"灵宠浇水 {uid2}"}


def test_help_and_parse_contract(game, play):
    assert "灵宠浇水" in play("help", "血脉与道具").text()
    from nonebot_plugin_spirit_pet.adapters import handlers

    assert handlers._parse("灵宠浇水 10001 1") == ("farm_water", "10001 1")
    assert handlers._parse("灵宠浇水") == ("farm_water", "")
