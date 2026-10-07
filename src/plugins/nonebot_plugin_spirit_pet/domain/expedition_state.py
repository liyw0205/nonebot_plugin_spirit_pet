from pydantic import BaseModel, ConfigDict

from .content import Identifier, NonNegative


class RewardSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    exp: NonNegative
    stones: NonNegative
    items: dict[Identifier, NonNegative]
