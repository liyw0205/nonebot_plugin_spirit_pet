from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config

from .support import sql

NOW = 1_800_000_000


def account(game, play, user="u1"):
    play("adopt", "青鸾", user=user)


def add_pet(game, species="qingluan", user="u1"):
    with game[1].connect() as conn:
        return conn.execute(
            "INSERT INTO pets(user_id, species_id, name, affinity, energy, energy_updated)"
            " VALUES (?, ?, ?, 100, 100, ?)",
            (user, species, species, NOW),
        ).lastrowid


def claim_rows(game, ids, user="u1"):
    for quest_id in ids:
        sql(
            game[1],
            "INSERT INTO quest_progress(user_id, quest_id, progress, claimed) VALUES (?, ?, 1, 1)"
            " ON CONFLICT(user_id, quest_id) DO UPDATE SET claimed=1",
            (user, quest_id),
        )


def test_content_defines_twenty_ordered_titles(game):
    titles = sorted(game[0].content.titles.values(), key=lambda title: title.order)
    assert len(titles) == 20
    assert [title.order for title in titles] == list(range(1, 21))
    assert len({title.name for title in titles}) == 20
    for title in titles:
        assert title.target > 0 and title.description


def test_catalog_previews_without_an_account(game, play):
    listing = play("titles")
    assert "尚未结契" in listing.text()
    assert "1. 初入仙途 · 未获得" in listing.text()
    assert listing.commands == ("灵宠称号 2", "灵宠帮助")
    assert not sql(game[1], "SELECT * FROM players")


def test_catalog_shows_the_current_title_and_progress(game, play):
    account(game, play)
    listing = play("titles")
    assert listing.title == "灵宠称号 1/4"
    assert "当前称号：初入仙途 · 已获得 1/20 项" in listing.text()
    assert "1. 初入仙途 · 已获得 · 与第一位伙伴结下灵契。" in listing.text()
    assert "2. 双灵同修 · 进度 0/1 · 拥有两只同族灵宠。" in listing.text()
    # 论剑客 is the eighth title, so it sits on the second page.
    assert "8. 论剑客 · 进度 0/10 · 在论剑中获胜十场。" in play("titles", "2").text()
    assert play("titles", "4").title == "灵宠称号 4/4"


def test_highest_ordered_held_title_wins(game, play):
    account(game, play)
    for order in range(1, 17):
        sql(
            game[1],
            "INSERT INTO pve_stage_progress(user_id, stage_id, first_cleared_at, first_operation_id)"
            " VALUES ('u1', ?, ?, ?)",
            (f"tower_{order:02d}", NOW, f"seed-tower-{order}"),
        )
    sql(game[1], "UPDATE pets SET realm=6")
    listing = play("titles")
    # 初入仙途、金丹真人、塔门守卫、万灵塔主、渡劫问鼎 are all satisfied.
    assert "当前称号：渡劫问鼎 · 已获得 5/20 项" in listing.text()
    assert "15. 万灵塔主 · 已获得" in play("titles", "3").text()
    assert "16. 渡劫问鼎 · 已获得" in play("titles", "4").text()


def test_main_quest_and_weekly_claim_titles(game, play):
    account(game, play)
    assert "11. 主线行者 · 进度 0/8" in play("titles", "3").text()
    claim_rows(game, [f"main_{index:02d}" for index in range(1, 9)])
    claim_rows(game, list(game[0].content.weekly_quests))
    listing = play("titles", "3")
    assert "11. 主线行者 · 已获得" in listing.text()
    assert "12. 周常不辍 · 已获得" in listing.text()
    assert "当前称号：周常不辍 · 已获得 3/20 项" in listing.text()


def test_duplicate_species_title_needs_two_of_one_species(game, play):
    account(game, play)
    add_pet(game, "qingluan")
    assert "2. 双灵同修 · 已获得" in play("titles").text()
    assert "当前称号：双灵同修 · 已获得 2/20 项" in play("titles").text()


def test_profile_shows_the_current_title(game, play):
    account(game, play)
    assert "称号：初入仙途 · 已获得 1/20 项" in play("status").text()


def test_help_lists_the_title_entry(game, play):
    guide = play("help", "身份与收集")
    assert "灵宠称号" in guide.text()


def test_native_payload_keeps_buttons_without_links(game, play):
    account(game, play)
    listing = play("titles")
    _, message = _qq_segments(listing, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(listing.commands)
    assert listing.inline_commands == ()
