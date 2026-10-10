from dataclasses import dataclass


@dataclass
class Player:
    user_id: str
    internal_id: int
    stones: int
    active_pet_id: int | None
    registered_at: int | None = None
    sign_day: str = ""
    last_bond_day: str = ""
    current_bond_streak: int = 0
    best_bond_streak: int = 0
    quest_day: str = ""
    last_train: int | None = None
    last_explore: int | None = None
    last_pve: int | None = None
    last_pvp: int | None = None

    @property
    def uid(self) -> int:
        return self.internal_id + 9999

    @property
    def uid_label(self) -> str:
        return f"UID {self.uid}"


@dataclass
class Pet:
    pet_id: int
    user_id: str
    species_id: str
    name: str
    realm: int
    layer: int
    bloodline: int
    exp: int
    affinity: int
    energy: int
    energy_updated: int
    lineage_id: str | None = None
    archived: bool = False
    major_breakthrough_failures: int = 0
