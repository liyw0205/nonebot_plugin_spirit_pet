"""Pet dedication: preview-first, irreversible retirement with reward and freed roster slot."""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import release
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql

NOW = 1_800_000_000


def ctx_of(game, now=NOW, user="u1"):
    return Context(Repository(game[1].connect()), game[0].content, game[0].config, game[0].rng, user, now, "read")


def add_pet(game, species_id, name, realm=0, user="u1"):
    sql(
        game[1],
        "INSERT INTO pets(user_id, species_id, name, realm, affinity, energy_updated)"
        " VALUES (?, ?, ?, ?, 0, ?)",
        (user, species_id, name, realm, NOW),
    )
    return max(row["pet_id"] for row in sql(game[1], "SELECT pet_id FROM pets WHERE user_id=?", (user,)))


def ready(game, play):
    """Adopt the starter and add a spare pet that is not in the roster."""
    play("adopt", "青鸾")
    return add_pet(game, "xuanhu", "玄狐甲")


def roster(game):
    return tuple(row["pet_id"] for row in sql(
        game[1], "SELECT pet_id FROM active_pet_slots WHERE user_id='u1' ORDER BY slot",
    ))


def marker(game, pet_id):
    rows = sql(
        game[1], "SELECT quest_id FROM quest_progress WHERE user_id='u1' AND quest_id=?",
        (f"released_{pet_id}",),
    )
    return bool(rows)


def pet_row(game, pet_id):
    return sql(game[1], "SELECT * FROM pets WHERE pet_id=?", (pet_id,))[0]


def test_rule_is_wired_and_positive(game):
    rule = game[0].content.rules.pet_release
    assert rule.stones_base + rule.stones_per_realm > 0
    assert rule.items


def test_rule_validation_rejects_an_empty_grant():
    from nonebot_plugin_spirit_pet.domain.content import PetReleaseRule

    assert PetReleaseRule.model_validate(
        {"stones_base": 10, "stones_per_realm": 5, "items": {}}
    ).stones_base == 10
    with pytest.raises(ValidationError, match="grant something"):
        PetReleaseRule.model_validate({"stones_base": 0, "stones_per_realm": 0, "items": {}})


def test_page_without_a_pet_is_read_only(game, play):
    page = play("pet_release", user="ghost")
    assert "尚未结契" in page.text()
    assert page.commands == ("灵宠帮助",)
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='ghost'") == []


def test_page_lists_candidates_with_rewards(game, play):
    spare = ready(game, play)
    page = play("pet_release")
    assert "归灵不可撤销" in page.text()
    assert "灵石" in page.text()
    assert len(page.inline_commands) == 1  # the starter is in the roster, only the spare qualifies


def test_the_roster_pet_is_blocked(game, play):
    spare = ready(game, play)
    starter = roster(game)[0]
    page = play("pet_release")
    lines = [line for line in page.text().splitlines() if f"#{starter}" in line]
    assert lines and "仍在出战阵容" in lines[0]


def test_a_bare_command_only_previews(game, play):
    spare = ready(game, play)
    stones = player(game[1])["stones"]
    reply = play("pet_release", str(spare), op="preview")
    assert reply.title == "归灵预览"
    assert "确认请发送" in reply.text()
    assert not marker(game, spare)
    assert pet_row(game, spare)["archived"] == 0
    assert player(game[1])["stones"] == stones


def test_confirming_retires_the_pet_and_pays_once(game, play):
    spare = ready(game, play)
    stones = player(game[1])["stones"]
    essence = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='bloodline_essence'")
    reply = play("pet_release", f"确认 {spare}", op="confirm")
    assert reply.title == "归灵完成"
    assert marker(game, spare)
    assert pet_row(game, spare)["archived"] == 1
    reward = release.reward_of(ctx_of(game), ctx_of(game).repo.pet(spare))
    assert player(game[1])["stones"] == stones + reward.stones.minimum
    after = sql(game[1], "SELECT quantity FROM inventory WHERE user_id='u1' AND item_id='bloodline_essence'")
    assert after[0]["quantity"] == (essence[0]["quantity"] if essence else 0) + 1


def test_the_reward_scales_with_realm(game, play):
    play("adopt", "青鸾")
    low = add_pet(game, "xuanhu", "低境界", realm=0)
    high = add_pet(game, "baize", "高境界", realm=3)
    ctx = ctx_of(game)
    low_reward = release.reward_of(ctx, ctx.repo.pet(low))
    high_reward = release.reward_of(ctx, ctx.repo.pet(high))
    assert high_reward.stones.minimum > low_reward.stones.minimum


