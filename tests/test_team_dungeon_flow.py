import re
from urllib.parse import parse_qs, urlparse

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import player, sql
from .team_support import USERS, UIDS, create_players, create_team
from .test_targeted_care import snapshot


def ready_team(play):
    create_players(play, count=2)
    create_team(play, members=(1,))
    for user in USERS[:2]:
        play("team_ready", user=user)


def state(store):
    return snapshot(store) | {table: sql(store, f"SELECT * FROM {table} ORDER BY rowid") for table in (
        "teams", "team_requests", "battle_records", "battle_participants", "operations",
    )}


def test_team_roster_opens_dungeon_choices_and_handles_missing_member_pet(game, play):
    ready_team(play)
    roster = play("team_status", user=USERS[0])
    assert "灵宠队伍 秘境" in roster.commands
    catalog = play("team_status", "秘境", user=USERS[0])
    assert any(link.command == "灵宠组队挑战 上古灵殿" for link in catalog.inline_commands)
    assert not any(link.command == "灵宠组队挑战 幽冥深渊" for link in catalog.inline_commands)
    assert "境界不足" in catalog.text()
    sql(game[1], "DELETE FROM active_pet_slots WHERE user_id=?", (USERS[1],))
    sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id=?", (USERS[1],))
    missing = play("team_status", user=USERS[0])
    assert "UID 10001" in missing.text() and "尚未出战" in missing.text()
    detail = play("team_status", UIDS[1], user=USERS[0])
    assert "尚未出战" in detail.text()
    catalog = play("team_status", "秘境", user=USERS[0])
    assert not any(link.command.startswith("灵宠组队挑战") for link in catalog.inline_commands)
    own = play("team_status", user=USERS[1])
    assert any(link.command == "灵宠列表" for link in own.inline_commands)


def test_team_catalog_challenge_settles_members_and_returns_to_team(game, play):
    ready_team(play)
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    catalog = play("team_status", "秘境", user=USERS[0])
    command = next(link.command for link in catalog.inline_commands if link.command == "灵宠组队挑战 上古灵殿")
    stones = {user: player(game[1], user)["stones"] for user in USERS[:2]}
    reply = play(*handlers._parse(command), user=USERS[0], op="team-dungeon-once")
    assert reply.title == "秘境获胜"
    assert reply.commands == ("灵宠战报", "灵宠队伍", "灵宠任务", "灵宠队伍 秘境")
    assert play(*handlers._parse(command), user=USERS[0], op="team-dungeon-once") == reply
    for user in USERS[:2]:
        reward = game[0].content.dungeons["temple"].reward
        assert player(game[1], user)["stones"] == stones[user] + reward.stones.minimum
        assert player(game[1], user)["last_pve"] == 1_800_000_000
        assert sql(game[1], "SELECT exp FROM pets WHERE user_id=?", (user,)) == [{"exp": reward.exp.minimum}]
    assert sql(game[1], "SELECT energy FROM pets ORDER BY pet_id") == [{"energy": 70}, {"energy": 70}]
    assert sql(game[1], "SELECT ready_pet_id FROM team_members") == [{"ready_pet_id": None}, {"ready_pet_id": None}]
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='pve_once'") == [
        {"progress": 1}, {"progress": 1},
    ]
    with pytest.raises(GameError, match="全体成员准备"):
        play(*handlers._parse(command), user=USERS[0])


@pytest.mark.parametrize("argument", ["秘境 0", "秘境 -1", "秘境 many", "秘境 999", "秘境 1 2"])
def test_team_catalog_rejects_bad_pages_without_changes(game, play, argument):
    ready_team(play)
    before = state(game[1])
    with pytest.raises(GameError):
        play("team_status", argument, user=USERS[0])
    assert state(game[1]) == before


def test_team_catalog_registration_membership_and_detail_recovery(game, play):
    with pytest.raises(GameError) as error:
        play("team_status", "秘境")
    assert error.value.reply.inline_commands[0].command == "灵宠领养 "
    assert not sql(game[1], "SELECT * FROM players")
    play("adopt")
    detail = play("dungeons", "上古灵殿")
    command = detail.inline_commands[0].command
    assert command == "灵宠组队"
    with pytest.raises(GameError, match="尚未加入队伍"):
        play("team_status", "秘境")
    play(*handlers._parse(command))
    page = play("team_status", "秘境")
    assert "至少需要两名玩家" in page.text()
    assert not any(link.command.startswith("灵宠组队挑战") for link in page.inline_commands)


