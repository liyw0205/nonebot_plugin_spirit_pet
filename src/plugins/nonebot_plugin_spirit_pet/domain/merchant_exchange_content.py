from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, Positive


class MerchantOffer(Definition):
    """One weekly reputation exchange on the merchant board.

    ``cost_rep`` is paid from the spendable balance (lifetime reputation minus
    already spent reputation), so exchanging never lowers the offer gates.
    """

    id: Identifier
    name: Name
    description: str
    cost_rep: Positive
    item: Identifier
    amount: Annotated[int, Field(ge=1, le=99)]
    weekly_limit: Annotated[int, Field(ge=1, le=20)]
