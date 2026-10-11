from contextlib import closing, contextmanager
from dataclasses import dataclass
from random import Random

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.gameplay.loadout import combatant, combatants, team_pets
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .scenarios import _equip

SIMULATION_NOW = 1_800_000_000


@dataclass(frozen=True)
class LineupScenario:
    dungeon_id: str
    realm: int
    profile: str
    variant: str
    rosters: tuple[tuple[str, ...], ...]

    @property
    def id(self) -> str:
        return f"{self.dungeon_id}/{self.profile}/{self.variant}"

    @property
    def seed_group(self) -> str:
        return f"{self.dungeon_id}/{self.profile}"


def lineup_scenarios(content) -> list[LineupScenario]:
    starters = tuple(species.id for species in content.species.values() if species.starter)[:3]
    if len(starters) != 3:
        raise ValueError("lineup comparisons require three distinct starter species")
    realms = [realm.id for realm in content.realms]
    result = []
    for dungeon in content.dungeons.values():
        baseline = tuple((species,) for species in starters) if dungeon.team else ((starters[0],),)
        expanded = (starters, *baseline[1:])
        for profile in ("entry", "prepared"):
            for variant, rosters in (("baseline", baseline), ("multi", expanded)):
                result.append(LineupScenario(dungeon.id, realms.index(dungeon.min_realm), profile, variant, rosters))
    return result


@contextmanager
def lineup_fixture(store, content, config, scenario):
    """Keep the production roster and loadout in one disposable transaction."""
    if scenario.profile not in {"entry", "prepared"} or not 0 <= scenario.realm < len(content.realms):
        raise ValueError("invalid simulation profile or realm")
    with closing(store.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            repo = Repository(conn)
            users, pet_ids = [], []
            for index, roster in enumerate(scenario.rosters):
                user_id = f"lineup-simulation-{index}"
                users.append(user_id)
                repo.create_player(user_id, f"lineup-sim-{index + 1}", 0)
                ctx = Context(repo, content, config, Random(0), user_id, SIMULATION_NOW, "lineup-fixture")
                owned = []
                for species_id in roster:
                    species = content.species[species_id]
                    pet = repo.create_pet(user_id, species_id, species.name, species.initial_affinity, SIMULATION_NOW)
                    pet.realm = scenario.realm
                    pet.layer = 5 if scenario.profile == "prepared" else 1
                    pet.bloodline = min(scenario.realm // 2, max(content.bloodlines)) if pet.layer == 5 else 0
                    pet.affinity = 30 if pet.layer == 5 else species.initial_affinity
                    owned.append(pet.pet_id)
                    if scenario.profile == "prepared":
                        _equip(ctx, pet)
                repo.set_active_pets(user_id, owned)
                pet_ids.append(owned)
            if len(users) > 1:
                team_id = conn.execute("INSERT INTO teams(leader_id) VALUES (?)", (users[0],)).lastrowid
                conn.executemany("INSERT INTO team_members(user_id, team_id) VALUES (?, ?)",
                                 [(user, team_id) for user in users])
            repo.save()
            ctx = Context(repo, content, config, Random(0), users[0], SIMULATION_NOW, "lineup-fixture")
            if len(users) == 1:
                units = combatants(ctx, recover_energy=False)
            else:
                selected = team_pets(ctx, users, users[0])
                units = [combatant(ctx, owner, recover_energy=False, pet_id=pet.pet_id) for owner, pet in selected]
            yield conn, users, pet_ids, units
        finally:
            conn.rollback()