@pytest.mark.parametrize("blocked,reason", [
    ("unready", "尚未准备"), ("inactive", "尚未出战"), ("archived", "已封存"),
    ("trip", "派遣"), ("energy", "精力不足"), ("cooldown", "调息"),
])
def test_team_catalog_rechecks_stale_rosters_and_battle_has_no_partial_cost(game, play, blocked, reason):
    ready_team(play)
    command = next(link.command for link in play("team_status", "秘境", user=USERS[0]).inline_commands
                   if link.command == "灵宠组队挑战 上古灵殿")
    if blocked == "unready":
        play("team_unready", user=USERS[1])
    elif blocked == "inactive":
        sql(game[1], "DELETE FROM active_pet_slots WHERE user_id=?", (USERS[1],))
        sql(game[1], "UPDATE players SET active_pet_id=NULL WHERE user_id=?", (USERS[1],))
    elif blocked == "archived":
        sql(game[1], "UPDATE pets SET archived=1 WHERE user_id=?", (USERS[1],))
    elif blocked == "trip":
        play("expedition_start", "采灵药", user=USERS[1])
    elif blocked == "energy":
        sql(game[1], "UPDATE pets SET energy=0 WHERE user_id=?", (USERS[1],))
    else:
        sql(game[1], "UPDATE players SET last_pve=1800000000 WHERE user_id=?", (USERS[1],))
    before = state(game[1])
    page = play("team_status", "秘境", user=USERS[0])
    assert reason in page.text()
    assert command not in [link.command for link in page.inline_commands]
    # Looking at choices does not regenerate or spend energy, mutate readiness, or reserve a fight.
    assert snapshot(game[1]) == {key: before[key] for key in snapshot(game[1])}
    before = state(game[1])
    with pytest.raises(GameError):
        play(*handlers._parse(command), user=USERS[0])
    assert state(game[1]) == before


def test_member_can_preview_but_cannot_start_team_dungeon(game, play):
    ready_team(play)
    page = play("team_status", "秘境", user=USERS[1])
    assert "请由队长发起" in page.text()
    assert all(not link.command.startswith("灵宠组队挑战") for link in page.inline_commands)
    before = state(game[1])
    with pytest.raises(GameError, match="仅队长"):
        play("team_challenge", "上古灵殿", user=USERS[1])
    with pytest.raises(GameError, match="单人秘境"):
        play("team_challenge", "青岚林", user=USERS[0])
    with pytest.raises(GameError):
        play("team_challenge", "不存在", user=USERS[0])
    assert state(game[1]) == before


def test_team_battle_record_failure_rolls_back_every_member_and_can_retry(game, play, monkeypatch):
    ready_team(play)
    sql(game[1], "UPDATE pets SET realm=6,layer=10")
    before = state(game[1])
    original = Repository.record_battle

    def fail(repo, **kwargs):
        original(repo, **kwargs)
        raise RuntimeError("injected team battle record failure")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "record_battle", fail)
        with pytest.raises(RuntimeError, match="injected team battle"):
            play("team_challenge", "上古灵殿", user=USERS[0], op="team-retry")
    assert state(game[1]) == before
    reply = play("team_challenge", "上古灵殿", user=USERS[0], op="team-retry")
    assert reply.title == "秘境获胜"
    sql(game[1], "DELETE FROM operations")
    settled = state(game[1])
    assert play("team_challenge", "上古灵殿", user=USERS[0], op="team-retry") == reply
    replayed = state(game[1])
    # Permanent battle receipts repopulate the expired transport cache without settling again.
    assert len(replayed["operations"]) == 1
    assert replayed["operations"][0]["operation_id"] == "team-retry"
    assert replayed["operations"][0]["user_id"] == USERS[0]
    replayed.pop("operations")
    settled.pop("operations")
    assert replayed == settled
    assert len(sql(game[1], "SELECT * FROM battle_records")) == 1


@pytest.mark.parametrize("prefix", ["", "/", "!"])
def test_team_catalog_qq_rows_keep_details_challenges_and_paging_distinct(game, play, prefix):
    ready_team(play)
    reply = play("team_status", "秘境", user=USERS[0])
    plain, native = _qq_segments(reply, Config(spirit_pet_qq_mode="native", spirit_pet_command_prefix=prefix))
    markdown = native["markdown"][0].data["markdown"].content
    links = [parse_qs(urlparse(url).query)["command"][0]
             for url in re.findall(r"\]\((mqqapi://[^)]+)\)", markdown)]
    payloads = [button.action.data for segment in native["keyboard"]
                for row in segment.data["keyboard"].content.rows for button in row.buttons]
    assert len(payloads) <= 4
    assert set(links) == {prefix + link.command for link in reply.inline_commands}
    assert set(payloads) == {prefix + command for command in reply.commands}
    assert len(links + payloads) == len(set(links + payloads))
    assert "mqqapi://" not in plain
    assert "private-platform-account" not in plain
    assert f"发起挑战（{prefix}灵宠组队挑战 上古灵殿）" in plain
    assert all(handlers._parse(link.command) is not None for link in reply.inline_commands)
