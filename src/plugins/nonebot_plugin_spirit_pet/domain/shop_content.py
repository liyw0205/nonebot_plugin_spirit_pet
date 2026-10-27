from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier


class ShopOffer(Definition):
    """One daily featured shop entry: a real item, a discount and a stock cap."""

    id: Identifier
    item: Identifier
    discount: Annotated[int, Field(ge=1, le=50)]
    stock: Annotated[int, Field(ge=1, le=9)]
