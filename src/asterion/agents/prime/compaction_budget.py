"""Fail-closed arithmetic for reserving Prime Pi compaction work.

This module deliberately has no provider or environment dependency.  It is the
single production path used to turn the two possible compaction callbacks into
a bounded token and micro-unit-cost reservation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import sys


_ERROR = "invalid compaction reservation"
_SAFE_INTEGER_MAX = (1 << 53) - 1
_PER_MILLION = 1_000_000
_BRANCH_COUNT = 2
_INPUT_CAP_MAX = 4_096
_OUTPUT_CAP_MAX = 3_276
_RESERVED_TOKENS_MAX = 16_000
_COST_MICRO_UNITS_MAX = 125_000


def _fail() -> None:
    raise ValueError(_ERROR)


def _safe_nonnegative_integer(value: object) -> int:
    """Return an integer suitable for JSON/JavaScript exact arithmetic."""

    if type(value) is not int or value < 0 or value > _SAFE_INTEGER_MAX:
        _fail()
    return value


@dataclass(frozen=True)
class ModelPrice:
    """Operator-resolved prices in micro-units per one million tokens."""

    input_per_million: int
    output_per_million: int

    def __post_init__(self) -> None:
        _safe_nonnegative_integer(self.input_per_million)
        _safe_nonnegative_integer(self.output_per_million)


@dataclass(frozen=True)
class BranchCompactionQuote:
    input_tokens: int
    output_tokens: int
    reserved_tokens: int
    input_cost_micro_units: int
    output_cost_micro_units: int
    cost_micro_units: int


@dataclass(frozen=True)
class CompactionReservationQuote:
    reserved_tokens: int
    cost_micro_units: int
    branch_quotes: tuple[BranchCompactionQuote, BranchCompactionQuote]


def _validated_caps(caps: object, maximum: int) -> tuple[int, int]:
    if type(caps) is not tuple or len(caps) != _BRANCH_COUNT:
        _fail()
    first = _safe_nonnegative_integer(caps[0])
    second = _safe_nonnegative_integer(caps[1])
    if first > maximum or second > maximum:
        _fail()
    return first, second


def _ceil_priced_component(tokens: int, per_million: int) -> int:
    """Price one component, rounding it upward before branch aggregation."""

    return (tokens * per_million + _PER_MILLION - 1) // _PER_MILLION


def quote_compaction_reservation(
    *,
    branch_input_caps: tuple[int, int],
    branch_output_caps: tuple[int, int],
    price: ModelPrice,
) -> CompactionReservationQuote:
    """Reserve both possible compaction callbacks under fixed public bounds."""

    input_caps = _validated_caps(branch_input_caps, _INPUT_CAP_MAX)
    output_caps = _validated_caps(branch_output_caps, _OUTPUT_CAP_MAX)
    if type(price) is not ModelPrice:
        _fail()

    branch_quotes = tuple(
        BranchCompactionQuote(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reserved_tokens=input_tokens + output_tokens,
            input_cost_micro_units=_ceil_priced_component(
                input_tokens, price.input_per_million
            ),
            output_cost_micro_units=_ceil_priced_component(
                output_tokens, price.output_per_million
            ),
            cost_micro_units=(
                _ceil_priced_component(input_tokens, price.input_per_million)
                + _ceil_priced_component(output_tokens, price.output_per_million)
            ),
        )
        for input_tokens, output_tokens in zip(input_caps, output_caps, strict=True)
    )
    # The exact length is established above; this type is retained for callers.
    typed_branch_quotes = (branch_quotes[0], branch_quotes[1])
    reserved_tokens = sum(branch.reserved_tokens for branch in typed_branch_quotes)
    cost_micro_units = sum(branch.cost_micro_units for branch in typed_branch_quotes)
    if (
        reserved_tokens > _RESERVED_TOKENS_MAX
        or cost_micro_units > _COST_MICRO_UNITS_MAX
    ):
        _fail()
    return CompactionReservationQuote(
        reserved_tokens=reserved_tokens,
        cost_micro_units=cost_micro_units,
        branch_quotes=typed_branch_quotes,
    )


def _quote_from_json(payload: object) -> CompactionReservationQuote:
    if type(payload) is not dict or set(payload) != {
        "branch_input_caps",
        "branch_output_caps",
        "price",
    }:
        _fail()
    price_payload = payload["price"]
    if type(price_payload) is not dict or set(price_payload) != {
        "input_per_million",
        "output_per_million",
    }:
        _fail()
    input_caps = payload["branch_input_caps"]
    output_caps = payload["branch_output_caps"]
    if type(input_caps) is not list or type(output_caps) is not list:
        _fail()
    return quote_compaction_reservation(
        branch_input_caps=tuple(input_caps),
        branch_output_caps=tuple(output_caps),
        price=ModelPrice(**price_payload),
    )


def main() -> None:
    """Read one JSON request from stdin and write its canonical quote to stdout."""

    try:
        quote = _quote_from_json(json.load(sys.stdin))
    except (ValueError, TypeError, json.JSONDecodeError):
        # Do not turn malformed operator input into a partly useful reservation.
        raise ValueError(_ERROR) from None
    sys.stdout.write(json.dumps(asdict(quote), sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
