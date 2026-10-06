from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .catalog import Catalog


def validate_lineages(content: "Catalog") -> None:
    profiles = defaultdict(list)
    for lineage in content.lineages.values():
        content._require([lineage.species_id], content.species, "lineage species")
        content._require([lineage.min_bloodline], content.bloodlines, "lineage bloodline")
        content._require(lineage.cost.items, content.items, "lineage cost items")
        if any(content.items[item].kind != "material" for item in lineage.cost.items):
            raise ValueError("lineage cost items must be materials")
        if not (lineage.cost.exp or lineage.cost.stones or lineage.cost.items):
            raise ValueError("lineage choice must have a cost")
        multipliers = tuple(lineage.stat_multipliers.model_dump().values())
        if max(multipliers) <= 1:
            raise ValueError("lineage must improve at least one stat")
        if multipliers in profiles[lineage.species_id]:
            raise ValueError("lineages of the same species must have distinct stat multipliers")
        profiles[lineage.species_id].append(multipliers)
    missing = [species for species in content.species if len(profiles[species]) < 2]
    if missing:
        raise ValueError(f"species require at least two lineage branches: {sorted(missing)}")
