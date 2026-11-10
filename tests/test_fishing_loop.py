"""Player-facing fishing loop, QQ payloads and adjacent transaction boundaries."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import items, pet, sql
from .test_fishing_choices import DAY, NOW, Roll, account, snapshot


def test_bait_seed_farm_food_and_next_cast_form_a_playable_loop(game, play):
    account(game, play)
    food = items(game[1])["spirit_food"]
    original_rng = game[0].rng
    # First boundary after the unchanged common drops now reaches the seed pool.
    game[0].rng = Roll(81)
    detail = play("fishing", "详情 溪口 谷香饵", now=NOW)
    command = next(link.command for link in detail.inline_commands if link.label == "抛竿")
    action, argument = handlers._parse(command)
    play(action, argument, now=NOW, op="loop-seed")
    assert items(game[1])["spirit_food"] == food - 1
    assert items(game[1])["seed_spirit_rice"] == 1
    sql(game[1], "UPDATE players SET stones=1000")
    play("farm_open", "1", now=NOW)
    play("farm_plant", "1 灵稻种", now=NOW)
    # Restore the fixture's minimum random source for the harvest and second cast.
    game[0].rng = original_rng
    harvest = play("farm_harvest", "1", now=NOW + 1800)
    assert "灵粮 +3" in harvest.text()
    assert items(game[1])["spirit_food"] == food + 2
    play("fishing", "溪口 谷香饵", now=NOW + 1800, op="loop-again")
    assert "鱼获 2/4" in play("fishing", "详情 溪口", now=NOW + 1800).text()
    assert "鱼篓共 2 竿" in play("fishing", "鱼篓", now=NOW + 1800).text()


def test_readiness_only_changes_after_success_and_ledger_failure_restores_it(game, play, monkeypatch):
    account(game, play)
    play("team_create", now=NOW)
    play("team_ready", now=NOW)
    ready = sql(game[1], "SELECT * FROM team_members")
    play("fishing", "详情 溪口 谷香饵", now=NOW)
    assert sql(game[1], "SELECT * FROM team_members") == ready
    record = Repository.record_fishing_cast

    def fail_after_insert(self, *args):
        record(self, *args)
        raise RuntimeError("after ledger insert")

    before = snapshot(game[1])
    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_fishing_cast", fail_after_insert)
        with pytest.raises(RuntimeError, match="after ledger"):
            play("fishing", "溪口 谷香饵", now=NOW)
    assert snapshot(game[1]) == before
    play("fishing", "溪口 谷香饵", now=NOW)
    assert sql(game[1], "SELECT ready_pet_id FROM team_members")[0]["ready_pet_id"] is None


def test_cap_serializes_different_messages_and_resets_on_beijing_midnight(game, play):
    account(game, play)
    for index in range(2):
        play("fishing", "溪口", op=f"prior-{index}", now=NOW)

    def cast(index):
        try:
            return game[0].execute("u1", "fishing", "溪口 谷香饵", f"last-{index}", NOW).title
        except GameError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(cast, range(2)))
    assert outcomes.count("灵宠垂钓") == 1
    assert sum("次数已用完" in result for result in outcomes) == 1
    assert len(sql(game[1], "SELECT * FROM fishing_casts")) == 3
    play("fishing", "溪口", now=NOW + DAY)
    assert len(sql(game[1], "SELECT * FROM fishing_casts")) == 4


def test_expired_receipt_is_global_across_commands_and_retains_inline_data(game, play):
    account(game, play)
    first = play("fishing", "溪口", op="global-receipt", now=NOW)
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1], cache=False)
    assert play("train", now=NOW + 8 * DAY, op="global-receipt") == first
    assert snapshot(game[1], cache=False) == before
    sql(game[1], "DELETE FROM operations")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="different user"):
        play("adopt", "玄狐", user="other", now=NOW + 8 * DAY, op="global-receipt")
    assert snapshot(game[1]) == before


@pytest.mark.parametrize("spot,bait,roll,item", [
    ("深潭", "谷香饵", 70, "seed_blood_herb"),
    ("深潭", "晶砂饵", 180, "bloodline_essence"),
    ("灵渊", "谷香饵", 125, "seed_blood_herb"),
    ("灵渊", "晶砂饵", 120, "bloodline_essence"),
    ("灵渊", "灵光饵", 180, "energy_pill"),
])
def test_higher_water_bait_tables_use_actual_content(game, play, spot, bait, roll, item):
    account(game, play)
    sql(game[1], "UPDATE pets SET realm=4")
    game[0].rng = Roll(roll)
    play("fishing", f"{spot} {bait}", now=NOW)
    saved = json.loads(sql(game[1], "SELECT snapshot FROM fishing_casts")[0]["snapshot"])
    assert saved["item_id"] == item
    assert pet(game[1])["energy"] == 100 - (14 if spot == "深潭" else 20)


def test_finished_expedition_and_two_food_bait_shortage_are_zero_write(game, play):
    account(game, play)
    sql(game[1], "UPDATE inventory SET quantity=1 WHERE item_id='spirit_food'")
    before = snapshot(game[1])
    with pytest.raises(GameError, match="每竿需 2"):
        play("fishing", "溪口 灵光饵", now=NOW)
    assert snapshot(game[1]) == before
    play("expedition_start", "采灵药", now=NOW)
    finished = sql(game[1], "SELECT finishes_at FROM expeditions")[0]["finishes_at"]
    preview = play("fishing", "详情 溪口", now=finished)
    assert "派遣奖励待领取" in preview.text()
    before = snapshot(game[1])
    with pytest.raises(GameError, match="奖励待领取"):
        play("fishing", "溪口", now=finished)
    assert snapshot(game[1]) == before


def test_native_links_and_fallback_have_complete_distinct_commands(game, play):
    account(game, play)
    page = play("fishing", "详情 溪口 谷香饵", now=NOW)
    for link in page.inline_commands:
        assert handlers._parse(link.command) is not None
        assert 0 <= link.line < len(page.lines)
    _, native = _qq_segments(page, Config(spirit_pet_qq_mode="native"))
    markdown = "\n".join(segment.data["markdown"].content for segment in native["markdown"])
    commands = [parse_qs(urlparse(url).query)["command"][0]
                for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    assert len(commands) == len(page.inline_commands)
    assert all(command.lstrip("/") in {link.command for link in page.inline_commands} for command in commands)
    buttons = [button.action.data.lstrip("/") for segment in native["keyboard"]
               for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert len(buttons) <= 4 and not set(buttons) & {link.command for link in page.inline_commands}
    _, plain = _qq_segments(page, Config(spirit_pet_qq_mode="text"))
    assert "mqqapi://" not in str(plain)
    assert "灵宠垂钓 溪口 谷香饵" in str(plain)
    help_text = play("help", "血脉与道具").text()
    assert "谷香饵" in help_text and "灵宠垂钓 鱼篓 页码" in help_text
    assert "水域详情可择饵" in play("objectives").text()


def test_old_collections_continue_without_repaying_or_inventing_history(game, play, tmp_path):
    account(game, play)
    for item in ("spirit_food", "forge_ore", "seed_spirit_rice", "exp_pill"):
        sql(game[1], "INSERT INTO quest_progress VALUES ('u1',?,1,1)", (f"fish_creek_{item}",))
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','fishing_set_creek',1,1)")
    # Make a genuine isolated schema-26 copy and take it through startup migration.
    legacy = game[1].__class__(tmp_path / "legacy-fishing.db")
    with closing(game[1].connect()) as source, closing(legacy.connect()) as target:
        source.backup(target)
        target.execute("DROP TABLE fishing_casts")
        target.execute("PRAGMA user_version=26")
    before = snapshot(legacy, cache=False)
    legacy.initialize()
    service = Game(legacy, game[0].config, game[0].rng, game[0].content)
    assert "鱼篓共 0 竿" in service.execute("u1", "fishing", "鱼篓", "legacy-page", NOW).text()
    assert "鱼获 4/4" in service.execute("u1", "fishing", "详情 溪口", "legacy-detail", NOW).text()
    reply = service.execute("u1", "fishing", "溪口 谷香饵", "legacy-cast", NOW)
    assert "集齐：" not in reply.text()
    assert len(sql(legacy, "SELECT * FROM fishing_casts")) == 1
    assert before["player_identity"] == snapshot(legacy, cache=False)["player_identity"]
