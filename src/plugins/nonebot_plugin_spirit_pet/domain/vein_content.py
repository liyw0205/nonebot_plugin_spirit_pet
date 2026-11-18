from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Reward


class VeinNode(Definition):
    name: Name
    description: str
    material: Identifier


class VeinRoute(Definition):
    id: Identifier
    name: Name
    description: str
    min_realm: Identifier
    nodes: Annotated[list[VeinNode], Field(min_length=3, max_length=3)]
    reward: Reward
    guarded_reward: Reward
    bond: Annotated[int, Field(strict=True, ge=1, le=100)]

    @model_validator(mode="after")
    def valid_nodes(self):
        if len({node.name for node in self.nodes}) != len(self.nodes):
            raise ValueError("vein node names must be unique")
        if self.reward == self.guarded_reward:
            raise ValueError("guarded vein reward must differ from base reward")
        return self