def test_releasing_frees_a_roster_slot(game, play):
    play("adopt", "青鸾")
    first = roster(game)[0]
    spare = add_pet(game, "xuanhu", "玄狐乙")
    play("lineup", f"{first} {spare}", op="two")
    # the spare is in the roster now, so it must be benched before it can be dedicated
    with pytest.raises(GameError, match="出战阵容"):
        play("pet_release", f"确认 {spare}")
    play("lineup", str(first), op="solo")
    owned_before = len(sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' AND archived=0"))
    play("pet_release", f"确认 {spare}", op="release")
    owned_after = len(sql(game[1], "SELECT pet_id FROM pets WHERE user_id='u1' AND archived=0"))
    assert owned_after == owned_before - 1


def test_refusals_write_nothing(game, play):
    spare = ready(game, play)
    with pytest.raises(GameError, match="没有找到这只伙伴"):
        play("pet_release", "确认 9999")
    with pytest.raises(GameError, match="格式"):
        play("pet_release", "确认")
    assert not marker(game, spare)

    # expedition: the spare is the active pet while it departs, then it is benched again
    starter = roster(game)[0]
    play("lineup", str(spare), op="spare-active")
    play("expedition_start", "采灵药", op="trip", now=NOW)
    play("lineup", str(starter), op="solo-trip")
    with pytest.raises(GameError, match="派遣"):
        play("pet_release", f"确认 {spare}")
    assert not marker(game, spare)


def test_a_bonded_pet_must_be_unbound_first(game, play):
    play("adopt", "青鸾")
    first = roster(game)[0]
    spare = add_pet(game, "xuanhu", "玄狐丙")
    sql(game[1], "UPDATE pets SET affinity=100 WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET stones=5000 WHERE user_id='u1'")
    sql(game[1], "INSERT INTO inventory(user_id, item_id, quantity) VALUES ('u1', 'bloodline_essence', 2)"
                 " ON CONFLICT(user_id, item_id) DO UPDATE SET quantity=2")
    play("lineup", f"{first} {spare}", op="pair")
    names = [sql(game[1], "SELECT name FROM pets WHERE pet_id=?", (pet_id,))[0]["name"] for pet_id in (first, spare)]
    play("pair_bond", f"结契 {names[0]} {names[1]}", op="bond")
    play("lineup", str(first), op="solo-bond")
    with pytest.raises(GameError, match="同心"):
        play("pet_release", f"确认 {spare}")
    assert not marker(game, spare)


def test_an_ascended_pet_is_refused(game, play):
    spare = ready(game, play)
    sql(game[1], "INSERT INTO quest_progress(user_id, quest_id, progress, claimed)"
                 " VALUES ('u1', ?, 1, 1)", (f"ascended_{spare}",))
    with pytest.raises(GameError, match="飞升"):
        play("pet_release", f"确认 {spare}")
    assert not marker(game, spare)


def test_a_dedicated_pet_cannot_be_restored_or_seen_in_the_vault(game, play):
    spare = ready(game, play)
    play("pet_release", f"确认 {spare}", op="gone")
    vault = play("pet_archive_list", "1")
    assert f"编号 {spare}：" not in vault.text()
    with pytest.raises(GameError, match="已归灵"):
        play("pet_restore", str(spare))
    with pytest.raises(GameError, match="已归灵"):
        play("pet_release", f"确认 {spare}")


def test_the_last_pet_is_never_dedicated(game, play):
    play("adopt", "青鸾")
    only = roster(game)[0]
    sql(game[1], "DELETE FROM active_pet_slots WHERE user_id='u1'")
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id='u1'")
    with pytest.raises(GameError, match="至少需要保留一只"):
        play("pet_release", f"确认 {only}")
    assert not marker(game, only)


def test_battle_history_and_pet_row_are_kept(game, play):
    spare = ready(game, play)
    records_before = sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"]
    play("pet_release", f"确认 {spare}", op="history")
    assert pet_row(game, spare)["pet_id"] == spare
    assert sql(game[1], "SELECT COUNT(*) AS n FROM battle_records")[0]["n"] == records_before


def test_objective_help_and_parse(game, play):
    spare = ready(game, play)
    assert "归灵：" in play("objectives").text()
    play("pet_release", f"确认 {spare}", op="obj")
    assert "归灵：已归灵 1 只" in play("objectives").text()
    assert "灵宠归灵" in play("help", "结契").text()
    assert handlers._parse("灵宠归灵") == ("pet_release", "")
    assert handlers._parse("灵宠归灵 确认 2") == ("pet_release", "确认 2")


def test_same_operation_replays_identically(game, play):
    spare = ready(game, play)
    first = play("pet_release", f"确认 {spare}", op="replay")
    stones = player(game[1])["stones"]
    again = play("pet_release", f"确认 {spare}", op="replay")
    assert again.text() == first.text()
    assert player(game[1])["stones"] == stones


def test_native_payload_keeps_buttons_and_links_disjoint(game, play):
    spare = ready(game, play)
    page = play("pet_release")
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
