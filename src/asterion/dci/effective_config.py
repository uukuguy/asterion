"""Credential- and body-free effective configuration evidence for Asterion DCI."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from asterion.dci.config import AsterionRuntimeConfig, ValueSource


SCHEMA = "dci.effective-config/v1"
PRODUCT = "asterion-dci"
SCHEMA_PATH = Path(__file__).with_name("resources") / "effective-config.schema.json"
_UNSAFE_KEY = re.compile(
    r"(^|_)(api_?key|credential|secret|token|password|prompt|answer|body|path|dir)($|_)",
    re.IGNORECASE,
)
_BODY_FREE_DIGEST_FIELDS = {"request_shape_sha256", "prompt_contract_sha256"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _safe_mapping(value: Mapping[str, object], *, location: str) -> dict[str, object]:
    cloned = json.loads(json.dumps(dict(value), ensure_ascii=False))

    def validate(item: object, path: str) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in _BODY_FREE_DIGEST_FIELDS:
                    if (
                        path != "judge"
                        or not isinstance(nested, str)
                        or _SHA256.fullmatch(nested) is None
                    ):
                        raise ValueError(
                            f"unsafe effective configuration field at {path}.{key}"
                        )
                elif key == "judge_api_key_env":
                    if (
                        path != "judge"
                        or not isinstance(nested, str)
                        or _ENVIRONMENT_NAME.fullmatch(nested) is None
                    ):
                        raise ValueError(
                            f"unsafe effective configuration field at {path}.{key}"
                        )
                elif _UNSAFE_KEY.search(str(key)):
                    raise ValueError(f"unsafe effective configuration field at {path}.{key}")
                if key == "endpoint" and isinstance(nested, str):
                    _validate_safe_endpoint(nested, path=f"{path}.{key}")
                validate(nested, f"{path}.{key}")
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                validate(nested, f"{path}[{index}]")
        elif isinstance(item, str) and item.startswith(("/", "~/")):
            raise ValueError(f"unsafe absolute/private path at {path}")

    validate(cloned, location)
    return cloned


def _validate_safe_endpoint(value: str, *, path: str) -> None:
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as error:
        raise ValueError(f"unsafe judge endpoint at {path}") from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"unsafe judge endpoint at {path}")


def _matches_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ValueError("effective configuration schema uses an unsupported type")


def _validate_schema(value: object, schema: Mapping[str, object], *, path: str) -> None:
    declared = schema.get("type")
    if declared is not None:
        types = [declared] if isinstance(declared, str) else declared
        if not isinstance(types, list) or not all(isinstance(item, str) for item in types):
            raise ValueError("effective configuration schema has an invalid type")
        if not any(_matches_type(value, item) for item in types):
            raise ValueError(f"effective configuration schema rejected {path}: invalid type")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"effective configuration schema rejected {path}: const mismatch")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or value not in enum):
        raise ValueError(f"effective configuration schema rejected {path}: invalid value")

    if isinstance(value, dict):
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            raise ValueError("effective configuration schema is invalid")
        missing = set(required) - value.keys()
        if missing:
            raise ValueError(f"effective configuration schema rejected {path}: missing")
        additional = schema.get("additionalProperties", True)
        for key, nested in value.items():
            child = properties.get(key)
            if child is None:
                if additional is False:
                    raise ValueError(
                        f"effective configuration schema rejected {path}: unknown field"
                    )
                child = additional if isinstance(additional, dict) else None
            if child is not None:
                if not isinstance(child, dict):
                    raise ValueError("effective configuration schema is invalid")
                _validate_schema(nested, child, path=f"{path}.{key}")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        pattern = schema.get("pattern")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise ValueError(f"effective configuration schema rejected {path}: too short")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ValueError(f"effective configuration schema rejected {path}: pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        exclusive = schema.get("exclusiveMinimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ValueError(f"effective configuration schema rejected {path}: minimum")
        if isinstance(exclusive, (int, float)) and value <= exclusive:
            raise ValueError(
                f"effective configuration schema rejected {path}: exclusive minimum"
            )


def validate_effective_config(value: Mapping[str, object]) -> None:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("effective configuration schema could not be loaded") from error
    if not isinstance(schema, dict):
        raise ValueError("effective configuration schema must be an object")
    _validate_schema(dict(value), schema, path="effective-config")


@dataclass(frozen=True)
class AsterionEffectiveConfig:
    runtime: AsterionRuntimeConfig
    context: Mapping[str, object] = field(default_factory=dict)
    judge: Mapping[str, object] = field(default_factory=dict)
    experiment: Mapping[str, object] = field(default_factory=dict)
    sources: Mapping[str, ValueSource] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, object]:
        agent: dict[str, object] = {
            "provider": self.runtime.provider,
            "model": self.runtime.model,
            "reasoning": self.runtime.thinking_level,
            "tools": self.runtime.tools,
            "max_turns": self.runtime.max_turns,
            "timeout_seconds": self.runtime.timeout_seconds,
        }
        if self.runtime.runtime == "claude-code":
            agent["authentication_mode"] = self.runtime.authentication_mode
        source_values = dict(self.runtime.sources)
        source_values.update(self.sources)
        projection: dict[str, object] = {
            "schema": SCHEMA,
            "product": PRODUCT,
            "runtime": self.runtime.runtime,
            "agent": _safe_mapping(agent, location="agent"),
            "context": _safe_mapping(self.context, location="context"),
            "judge": _safe_mapping(self.judge, location="judge"),
            "experiment": _safe_mapping(self.experiment, location="experiment"),
            "sources": _safe_mapping(source_values, location="sources"),
        }
        projection["identity_sha256"] = hashlib.sha256(
            _canonical_bytes(projection)
        ).hexdigest()
        validate_effective_config(projection)
        return projection
