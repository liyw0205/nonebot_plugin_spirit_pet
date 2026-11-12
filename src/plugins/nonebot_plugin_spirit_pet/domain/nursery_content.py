from pydantic import Field

from .content import Definition, Identifier, Name


class NurseryLesson(Definition):
    id: Identifier
    name: Name
    description: str
    exp: int = Field(default=0, ge=0, le=20)
    affinity: int = Field(default=0, ge=0, le=2)
    bond: int = Field(default=0, ge=0, le=8)


class NurseryRule(Definition):
    item_id: Identifier
    energy: int = Field(ge=1, le=10)
    interval: int = Field(ge=60, le=3600)
    lessons: int = Field(ge=1, le=2)
    guardian_bond: int = Field(ge=0, le=4)
    choices: list[NurseryLesson] = Field(min_length=3, max_length=3)
