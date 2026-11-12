from concurrent.futures import ThreadPoolExecutor
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_spirit_pet.application.game import Game
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.storage.repository import Repository
from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments
from nonebot_plugin_spirit_pet.core.config import Config
from .support import items, player, sql
from .test_commands import onebot_event

NOW = 1_800_000_000


def ready(play):
    play('adopt', '青鸾')
    for offset in (3, 2, 1, 0):
        play('sign', now=NOW - offset * 86400)
    play('buy', '灵稻种 2')
    play('buy', '灵粮 3')
    play('farm_open', '1')
    play('farm_plant', '1 灵稻种')


def action(play, choice, now=NOW):
    reply = play('farm_care', '1', now=now)
    return next(link.command.split(' ', 1)[1] for link in reply.inline_commands if link.label == choice)


def test_public_preview_does_not_register(game, play):
    assert '每季' in play('farm_care').text()
    assert not sql(game[1], 'SELECT * FROM players')


@pytest.mark.parametrize('choices,food,cut,bonus', [
    (['松土'] * 3, 0, 270, 0),
    (['培肥'] * 3, 3, 0, 60),
    (['松土', '培肥', '培肥'], 2, 90, 40),
])
def test_full_public_cycle_and_real_food_consumer(game, play, choices, food, cut, bonus):
    ready(play)
    before = items(game[1]).get('spirit_food', 0)
    stones = player(game[1])['stones']
    for index, choice in enumerate(choices):
        now = NOW + index * 600
        play('farm_care', action(play, choice, now), now=now, op=f'care-{index}')
    assert items(game[1]).get('spirit_food', 0) == before - food
    assert player(game[1])['stones'] == stones - 10 * choices.count('松土')
    with pytest.raises(GameError, match='还在生长'):
        play('farm_harvest', '1', now=NOW + 1799 - cut)
    result = play('farm_harvest', '1', now=NOW + 1800 - cut)
    gained = int(3 * (1 + bonus / 100))
    assert f'灵粮 +{gained}' in result.text()
    assert items(game[1]).get('spirit_food', 0) == before - food + gained
    play('feed', now=NOW + 1800 - cut)
    assert items(game[1]).get('spirit_food', 0) == before - food + gained - 1


def test_replant_and_old_step_guard(game, play):
    ready(play)
    old = action(play, '培肥')
    play('farm_care', old)
    with pytest.raises(GameError, match='旧季'):
        play('farm_care', old)
    play('farm_harvest', '1 灵稻种', now=NOW + 1800)
    with pytest.raises(GameError, match='旧季'):
        play('farm_care', old, now=NOW + 1800)
    assert '增产0%' in play('farm_care', '1', now=NOW + 1800).text()


def test_permanent_receipt_restart_and_concurrency(game, play):
    ready(play)
    command = action(play, '培肥')
    before = items(game[1])['spirit_food']
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: play('farm_care', command, op='same-care'), range(2)))
    assert replies[0] == replies[1]
    assert items(game[1])['spirit_food'] == before - 1
    sql(game[1], 'DELETE FROM operations')
    restart = Game(game[1], game[0].config, game[0].rng)
    assert restart.execute('u1', 'farm_care', command, 'same-care', NOW + 86400) == replies[0]
    with pytest.raises(GameError, match='different user'):
        restart.execute('u2', 'farm_care', command, 'same-care', NOW + 86400)


def test_transaction_rollback(game, play, monkeypatch):
    ready(play)
    command = action(play, '培肥')
    before = items(game[1])
    def fail(*args, **kwargs):
        raise RuntimeError('injected receipt failure')
    monkeypatch.setattr(Repository, 'record_duel_action', fail)
    with pytest.raises(RuntimeError, match='injected'):
        play('farm_care', command)
    assert items(game[1]) == before
    assert '养护 0/3' in play('farm_care', '1').text()


@pytest.mark.parametrize('time', [NOW - 1, NOW + 1800, NOW + 1800 + 48 * 3600])
def test_time_and_maturity_refuse_without_cost(game, play, time):
    ready(play)
    command = action(play, '培肥')
    before = items(game[1])
    with pytest.raises(GameError):
        play('farm_care', command, now=time)
    assert items(game[1]) == before


def test_stage_wait_and_clock_rollback(game, play):
    ready(play)
    play('farm_care', action(play, '松土'))
    assert '尚需600秒' in play('farm_care', '1').text()
    with pytest.raises(GameError, match='尚需'):
        play('farm_care', f'1 培肥 季 {NOW} 步 2')
    play('farm_care', f'1 培肥 季 {NOW} 步 2', now=NOW + 600)
    with pytest.raises(GameError, match='上次养护'):
        play('farm_care', f'1 培肥 季 {NOW} 步 3', now=NOW + 599)


def test_wilt_returns_seed_without_bonus(game, play):
    ready(play)
    play('farm_care', action(play, '培肥'))
    food = items(game[1])['spirit_food']
    play('farm_harvest', '1', now=NOW + 1800 + 48 * 3600)
    assert items(game[1])['spirit_food'] == food
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE quest_id LIKE 'farm_care_%'")


