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
    operation_id: str

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
        if pet.archived:
            raise GameError(f"{pet.name}已封存，请先复原后再出战。")
        restore_energy(pet, self.now, self.config.spirit_pet_energy_interval)
        return pet

    def require_idle_pet(self, pet: Pet) -> None:
        expedition = self.repo.active_expedition(pet.pet_id)
        if expedition is not None:
            state = "正在外出派遣" if self.now < expedition["finishes_at"] else "派遣已完成，奖励待领取"
            raise GameError(f"{pet.name}{state}，当前不能行动，请先查看 灵宠行程。")

    def check_action(self, player: Player, pet: Pet, action: str, energy: int, cooldown: int):
        self.require_idle_pet(pet)
        remaining = cooldown_left(getattr(player, f"last_{action}"), self.now, cooldown)
        if remaining:
            raise GameError(f"{pet.name}尚需调息 {remaining} 秒。")
        if pet.energy < energy:
            raise GameError(f"{pet.name}精力不足，需要 {energy} 点。")
