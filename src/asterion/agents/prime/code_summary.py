"""Prime-owned summary of the names a persistent kernel still defines.

A native compaction asks a model for the generic section template (Goal,
Constraints, Progress, Key Decisions, Next Steps, Critical Context). This
summary is a different record: it lists the live interfaces, and it is produced
below the token count at which Pi's own automatic compaction starts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

CODE_SUMMARY_VERSION = "asterion.prime-code-summary/v1"
# Pi's automatic compaction keeps the tail until this many tokens and then
# refuses to cut a shorter session. A preset below this value is low-threshold.
NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS = 20_000
_NATIVE_MARKERS = (
    "## Goal",
    "## Constraints & Preferences",
    "## Progress",
    "## Key Decisions",
    "## Next Steps",
    "## Critical Context",
)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_KINDS = frozenset({"class", "callable", "value"})


class CodeSummaryError(ValueError):
    def __init__(self) -> None:
        super().__init__("Prime code summary rejected")


@dataclass(frozen=True, slots=True)
class KernelBinding:
    name: str
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in _KINDS or _NAME.fullmatch(self.name) is None:
            raise CodeSummaryError()


@dataclass(frozen=True, slots=True)
class CodeAwareSummary:
    kind: str
    bindings: tuple[str, ...]
    text: str
    sha256: str
    below_native_threshold: bool


def is_native_generic_summary(text: str) -> bool:
    """A native summary uses the fixed section template. This record does not."""

    if type(text) is not str or not text:
        raise CodeSummaryError()
    return any(marker in text for marker in _NATIVE_MARKERS)


def is_dedicated_code_summary(text: object) -> bool:
    """The summary Prime itself persists, below Pi's automatic cut.

    A native Goal/Constraints template is never this record, including one that
    pastes the version line above those sections.
    """

    if type(text) is not str or not text.startswith(CODE_SUMMARY_VERSION + "\n"):
        return False
    if "\nbelow_native_threshold: true\n" not in text:
        return False
    return not is_native_generic_summary(text)


def build_code_aware_summary(
    bindings: tuple[KernelBinding, ...], *, keep_recent_tokens: int
) -> CodeAwareSummary:
    """List the live interfaces. Refuse a native template or an empty kernel."""

    if (
        type(bindings) is not tuple
        or not bindings
        or any(type(item) is not KernelBinding for item in bindings)
        or type(keep_recent_tokens) is not int
        or keep_recent_tokens < 1
    ):
        raise CodeSummaryError()
    names = tuple(item.name for item in bindings)
    if len(names) != len(set(names)):
        raise CodeSummaryError()
    below = keep_recent_tokens < NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS
    lines = [
        CODE_SUMMARY_VERSION,
        f"keep_recent_tokens: {keep_recent_tokens}",
        f"native_automatic_keep_recent_tokens: {NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS}",
        f"below_native_threshold: {str(below).lower()}",
        "interfaces:",
    ]
    lines.extend(f"- {item.kind} {item.name}" for item in bindings)
    text = "\n".join(lines) + "\n"
    if is_native_generic_summary(text) or CODE_SUMMARY_VERSION not in text:
        raise CodeSummaryError()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return CodeAwareSummary(
        CODE_SUMMARY_VERSION, names, text, digest, below
    )


__all__ = (
    "CODE_SUMMARY_VERSION",
    "NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS",
    "CodeAwareSummary",
    "CodeSummaryError",
    "KernelBinding",
    "build_code_aware_summary",
    "is_dedicated_code_summary",
    "is_native_generic_summary",
)
