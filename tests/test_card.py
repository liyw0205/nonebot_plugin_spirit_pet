"""灵宠名帖: the three visibility tiers of a cultivator card."""

import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters.handlers import _parse
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import achievements, borrow, card, collection_rank, titles
from nonebot_plugin_spirit_pet.gameplay.arena.common import current_season, rating
from nonebot_plugin_spirit_pet.gameplay.arena.tier_rewards import tier_of
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, player_uid, sql

NOW = 1_800_000_000
DAY = 86400


def context(game, user="u1"):
    service, store = game
    return Context(Repository(store.connect()), service.content, service.config, service.rng, user, NOW, f"card-{user}")


def two_players(game, play):
    play("adopt", "青鸾", user="u1")
    play("adopt", "玄狐", user="u2")
    return player_uid(game[1], "u2")


def befriend(game, first="u1", second="u2"):
    low, high = sorted((first, second))
    sql(game[1], "INSERT INTO friend_links(user_low, user_high, created_at) VALUES (?, ?, ?)",
        (low, high, NOW))


def snapshot(game):
    return (
        sql(game[1], "SELECT user_id, item_id, quantity FROM inventory ORDER BY user_id, item_id"),
        sql(game[1], "SELECT user_id, stones, active_pet_id FROM players ORDER BY user_id"),
        sql(game[1], "SELECT * FROM quest_progress ORDER BY user_id, quest_id"),
        sql(game[1], "SELECT battle_id FROM battle_records ORDER BY battle_id"),
    )


# ---------------------------------------------------------------- read-only

def test_unregistered_player_sees_a_preview_and_writes_nothing(game, play):
    page = play("card", user="ghost")
    assert "尚未结契" in page.text()
    assert sql(game[1], "SELECT user_id FROM players") == []
    assert sql(game[1], "SELECT quest_id FROM quest_progress") == []


# ---------------------------------------------------------------- self

def test_your_own_card_matches_the_account_pages(game, play):
    play("adopt", "青鸾")
    own = play("card")
    by_uid = play("card", str(player_uid(game[1], "u1")))
    assert own.lines == by_uid.lines
    assert "本人" in own.text()
    assert "出战阵容" in own.text()
    assert "成就：已领取" in own.text()
    assert "图鉴：" in own.text()
    assert "好友：0 位" in own.text()


def test_the_card_never_leaks_purse_or_archive_or_registration(game, play):
    play("adopt", "青鸾")
    text = play("card").text()
    for secret in ("灵石", "背包", "封存", "注册时间"):
        assert secret not in text, f"{secret} must stay in 我的信息"


# ---------------------------------------------------------------- strangers

def test_a_stranger_only_sees_what_the_boards_publish(game, play):
    owner = two_players(game, play)
    page = play("card", str(owner))
    text = page.text()
    assert "陌生修士" in text
    assert f"UID {owner}" in text
    assert "论剑段位：" in text and "收集榜：" in text
    for hidden in ("出战阵容", "成就：", "图鉴：", "好友：", "挂出的伙伴", "灵石", "封存", "注册"):
        assert hidden not in text, f"{hidden} must not reach a stranger"


def test_a_stranger_gets_a_friend_invite(game, play):
    owner = two_players(game, play)
    page = play("card", str(owner))
    links = {link.label: link.command for link in page.inline_commands}
    assert links["加为好友"] == f"灵宠好友 添加 {owner}"


def test_an_unknown_uid_is_refused_without_writing(game, play):
    play("adopt", "青鸾")
    before = snapshot(game)
    with pytest.raises(GameError, match="未找到该 UID"):
        play("card", "999999")
    assert snapshot(game) == before


def test_a_non_numeric_argument_is_refused(game, play):
    play("adopt", "青鸾")
    with pytest.raises(GameError, match="格式：灵宠名帖"):
        play("card", "青鸾")


# ---------------------------------------------------------------- friends

def test_a_friend_sees_the_lineup_and_the_counts(game, play):
    owner = two_players(game, play)
    befriend(game)
    page = play("card", str(owner))
    text = page.text()
    assert "好友" in text and "陌生修士" not in text
    assert "出战阵容" in text
    assert "玄狐 · 启灵 1层" in text
    assert "成就：已领取 0 项" in text
    assert f"图鉴：1/{len(game[0].content.species)} 种" in text
    assert "好友：1 位" in text
    assert "挂出的伙伴：0 只" in text


