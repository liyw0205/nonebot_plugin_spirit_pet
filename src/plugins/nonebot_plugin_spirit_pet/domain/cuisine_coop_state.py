from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Effects, Identifier, Name

COOK_TOGETHER_SECONDS = 24 * 3600


class CuisineCoopSnapshot(Definition):
    kind: Literal["cuisine_coop"] = "cuisine_coop"
    version: Literal[1] = 1
    project_id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    owner_id: Annotated[str, Field(min_length=1)]
    helper_id: Annotated[str, Field(min_length=1)]
    owner_pet_id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    owner_pet_name: Annotated[str, Field(min_length=1, max_length=80)]
    helper_pet_id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)] | None = None
    helper_pet_name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    dish_id: Identifier
    dish_name: Name
    item_id: Identifier
    item_name: Name
    ingredients: dict[Identifier, Annotated[int, Field(gt=0, le=1_000_000)]] = Field(min_length=1, max_length=4)
    ingredient_names: dict[Identifier, Name] = Field(min_length=1, max_length=4)
    stones: Annotated[int, Field(ge=0, le=1_000_000)]
    heat: Annotated[int, Field(ge=1, le=5)]
    effects: Effects
    status: Literal["pending", "ready", "finished", "rejected", "cancelled", "expired"]
    event: Literal["start", "accept", "complete", "reject", "cancel", "expire"]
    started_at: Annotated[int, Field(ge=0)]
    expires_at: Annotated[int, Field(ge=0)]
    updated_at: Annotated[int, Field(ge=0)]
    finished_at: Annotated[int, Field(ge=0)] | None = None
    settlement: dict[str, list[str]] | None = None
    refunds: dict[str, list[str]] | None = None

    @model_validator(mode="after")
    def validate_transition(self):
        if self.owner_id == self.helper_id or self.owner_pet_id == self.helper_pet_id:
            raise ValueError("participants and their pets must differ")
        if set(self.ingredients) != set(self.ingredient_names):
            raise ValueError("ingredient names must match the frozen recipe")
        if self.expires_at != self.started_at + COOK_TOGETHER_SECONDS or self.updated_at < self.started_at:
            raise ValueError("cuisine cooperation timestamps are not ordered")
        expected = {
            "start": "pending", "accept": "ready", "complete": "finished",
            "reject": "rejected", "cancel": "cancelled", "expire": "expired",
        }
        if expected[self.event] != self.status:
            raise ValueError("cuisine cooperation status does not match its event")
        if self.status != "expired" and self.updated_at >= self.expires_at:
            raise ValueError("cuisine cooperation action passed its deadline")
        if self.status == "expired" and self.updated_at < self.expires_at:
            raise ValueError("cuisine cooperation expired before its deadline")
        if self.status in {"ready", "finished"} and (self.helper_pet_id is None or self.helper_pet_name is None):
            raise ValueError("accepted cuisine cooperation must identify the helper pet")
        if self.status == "finished" and (self.finished_at is None or self.settlement is None):
            raise ValueError("finished cuisine cooperation must include its settlement")
        if self.status in {"rejected", "cancelled", "expired"} and self.refunds is None:
            raise ValueError("refunded cuisine cooperation must retain its refund receipt")
        if self.status == "finished" and self.finished_at != self.updated_at:
            raise ValueError("cuisine cooperation settlement time must match its final action")
        if self.effects.breakthrough_bonus or not (
            self.effects.energy or self.effects.exp or self.effects.affinity
        ):
            raise ValueError("cuisine cooperation must freeze a normal meal effect")
        if self.status == "finished":
            if set(self.settlement or ()) != {"owner", "helper"} or self.refunds is not None:
                raise ValueError("finished cuisine cooperation must have bilateral settlement only")
        elif self.finished_at is not None or self.settlement is not None:
            raise ValueError("unfinished cuisine cooperation cannot have a settlement")
        if self.status in {"pending", "ready"} and self.refunds is not None:
            raise ValueError("active cuisine cooperation cannot have refunds")
        if self.status in {"rejected", "cancelled", "expired"}:
            expected_refunds = {"owner", "helper"} if self.helper_pet_id is not None and self.status != "rejected" else {"owner"}
            if set(self.refunds or ()) != expected_refunds:
                raise ValueError("cuisine cooperation refunds do not match paid participants")
        if self.event == "start" and self.helper_pet_id is not None:
            raise ValueError("new cuisine cooperation cannot preselect the helper pet")
        if self.event in {"start", "reject"} and self.helper_pet_id is not None:
            raise ValueError("only a pending invitation can omit helper payment")
        if self.event == "accept" and self.helper_pet_id is None:
            raise ValueError("accepted cuisine cooperation must freeze the helper pet")
        return self
