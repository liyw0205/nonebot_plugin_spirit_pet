from dataclasses import dataclass

from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.gameplay import talents
from nonebot_plugin_spirit_pet.gameplay.combat import enemy_fighter

from .scenarios import build_fighters


@dataclass(frozen=True)
class SpecialScenario:
    category: str
    subject: str
    variant: str
    realm: int
    party: tuple[str, ...]
    opponents: tuple[str, ...] = ()
    dungeon_id: str | None = None
    initial_venom: bool = False

    @property
    def id(self) -> str:
        return f"{self.category}/{self.subject}/{self.variant}"

    @property
    def seed_group(self) -> str:
        subject = self.party[0] if self.category == "lineage" else self.subject
        return f"{self.category}/{subject}/{self.realm}"


def special_scenarios(content: Catalog) -> list[SpecialScenario]:
    result = []
    realm = min(2, len(content.realms) - 1)
    dungeon = next(dungeon for dungeon in content.dungeons.values()
                   if not dungeon.team and dungeon.min_realm == content.realms[realm].id)
    for branch in content.lineages.values():
        for variant in ("selected", "control"):
            result.append(SpecialScenario("lineage", branch.id, variant, realm, (branch.species_id,),
                                          dungeon_id=dungeon.id))
    fixtures = {
        "ice_seal": (("hanying",), ("xuanhu",), False),
        "poison_sapping": (("duman",), ("baize",), False),
        "earthen_ward": (("baize",), ("xuanhu",), False),
        "pure_breath": (("qingluan", "xuanhu"), ("duman", "baize"), True),
        "spirit_dispel": (("qingluan",), ("baize",), False),
        "battle_chant": (("qingluan", "xuanhu"), ("baize", "jiaolong"), False),
        "mountain_taunt": (("baize", "qingluan"), ("xuanhu", "jiaolong"), False),
        "spirit_wave": (("qingluan", "xuanhu"), ("baize", "jiaolong"), False),
    }
    for key, (party, opponents, initial_venom) in fixtures.items():
        if key not in content.skills:
            continue
        minimum = content.skills[key].requirements.min_realm
        realm = next(index for index, stage in enumerate(content.realms) if stage.id == minimum)
        category = "effect" if content.skills[key].effects else "skill"
        for variant in ("selected", "control"):
            result.append(SpecialScenario(category, key, variant, realm, party, opponents,
                                          initial_venom=initial_venom))
    return result


def build_special(store, content, config, scenario):
    if scenario.category == "lineage":
        branch = content.lineages[scenario.subject]
        lineage_id = branch.id if scenario.variant == "selected" else None
        left = build_fighters(
            store, content, config, scenario.party, scenario.realm, "prepared",
            lineage_ids=(lineage_id,), bloodlines=(branch.min_bloodline,),
        )
        dungeon = content.dungeons[scenario.dungeon_id]
        right = [enemy_fighter(content.enemies[key], content.skills) for key in dungeon.enemies]
    else:
        party = (*scenario.party, *scenario.opponents)
        skills = tuple((scenario.subject,) if index == 0 and scenario.variant == "selected" else ()
                       for index in range(len(party)))
        units = build_fighters(store, content, config, party, scenario.realm, "prepared", skill_ids=skills)
        left, right = units[:len(scenario.party)], units[len(scenario.party):]
        if scenario.initial_venom:
            # A valid one-HP venom hit establishes a reproducible mid-fight cleansing opportunity.
            source = next(unit for unit in right if unit.talent and unit.talent.kind == "venom")
            lost, _ = talents.receive_damage(left[1], 1)
            talents.after_hit(source, left[1], lost)
    return left, right
