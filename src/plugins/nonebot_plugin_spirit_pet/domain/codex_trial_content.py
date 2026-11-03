from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class CodexMilestone(Definition):
    """A one-time bonus paid when this many species have been cleared."""

    count: Positive
    items: dict[Identifier, Positive] = {}


class CodexRotation(Definition):
    """One weekly constraint for the rotating codex trial.

    Exactly one condition is armed per rotation, decided by ``kind``:

    * ``round_limit`` — the battle is cut off after ``rounds`` rounds, so failing to win by
      then is a loss and a slow grind stops being a win.
    * ``element_lock`` — only a companion carrying one of ``elements`` may enter; which one
      the week demands is picked from the pool, so it has to hold at least two.
    * ``stat_scale`` — the mirror's four stats are multiplied by ``scale`` on top of the
      trial's own ``boost``.

    Fields belonging to the other kinds must stay unset, so a content edit cannot silently
    arm two conditions at once.
    """

    id: Identifier
    name: Name
    description: Name
    kind: Literal["round_limit", "element_lock", "stat_scale"]
    rounds: Annotated[int, Field(ge=1, le=40)] | None = None
    scale: Annotated[float, Field(ge=1.0, le=3.0)] | None = None
    elements: list[Identifier] = Field(default_factory=list, max_length=8)
    energy: Positive
    reward: Reward

    @model_validator(mode="after")
    def _one_condition(self):
        armed = {
            "round_limit": self.rounds is not None,
            "element_lock": bool(self.elements),
            "stat_scale": self.scale is not None,
        }
        if not armed[self.kind]:
            raise ValueError(f"codex rotation {self.id} must set its own {self.kind} value")
        if any(value for kind, value in armed.items() if kind != self.kind):
            raise ValueError(f"codex rotation {self.id} must not set values for another kind")
        if self.kind == "element_lock" and len(self.elements) < 2:
            raise ValueError(f"codex rotation {self.id} needs at least two elements")
        if len(set(self.elements)) != len(self.elements):
            raise ValueError(f"codex rotation {self.id} repeats an element")
        return self

    def value(self):
        """The armed value, whichever kind this rotation is."""
        return {
            "round_limit": self.rounds,
            "element_lock": self.elements,
            "stat_scale": self.scale,
        }[self.kind]


class CodexTrial(Definition):
    """One config for the per-species mirror trials (species come from the codex)."""

    id: Identifier
    name: Name
    boost: Annotated[float, Field(ge=1.0, le=5.0)]
    energy: Positive
    reward: Reward
    milestones: list[CodexMilestone] = []
    weekly_slots: Annotated[int, Field(ge=1, le=5)] | None = None
    weekly_bonus: Reward | None = None
    rotations: list[CodexRotation] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _milestones_ascend(self):
        counts = [milestone.count for milestone in self.milestones]
        if counts != sorted(counts) or len(counts) != len(set(counts)):
            raise ValueError(f"codex trial {self.id} milestones must be unique and ascending")
        ids = [rotation.id for rotation in self.rotations]
        if len(ids) != len(set(ids)):
            raise ValueError(f"codex trial {self.id} repeats a rotation id")
        if (self.weekly_slots is None) != (self.weekly_bonus is None):
            raise ValueError(f"codex trial {self.id} weekly slots and bonus must be set together")
        if self.weekly_slots is None and self.rotations:
            raise ValueError(f"codex trial {self.id} declares rotations without weekly slots")
        if self.weekly_slots is not None and len(self.rotations) < self.weekly_slots:
            raise ValueError(
                f"codex trial {self.id} needs at least weekly_slots distinct rotations"
            )
        return self
