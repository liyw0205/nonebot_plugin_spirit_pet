import asyncio
import json

from nonebot import get_driver, get_plugin_config, on_message
from nonebot.adapters import Bot, Event
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import Rule

from ..core.config import Config
from .messaging import send_reply
from ..domain.models import GameError
from ..application.commands import COMMANDS
from ..application.game import Game
from ..storage.database import Store

config = get_plugin_config(Config)
store = Store(config.spirit_pet_db.expanduser())
game = Game(store, config)
driver = get_driver()
driver.on_startup(store.initialize)
_KNOWN_COMMANDS = sorted(COMMANDS, key=len, reverse=True)


def _parse(text: str) -> tuple[str, str] | None:
    value = text.strip()
    prefix = config.spirit_pet_command_prefix
    if prefix and value.startswith(prefix):
        value = value[len(prefix) :].lstrip()
    for name in _KNOWN_COMMANDS:
        if value == name:
            return COMMANDS[name], ""
        if value.startswith(name) and len(value) > len(name) and value[len(name)].isspace():
            return COMMANDS[name], value[len(name) :].strip()
    return None


def _plain_text(event: Event, message=None) -> str:
    source = message if message is not None else event.get_message()
    extract = getattr(source, "extract_plain_text", None)
    return extract() if callable(extract) else str(source)


async def _is_command(event: Event, message=EventMessage()) -> bool:
    try:
        return _parse(_plain_text(event, message)) is not None
    except (AttributeError, TypeError, ValueError):
        return False


command_matcher = on_message(rule=Rule(_is_command), priority=12, block=True)


def _operation_id(bot: Bot, event: Event) -> str:
    message_id = getattr(event, "message_id", None)
    if message_id is None:
        message_id = getattr(event, "id", None)
    if message_id is None or str(message_id) == "":
        raise ValueError("message ID is required for safe game mutations")
    return json.dumps(
        [bot.adapter.get_name(), bot.self_id, event.get_session_id(), str(message_id)],
        ensure_ascii=False,
    )


async def _run(bot: Bot, event: Event, text: str) -> None:
    parsed = _parse(text)
    if parsed is None:
        return
    action, argument = parsed
    try:
        reply = await asyncio.to_thread(
            game.execute,
            str(event.get_user_id()),
            action,
            argument,
            _operation_id(bot, event),
        )
    except GameError as exc:
        await bot.send(event, str(exc))
        return
    except Exception as exc:
        logger.exception(f"Spirit Pet command failed ({type(exc).__name__})")
        await bot.send(event, "仙途暂遇灵息紊乱，请稍后再试。")
        return
    try:
        await send_reply(bot, event, reply, config)
    except Exception as exc:
        logger.exception(f"Spirit Pet message send failed ({type(exc).__name__})")


@command_matcher.handle()
async def handle_command(bot: Bot, event: Event, message=EventMessage()) -> None:
    await _run(bot, event, _plain_text(event, message))
