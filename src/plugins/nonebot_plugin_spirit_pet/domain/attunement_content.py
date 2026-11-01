from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Positive


class AttunementOption(Definition):
    """One element a pet can be attuned to, and what the change costs."""

    element: Identifier
    stones: Positive
    items: dict[Identifier, Positive] = Field(default_factory=dict)


class Attunements(Definition):
    options: Annotated[list[AttunementOption], Field(min_length=1)]

    @property
    def by_element(self) -> dict[str, AttunementOption]:
        return {option.element: option for option in self.options}
