"""Shared canonical ordering for protocol string arrays."""

from __future__ import annotations


def is_unicode_scalar_string(value: str) -> bool:
    """Return whether every character is a Unicode scalar value."""

    return all(not 0xD800 <= ord(character) <= 0xDFFF for character in value)


def is_sorted_unique_scalar_strings(values: list[str]) -> bool:
    """Check strict lexicographic Unicode scalar-value ordering."""

    return all(is_unicode_scalar_string(value) for value in values) and all(
        previous < current for previous, current in zip(values, values[1:])
    )
