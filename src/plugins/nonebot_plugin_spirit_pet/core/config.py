from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Config(BaseModel):
    spirit_pet_db: Path = Path("data/spirit_pet/spirit_pet.db")
    spirit_pet_train_cooldown: int = Field(default=300, ge=1)
    spirit_pet_explore_cooldown: int = Field(default=900, ge=1)
    spirit_pet_energy_interval: int = Field(default=300, ge=1)
    spirit_pet_pve_cooldown: int = Field(default=600, ge=1)
    spirit_pet_pvp_cooldown: int = Field(default=900, ge=1)
    spirit_pet_team_request_ttl: int = Field(default=600, ge=1)
    spirit_pet_team_request_limit: int = Field(default=10, ge=1, le=100)
    spirit_pet_expedition_duration: int = Field(default=3600, ge=1)
    spirit_pet_max_pets: int = Field(default=50, ge=1, le=200)
    spirit_pet_qq_mode: Literal["text", "native", "template"] = "text"
    spirit_pet_qq_template_id: str = ""
    spirit_pet_qq_template_param: str = "content"
    spirit_pet_qq_keyboard: bool = True
    spirit_pet_qq_blue_links: bool = True
    spirit_pet_command_prefix: str = "/"

    @model_validator(mode="after")
    def check_template(self) -> "Config":
        if self.spirit_pet_db.name in {"", ".", ".."}:
            raise ValueError("database path must point to a file")
        if self.spirit_pet_qq_mode == "template" and (
            not self.spirit_pet_qq_template_id.strip()
            or not self.spirit_pet_qq_template_param.strip()
        ):
            raise ValueError("template mode requires a template ID and parameter name")
        if any(char.isspace() for char in self.spirit_pet_command_prefix):
            raise ValueError("command prefix cannot contain whitespace")
        return self
