import re
from typing import Any
from urllib.parse import quote

from nonebot.adapters import Bot, Event
from nonebot.log import logger

from ..core.config import Config
from ..domain.models import Reply
from ..gameplay.help import help_link


_SECTION_HEADINGS = frozenset({
    "总览", "概况", "成长", "状态", "战斗", "进阶", "下一步",
})
_ACTION_LABELS = {
    "灵宠帮助": "帮助总览",
    "灵宠帮助 结契": "结契入口",
    "灵宠帮助 成长": "成长指南",
    "灵宠帮助 秘境与关卡": "秘境与关卡",
    "灵宠帮助 血脉与道具": "血脉与道具",
    "灵宠帮助 对战与赛季": "对战与赛季",
    "灵宠帮助 灵物与灵术": "灵物与灵术",
    "灵宠帮助 组队与派遣": "组队与派遣",
    "灵宠帮助 身份与收集": "身份与收集",
    "我的灵宠": "查看灵宠",
    "我的信息": "我的信息",
    "灵宠道号": "修改道号",
    "灵宠修炼": "修炼",
    "灵宠互动": "互动",
    "灵宠突破": "突破境界",
    "灵宠进化": "进化血脉",
    "灵宠行程": "查看行程",
    "灵宠列表": "灵宠名册",
    "灵宠装备": "查看装备",
    "灵宠技能": "查看灵术",
}


def _action_label(command: str) -> str:
    visible = command.strip().removeprefix("/")
    return _ACTION_LABELS.get(visible, visible)


def _command_enters(command: str) -> bool:
    """A trailing blank asks QQ to prefill the command instead of sending it."""
    return not command.endswith((" ", "\t"))


def _action_items(reply: Reply) -> tuple[tuple[str, str], ...]:
    """Select short, page-specific next steps while retaining raw command payloads."""
    commands = reply.commands
    if reply.title == "灵宠仙途" or reply.title.startswith("帮助 ·"):
        commands = ()
    linked = {action.command for action in reply.inline_commands}
    commands = tuple(command for command in commands if command not in linked)
    return tuple((_action_label(command), command) for command in commands)


def inline_command(label: str, command: str, prefix: str = "/") -> str:
    label = label.removeprefix("/").strip()
    if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9 /+\-]+", label):
        raise ValueError("invalid button label")
    if any(char in command for char in "\r\n\\[]()"):
        raise ValueError("invalid button command")
    encoded = quote(f"{prefix}{command}", safe="")
    enter = str(_command_enters(command)).lower()
    return f"[{label}](mqqapi://aio/inlinecmd?command={encoded}&enter={enter}&reply=false)"


def qq_keyboard(
    commands: tuple[str, ...], prefix: str = "/", labels: tuple[str, ...] | None = None,
) -> Any:
    from nonebot.adapters.qq.message import MessageSegment
    from nonebot.adapters.qq.models import Action, Button, InlineKeyboard, InlineKeyboardRow, MessageKeyboard, Permission, RenderData

    rows = []
    for offset in range(0, min(len(commands), 8), 2):
        buttons = []
        for index, command in enumerate(commands[offset : offset + 2], offset):
            label = (labels[index] if labels and index < len(labels) else _action_label(command))
            buttons.append(
                Button(
                    id=f"spirit-pet-{index}",
                    render_data=RenderData(label=label, visited_label=label, style=1),
                    action=Action(
                        type=2,
                        permission=Permission(type=2),
                        data=f"{prefix}{command}",
                        reply=True,
                        enter=_command_enters(command),
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
    actions = _action_items(reply)
    commands = tuple(command for _, command in actions)
    labels = tuple(label for label, _ in actions)
    qq_mode = config.spirit_pet_qq_mode
    plain = reply.text()
    if labels:
        plain += "\n下一步：" + "、".join(labels)

    def escape(value: str) -> str:
        return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", value)

    is_help = reply.title == "灵宠仙途" or reply.title.startswith("帮助 ·")
    body = []
    use_links = qq_mode == "native" and config.spirit_pet_qq_blue_links
    links_by_line: dict[int, list] = {}
    for action in reply.inline_commands:
        if 0 <= action.line < len(reply.lines):
            links_by_line.setdefault(action.line, []).append(action)

    def contextual_actions(index: int) -> str:
        rendered = []
        for action in links_by_line.get(index, ()):
            if use_links:
                rendered.append(inline_command(action.label, action.command, prefix))
            else:
                rendered.append(f"{escape(action.label)}（{escape(action.command.rstrip())}）")
        return " · ".join(rendered)

    for source_index, line in enumerate(reply.lines):
        contextual = contextual_actions(source_index)
        if line in _SECTION_HEADINGS:
            if body and body[-1] != "":
                body.append("")
            body.append(f"**{escape(line)}**")
        elif is_help and (link := help_link(line)) is not None:
            heading, detail = line.split("：", 1)
            visible_heading = (
                inline_command(*link, prefix)
                if use_links
                else escape(heading)
            )
            rendered = f"{visible_heading} · {escape(detail)}"
            if contextual:
                rendered += f" · {contextual}"
            body.extend((rendered, ""))
        elif line.startswith("道号：") and reply.title == "我的信息":
            edit_link = (
                f" · {inline_command('修改道号', '灵宠道号 ', prefix)}" if use_links else " · 改名：灵宠道号 新道号"
            )
            rendered = f"**道号**：{escape(line.removeprefix('道号：'))}{edit_link}"
            if contextual:
                rendered += f" · {contextual}"
            body.append(rendered)
        elif line.startswith("你的道号：") and reply.title == "灵契初成":
            rendered = f"**{escape(line)}**"
            if contextual:
                rendered += f" · {contextual}"
            body.append(rendered)
        else:
            rendered = escape(line)
            if contextual:
                rendered += f" · {contextual}"
            body.append(rendered)
    body_markdown = "\n".join(body)
    markdown = f"**{escape(reply.title)}**\n\n" + body_markdown
    if reply.title == "我的信息":
        actions = tuple(item for item in actions if item[1] != "灵宠道号")
        commands = tuple(command for _, command in actions)
        labels = tuple(label for label, _ in actions)
    if actions and not is_help:
        action_block = "\n".join(
            f"- {inline_command(label, command, prefix) if use_links else escape(label)}"
            for label, command in actions
        )
        markdown += f"\n\n{action_block}"
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
    if config.spirit_pet_qq_keyboard and commands and not is_help:
        message += qq_keyboard(commands, prefix, labels)
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
