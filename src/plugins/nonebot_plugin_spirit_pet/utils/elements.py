from collections.abc import Iterable, Mapping

from ..domain.battle_content import Element


def element_ancestors(element: str, definitions: Mapping[str, Element]) -> frozenset[str]:
    """Include the element itself and each of its parent elements."""
    lineage = set()
    current: str | None = element
    while current is not None:
        if current in lineage:
            raise ValueError(f"cyclic element ancestry: {element}")
        if current not in definitions:
            raise ValueError(f"unknown element ancestor: {current}")
        lineage.add(current)
        current = definitions[current].parent
    return frozenset(lineage)


def expand_elements(elements: Iterable[str], definitions: Mapping[str, Element]) -> frozenset[str]:
    return frozenset(ancestor for element in elements for ancestor in element_ancestors(element, definitions))
