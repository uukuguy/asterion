"""Source-locked, game-agnostic guidance for one P7 solving session."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Final, Mapping


P7_SOLVING_PROMPT: Final = """Solve the first public visual grid level with the persistent IPython tool.
In the first cell, import only p7_client and call observe() before acting.
Analyze every frame programmatically. Track objects, colors, connected components, and differences between observations.
Choose dynamically from the available actions. Act in short exploratory batches, inspect the resulting evidence, and revise your world model when observations disagree with it.
Call status() after each batch and before deciding what to do next.
Finish immediately when terminal == "LEVEL_SOLVED". Do not issue another tool call after the completed level."""

_UPSTREAM_COMMIT: Final = "398d4dd63cf01d00adbea41c13437ba0b8ad40fc"
_LICENSE_SHA256: Final = "sha256:bf446b52c755dc80e8661ad171edbdec85d2df1307349fbf2dd2e91405166fd9"
_PROMPT_SHA256: Final = "sha256:" + sha256(P7_SOLVING_PROMPT.encode("utf-8")).hexdigest()
P7_SOLVING_GUIDANCE_LOCK: Final[Mapping[str, str]] = MappingProxyType(
    {
        "format": "asterion.prime-p7-solving-guidance-lock/v1",
        "license_sha256": _LICENSE_SHA256,
        "prompt_sha256": _PROMPT_SHA256,
        "upstream_commit": _UPSTREAM_COMMIT,
    }
)

_REQUIRED: Final = (
    "import only p7_client",
    "observe",
    "programmatically",
    "objects",
    "colors",
    "components",
    "differences",
    "short exploratory batches",
    "world model",
    "status",
    'terminal == "level_solved"',
)
_FORBIDDEN: Final = re.compile(
    r"ACTION[1-7]|ls20|9607627b|(?:^|\s)/(?:workspace|prime|tmp|users)(?:/|\s|$)",
    re.IGNORECASE,
)


class P7SolvingPromptError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving guidance is unavailable")


def validate_p7_solving_prompt(value: object) -> None:
    """Require the one locked prompt and its canonical source identity."""

    if type(value) is not str:
        raise P7SolvingPromptError()
    lowered = value.lower()
    lock = dict(P7_SOLVING_GUIDANCE_LOCK)
    canonical_lock = json.dumps(
        lock, allow_nan=False, separators=(",", ":"), sort_keys=True
    )
    if (
        value != P7_SOLVING_PROMPT
        or any(item not in lowered for item in _REQUIRED)
        or _FORBIDDEN.search(value) is not None
        or lock.get("prompt_sha256")
        != "sha256:" + sha256(value.encode("utf-8")).hexdigest()
        or json.loads(canonical_lock) != lock
    ):
        raise P7SolvingPromptError()


__all__ = (
    "P7_SOLVING_GUIDANCE_LOCK",
    "P7_SOLVING_PROMPT",
    "P7SolvingPromptError",
    "validate_p7_solving_prompt",
)