@pytest.mark.parametrize('choice', ['松土', '培肥'])
def test_resource_shortage_rolls_back(game, play, choice):
    ready(play)
    command = action(play, choice)
    sql(game[1], "UPDATE players SET stones=0")
    sql(game[1], "DELETE FROM inventory WHERE item_id='spirit_food'")
    with pytest.raises(GameError):
        play('farm_care', command)
    assert '养护 0/3' in play('farm_care', '1').text()


def test_qq_and_parser_contract(game, play):
    ready(play)
    reply = play('farm_care', '1')
    assert handlers._parse('灵宠养苗 1') == ('farm_care', '1')
    for link in reply.inline_commands:
        assert 0 <= link.line < len(reply.lines)
        assert handlers._parse(link.command)[0] in ('farm_care', 'farm')
    assert not set(reply.commands) & {link.command for link in reply.inline_commands}
    for mode in ('native', 'text', 'template'):
        extra = {'spirit_pet_qq_template_id': 'fixture', 'spirit_pet_qq_template_param': 'content'} if mode == 'template' else {}
        body, payload = _qq_segments(reply, Config(spirit_pet_qq_mode=mode, spirit_pet_command_prefix='!', **extra))
        assert body or payload


def test_harvest_failure_restores_care(game, play, monkeypatch):
    ready(play)
    play('farm_care', action(play, '培肥'))
    before = items(game[1])
    def fail(*args, **kwargs):
        raise RuntimeError('injected yield failure')
    monkeypatch.setattr(Repository, 'add_item', fail)
    with pytest.raises(RuntimeError, match='injected'):
        play('farm_harvest', '1', now=NOW + 1800)
    assert items(game[1]) == before
    assert '增产20%' in play('farm_care', '1').text()


def test_old_save_plant_and_objectives_use_actual_maturity(game, play):
    ready(play)
    sql(game[1], "DELETE FROM quest_progress WHERE quest_id='farm_cycle_1'")
    play('farm_care', action(play, '松土'))
    assert '1 块可收获' in play('objectives', now=NOW + 1710).text()


def test_different_operations_same_step_concurrent(game, play):
    ready(play)
    command = action(play, '培肥')
    before = items(game[1])['spirit_food']
    def execute(index):
        try:
            return play('farm_care', command, op=f'concurrent-{index}')
        except GameError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sum(reply is not None for reply in results) == 1
    assert items(game[1])['spirit_food'] == before - 1


def test_onebot_public_entry_to_care_and_harvest(game, monkeypatch):
    monkeypatch.setattr(handlers, 'game', game[0])
    monkeypatch.setattr(handlers, 'config', Config(spirit_pet_command_prefix='!'))
    bot = SimpleNamespace(self_id='9000', adapter=SimpleNamespace(get_name=lambda: 'OneBot V11'), send=AsyncMock())
    commands = ['灵宠领养 青鸾', '灵宠签到', '灵宠开垦 1', '灵宠购买 灵稻种 1',
                '灵宠播种 1 灵稻种', '灵宠养苗 1']
    for index, command in enumerate(commands, 100):
        event = onebot_event('!' + command, index)
        asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert sql(game[1], "SELECT * FROM quest_progress WHERE user_id='12345' AND quest_id='farm_cycle_1'")
    assert bot.send.await_count == len(commands)
    cycle = sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='12345' AND quest_id='farm_cycle_1'")[0]['progress']
    event = onebot_event(f'!灵宠养苗 1 松土 季 {cycle} 步 1', 200)
    asyncio.run(handlers.handle_command(bot, event, event.get_message()))
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE user_id='12345' AND quest_id='farm_care_step_1'")[0]['progress'] == 1
    game[0].execute('12345', 'farm_harvest', '1', 'onebot-mature', cycle + 1710)
    assert not sql(game[1], "SELECT * FROM quest_progress WHERE user_id='12345' AND quest_id LIKE 'farm_crop_1_%'")


def test_harvest_replay_after_replant_cannot_take_next_crop(game, play):
    ready(play)
    play('farm_care', action(play, '培肥'))
    first = play('farm_harvest', '1 灵稻种', now=NOW + 1800, op='care-harvest')
    sql(game[1], 'DELETE FROM operations')
    assert play('farm_harvest', '1 灵稻种', now=NOW + 3600, op='care-harvest') == first
    assert sql(game[1], "SELECT progress FROM quest_progress WHERE quest_id='farm_crop_1_spirit_rice'")[0]['progress'] == NOW + 1800


def test_rotation_and_care_add_before_flooring(game, play):
    ready(play)
    sql(game[1], "INSERT INTO quest_progress VALUES ('u1','farm_rotation_1',1,0)")
    for index in range(3):
        now = NOW + index * 600
        play('farm_care', action(play, '培肥', now), now=now)
    result = play('farm_harvest', '1', now=NOW + 1800)
    assert '灵粮 +5' in result.text()
    assert '轮作加成' in result.text() and '养苗增产 +60%' in result.text()
