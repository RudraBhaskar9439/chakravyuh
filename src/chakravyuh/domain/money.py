"""Money value object using integer currency subunits."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Money(BaseModel):
    """An exact monetary amount; floating-point amounts are never accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_subunits: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = value.upper()
        if not currency.isalpha():
            msg = "currency must be a three-letter alphabetic code"
            raise ValueError(msg)
        return currency

    def __add__(self, other: Self) -> Self:
        if self.currency != other.currency:
            msg = "cannot add amounts in different currencies"
            raise ValueError(msg)
        return self.__class__(
            amount_subunits=self.amount_subunits + other.amount_subunits,
            currency=self.currency,
        )