def test_the_friend_card_counts_match_the_owning_pages(game, play):
    owner = two_players(game, play)
    befriend(game)
    ctx = context(game)
    with closing(ctx.repo.conn):
        claimed = achievements.claimed_count(ctx, "u2")
        owned_species = collection_rank.collected_species(ctx, "u2")
    text = play("card", str(owner)).text()
    assert f"成就：已领取 {claimed} 项" in text
    assert f"图鉴：{owned_species}/" in text


def test_the_lent_count_follows_the_lend_offers(game, play):
    owner = two_players(game, play)
    befriend(game)
    pet_id = sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u2'")[0]["pet_id"]
    play("borrow", f"出借 {pet_id}", user="u2")
    assert "挂出的伙伴：1 只" in play("card", str(owner)).text()


def test_unfriending_returns_the_card_to_the_public_view(game, play):
    owner = two_players(game, play)
    befriend(game)
    assert "出战阵容" in play("card", str(owner)).text()
    sql(game[1], "DELETE FROM friend_links")
    text = play("card", str(owner)).text()
    assert "陌生修士" in text and "出战阵容" not in text


def test_the_tier_and_standing_match_the_dedicated_pages(game, play):
    owner = two_players(game, play)
    ctx = context(game)
    with closing(ctx.repo.conn):
        season = current_season(ctx)
        expected = tier_of(season, rating(ctx, season, "u2")).name
        standing = collection_rank.personal_rank(ctx, "u2")
    text = play("card", str(owner)).text()
    assert f"论剑段位：{expected}" in text
    assert (f"第 {standing} 名" if standing is not None else "尚未入榜") in text


def test_the_worn_title_is_shown(game, play):
    owner = two_players(game, play)
    befriend(game)
    ctx = context(game)
    with closing(ctx.repo.conn):
        holder = titles.current(ctx, "u2")
    line = play("card", str(owner)).text()
    assert f"称号：{holder.name if holder is not None else '尚无'}" in line


def test_a_player_without_an_active_pet_says_so(game, play):
    owner = two_players(game, play)
    befriend(game)
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u2'")
    assert "出战：尚未选择伙伴" in play("card", str(owner)).text()


# ---------------------------------------------------------------- surfaces

def test_the_card_writes_nothing(game, play):
    owner = two_players(game, play)
    befriend(game)
    before = snapshot(game)
    play("card")
    play("card", str(owner))
    assert snapshot(game) == before


def test_help_and_parser_cover_the_command(game, play):
    play("adopt", "青鸾")
    assert _parse("灵宠名帖") == ("card", "")
    assert _parse("灵宠名帖 10001") == ("card", "10001")

    from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

    rows = {row[0] for row in _HELP_SECTIONS["身份与收集"]}
    assert "灵宠名帖 UID" in rows


def test_every_rendered_link_reparses(game, play):
    owner = two_players(game, play)
    for action, arg in (("card", ""), ("card", str(owner))):
        page = play(action, arg)
        for link in page.inline_commands:
            assert link.line < len(page.lines)
            assert _parse(link.command) is not None
    befriend(game)
    page = play("card", str(owner))
    for link in page.inline_commands:
        assert _parse(link.command) is not None


def test_qq_payload_keeps_buttons_and_blue_links_disjoint(game, play):
    owner = two_players(game, play)
    page = play("card", str(owner))
    _, message = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    buttons = {
        button.action.data.removeprefix("/")
        for segment in message["keyboard"]
        for row in segment.data["keyboard"].content.rows
        for button in row.buttons
    }
    assert buttons == set(page.commands)
    assert len(buttons) <= 4
    markdown = message["markdown"][0].data["markdown"]
    text = markdown.content if hasattr(markdown, "content") else markdown["content"]
    linked = {
        parse_qs(urlparse(url).query)["command"][0]
        for url in re.findall(r"\]\((mqqapi://[^)]+)\)", text)
    }
    assert linked == {f"/{link.command}" for link in page.inline_commands}
    assert not linked & buttons


def test_the_onebot_text_page_spells_the_command(game, play):
    play("adopt", "青鸾")
    rendered = _qq_segments(play("card"), Config(spirit_pet_qq_mode="text"))[0]
    assert "名帖（/灵宠名帖）" in rendered


def test_relation_is_symmetric_and_self_first(game, play):
    owner = two_players(game, play)
    assert card.relation(context(game, "u1"), "u1") == card.SELF
    assert card.relation(context(game, "u1"), "u2") == card.PUBLIC
    befriend(game)
    assert card.relation(context(game, "u1"), "u2") == card.FRIEND
    assert card.relation(context(game, "u2"), "u1") == card.FRIEND
