from dataclasses import dataclass


@dataclass(frozen=True)
class Reply:
    title: str
    lines: tuple[str, ...]
    commands: tuple[str, ...] = ("我的灵宠", "灵宠签到", "灵宠修炼", "灵宠历练")

    def text(self) -> str:
        return f"【{self.title}】\n" + "\n".join(self.lines)


class GameError(Exception):
    """Expected game-rule rejection; never partially commits a mutation."""
