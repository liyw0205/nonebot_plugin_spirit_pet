from heapq import heappop, heappush

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


def neighbors(site: int) -> list[int]:
    row, col = divmod(site - 1, 3)
    return [r * 3 + c + 1 for r, c in ((row - 1, col), (row, col - 1),
                                       (row, col + 1), (row + 1, col))
            if 0 <= r < 3 and 0 <= c < 3]


def home_costs(costs: list[int]) -> list[int]:
    # Reverse edges: a move pays the destination's cost, including the entrance.
    distances = [10**9] * 9
    distances[0] = 0
    pending = [(0, 1)]
    while pending:
        distance, site = heappop(pending)
        if distance != distances[site - 1]:
            continue
        for adjacent in neighbors(site):
            value = distance + costs[site - 1]
            if value < distances[adjacent - 1]:
                distances[adjacent - 1] = value
                heappush(pending, (value, adjacent))
    return distances


class HerbSite(Definition):
    name: Name
    cost: int = Field(ge=1, le=3)
    item_id: Identifier | None = None
    harvest_cost: int = Field(default=1, ge=1, le=3)


class HerbRoute(Definition):
    id: Identifier
    name: Name
    description: str
    budget: int = Field(ge=8, le=16)
    sites: list[HerbSite] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def playable(self):
        if self.sites[0].item_id is not None:
            raise ValueError("herbalism entrance cannot contain a harvest")
        if len({site.name for site in self.sites}) != 9:
            raise ValueError("herbalism sites must have unique names")
        if sum(site.item_id is not None for site in self.sites) < 3:
            raise ValueError("herbalism needs at least three harvest sites")
        costs = [site.cost for site in self.sites]
        home = home_costs(costs)
        for index, site in enumerate(self.sites):
            outward = home[index] + site.cost - costs[0]
            if site.item_id and outward + site.harvest_cost + home[index] > self.budget:
                raise ValueError("herbalism harvest must allow a round trip")
        return self
