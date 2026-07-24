"""Closed paper-aligned DCI live context-profile contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Mapping

if TYPE_CHECKING:
    from asterion.dci.context_extension import ResolvedContextExtension


CONTEXT_PROFILE_CONTRACT_VERSION = "dci.context-profile/v1"
ContextProfileName = Literal["level0", "level1", "level2", "level3", "level4"]

_PROFILE_NAMES: tuple[ContextProfileName, ...] = (
    "level0",
    "level1",
    "level2",
    "level3",
    "level4",
)
_IDENTITY_FIELDS = {
    "profile",
    "contract_version",
    "tool_result_character_cap",
    "compaction_character_trigger",
    "retained_turns",
    "summary_recent_token_target",
    "summary_failure_limit",
}
_EXPECTED_SETTINGS: Mapping[
    ContextProfileName, tuple[int | None, int | None, int | None, int | None, int | None]
] = MappingProxyType(
    {
        "level0": (None, None, None, None, None),
        "level1": (50_000, None, None, None, None),
        "level2": (20_000, None, None, None, None),
        "level3": (20_000, 240_000, 12, None, None),
        "level4": (20_000, 240_000, 12, 20_000, 3),
    }
)


@dataclass(frozen=True)
class DciContextProfile:
    """Immutable settings for one exact paper context-management profile."""

    name: ContextProfileName
    contract_version: str
    tool_result_character_cap: int | None
    compaction_character_trigger: int | None
    retained_turns: int | None
    summary_recent_token_target: int | None
    summary_failure_limit: int | None

    def identity_payload(self) -> dict[str, object]:
        """Return the complete behavior-affecting profile identity."""

        return {
            "profile": self.name,
            "contract_version": self.contract_version,
            "tool_result_character_cap": self.tool_result_character_cap,
            "compaction_character_trigger": self.compaction_character_trigger,
            "retained_turns": self.retained_turns,
            "summary_recent_token_target": self.summary_recent_token_target,
            "summary_failure_limit": self.summary_failure_limit,
        }


def context_profile_names() -> tuple[ContextProfileName, ...]:
    """Return the closed set of supported paper profile names."""

    _profiles()
    return _PROFILE_NAMES


def resolve_context_profile(value: object) -> DciContextProfile | None:
    """Resolve one exact profile name or reject aliases and unknown values."""

    if value is None:
        return None
    if not isinstance(value, str) or value not in _PROFILE_NAMES:
        raise ValueError("DCI context profile is invalid")
    return _profiles()[value]


def context_policy_identity(
    profile: DciContextProfile,
    extension: ResolvedContextExtension,
) -> dict[str, object]:
    """Bind one canonical profile to the exact shipped extension implementation."""

    if (
        extension.contract_version != profile.contract_version
        or not extension.version
        or re.fullmatch(r"[0-9a-f]{64}", extension.sha256) is None
    ):
        raise ValueError("DCI context policy identity is invalid")
    return {
        "schema": "dci.context-policy-identity/v1",
        "status": "effective",
        "profile": profile.identity_payload(),
        "extension_version": extension.version,
        "extension_sha256": extension.sha256,
    }


@lru_cache(maxsize=1)
def _profiles() -> Mapping[ContextProfileName, DciContextProfile]:
    try:
        raw = resources.files("asterion.dci.resources").joinpath(
            "context-profiles.json"
        ).read_text(encoding="utf-8")
        payload = json.loads(raw)
        profiles_payload = payload["profiles"]
    except (KeyError, OSError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("DCI context profile contract is invalid") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "profiles"}
        or payload.get("schema") != CONTEXT_PROFILE_CONTRACT_VERSION
        or not isinstance(profiles_payload, dict)
        or tuple(profiles_payload) != _PROFILE_NAMES
    ):
        raise RuntimeError("DCI context profile contract is invalid")

    parsed: dict[ContextProfileName, DciContextProfile] = {}
    for name in _PROFILE_NAMES:
        value = profiles_payload.get(name)
        if not isinstance(value, dict) or set(value) != _IDENTITY_FIELDS:
            raise RuntimeError("DCI context profile contract is invalid")
        expected = _EXPECTED_SETTINGS[name]
        actual = (
            value.get("tool_result_character_cap"),
            value.get("compaction_character_trigger"),
            value.get("retained_turns"),
            value.get("summary_recent_token_target"),
            value.get("summary_failure_limit"),
        )
        if (
            value.get("profile") != name
            or value.get("contract_version") != CONTEXT_PROFILE_CONTRACT_VERSION
            or actual != expected
            or any(
                item is not None
                and (isinstance(item, bool) or not isinstance(item, int) or item <= 0)
                for item in actual
            )
        ):
            raise RuntimeError("DCI context profile contract is invalid")
        parsed[name] = DciContextProfile(
            name=name,
            contract_version=CONTEXT_PROFILE_CONTRACT_VERSION,
            tool_result_character_cap=expected[0],
            compaction_character_trigger=expected[1],
            retained_turns=expected[2],
            summary_recent_token_target=expected[3],
            summary_failure_limit=expected[4],
        )
    return MappingProxyType(parsed)
