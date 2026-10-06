from dataclasses import dataclass
from typing import Any

from ..content.catalog import Catalog
from ..core.config import Config
from ..domain.models import GameError
from ..domain.state import Pet, Player
from ..storage.repository import Repository
from ..utils.energy import restore_energy
from ..utils.time import cooldown_left


@dataclass
class Context:
    repo: Repository
    content: Catalog
    config: Config
    rng: Any
    user_id: str
    now: int

    def player(self, user_id: str | None = None) -> Player:
        player = self.repo.player(user_id or self.user_id)
        if player is None:
            raise GameError("尚未结契，请先发送 /灵宠领养 青鸾。")
        return player

    def pet(self, user_id: str | None = None) -> Pet:
        player = self.player(user_id)
        if player.active_pet_id is None:
            raise GameError("尚未选择出战灵宠。")
        pet = self.repo.pet(player.active_pet_id)
        restore_energy(pet, self.now, self.config.spirit_pet_energy_interval)
        return pet

    def check_action(self, player: Player, pet: Pet, action: str, energy: int, cooldown: int):
        remaining = cooldown_left(getattr(player, f"last_{action}"), self.now, cooldown)
        if remaining:
            raise GameError(f"{pet.name}尚需调息 {remaining} 秒。")
        if pet.energy < energy:
            raise GameError(f"{pet.name}精力不足，需要 {energy} 点。")
