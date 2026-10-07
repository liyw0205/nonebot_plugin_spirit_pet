from dataclasses import dataclass


@dataclass
class Player:
    user_id: str
    dao_name: str
    stones: int
    active_pet_id: int | None
    sign_day: str = ""
    quest_day: str = ""
    last_train: int | None = None
    last_explore: int | None = None
    last_pve: int | None = None
    last_pvp: int | None = None


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
