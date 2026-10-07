import re
from typing import Any
from urllib.parse import quote

from nonebot.adapters import Bot, Event
from nonebot.log import logger

from ..core.config import Config
from ..domain.models import Reply


def inline_command(label: str, command: str, prefix: str = "/") -> str:
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9 /+\-]+", label):
        raise ValueError("invalid button label")
    if any(char in command for char in "\r\n\\[]()"):
        raise ValueError("invalid button command")
    encoded = quote(f"{prefix}{command}", safe="")
    return f"[{label}](mqqapi://aio/inlinecmd?command={encoded}&enter=false&reply=false)"


def qq_keyboard(commands: tuple[str, ...], prefix: str = "/") -> Any:
    from nonebot.adapters.qq.message import MessageSegment
    from nonebot.adapters.qq.models import Action, Button, InlineKeyboard, InlineKeyboardRow, MessageKeyboard, Permission, RenderData

    rows = []
    for offset in range(0, min(len(commands), 8), 2):
        buttons = []
        for index, command in enumerate(commands[offset : offset + 2], offset):
            buttons.append(
                Button(
                    id=f"spirit-pet-{index}",
                    render_data=RenderData(label=command, visited_label=command, style=1),
                    action=Action(
                        type=2,
                        permission=Permission(type=2),
                        data=f"{prefix}{command}",
                        reply=True,
                        enter=True,
                        unsupport_tips="请直接发送指令",
                    ),
                )
            )
        rows.append(InlineKeyboardRow(buttons=buttons))
    return MessageSegment.keyboard(MessageKeyboard(content=InlineKeyboard(rows=rows)))


async def send_reply(bot: Bot, event: Event, reply: Reply, config: Config) -> None:
    adapter = getattr(bot, "adapter", None)
    adapter_name = getattr(adapter, "get_name", lambda: "")()
    if adapter_name == "QQ" or bot.__class__.__module__.startswith("nonebot.adapters.qq"):
        await _send_qq(bot, event, reply, config)
    else:
        await bot.send(event, reply.text())


def _qq_segments(reply: Reply, config: Config) -> tuple[str, Any]:
    prefix = config.spirit_pet_command_prefix
    plain = reply.text() + "\n快捷指令：" + " / ".join(prefix + command for command in reply.commands)
    links = "　".join(inline_command(command, command, prefix) for command in reply.commands)

    def escape(value: str) -> str:
        return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", value)

    markdown = f"### {escape(reply.title)}\n\n" + "\n\n".join(
        f"> {escape(line)}" for line in reply.lines
    )
    qq_mode = config.spirit_pet_qq_mode
    if qq_mode == "native" and config.spirit_pet_qq_blue_links:
        markdown += f"\n\n{links}"
    from nonebot.adapters.qq.message import Message, MessageSegment

    if qq_mode == "template":
        from nonebot.adapters.qq.models import MessageMarkdown, MessageMarkdownParams

        markdown_segment = MessageSegment.markdown(
            MessageMarkdown(
                custom_template_id=config.spirit_pet_qq_template_id,
                params=[
                    MessageMarkdownParams(
                        key=config.spirit_pet_qq_template_param,
                        values=[plain],
                    )
                ],
            )
        )
    elif qq_mode == "native":
        markdown_segment = MessageSegment.markdown(markdown)
    else:
        return plain, Message(plain)
    message = Message(markdown_segment)
    if config.spirit_pet_qq_keyboard:
        message += qq_keyboard(reply.commands, prefix)
    return plain, message


async def _send_qq(bot: Bot, event: Event, reply: Reply, config: Config) -> None:
    if config.spirit_pet_qq_mode == "text":
        await bot.send(event, reply.text())
        return

    from nonebot.adapters.qq.exception import ActionFailed

    try:
        fallback, message = _qq_segments(reply, config)
    except (ImportError, AttributeError, ValueError, TypeError):
        logger.warning("QQ rich-message support unavailable; sending plain-text reply")
        await bot.send(event, reply.text())
        return
    try:
        await bot.send(event, message)
    except ActionFailed as exc:
        # A timeout may already have delivered the message; never retry that case.
        if exc.status_code not in (400, 403, 422):
            raise
        logger.warning(f"QQ rich message rejected (status={exc.status_code}, code={exc.code}); using text")
        await bot.send(event, fallback)
