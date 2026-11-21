from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class FamilyTutelageCourse(Definition):
    id: Identifier
    name: Name
    skill: Identifier
    enemy: Identifier
    parent_level: Annotated[int, Field(ge=2, le=4)] = 2
    lesson_energy: Annotated[int, Field(ge=1, le=30)] = 6
    lesson_stones: Annotated[int, Field(ge=1, le=500)] = 60
    lesson_materials: dict[Identifier, Annotated[int, Field(ge=1, le=10)]] = Field(min_length=1, max_length=3)
    exam_energy: Annotated[int, Field(ge=1, le=30)] = 8
    max_rounds: Annotated[int, Field(ge=5, le=40)] = 40
    proficiency: Annotated[int, Field(ge=1, le=20)] = 12


class FamilyTutelageRules(Definition):
    lessons: Literal[2] = 2
    interval: Annotated[int, Field(ge=60, le=86400)] = 600
    duration: Literal[604800] = 604800
    weekly_starts: Annotated[int, Field(ge=1, le=3)] = 2
    attempts: Annotated[int, Field(ge=1, le=3)] = 3


class FamilyTutelageCatalog(Definition):
    rules: FamilyTutelageRules
    courses: list[FamilyTutelageCourse] = Field(min_length=4, max_length=8)

    @model_validator(mode="after")
    def check_unique_courses(self):
        for field in ("id", "name", "skill"):
            if len({getattr(course, field) for course in self.courses}) != len(self.courses):
                raise ValueError(f"family tutelage courses must have unique {field}")
        if not {"wind_slash", "fireball", "water_arrow", "wood_heal"}.issubset(
            course.skill for course in self.courses
        ):
            raise ValueError("family tutelage must cover the four introductory skills")
        return self
