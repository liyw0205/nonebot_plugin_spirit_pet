from pydantic import model_validator

from .content import Definition, Identifier, Name, Reward, Stats


class DuelOpponent(Definition):
    """A sparring guardian fought one exchange at a time."""

    id: Identifier
    name: Name
    description: str
    realm: Identifier
    stats: Stats
    reward: Reward

    @model_validator(mode="after")
    def _sane(self):
        if self.reward.stones.maximum <= 0 and self.reward.exp.maximum <= 0:
            raise ValueError(f"duel opponent {self.id} must grant stones or exp")
        return self
