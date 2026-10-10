from dataclasses import dataclass


@dataclass(frozen=True)
class Reply:
    title: str
    lines: tuple[str, ...]
    commands: tuple[str, ...] = ("我的灵宠", "灵宠签到", "灵宠修炼", "灵宠历练")

    def text(self) -> str:
        return f"【{self.title}】\n" + "\n".join(self.lines)


class GameError(Exception):
    """可预期的玩法拒绝；由事务层回滚，不发送堆栈。"""

    def __init__(self, message: str, *, reply: Reply | None = None):
        super().__init__(message)
        self.reply = reply
