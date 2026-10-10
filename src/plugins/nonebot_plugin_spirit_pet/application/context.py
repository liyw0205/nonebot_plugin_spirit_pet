from dataclasses import dataclass
from typing import Any

from ..content.catalog import Catalog
from ..core.config import Config
from ..domain.models import GameError, Reply
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

    def adoption_reply(self) -> Reply:
        starters = [species.name for species in self.content.species.values() if species.starter]
        return Reply("初遇灵宠", (
            "尚未结契。挑一位山海伙伴，开启你们的仙途吧。",
            "初始伙伴：" + "、".join(starters),
            "首次领养会获得专属道号，伙伴也会立即出战。",
            "例如：灵宠领养 " + starters[0],
        ), tuple(f"灵宠领养 {name}" for name in starters))

    def missing_pet(self, user_id: str | None = None) -> GameError:
        owner = user_id or self.user_id
        if owner != self.user_id:
            return GameError("对方尚未选择出战灵宠，当前无法继续。")
        commands = ["灵宠列表", "灵宠出战 "]
        lines = ["尚未选择出战灵宠。去名册挑一位伙伴，再一起出发吧。", "例如：灵宠出战 编号"]
        if self.repo.archived_pet_count(owner):
            lines.append("封存的伙伴也能在灵宠封存库中复原。")
            commands.append("灵宠封存库")
        reply = Reply("选择伙伴", tuple(lines), tuple(commands))
        return GameError(lines[0], reply=reply)

    def player(self, user_id: str | None = None) -> Player:
        owner = user_id or self.user_id
        player = self.repo.player(owner)
        if player is None:
            if owner != self.user_id:
                raise GameError("对方尚未结契，当前无法继续。")
            reply = self.adoption_reply()
            raise GameError(reply.lines[0], reply=reply)
        return player

    def pet(self, user_id: str | None = None) -> Pet:
        owner = user_id or self.user_id
        player = self.player(owner)
        if player.active_pet_id is None:
            raise self.missing_pet(owner)
        pet = self.repo.pet(player.active_pet_id)
        if pet.archived:
            if owner != self.user_id:
                raise GameError("对方的出战灵宠暂不可用，当前无法继续。")
            raise GameError(f"{pet.name}已封存，请先复原后再出战。")
        restore_energy(pet, self.now, self.config.spirit_pet_energy_interval)
        return pet

    def active_pets(self, user_id: str | None = None) -> list[Pet]:
        """Load and refresh every pet in the user's battle roster."""
        owner = user_id or self.user_id
        self.player(owner)
        pets = self.repo.active_pets(owner)
        if not pets:
            raise self.missing_pet(owner)
        for pet in pets:
            if pet.archived:
                if owner != self.user_id:
                    raise GameError("对方的出战灵宠暂不可用，当前无法继续。")
                raise GameError(f"{pet.name}已封存，请先复原后再出战。")
            restore_energy(pet, self.now, self.config.spirit_pet_energy_interval)
        if len(pets) > 3:
            raise GameError("出战阵容最多三只灵宠。")
        if len({pet.species_id for pet in pets}) != len(pets):
            raise GameError("同一出战阵容不能包含重复宠物种类。")
        return pets

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
