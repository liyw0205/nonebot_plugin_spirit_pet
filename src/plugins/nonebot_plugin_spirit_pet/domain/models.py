from dataclasses import dataclass


@dataclass(frozen=True)
class InlineCommand:
    line: int
    label: str
    command: str


@dataclass(frozen=True)
class Reply:
    title: str
    lines: tuple[str, ...]
    commands: tuple[str, ...] = ("我的灵宠", "灵宠签到", "灵宠修炼", "灵宠历练")
    inline_commands: tuple[InlineCommand, ...] = ()

    def text(self) -> str:
        lines = list(self.lines)
        for action in self.inline_commands:
            if 0 <= action.line < len(lines):
                suffix = f"{action.label}（{action.command.rstrip()}）"
                lines[action.line] += f" · {suffix}"
        return f"【{self.title}】\n" + "\n".join(lines)

    @classmethod
    def from_data(cls, data: dict) -> "Reply":
        return cls(
            data["title"],
            tuple(data["lines"]),
            tuple(data.get("commands", ())),
            tuple(InlineCommand(**item) for item in data.get("inline_commands", ())),
        )


class GameError(Exception):
    """可预期的玩法拒绝；由事务层回滚，不发送堆栈。"""

    def __init__(self, message: str, *, reply: Reply | None = None):
        super().__init__(message)
        self.reply = reply
