from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from nonebot_plugin_spirit_pet.domain.models import GameError

from .support import items, pet, player, sql


NOW = 1_800_000_000
USERS = tuple(f"private-platform-account-{index}" for index in range(6))
NAMES = ("青云", "赤霄", "月华", "玄霜", "流火", "澄澜")


def create_players(play, count=4):
    for index in range(count):
        play("adopt", "青鸾", user=USERS[index])
        play("dao_name", NAMES[index], user=USERS[index])


def create_team(play, leader=0, members=()):
    play("team_create", user=USERS[leader])
    for member in members:
        play("team_join", NAMES[leader], user=USERS[member])
        play("team_accept", NAMES[member], user=USERS[leader])


def memberships(store):
    return sql(store, "SELECT * FROM team_members ORDER BY user_id")


def requests(store):
    return sql(store, "SELECT * FROM team_requests ORDER BY team_id, candidate_id")


def resources(store, users):
    return [(player(store, user), pet(store, user), items(store, user)) for user in users]


def race(game, commands):
    barrier = Barrier(len(commands))

    def execute(command):
        barrier.wait(timeout=10)
        try:
            return game.execute(*command)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        return list(pool.map(execute, commands))


def command(user, action, arg, event, now=NOW):
    return USERS[user], action, arg, event, now


def public_text(reply):
    return "\n".join((reply.text(), *reply.commands))
