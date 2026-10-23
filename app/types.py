"""Exact decimal storage. Money is stored as integer paise, quantities as
integer thousandths, percentages as basis points. No floating-point drift."""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator


class _Scaled(TypeDecorator):
    impl = BigInteger
    cache_ok = True
    scale = 100
    places = Decimal("0.01")

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int((Decimal(str(value)) * self.scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(int(value)) / self.scale).quantize(self.places)


class Money(_Scaled):
    cache_ok = True
    scale = 100
    places = Decimal("0.01")


class Qty(_Scaled):
    cache_ok = True
    scale = 1000
    places = Decimal("0.001")


class Percent(_Scaled):
    cache_ok = True
    scale = 100
    places = Decimal("0.01")


def d(value, places="0.01") -> Decimal:
    """Parse anything to a rounded Decimal."""
    if value is None or value == "":
        return Decimal("0").quantize(Decimal(places))
    return Decimal(str(value).strip().replace(",", "")).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def money(value) -> str:
    return str(d(value, "0.01"))


def qty(value) -> str:
    v = d(value, "0.001")
    s = format(v.normalize(), "f")
    return s
