from dataclasses import dataclass
from typing import Any

from ..content.catalog import Catalog
from ..core.config import Config
from ..domain.models import GameError, InlineCommand, Reply
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
            "还没有灵宠伙伴。先完成领养，就能开启你们的仙途。",
            "初始伙伴：" + "、".join(starters),
            "领养成功后，伙伴会自动出战。",
            "下一步：灵宠帮助",
        ), ("灵宠帮助",), (InlineCommand(0, "开始领养", "灵宠领养 "),))

    def missing_pet(self, user_id: str | None = None) -> GameError:
        owner = user_id or self.user_id
        if owner != self.user_id:
            return GameError("对方尚未选择出战灵宠，当前无法继续。")
        links = [
            InlineCommand(0, "查看灵宠名册", "灵宠列表"),
            InlineCommand(1, "填写出战编号", "灵宠出战 "),
        ]
        lines = ["尚未选择出战灵宠。去名册挑一位伙伴，再一起出发吧。", "例如：灵宠出战 编号"]
        if self.repo.archived_pet_count(owner):
            lines.append("封存的伙伴也能在灵宠封存库中复原。")
            links.append(InlineCommand(2, "查看封存库", "灵宠封存库"))
        reply = Reply("选择伙伴", tuple(lines), (), tuple(links))
        return GameError(lines[0], reply=reply)

    def archived_active_pet(self, pet: Pet, user_id: str) -> GameError:
        if user_id != self.user_id:
            return GameError("对方的出战灵宠暂不可用，当前无法继续。")
        reply = Reply("灵宠已封存", (
            f"{pet.name}已经封存，复原后才能继续同行。",
            "也可以打开名册，改选其他伙伴出战。",
        ), (), (
            InlineCommand(0, "复原这只灵宠", f"灵宠复原 {pet.pet_id}"),
            InlineCommand(1, "查看灵宠名册", "灵宠列表"),
        ))
        return GameError(reply.lines[0], reply=reply)

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
            raise self.archived_active_pet(pet, owner)
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
                raise self.archived_active_pet(pet, owner)
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
