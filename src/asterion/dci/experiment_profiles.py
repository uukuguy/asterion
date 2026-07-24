"""Immutable AF-340 experiment identities and full-execution authorization."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from asterion.dci.paper_benchmarks import (
    canonical_sha256,
    paper_benchmark_inventory_sha256,
    paper_experiment_scope_ids,
    paper_experiment_scopes_sha256,
    resolve_paper_experiment_scope,
)

EXPERIMENT_PROFILE_SCHEMA = "dci.experiment-profiles/v1"
EXPERIMENT_AUTHORIZATION_SCHEMA = "asterion.dci.paper-full-authorization/v1"
EXPERIMENT_PROFILE_SCHEMA_SHA256 = (
    "d51246204504cabc348c5f35b5bfe3e13c7519aa4bc78c55cb2be7f49e71fb06"
)
_PROFILE_IDS = (
    "current-default/pi",
    "current-default/claude-subscription",
    "current-default/claude-minimax",
    "paper-reference/pi",
    "paper-reference/claude-code",
)
_PUBLIC_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*")
_EXPECTED_PROFILE_SEMANTICS = {
    "current-default/pi": ("pi", "openai-codex", "gpt-5.6-luna", "saved-auth-or-provider-key", None, "read,bash", 100, "deepseek-v4-flash"),
    "current-default/claude-subscription": ("claude-code", None, None, "local-subscription", None, "read,grep", 100, "deepseek-v4-flash"),
    "current-default/claude-minimax": ("claude-code", None, None, "invocation-minimax-coding-plan", None, "read,grep", 100, "deepseek-v4-flash"),
    "paper-reference/pi": ("pi", "openai", "gpt-5.4-nano", "saved-auth-or-provider-key", "high", "read,bash", 300, "gpt-4.1"),
    "paper-reference/claude-code": ("claude-code", None, "claude-sonnet-4-6", "local-subscription", "medium", "read,grep", 300, "gpt-4.1"),
}
_CURRENT_JUDGE = {
    "base_url": "https://api.deepseek.com/v1", "api": "chat-completions",
    "model": "deepseek-v4-flash", "key_source": "DEEPSEEK_API_KEY",
    "thinking": False, "json_object": True,
    "request_shape_sha256": "b235c27019598e623db3a0ec4a76f847dac52f9581bc1a1acc8e4324b3d56db8",
    "output_shape_identity": "json-object/v1",
    "prompt_contract": "dci.answer-judge/v1",
    "prompt_contract_sha256": "4d05c3ff588df3b0d60c1547ba6aa5014c5737cf79500022fed66fe8fd92fcb0",
    "pricing_identity": "usd-per-1m/input=0,cached=0,output=0/runtime-default",
}
_PAPER_JUDGE = {
    "base_url": "https://api.openai.com/v1", "api": "responses",
    "model": "gpt-4.1", "key_source": "OPENAI_API_KEY",
    "thinking": False, "json_object": True,
    "request_shape_sha256": "6b12b487bfde0bb179f900c10ec762daa122726883a534d80c95d954c004d093",
    "output_shape_identity": "json-schema/strict/v1",
    "prompt_contract": "dci.paper-answer-judge/gpt-4.1/v1",
    "prompt_contract_sha256": "883c0cbbc76c73ed265d956092cac08e9d35fc0191f1ad2fb73a1ec28b7339c9",
    "pricing_identity": "paper-unreported",
}


@dataclass(frozen=True, slots=True)
class ExperimentProfile:
    profile_id: str
    runtime: str
    provider: str | None
    model: str | None
    authentication_mode: str
    reasoning: str | None
    tools: str
    max_turns: int
    context_profile: str
    judge: Mapping[str, object]
    dataset_inventory_sha256: str
    experiment_scopes_sha256: str
    scope_ids: tuple[str, ...]
    selected_ids_sha256: tuple[str, ...]
    paper_unreported_scope_ids: tuple[str, ...]
    corpus_identity: str
    metric_identities: tuple[str, ...]
    aggregation_identity: str
    comparison: Mapping[str, object]
    compatible_config_key: str | None

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_canonical_dict())

    @property
    def paper_scope_ids(self) -> tuple[str, ...]:
        return self.scope_ids

    @property
    def paper_scope_dataset_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    resolve_paper_experiment_scope(scope_id).dataset_id
                    for scope_id in self.scope_ids
                }
            )
        )

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "runtime": self.runtime,
            "provider": self.provider,
            "model": self.model,
            "authentication_mode": self.authentication_mode,
            "reasoning": self.reasoning,
            "tools": self.tools,
            "max_turns": self.max_turns,
            "context_profile": self.context_profile,
            "judge": dict(self.judge),
            "dataset_inventory_sha256": self.dataset_inventory_sha256,
            "experiment_scopes_sha256": self.experiment_scopes_sha256,
            "scope_ids": list(self.scope_ids),
            "selected_ids_sha256": list(self.selected_ids_sha256),
            "paper_unreported_scope_ids": list(self.paper_unreported_scope_ids),
            "corpus_identity": self.corpus_identity,
            "metric_identities": list(self.metric_identities),
            "aggregation_identity": self.aggregation_identity,
            "comparison": dict(self.comparison),
            "compatible_config_key": self.compatible_config_key,
        }


@dataclass(frozen=True, slots=True, init=False)
class FullExecutionAuthorization:
    profile_id: str
    profile_sha256: str
    dataset_inventory_sha256: str
    experiment_scopes_sha256: str
    authorized_scope_ids: tuple[str, ...]
    selected_ids_sha256: tuple[str, ...]
    output_root: Path
    output_root_device: int
    output_root_inode: int
    estimated_budget_usd: float
    invocation_authorized: bool
    _issuance_token: str = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("FullExecutionAuthorization is issued only by authorize_full_execution")


@dataclass(frozen=True, slots=True)
class _AuthorizationSnapshot:
    profile_id: str
    profile_sha256: str
    dataset_inventory_sha256: str
    experiment_scopes_sha256: str
    authorized_scope_ids: tuple[str, ...]
    selected_ids_sha256: tuple[str, ...]
    scope_selections: tuple[tuple[str, str], ...]
    output_root: Path
    output_root_device: int
    output_root_inode: int
    estimated_budget_usd: float
    invocation_authorized: bool
    issuance_token: str


@dataclass(slots=True)
class _AuthorizationRecord:
    issuer: FullExecutionAuthorization
    snapshot: _AuthorizationSnapshot
    consumed_scopes: set[str]


_AUTHORIZATION_REGISTRY: dict[str, _AuthorizationRecord] = {}
_AUTHORIZATION_LOCK = threading.Lock()


def _validate_profile_schema(schema: object, fields: set[str]) -> None:
    try:
        profile = schema["$defs"]["profile"]  # type: ignore[index]
        properties = profile["properties"]
        judge = properties["judge"]
        comparison = properties["comparison"]
    except (KeyError, TypeError):
        raise RuntimeError("DCI experiment profile contract is invalid") from None
    if (
        type(schema) is not dict
        or set(schema)
        != {"$schema", "$id", "type", "additionalProperties", "required", "properties", "$defs"}
        or schema.get("$id") != EXPERIMENT_PROFILE_SCHEMA
        or canonical_sha256(schema) != EXPERIMENT_PROFILE_SCHEMA_SHA256
        or schema.get("additionalProperties") is not False
        or type(profile) is not dict
        or profile.get("additionalProperties") is not False
        or set(profile.get("required", ())) != fields
        or set(properties) != fields
        or judge.get("additionalProperties") is not False
        or set(judge.get("required", ())) != set(_CURRENT_JUDGE)
        or set(judge.get("properties", {})) != set(_CURRENT_JUDGE)
        or comparison.get("additionalProperties") is not False
        or set(comparison.get("properties", {}))
        != {"accuracy_margin", "ndcg_margin", "published_target", "target_identity"}
        or type(comparison.get("oneOf")) is not list
        or len(comparison["oneOf"]) != 3
    ):
        raise RuntimeError("DCI experiment profile contract is invalid")


def _validate_body_free_profile(profile: ExperimentProfile) -> None:
    forbidden = {"api_key", "credential", "prompt_body", "answer", "private_path", "tool_body"}

    def walk(value: object) -> None:
        if isinstance(value, Mapping):
            if any(key in forbidden for key in value):
                raise RuntimeError("DCI experiment profile contract is invalid")
            for item in value.values():
                walk(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                walk(item)

    walk(profile.to_canonical_dict())


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


@lru_cache(maxsize=1)
def _profiles() -> Mapping[str, ExperimentProfile]:
    try:
        package = resources.files("asterion.dci.resources")
        payload = json.loads(package.joinpath("experiment-profiles.json").read_text(), object_pairs_hook=_unique_object)
        schema = json.loads(package.joinpath("experiment-profile.schema.json").read_text(), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError):
        raise RuntimeError("DCI experiment profile contract is invalid") from None
    if (type(payload) is not dict or set(payload) != {"schema", "profiles"}
            or payload.get("schema") != EXPERIMENT_PROFILE_SCHEMA
            or type(payload.get("profiles")) is not list
            or type(schema) is not dict):
        raise RuntimeError("DCI experiment profile contract is invalid")

    scope_ids = paper_experiment_scope_ids()
    selected = tuple(resolve_paper_experiment_scope(scope_id).selected_ids_sha256 for scope_id in scope_ids)
    unreported = tuple(scope_id for scope_id in scope_ids if resolve_paper_experiment_scope(scope_id).selection_seed_status == "paper-unreported")
    fields = {"profile_id", "runtime", "provider", "model", "authentication_mode", "reasoning", "tools", "max_turns", "context_profile", "judge", "dataset_inventory_sha256", "experiment_scopes_sha256", "scope_ids", "selected_ids_sha256", "paper_unreported_scope_ids", "corpus_identity", "metric_identities", "aggregation_identity", "comparison", "compatible_config_key"}
    _validate_profile_schema(schema, fields)
    parsed: dict[str, ExperimentProfile] = {}
    for item in payload["profiles"]:
        if type(item) is not dict or set(item) != fields:
            raise RuntimeError("DCI experiment profile contract is invalid")
        profile_id, judge = item["profile_id"], item["judge"]
        if (type(profile_id) is not str or profile_id in parsed or type(judge) is not dict
                or item["dataset_inventory_sha256"] != paper_benchmark_inventory_sha256()
                or item["experiment_scopes_sha256"] != paper_experiment_scopes_sha256()
                or item["scope_ids"] != list(scope_ids)
                or item["selected_ids_sha256"] != list(selected)
                or item["paper_unreported_scope_ids"] != list(unreported)
                or type(item["max_turns"]) is not int or item["max_turns"] <= 0
                or item["context_profile"] != "level3"):
            raise RuntimeError("DCI experiment profile contract is invalid")
        parsed[profile_id] = ExperimentProfile(
            profile_id=profile_id, runtime=item["runtime"], provider=item["provider"], model=item["model"],
            authentication_mode=item["authentication_mode"], reasoning=item["reasoning"], tools=item["tools"],
            max_turns=item["max_turns"], context_profile=item["context_profile"], judge=MappingProxyType(dict(judge)),
            dataset_inventory_sha256=item["dataset_inventory_sha256"], experiment_scopes_sha256=item["experiment_scopes_sha256"],
            scope_ids=scope_ids, selected_ids_sha256=selected, paper_unreported_scope_ids=unreported,
            corpus_identity=item["corpus_identity"], metric_identities=tuple(item["metric_identities"]),
            aggregation_identity=item["aggregation_identity"], comparison=MappingProxyType(dict(item["comparison"])),
            compatible_config_key=item["compatible_config_key"],
        )
    if tuple(parsed) != _PROFILE_IDS:
        raise RuntimeError("DCI experiment profile contract is invalid")
    for name, expected in _EXPECTED_PROFILE_SEMANTICS.items():
        profile = parsed[name]
        actual = (
            profile.runtime, profile.provider, profile.model,
            profile.authentication_mode, profile.reasoning, profile.tools,
            profile.max_turns, profile.judge.get("model"),
        )
        if actual != expected:
            raise RuntimeError("DCI experiment profile contract is invalid")
        expected_judge = _PAPER_JUDGE if name.startswith("paper-reference/") else _CURRENT_JUDGE
        expected_comparison = {
            "current-default/pi": {"accuracy_margin": -0.05, "ndcg_margin": -0.02},
            "current-default/claude-subscription": {"target_identity": "current-default/claude-subscription"},
            "current-default/claude-minimax": {"target_identity": "current-default/claude-minimax"},
            "paper-reference/pi": {"accuracy_margin": -0.05, "ndcg_margin": -0.02, "published_target": "DCI-Agent-Lite"},
            "paper-reference/claude-code": {"published_target": "DCI-Agent-CC"},
        }[name]
        if (
            dict(profile.judge) != expected_judge
            or profile.corpus_identity != "dci.paper-corpora/af-320-v1"
            or profile.metric_identities
            != ("llm-answer-correctness", "ndcg@10-binary-deduplicated")
            or profile.aggregation_identity
            != "dci.paper-aggregation/query-preserving/v1"
            or dict(profile.comparison) != expected_comparison
            or profile.compatible_config_key is not None
        ):
            raise RuntimeError("DCI experiment profile contract is invalid")
        _validate_body_free_profile(profile)
    return MappingProxyType(parsed)


def experiment_profile_ids() -> tuple[str, ...]:
    return tuple(_profiles())


def experiment_profile_schema_sha256() -> str:
    return EXPERIMENT_PROFILE_SCHEMA_SHA256


def experiment_profiles_sha256() -> str:
    return canonical_sha256(
        {
            "schema": EXPERIMENT_PROFILE_SCHEMA,
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "identity_sha256": profile.identity_sha256,
                }
                for profile in _profiles().values()
            ],
        }
    )


def resolve_experiment_profile(profile_id: object, *, invocation_provider: str | None = None, invocation_model: str | None = None) -> ExperimentProfile:
    if type(profile_id) is not str or profile_id not in _profiles():
        raise ValueError("DCI experiment profile is invalid")
    profile = _profiles()[profile_id]
    if profile_id != "current-default/claude-minimax":
        if invocation_provider is not None or invocation_model is not None:
            raise ValueError("DCI experiment profile invocation identity is invalid")
        return profile
    if invocation_provider not in {"minimax", "minimax-cn"} or type(invocation_model) is not str or _PUBLIC_IDENTITY.fullmatch(invocation_model) is None:
        raise ValueError("DCI MiniMax invocation identity is required")
    compatible_config_key = (
        "MINIMAX_API_KEY" if invocation_provider == "minimax" else "MINIMAX_CN_API_KEY"
    )
    return replace(
        profile,
        provider=invocation_provider,
        model=invocation_model,
        compatible_config_key=compatible_config_key,
    )


def experiment_profile_sha256(profile_id: str, *, invocation_provider: str | None = None, invocation_model: str | None = None) -> str:
    profile = resolve_experiment_profile(profile_id, invocation_provider=invocation_provider, invocation_model=invocation_model)
    return canonical_sha256(profile.to_canonical_dict())


def _fresh_private_output_root(output_root: Path) -> Path:
    requested = Path(os.path.abspath(os.path.normpath(Path(output_root).expanduser())))
    if requested.is_symlink():
        raise ValueError("DCI full output root must not be a symlink")
    absolute = requested.parent.resolve() / requested.name
    if absolute.exists():
        raise ValueError("DCI full output root must be fresh")
    absolute.mkdir(parents=True, mode=0o700)
    absolute.chmod(0o700)
    if stat.S_IMODE(absolute.stat().st_mode) != 0o700:
        raise ValueError("DCI full output root must be private")
    return absolute


def _private_root_identity(output_root: Path) -> tuple[int, int]:
    try:
        metadata = output_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("DCI full execution output root identity is invalid")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ValueError("DCI full execution output root permissions changed")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(output_root, flags)
        try:
            opened = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise ValueError("DCI full execution output root identity is invalid") from None
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise ValueError("DCI full execution output root identity changed")
    return metadata.st_dev, metadata.st_ino


def _issue_authorization(**values: object) -> FullExecutionAuthorization:
    authorization = object.__new__(FullExecutionAuthorization)
    for name, value in values.items():
        object.__setattr__(authorization, name, value)
    return authorization


def _authorization_matches_snapshot(
    authorization: FullExecutionAuthorization, snapshot: _AuthorizationSnapshot
) -> bool:
    return (
        authorization.profile_id == snapshot.profile_id
        and authorization.profile_sha256 == snapshot.profile_sha256
        and authorization.dataset_inventory_sha256
        == snapshot.dataset_inventory_sha256
        and authorization.experiment_scopes_sha256
        == snapshot.experiment_scopes_sha256
        and authorization.authorized_scope_ids == snapshot.authorized_scope_ids
        and authorization.selected_ids_sha256 == snapshot.selected_ids_sha256
        and tuple(
            zip(
                authorization.authorized_scope_ids,
                authorization.selected_ids_sha256,
                strict=True,
            )
        )
        == snapshot.scope_selections
        and authorization.output_root == snapshot.output_root
        and authorization.output_root_device == snapshot.output_root_device
        and authorization.output_root_inode == snapshot.output_root_inode
        and authorization.estimated_budget_usd == snapshot.estimated_budget_usd
        and authorization.invocation_authorized is snapshot.invocation_authorized
        and authorization._issuance_token == snapshot.issuance_token
    )


def authorize_full_execution(
    profile_id: str,
    output_root: Path,
    estimated_budget_usd: float,
    invocation_authorized: bool,
    *,
    preflight_profile_sha256: str,
    preflight_dataset_inventory_sha256: str,
    preflight_experiment_scopes_sha256: str,
    preflight_scope_ids: Sequence[str],
    preflight_selected_ids_sha256: Sequence[str],
    invocation_provider: str | None = None,
    invocation_model: str | None = None,
    cache_only: bool = False,
) -> FullExecutionAuthorization:
    profile = resolve_experiment_profile(profile_id, invocation_provider=invocation_provider, invocation_model=invocation_model)
    profile_sha256 = experiment_profile_sha256(
        profile_id,
        invocation_provider=invocation_provider,
        invocation_model=invocation_model,
    )
    if invocation_authorized is not True:
        raise ValueError("DCI full execution requires invocation authorization")
    if isinstance(estimated_budget_usd, bool) or not isinstance(estimated_budget_usd, (int, float)) or not math.isfinite(float(estimated_budget_usd)) or float(estimated_budget_usd) < 0:
        raise ValueError("DCI full execution budget is invalid")
    if cache_only:
        raise ValueError("DCI full execution cannot be authorized by cache evidence")
    scope_ids = tuple(preflight_scope_ids)
    selected_digests = tuple(preflight_selected_ids_sha256)
    expected = dict(zip(profile.scope_ids, profile.selected_ids_sha256, strict=True))
    if (
        preflight_profile_sha256 != profile_sha256
        or preflight_dataset_inventory_sha256 != profile.dataset_inventory_sha256
        or preflight_experiment_scopes_sha256 != profile.experiment_scopes_sha256
        or not scope_ids
        or len(scope_ids) != len(set(scope_ids))
        or len(scope_ids) != len(selected_digests)
        or any(expected.get(scope_id) != digest for scope_id, digest in zip(scope_ids, selected_digests, strict=True))
    ):
        raise ValueError("DCI full execution preflight identity mismatch")
    private_root = _fresh_private_output_root(output_root)
    device, inode = _private_root_identity(private_root)
    token = secrets.token_hex(32)
    authorization = _issue_authorization(
        profile_id=profile.profile_id,
        profile_sha256=profile_sha256,
        dataset_inventory_sha256=profile.dataset_inventory_sha256,
        experiment_scopes_sha256=profile.experiment_scopes_sha256,
        authorized_scope_ids=scope_ids,
        selected_ids_sha256=selected_digests,
        output_root=private_root,
        output_root_device=device,
        output_root_inode=inode,
        estimated_budget_usd=float(estimated_budget_usd),
        invocation_authorized=True,
        _issuance_token=token,
    )
    snapshot = _AuthorizationSnapshot(
        profile_id=profile.profile_id,
        profile_sha256=profile_sha256,
        dataset_inventory_sha256=profile.dataset_inventory_sha256,
        experiment_scopes_sha256=profile.experiment_scopes_sha256,
        authorized_scope_ids=scope_ids,
        selected_ids_sha256=selected_digests,
        scope_selections=tuple(zip(scope_ids, selected_digests, strict=True)),
        output_root=private_root,
        output_root_device=device,
        output_root_inode=inode,
        estimated_budget_usd=float(estimated_budget_usd),
        invocation_authorized=True,
        issuance_token=token,
    )
    with _AUTHORIZATION_LOCK:
        _AUTHORIZATION_REGISTRY[token] = _AuthorizationRecord(
            authorization, snapshot, set()
        )
    return authorization


def consume_full_execution_authorization(
    authorization: FullExecutionAuthorization, scope_id: str
) -> None:
    """Consume one exact scope capability after revalidating its private root."""

    if not isinstance(authorization, FullExecutionAuthorization):
        raise ValueError("DCI full execution authorization is invalid")
    token = getattr(authorization, "_issuance_token", None)
    with _AUTHORIZATION_LOCK:
        record = _AUTHORIZATION_REGISTRY.get(token)
        if (
            record is None
            or record.issuer is not authorization
            or not _authorization_matches_snapshot(authorization, record.snapshot)
        ):
            raise ValueError("DCI full execution authorization is invalid")
        issued = record.snapshot
        if (
            issued.invocation_authorized is not True
            or scope_id not in issued.authorized_scope_ids
            or issued.dataset_inventory_sha256 != paper_benchmark_inventory_sha256()
            or issued.experiment_scopes_sha256 != paper_experiment_scopes_sha256()
            or not math.isfinite(issued.estimated_budget_usd)
            or issued.estimated_budget_usd < 0
        ):
            raise ValueError("DCI full execution authorization scope is invalid")
        if scope_id in record.consumed_scopes:
            raise ValueError("DCI full execution authorization replay is invalid")
        device, inode = _private_root_identity(issued.output_root)
        if (device, inode) != (issued.output_root_device, issued.output_root_inode):
            raise ValueError("DCI full execution output root identity changed")
        record.consumed_scopes.add(scope_id)


def _consumed_authorized_output_identity(
    authorization: FullExecutionAuthorization,
) -> tuple[Path, int, int]:
    """Return an independent root identity only after exact capability consumption."""

    if not isinstance(authorization, FullExecutionAuthorization):
        raise ValueError("DCI full execution authorization is invalid")
    token = getattr(authorization, "_issuance_token", None)
    with _AUTHORIZATION_LOCK:
        record = _AUTHORIZATION_REGISTRY.get(token)
        if (
            record is None
            or not record.consumed_scopes
            or record.issuer is not authorization
            or not _authorization_matches_snapshot(authorization, record.snapshot)
        ):
            raise ValueError("DCI full execution authorization is invalid")
        snapshot = record.snapshot
        return (
            snapshot.output_root,
            snapshot.output_root_device,
            snapshot.output_root_inode,
        )


def consumed_full_execution_authorization_snapshot(
    authorization: FullExecutionAuthorization,
) -> dict[str, object]:
    """Return a durable body-free receipt only after every issued scope was consumed."""

    if not isinstance(authorization, FullExecutionAuthorization):
        raise ValueError("DCI full execution authorization is invalid")
    token = getattr(authorization, "_issuance_token", None)
    with _AUTHORIZATION_LOCK:
        record = _AUTHORIZATION_REGISTRY.get(token)
        if (
            record is None
            or record.issuer is not authorization
            or not _authorization_matches_snapshot(authorization, record.snapshot)
            or record.consumed_scopes != set(record.snapshot.authorized_scope_ids)
        ):
            raise ValueError("DCI full execution authorization is not fully consumed")
        snapshot = record.snapshot
        device, inode = _private_root_identity(snapshot.output_root)
        if (device, inode) != (snapshot.output_root_device, snapshot.output_root_inode):
            raise ValueError("DCI full execution output root identity changed")
        return {
            "schema": "dci.full-execution-authorization-receipt/v1",
            "profile_id": snapshot.profile_id,
            "profile_sha256": snapshot.profile_sha256,
            "dataset_inventory_sha256": snapshot.dataset_inventory_sha256,
            "experiment_scopes_sha256": snapshot.experiment_scopes_sha256,
            "authorized_scope_ids": list(snapshot.authorized_scope_ids),
            "selected_ids_sha256": list(snapshot.selected_ids_sha256),
            "output_root_device": snapshot.output_root_device,
            "output_root_inode": snapshot.output_root_inode,
            "estimated_budget_usd": snapshot.estimated_budget_usd,
            "invocation_authorized": snapshot.invocation_authorized,
            "issuance_token_sha256": hashlib.sha256(
                snapshot.issuance_token.encode()
            ).hexdigest(),
        }
