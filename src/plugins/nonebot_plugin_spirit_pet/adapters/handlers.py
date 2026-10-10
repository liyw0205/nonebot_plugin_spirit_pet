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
_QQ_LIFECYCLE_EVENTS = frozenset({
    "C2C_MSG_RECEIVE", "C2C_MSG_REJECT", "GROUP_MSG_RECEIVE", "GROUP_MSG_REJECT",
    "FRIEND_ADD", "FRIEND_DEL", "GROUP_ADD_ROBOT", "GROUP_DEL_ROBOT",
})
_QQ_MESSAGE_EVENTS = frozenset({
    "AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE",
    "GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE", "MESSAGE_CREATE",
})


def _event_value(source, *names):
    for name in names:
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value not in (None, ""):
            return value
    return None


def _event_type(event: Event) -> str:
    value = _event_value(event, "event_type", "__type__")
    if value is not None:
        return str(getattr(value, "value", value)).upper()
    try:
        return str(event.get_event_name()).upper()
    except (AttributeError, TypeError, ValueError):
        return event.__class__.__name__.upper()


def _event_user_id(event: Event) -> str:
    try:
        return str(event.get_user_id())
    except (AttributeError, TypeError, ValueError):
        author = _event_value(event, "author", "sender")
        value = _event_value(
            event, "member_openid", "group_member_openid", "user_openid", "openid", "user_id",
        ) or _event_value(author, "member_openid", "user_openid", "openid", "user_id", "id")
        if value in (None, ""):
            raise ValueError("user ID is required for safe game mutations")
        return str(value)


def _event_session_id(event: Event, user_id: str) -> str:
    try:
        return str(event.get_session_id())
    except (AttributeError, TypeError, ValueError):
        group = _event_value(event, "group_openid", "group_id")
        if group not in (None, ""):
            return f"group_{group}_{user_id}"
        return f"friend_{user_id}"


def _event_message_id(event: Event) -> str:
    value = _event_value(event, "message_id", "id", "event_id")
    if value in (None, ""):
        value = _event_value(_event_value(event, "data"), "message_id", "id", "event_id")
    if value in (None, ""):
        raise ValueError("message ID is required for safe game mutations")
    return str(value)


def _is_message_event(event: Event) -> bool:
    event_type = _event_type(event)
    if event_type in _QQ_LIFECYCLE_EVENTS:
        return False
    if event_type in _QQ_MESSAGE_EVENTS:
        return True
    module_name = event.__class__.__module__.lower()
    if "nonebot.adapters.qq" in module_name or event_type.startswith(("C2C_", "GROUP_", "FRIEND_")):
        return False
    try:
        event.get_message()
        return True
    except (AttributeError, TypeError, ValueError):
        return _event_value(event, "content", "raw_content", "raw_message", "message") not in (None, "")


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
    if message is not None:
        source = message
    else:
        try:
            source = event.get_message()
        except (AttributeError, TypeError, ValueError):
            source = event
    extract = getattr(source, "extract_plain_text", None)
    if callable(extract):
        return extract()
    if source is not event and source is not None:
        return str(source)
    value = _event_value(event, "content", "raw_content", "raw_message", "message")
    if isinstance(value, (list, tuple)):
        return "".join(str(item) for item in value)
    return str(value if value is not None else source)


async def _is_command(event: Event, message=EventMessage()) -> bool:
    try:
        return _is_message_event(event) and _parse(_plain_text(event, message)) is not None
    except (AttributeError, TypeError, ValueError):
        return False


command_matcher = on_message(rule=Rule(_is_command), priority=12, block=True)


def _operation_id(bot: Bot, event: Event) -> str:
    user_id = _event_user_id(event)
    return json.dumps(
        [bot.adapter.get_name(), bot.self_id, _event_session_id(event, user_id), _event_message_id(event)],
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
            _event_user_id(event),
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
