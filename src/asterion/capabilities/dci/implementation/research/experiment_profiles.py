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
from decimal import Decimal
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from asterion.capabilities.dci.implementation.reproduction.paper_benchmarks import (
    DatasetInputBinding,
    _DatasetInputBindingIdentity,
    _copy_dataset_input_binding,
    _dataset_input_binding_identity,
    _dataset_input_binding_matches,
    canonical_sha256,
    paper_benchmark_inventory_sha256,
    paper_experiment_scope_ids,
    paper_experiment_scopes_sha256,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.capabilities.dci.implementation.reproduction.provenance import dci_complete_implementation_identity

EXPERIMENT_PROFILE_SCHEMA = "dci.experiment-profiles/v1"
EXPERIMENT_AUTHORIZATION_SCHEMA = "asterion.dci.paper-full-authorization/v1"
EXPERIMENT_PROFILE_SCHEMA_SHA256 = (
    "6c06ef8b0885433f660d008d35d988aaf0bc5f0d893c2ea8caec240cd3728c7b"
)
_UPSTREAM_COMMIT = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
_PROFILE_IDS = (
    "asterion-safe/pi",
    "asterion-safe/claude-subscription",
    "asterion-safe/claude-minimax",
    "paper-reference/pi",
    "paper-reference/claude-code",
    f"upstream-github/{_UPSTREAM_COMMIT}/pi",
)
_PUBLIC_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*")
_UPSTREAM_PROFILE_ID = re.compile(r"upstream-github/([0-9a-f]{40})/pi")
_EXPECTED_PROFILE_SEMANTICS = {
    "asterion-safe/pi": ("pi", "openai-codex", "gpt-5.6-luna", "saved-auth-or-provider-key", None, "read,bash", 100, "deepseek-v4-flash"),
    "asterion-safe/claude-subscription": ("claude-code", None, None, "local-subscription", None, "read,grep", 100, "deepseek-v4-flash"),
    "asterion-safe/claude-minimax": ("claude-code", None, None, "invocation-minimax-coding-plan", None, "read,grep", 100, "deepseek-v4-flash"),
    "paper-reference/pi": ("pi", "openai", "gpt-5.4-nano", "saved-auth-or-provider-key", "high", "read,bash", 300, "gpt-4.1"),
    "paper-reference/claude-code": ("claude-code", None, "claude-sonnet-4-6", "local-subscription", "medium", "read,grep", 300, "gpt-4.1"),
    f"upstream-github/{_UPSTREAM_COMMIT}/pi": ("pi", "openai", "gpt-5.4-nano", "saved-auth-or-provider-key", "low", "read,bash", 300, "gpt-5.4-nano"),
}
_CURRENT_JUDGE = {
    "base_url": "https://api.deepseek.com/v1", "api": "chat-completions",
    "model": "deepseek-v4-flash", "key_source": "DEEPSEEK_API_KEY",
    "thinking": False, "json_object": True,
    "request_shape_sha256": "b235c27019598e623db3a0ec4a76f847dac52f9581bc1a1acc8e4324b3d56db8",
    "output_shape_identity": "json-object/v1",
    "prompt_contract": "asterion.dci.answer-judge/strict-json/v1",
    "prompt_contract_sha256": "4d05c3ff588df3b0d60c1547ba6aa5014c5737cf79500022fed66fe8fd92fcb0",
    "pricing_identity": "usd-per-1m/input=0,cached=0,output=0/runtime-default",
}
_PAPER_JUDGE = {
    "base_url": "https://api.openai.com/v1", "api": "responses",
    "model": "gpt-4.1", "key_source": "OPENAI_API_KEY",
    "thinking": False, "json_object": True,
    "request_shape_sha256": "dd2a62b52f888de23a88e42380b62fb6df9435914ca2710d186e2ef799d42967",
    "output_shape_identity": "paper-labeled-output/asterion-parser-adapter/v1",
    "prompt_contract": "dci.paper-answer-judge/gpt-4.1/v1",
    "prompt_contract_sha256": "47e7ae410ed9f14dc06b8e0f3f18388152b320574f83e3a5a5b7e874ab70c921",
    "pricing_identity": "paper-unreported",
}
_UPSTREAM_JUDGE = {
    "base_url": "https://api.openai.com/v1", "api": "responses",
    "model": "gpt-5.4-nano", "key_source": "OPENAI_API_KEY",
    "thinking": False, "json_object": True,
    "request_shape_sha256": "4265875757baa84a703a0cab19439bfb49f488419789653a80442727ab5f0d92",
    "output_shape_identity": "upstream-json-object/v1",
    "prompt_contract": f"dci.upstream-answer-judge/{_UPSTREAM_COMMIT}/v1",
    "prompt_contract_sha256": "fb02b190b7513c64e937e4c071359c15d18ff0eff45fc6635535d006e65bddff",
    "pricing_identity": "upstream-unreported",
}
_PAPER_UNREPORTED_PARAMETERS = {
    "duplicate_handling": "paper-unreported",
    "read_minimum_evidence_overlap": "paper-unreported",
    "segment_characters": "paper-unreported",
    "selection_seeds": "paper-unreported",
}


@dataclass(frozen=True, slots=True)
class ExperimentProfile:
    profile_id: str
    source_family: str
    source_identity: str | Mapping[str, str]
    prompt_contract: str
    judge_contract: str
    metric_contracts: tuple[str, ...]
    runtime_contract: str
    context_contract: str
    dataset_selection_contract: str
    implementation_contract: str
    implementation_sha256: str
    paper_unreported_parameters: Mapping[str, str]
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
            "source_family": self.source_family,
            "source_identity": (
                dict(self.source_identity)
                if isinstance(self.source_identity, Mapping)
                else self.source_identity
            ),
            "prompt_contract": self.prompt_contract,
            "judge_contract": self.judge_contract,
            "metric_contracts": list(self.metric_contracts),
            "runtime_contract": self.runtime_contract,
            "context_contract": self.context_contract,
            "dataset_selection_contract": self.dataset_selection_contract,
            "implementation_contract": self.implementation_contract,
            "implementation_sha256": self.implementation_sha256,
            "paper_unreported_parameters": dict(
                self.paper_unreported_parameters
            ),
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


class ExperimentAuthorizationError(RuntimeError):
    """Safe public failure for invalid full-execution authority or budget."""


@dataclass(frozen=True, slots=True, init=False)
class FullExecutionAuthorization:
    profile_id: str
    profile_sha256: str
    dataset_inventory_sha256: str
    experiment_scopes_sha256: str
    authorized_scope_ids: tuple[str, ...]
    dataset_input_bindings: tuple[DatasetInputBinding, ...] = field(repr=False)
    selected_ids_sha256: tuple[str, ...]
    bounded_selected_ids_sha256: tuple[str, ...]
    selected_query_counts: tuple[int, ...]
    planned_agent_operations: int
    planned_judge_operations: int
    output_root_device: int
    output_root_inode: int
    estimated_budget_usd: float
    invocation_authorized: bool
    max_agent_operations: int
    max_judge_operations: int
    max_cost_usd: float
    max_agent_cost_per_operation_usd: float
    max_judge_cost_per_operation_usd: float
    _issuance_token: str = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("FullExecutionAuthorization is issued only by authorize_full_execution")


@dataclass(frozen=True, slots=True, init=False)
class FullExecutionReservation:
    scope_id: str
    kind: str
    upper_bound_usd: float
    _authorization_token: str = field(repr=False, compare=False)
    _reservation_token: str = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError(
            "FullExecutionReservation is issued only by "
            "reserve_full_execution_operation"
        )


@dataclass(frozen=True, slots=True)
class _AuthorizationSnapshot:
    profile_id: str
    profile_sha256: str
    dataset_inventory_sha256: str
    experiment_scopes_sha256: str
    authorized_scope_ids: tuple[str, ...]
    dataset_input_bindings: tuple[_DatasetInputBindingIdentity, ...]
    selected_ids_sha256: tuple[str, ...]
    bounded_selected_ids_sha256: tuple[str, ...]
    selected_query_counts: tuple[int, ...]
    planned_agent_operations: int
    planned_judge_operations: int
    scope_selections: tuple[tuple[str, str], ...]
    output_root: Path
    output_root_device: int
    output_root_inode: int
    estimated_budget_usd: float
    invocation_authorized: bool
    max_agent_operations: int
    max_judge_operations: int
    max_cost_usd: float
    max_agent_cost_per_operation_usd: float
    max_judge_cost_per_operation_usd: float
    issuance_token: str


@dataclass(frozen=True, slots=True)
class _ScopeOutputIdentity:
    path: Path
    device: int
    inode: int


@dataclass(slots=True)
class _ReservationRecord:
    issuer: FullExecutionReservation
    scope_id: str
    kind: str
    upper_bound_usd: Decimal


@dataclass(frozen=True, slots=True)
class _SettledReservationRecord:
    issuer: FullExecutionReservation


@dataclass(slots=True)
class _AuthorizationRecord:
    issuer: FullExecutionAuthorization
    snapshot: _AuthorizationSnapshot
    manifest_output: _ScopeOutputIdentity
    scope_outputs: dict[str, _ScopeOutputIdentity]
    consumed_scopes: set[str]
    active_reservations: dict[str, _ReservationRecord]
    settled_reservations: dict[str, _SettledReservationRecord]
    reserved_agent_operations: int
    reserved_judge_operations: int
    completed_agent_operations: int
    completed_judge_operations: int
    reserved_cost_usd: Decimal
    actual_cost_usd: Decimal
    cancelled: bool
    finalized: bool


_AUTHORIZATION_REGISTRY: dict[str, _AuthorizationRecord] = {}
_AUTHORIZATION_LOCK = threading.Lock()


def _validate_profile_schema(schema: object, fields: set[str]) -> None:
    try:
        profile = schema["$defs"]["profile"]  # type: ignore[index]
        properties = profile["properties"]
        judge = properties["judge"]
        comparison = properties["comparison"]
        source_identity = properties["source_identity"]
        paper_unreported = properties["paper_unreported_parameters"]
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
        or type(source_identity.get("oneOf")) is not list
        or len(source_identity["oneOf"]) != 3
        or paper_unreported.get("additionalProperties") is not False
        or set(paper_unreported.get("properties", {}))
        != set(_PAPER_UNREPORTED_PARAMETERS)
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


def _read_profile_resources() -> tuple[object, object]:
    package = resources.files("asterion.capabilities.dci.resources")
    payload = json.loads(
        package.joinpath("experiment-profiles.json").read_text(),
        object_pairs_hook=_unique_object,
    )
    schema = json.loads(
        package.joinpath("experiment-profile.schema.json").read_text(),
        object_pairs_hook=_unique_object,
    )
    return payload, schema


def _expected_source_contract(profile_id: str) -> dict[str, object]:
    if profile_id.startswith("asterion-safe/"):
        runtime = "pi" if profile_id.endswith("/pi") else "claude-code"
        return {
            "source_family": "asterion-safe",
            "source_identity": {
                "implementation_contract": "asterion.dci.complete-implementation/v1"
            },
            "prompt_contract": "asterion.dci.prompt/safe/v1",
            "judge_contract": "asterion.dci.answer-judge/strict-json/v1",
            "metric_contracts": [
                "asterion.dci.answer-correctness/strict-json/v1",
                "ndcg@10-binary-deduplicated/v1",
            ],
            "runtime_contract": f"asterion.runtime/{runtime}.reference/v1",
            "context_contract": "dci.asterion-safe-context/level3/v1",
            "dataset_selection_contract": "asterion.dci.dataset-selection/af-340/v1",
            "implementation_contract": "asterion.dci.complete-implementation/v1",
            "paper_unreported_parameters": {},
        }
    if profile_id.startswith("paper-reference/"):
        runtime = "pi" if profile_id.endswith("/pi") else "claude-code"
        return {
            "source_family": "paper-reference",
            "source_identity": "arxiv:2605.05242v1",
            "prompt_contract": "dci.paper-prompt/arxiv:2605.05242v1/v1",
            "judge_contract": "dci.paper-answer-judge/gpt-4.1/v1",
            "metric_contracts": [
                "dci.paper-answer-correctness/arxiv:2605.05242v1/v1",
                "dci.paper-ndcg@10/arxiv:2605.05242v1/duplicate-handling-unreported/v1",
            ],
            "runtime_contract": f"dci.paper-runtime/{runtime}/v1",
            "context_contract": "dci.paper-context/level3/v1",
            "dataset_selection_contract": "dci.paper-dataset-selection/arxiv:2605.05242v1/v1",
            "implementation_contract": "asterion.dci.paper-reference-execution/v1",
            "paper_unreported_parameters": dict(_PAPER_UNREPORTED_PARAMETERS),
        }
    match = _UPSTREAM_PROFILE_ID.fullmatch(profile_id)
    if match is None or match.group(1) != _UPSTREAM_COMMIT:
        raise RuntimeError("DCI experiment profile contract is invalid")
    return {
        "source_family": "upstream-github",
        "source_identity": {
            "repository": "DCI-Agent/DCI-Agent-Lite",
            "commit": _UPSTREAM_COMMIT,
        },
        "prompt_contract": f"dci.upstream-github-prompt/{_UPSTREAM_COMMIT}/v1",
        "judge_contract": f"dci.upstream-answer-judge/{_UPSTREAM_COMMIT}/v1",
        "metric_contracts": [
            f"dci.upstream-answer-correctness/{_UPSTREAM_COMMIT}/v1",
            "ndcg@10-binary-upstream-list/v1",
        ],
        "runtime_contract": f"dci.upstream-github-runtime/{_UPSTREAM_COMMIT}/pi/v1",
        "context_contract": f"dci.upstream-github-context/{_UPSTREAM_COMMIT}/level3/v1",
        "dataset_selection_contract": f"dci.upstream-github-dataset-selection/{_UPSTREAM_COMMIT}/v1",
        "implementation_contract": f"asterion.dci.upstream-github-execution/{_UPSTREAM_COMMIT}/v1",
        "paper_unreported_parameters": {},
    }


@lru_cache(maxsize=1)
def _profiles() -> Mapping[str, ExperimentProfile]:
    try:
        payload, schema = _read_profile_resources()
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
    fields = {
        "profile_id", "source_family", "source_identity", "prompt_contract",
        "judge_contract", "metric_contracts", "runtime_contract",
        "context_contract", "dataset_selection_contract",
        "implementation_contract", "paper_unreported_parameters", "runtime",
        "provider", "model", "authentication_mode", "reasoning", "tools",
        "max_turns", "context_profile", "judge", "dataset_inventory_sha256",
        "experiment_scopes_sha256", "scope_ids", "selected_ids_sha256",
        "paper_unreported_scope_ids", "corpus_identity", "metric_identities",
        "aggregation_identity", "comparison", "compatible_config_key",
    }
    _validate_profile_schema(schema, fields)
    implementation_sha256 = dci_complete_implementation_identity()
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
        source_contract = _expected_source_contract(profile_id)
        if any(item.get(key) != value for key, value in source_contract.items()):
            raise RuntimeError("DCI experiment profile contract is invalid")
        raw_source_identity = item["source_identity"]
        source_identity: str | Mapping[str, str]
        if item["source_family"] == "asterion-safe":
            source_identity = implementation_sha256
        elif type(raw_source_identity) is dict:
            if any(type(key) is not str or type(value) is not str for key, value in raw_source_identity.items()):
                raise RuntimeError("DCI experiment profile contract is invalid")
            source_identity = MappingProxyType(dict(raw_source_identity))
        elif type(raw_source_identity) is str:
            source_identity = raw_source_identity
        else:
            raise RuntimeError("DCI experiment profile contract is invalid")
        parsed[profile_id] = ExperimentProfile(
            profile_id=profile_id, source_family=item["source_family"],
            source_identity=source_identity,
            prompt_contract=item["prompt_contract"],
            judge_contract=item["judge_contract"],
            metric_contracts=tuple(item["metric_contracts"]),
            runtime_contract=item["runtime_contract"],
            context_contract=item["context_contract"],
            dataset_selection_contract=item["dataset_selection_contract"],
            implementation_contract=item["implementation_contract"],
            implementation_sha256=implementation_sha256,
            paper_unreported_parameters=MappingProxyType(
                dict(item["paper_unreported_parameters"])
            ),
            runtime=item["runtime"], provider=item["provider"], model=item["model"],
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
        expected_judge = (
            _PAPER_JUDGE
            if name.startswith("paper-reference/")
            else (
                _UPSTREAM_JUDGE
                if name.startswith("upstream-github/")
                else _CURRENT_JUDGE
            )
        )
        expected_comparison = {
            "asterion-safe/pi": {"accuracy_margin": -0.05, "ndcg_margin": -0.02},
            "asterion-safe/claude-subscription": {"target_identity": "asterion-safe/claude-subscription"},
            "asterion-safe/claude-minimax": {"target_identity": "asterion-safe/claude-minimax"},
            "paper-reference/pi": {"accuracy_margin": -0.05, "ndcg_margin": -0.02, "published_target": "DCI-Agent-Lite"},
            "paper-reference/claude-code": {"published_target": "DCI-Agent-CC"},
            f"upstream-github/{_UPSTREAM_COMMIT}/pi": {"accuracy_margin": -0.05, "ndcg_margin": -0.02},
        }[name]
        if (
            dict(profile.judge) != expected_judge
            or profile.corpus_identity != "dci.paper-corpora/af-320-v1"
            or profile.metric_identities
            != (
                "llm-answer-correctness",
                (
                    "dci.paper-ndcg@10/arxiv:2605.05242v1/"
                    "duplicate-handling-unreported/v1"
                    if name.startswith("paper-reference/")
                    else (
                        "ndcg@10-binary-upstream-list/v1"
                        if name.startswith("upstream-github/")
                        else "ndcg@10-binary-deduplicated/v1"
                    )
                ),
            )
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
    if profile_id != "asterion-safe/claude-minimax":
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


def _open_directory_chain(path: Path, *, create: bool = False) -> int:
    absolute = Path(os.path.abspath(os.path.normpath(path)))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if not getattr(os, "O_NOFOLLOW", 0):
        raise OSError("no-follow directory traversal is unavailable")
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            try:
                next_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, mode=0o755, dir_fd=descriptor)
                next_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=descriptor,
                )
            except OSError:
                component_metadata = os.stat(
                    component,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                parent_metadata = os.fstat(descriptor)
                trusted_system_alias = (
                    stat.S_ISLNK(component_metadata.st_mode)
                    and component_metadata.st_uid == 0
                    and parent_metadata.st_uid == 0
                    and stat.S_IMODE(parent_metadata.st_mode) & 0o022 == 0
                )
                if not trusted_system_alias:
                    raise
                next_descriptor = os.open(
                    component,
                    flags & ~getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            os.close(descriptor)
            descriptor = next_descriptor
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _rmdir_if_identity(
    parent_descriptor: int,
    name: str,
    *,
    device: int,
    inode: int,
) -> None:
    try:
        current = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return
    if (
        stat.S_ISDIR(current.st_mode)
        and (current.st_dev, current.st_ino) == (device, inode)
    ):
        try:
            os.rmdir(name, dir_fd=parent_descriptor)
        except OSError:
            pass


def _create_private_directory(
    parent_descriptor: int,
    name: str,
) -> tuple[int, int, int]:
    if not name or name in {".", ".."} or os.sep in name:
        raise ValueError("DCI full output root identity is invalid")
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise ValueError("DCI full output root must be fresh")

    os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
    descriptor: int | None = None
    identity: tuple[int, int] | None = None
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ValueError("DCI full output root must be private")
        return descriptor, metadata.st_dev, metadata.st_ino
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if identity is not None:
            _rmdir_if_identity(
                parent_descriptor,
                name,
                device=identity[0],
                inode=identity[1],
            )
        raise


def _private_root_identity(output_root: Path) -> tuple[int, int]:
    try:
        descriptor = _open_directory_chain(output_root)
        try:
            opened = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        metadata = output_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("DCI full execution output root identity is invalid")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ValueError("DCI full execution output root permissions changed")
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
    public_bindings = authorization.dataset_input_bindings
    return (
        authorization.profile_id == snapshot.profile_id
        and authorization.profile_sha256 == snapshot.profile_sha256
        and authorization.dataset_inventory_sha256
        == snapshot.dataset_inventory_sha256
        and authorization.experiment_scopes_sha256
        == snapshot.experiment_scopes_sha256
        and authorization.authorized_scope_ids == snapshot.authorized_scope_ids
        and type(public_bindings) is tuple
        and len(public_bindings) == len(snapshot.dataset_input_bindings)
        and all(
            _dataset_input_binding_matches(binding, expected)
            for binding, expected in zip(
                public_bindings,
                snapshot.dataset_input_bindings,
                strict=True,
            )
        )
        and authorization.selected_ids_sha256 == snapshot.selected_ids_sha256
        and authorization.bounded_selected_ids_sha256
        == snapshot.bounded_selected_ids_sha256
        and authorization.selected_query_counts == snapshot.selected_query_counts
        and authorization.planned_agent_operations
        == snapshot.planned_agent_operations
        and authorization.planned_judge_operations
        == snapshot.planned_judge_operations
        and tuple(
            zip(
                authorization.authorized_scope_ids,
                authorization.selected_ids_sha256,
                strict=True,
            )
        )
        == snapshot.scope_selections
        and authorization.output_root_device == snapshot.output_root_device
        and authorization.output_root_inode == snapshot.output_root_inode
        and authorization.estimated_budget_usd == snapshot.estimated_budget_usd
        and authorization.invocation_authorized is snapshot.invocation_authorized
        and authorization.max_agent_operations == snapshot.max_agent_operations
        and authorization.max_judge_operations == snapshot.max_judge_operations
        and authorization.max_cost_usd == snapshot.max_cost_usd
        and authorization.max_agent_cost_per_operation_usd
        == snapshot.max_agent_cost_per_operation_usd
        and authorization.max_judge_cost_per_operation_usd
        == snapshot.max_judge_cost_per_operation_usd
        and authorization._issuance_token == snapshot.issuance_token
    )


def _positive_operation_limit(value: object) -> bool:
    return type(value) is int and value > 0


def _nonnegative_operation_limit(value: object) -> bool:
    return type(value) is int and value >= 0


def _usd_decimal(value: object) -> Decimal:
    if type(value) is int:
        numeric = value
    elif type(value) is float:
        numeric = value
    else:
        raise ValueError("USD value is invalid")
    try:
        finite_value = math.isfinite(float(numeric))
    except (OverflowError, TypeError, ValueError):
        raise ValueError("USD value is invalid") from None
    if not finite_value:
        raise ValueError("USD value is invalid")
    return Decimal(str(numeric))


def _positive_usd_limit(value: object) -> bool:
    try:
        return _usd_decimal(value) > 0
    except ValueError:
        return False


def _require_positive_usd_limit(value: object) -> float:
    if _usd_decimal(value) <= 0:
        raise ValueError("USD value is invalid")
    if type(value) is int or type(value) is float:
        return float(value)
    raise ValueError("USD value is invalid")


def _validate_authorization(
    authorization: object,
    *,
    require_active: bool = True,
) -> _AuthorizationRecord:
    if not isinstance(authorization, FullExecutionAuthorization):
        raise ExperimentAuthorizationError("full execution authorization is invalid")
    token = getattr(authorization, "_issuance_token", None)
    if type(token) is not str:
        raise ExperimentAuthorizationError("full execution authorization is invalid")
    record = _AUTHORIZATION_REGISTRY.get(token)
    if (
        record is None
        or record.issuer is not authorization
        or not _authorization_matches_snapshot(authorization, record.snapshot)
    ):
        raise ExperimentAuthorizationError("full execution authorization is invalid")
    snapshot = record.snapshot
    try:
        current_profile = resolve_experiment_profile(snapshot.profile_id)
    except (RuntimeError, ValueError):
        raise ExperimentAuthorizationError("full execution authorization is invalid") from None
    if (
        current_profile.identity_sha256 != snapshot.profile_sha256
        or current_profile.dataset_inventory_sha256
        != snapshot.dataset_inventory_sha256
        or current_profile.experiment_scopes_sha256
        != snapshot.experiment_scopes_sha256
        or snapshot.dataset_inventory_sha256 != paper_benchmark_inventory_sha256()
        or snapshot.experiment_scopes_sha256 != paper_experiment_scopes_sha256()
        or snapshot.invocation_authorized is not True
    ):
        raise ExperimentAuthorizationError("full execution authorization is invalid")
    try:
        device, inode = _private_root_identity(snapshot.output_root)
    except ValueError:
        raise ExperimentAuthorizationError(
            "full execution output root identity is invalid"
        ) from None
    if (device, inode) != (
        snapshot.output_root_device,
        snapshot.output_root_inode,
    ):
        raise ExperimentAuthorizationError(
            "full execution output root identity changed"
        )
    if require_active and (record.cancelled or record.finalized):
        raise ExperimentAuthorizationError("full execution authorization is inactive")
    return record


def _validate_output_identity(
    output: _ScopeOutputIdentity,
    error_label: str,
) -> _ScopeOutputIdentity:
    try:
        device, inode = _private_root_identity(output.path)
    except ValueError:
        raise ExperimentAuthorizationError(
            f"full execution {error_label} identity is invalid"
        ) from None
    if (device, inode) != (output.device, output.inode):
        raise ExperimentAuthorizationError(
            f"full execution {error_label} identity changed"
        )
    return output


def _validate_scope_output(
    record: _AuthorizationRecord, scope_id: object
) -> _ScopeOutputIdentity:
    if type(scope_id) is not str or scope_id not in record.snapshot.authorized_scope_ids:
        raise ExperimentAuthorizationError("full execution authorization scope is invalid")
    output = record.scope_outputs.get(scope_id)
    if output is None:
        raise ExperimentAuthorizationError("full execution authorization scope is invalid")
    return _validate_output_identity(output, "scope output")


def authorize_full_execution(
    profile_id: str | None = None,
    output_root: Path | None = None,
    estimated_budget_usd: float | None = None,
    invocation_authorized: bool = False,
    *,
    profile: ExperimentProfile | None = None,
    scope_ids: Sequence[str] | None = None,
    max_agent_operations: int | None = None,
    max_judge_operations: int | None = None,
    max_cost_usd: float | None = None,
    max_agent_cost_per_operation_usd: float | None = None,
    max_judge_cost_per_operation_usd: float | None = None,
    dataset_input_bindings: Sequence[DatasetInputBinding] | None = None,
    bounded_selected_ids_sha256: Sequence[str] | None = None,
    selected_query_counts: Sequence[int] | None = None,
    planned_agent_operations: int | None = None,
    planned_judge_operations: int | None = None,
    preflight_profile_sha256: str | None = None,
    preflight_dataset_inventory_sha256: str | None = None,
    preflight_experiment_scopes_sha256: str | None = None,
    preflight_scope_ids: Sequence[str] | None = None,
    preflight_selected_ids_sha256: Sequence[str] | None = None,
    invocation_provider: str | None = None,
    invocation_model: str | None = None,
    cache_only: bool = False,
) -> FullExecutionAuthorization:
    if output_root is None:
        raise ExperimentAuthorizationError("full execution output root is invalid")
    legacy = profile is None
    if profile is None:
        if type(profile_id) is not str:
            raise ExperimentAuthorizationError("full execution profile is invalid")
        profile = resolve_experiment_profile(
            profile_id,
            invocation_provider=invocation_provider,
            invocation_model=invocation_model,
        )
        profile_sha256 = experiment_profile_sha256(
            profile_id,
            invocation_provider=invocation_provider,
            invocation_model=invocation_model,
        )
        scope_ids = preflight_scope_ids
        selected_digests = preflight_selected_ids_sha256
        max_cost_usd = estimated_budget_usd
        max_agent_operations = (
            1 if max_agent_operations is None else max_agent_operations
        )
        max_judge_operations = (
            1 if max_judge_operations is None else max_judge_operations
        )
        max_agent_cost_per_operation_usd = (
            float(max_cost_usd)
            if max_agent_cost_per_operation_usd is None and max_cost_usd is not None
            else max_agent_cost_per_operation_usd
        )
        max_judge_cost_per_operation_usd = (
            float(max_cost_usd)
            if max_judge_cost_per_operation_usd is None and max_cost_usd is not None
            else max_judge_cost_per_operation_usd
        )
    else:
        if any(
            value is not None
            for value in (
                profile_id,
                estimated_budget_usd,
                preflight_profile_sha256,
                preflight_dataset_inventory_sha256,
                preflight_experiment_scopes_sha256,
                preflight_scope_ids,
                preflight_selected_ids_sha256,
                invocation_provider,
                invocation_model,
            )
        ):
            raise ExperimentAuthorizationError(
                "full execution authorization inputs are ambiguous"
            )
        if type(profile) is not ExperimentProfile:
            raise ExperimentAuthorizationError("full execution profile is invalid")
        try:
            expected_profile = resolve_experiment_profile(profile.profile_id)
        except (RuntimeError, ValueError):
            raise ExperimentAuthorizationError("full execution profile is invalid") from None
        if profile.identity_sha256 != expected_profile.identity_sha256:
            raise ExperimentAuthorizationError("full execution profile is invalid")
        profile_sha256 = profile.identity_sha256
        selected_digests = tuple(
            dict(zip(profile.scope_ids, profile.selected_ids_sha256, strict=True)).get(
                item, ""
            )
            for item in (scope_ids or ())
        )
    if invocation_authorized is not True:
        raise ExperimentAuthorizationError(
            "full execution requires invocation authorization"
        )
    if (
        not _positive_operation_limit(max_agent_operations)
        or not _nonnegative_operation_limit(max_judge_operations)
        or not _positive_usd_limit(max_cost_usd)
        or not _positive_usd_limit(max_agent_cost_per_operation_usd)
        or not _positive_usd_limit(max_judge_cost_per_operation_usd)
    ):
        raise ExperimentAuthorizationError("full execution limits are invalid")
    agent_operation_limit = max_agent_operations
    judge_operation_limit = max_judge_operations
    cost_limit = _require_positive_usd_limit(max_cost_usd)
    agent_operation_cost_limit = _require_positive_usd_limit(
        max_agent_cost_per_operation_usd
    )
    judge_operation_cost_limit = _require_positive_usd_limit(
        max_judge_cost_per_operation_usd
    )
    if type(agent_operation_limit) is not int or type(judge_operation_limit) is not int:
        raise ExperimentAuthorizationError("full execution limits are invalid")
    if cache_only:
        raise ExperimentAuthorizationError(
            "full execution cannot be authorized by cache evidence"
        )
    requested_scope_ids = tuple(scope_ids or ())
    selected_digests = tuple(selected_digests or ())
    expected = dict(zip(profile.scope_ids, profile.selected_ids_sha256, strict=True))
    if not requested_scope_ids:
        raise ExperimentAuthorizationError("full execution requires explicit scopes")
    if (
        (legacy and preflight_profile_sha256 != profile_sha256)
        or (legacy and preflight_dataset_inventory_sha256 != profile.dataset_inventory_sha256)
        or (legacy and preflight_experiment_scopes_sha256 != profile.experiment_scopes_sha256)
        or len(requested_scope_ids) != len(set(requested_scope_ids))
        or tuple(sorted(requested_scope_ids)) != requested_scope_ids
        or len(requested_scope_ids) != len(selected_digests)
        or any(
            expected.get(scope_id) != digest
            for scope_id, digest in zip(
                requested_scope_ids, selected_digests, strict=True
            )
        )
    ):
        raise ExperimentAuthorizationError("full execution authorization is invalid")
    try:
        scope_contracts = tuple(
            resolve_paper_experiment_scope(scope_id)
            for scope_id in requested_scope_ids
        )
    except ValueError:
        raise ExperimentAuthorizationError(
            "full execution authorization is invalid"
        ) from None
    supplied_bindings = (
        () if dataset_input_bindings is None else tuple(dataset_input_bindings)
    )
    try:
        input_binding_identities = tuple(
            _dataset_input_binding_identity(binding)
            for binding in supplied_bindings
        )
    except ValueError:
        input_binding_identities = ()
    if len(input_binding_identities) != len(requested_scope_ids) or any(
        identity[1]
        != resolve_paper_benchmark(scope.dataset_id).identity_sha256
        for identity, scope in zip(
            input_binding_identities,
            scope_contracts,
            strict=True,
        )
    ):
        raise ExperimentAuthorizationError(
            "full execution dataset input binding is invalid"
        )
    public_input_bindings = tuple(
        _copy_dataset_input_binding(identity)
        for identity in input_binding_identities
    )
    default_counts = tuple(scope.selection_count for scope in scope_contracts)
    bounded_digests = (
        selected_digests
        if bounded_selected_ids_sha256 is None
        else tuple(bounded_selected_ids_sha256)
    )
    selected_counts = (
        default_counts
        if selected_query_counts is None
        else tuple(selected_query_counts)
    )
    planned_agent_count = (
        sum(selected_counts)
        if planned_agent_operations is None
        else planned_agent_operations
    )
    if (
        len(bounded_digests) != len(requested_scope_ids)
        or len(selected_counts) != len(requested_scope_ids)
        or any(
            type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in bounded_digests
        )
        or any(type(count) is not int or count < 1 for count in selected_counts)
    ):
        raise ExperimentAuthorizationError(
            "full execution bounded selection is invalid"
        )
    if any(
        count > scope.selection_count
        for count, scope in zip(selected_counts, scope_contracts, strict=True)
    ):
        raise ExperimentAuthorizationError(
            "full execution bounded selection is invalid"
        )
    expected_judge_count = sum(
        count
        for count, scope in zip(selected_counts, scope_contracts, strict=True)
        if resolve_paper_benchmark(scope.dataset_id).mode == "qa"
    )
    planned_judge_count = (
        expected_judge_count
        if planned_judge_operations is None
        else planned_judge_operations
    )
    if (
        type(planned_agent_count) is not int
        or planned_agent_count < 1
        or type(planned_judge_count) is not int
        or planned_judge_count < 0
        or sum(selected_counts) != planned_agent_count
        or planned_judge_count != expected_judge_count
        or planned_agent_count > agent_operation_limit
        or planned_judge_count > judge_operation_limit
    ):
        raise ExperimentAuthorizationError(
            "full execution bounded operation plan is invalid"
        )
    private_root = Path(
        os.path.abspath(os.path.normpath(Path(output_root).expanduser()))
    )
    parent_descriptor: int | None = None
    root_descriptor: int | None = None
    root_identity: tuple[int, int] | None = None
    created_children: list[tuple[str, int, int]] = []
    scope_outputs: dict[str, _ScopeOutputIdentity] = {}
    manifest_output: _ScopeOutputIdentity | None = None
    try:
        parent_descriptor = _open_directory_chain(
            private_root.parent,
            create=True,
        )
        root_descriptor, device, inode = _create_private_directory(
            parent_descriptor,
            private_root.name,
        )
        root_identity = (device, inode)
        manifest_child_name = hashlib.sha256(
            b"dci.reproduction-manifests/v1"
        ).hexdigest()
        manifest_descriptor, manifest_device, manifest_inode = (
            _create_private_directory(root_descriptor, manifest_child_name)
        )
        try:
            manifest_output = _ScopeOutputIdentity(
                private_root / manifest_child_name,
                manifest_device,
                manifest_inode,
            )
            created_children.append(
                (manifest_child_name, manifest_device, manifest_inode)
            )
        finally:
            os.close(manifest_descriptor)
        for scope_id in requested_scope_ids:
            child_name = hashlib.sha256(scope_id.encode("utf-8")).hexdigest()
            child_descriptor, child_device, child_inode = (
                _create_private_directory(root_descriptor, child_name)
            )
            try:
                scope_outputs[scope_id] = _ScopeOutputIdentity(
                    private_root / child_name,
                    child_device,
                    child_inode,
                )
                created_children.append(
                    (child_name, child_device, child_inode)
                )
            finally:
                os.close(child_descriptor)
    except (OSError, ValueError):
        if root_descriptor is not None:
            for child_name, child_device, child_inode in reversed(
                created_children
            ):
                _rmdir_if_identity(
                    root_descriptor,
                    child_name,
                    device=child_device,
                    inode=child_inode,
                )
            os.close(root_descriptor)
        if parent_descriptor is not None:
            if root_identity is not None:
                _rmdir_if_identity(
                    parent_descriptor,
                    private_root.name,
                    device=root_identity[0],
                    inode=root_identity[1],
                )
            os.close(parent_descriptor)
        raise ExperimentAuthorizationError(
            "full execution output root identity is invalid"
        ) from None
    else:
        os.close(root_descriptor)
        os.close(parent_descriptor)
    token = secrets.token_hex(32)
    authorization = _issue_authorization(
        profile_id=profile.profile_id,
        profile_sha256=profile_sha256,
        dataset_inventory_sha256=profile.dataset_inventory_sha256,
        experiment_scopes_sha256=profile.experiment_scopes_sha256,
        authorized_scope_ids=requested_scope_ids,
        dataset_input_bindings=public_input_bindings,
        selected_ids_sha256=selected_digests,
        bounded_selected_ids_sha256=bounded_digests,
        selected_query_counts=selected_counts,
        planned_agent_operations=planned_agent_count,
        planned_judge_operations=planned_judge_count,
        output_root_device=device,
        output_root_inode=inode,
        estimated_budget_usd=cost_limit,
        invocation_authorized=True,
        max_agent_operations=agent_operation_limit,
        max_judge_operations=judge_operation_limit,
        max_cost_usd=cost_limit,
        max_agent_cost_per_operation_usd=agent_operation_cost_limit,
        max_judge_cost_per_operation_usd=judge_operation_cost_limit,
        _issuance_token=token,
    )
    snapshot = _AuthorizationSnapshot(
        profile_id=profile.profile_id,
        profile_sha256=profile_sha256,
        dataset_inventory_sha256=profile.dataset_inventory_sha256,
        experiment_scopes_sha256=profile.experiment_scopes_sha256,
        authorized_scope_ids=requested_scope_ids,
        dataset_input_bindings=input_binding_identities,
        selected_ids_sha256=selected_digests,
        bounded_selected_ids_sha256=bounded_digests,
        selected_query_counts=selected_counts,
        planned_agent_operations=planned_agent_count,
        planned_judge_operations=planned_judge_count,
        scope_selections=tuple(
            zip(requested_scope_ids, selected_digests, strict=True)
        ),
        output_root=private_root,
        output_root_device=device,
        output_root_inode=inode,
        estimated_budget_usd=cost_limit,
        invocation_authorized=True,
        max_agent_operations=agent_operation_limit,
        max_judge_operations=judge_operation_limit,
        max_cost_usd=cost_limit,
        max_agent_cost_per_operation_usd=agent_operation_cost_limit,
        max_judge_cost_per_operation_usd=judge_operation_cost_limit,
        issuance_token=token,
    )
    with _AUTHORIZATION_LOCK:
        if manifest_output is None:
            raise ExperimentAuthorizationError(
                "full execution output root identity is invalid"
            )
        _AUTHORIZATION_REGISTRY[token] = _AuthorizationRecord(
            authorization,
            snapshot,
            manifest_output,
            scope_outputs,
            set(),
            {},
            {},
            0,
            0,
            0,
            0,
            Decimal("0"),
            Decimal("0"),
            False,
            False,
        )
    return authorization


def consume_full_execution_authorization(
    authorization: FullExecutionAuthorization,
    scope_id: str,
    dataset_input_binding: DatasetInputBinding | None = None,
) -> None:
    """Consume one exact scope capability after revalidating its private root."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authorization)
        _validate_scope_output(record, scope_id)
        try:
            binding_index = record.snapshot.authorized_scope_ids.index(scope_id)
        except ValueError:
            raise ExperimentAuthorizationError(
                "full execution authorization scope is invalid"
            ) from None
        if (
            not _dataset_input_binding_matches(
                dataset_input_binding,
                record.snapshot.dataset_input_bindings[binding_index],
            )
        ):
            raise ExperimentAuthorizationError(
                "full execution dataset input binding is invalid"
            )
        if scope_id in record.consumed_scopes:
            raise ExperimentAuthorizationError(
                "full execution authorization replay is invalid"
            )
        record.consumed_scopes.add(scope_id)


def authorized_scope_output_root(
    authority: FullExecutionAuthorization, scope_id: str
) -> Path:
    """Return an exact descriptor-verified private root for one selected scope."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        output = _validate_scope_output(record, scope_id)
        if scope_id in record.consumed_scopes:
            raise ExperimentAuthorizationError(
                "full execution authorization replay is invalid"
            )
        return output.path


def _authorized_scope_output_identity(
    authority: FullExecutionAuthorization, scope_id: str
) -> tuple[Path, int, int]:
    """Return one unconsumed descriptor-verified child identity."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        output = _validate_scope_output(record, scope_id)
        if scope_id in record.consumed_scopes:
            raise ExperimentAuthorizationError(
                "full execution authorization replay is invalid"
            )
        return output.path, output.device, output.inode


def _authorized_manifest_output_identity(
    authority: FullExecutionAuthorization,
) -> tuple[Path, int, int]:
    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        output = _validate_output_identity(
            record.manifest_output,
            "manifest output",
        )
        return output.path, output.device, output.inode


def _authorized_scope_selection_identity(
    authority: FullExecutionAuthorization,
    scope_id: str,
) -> tuple[str, int]:
    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        try:
            index = record.snapshot.authorized_scope_ids.index(scope_id)
        except ValueError:
            raise ExperimentAuthorizationError(
                "full execution authorization scope is invalid"
            ) from None
        return (
            record.snapshot.bounded_selected_ids_sha256[index],
            record.snapshot.selected_query_counts[index],
        )


def _authorized_scope_dataset_input_binding(
    authority: FullExecutionAuthorization,
    scope_id: str,
) -> DatasetInputBinding:
    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        try:
            index = record.snapshot.authorized_scope_ids.index(scope_id)
        except ValueError:
            raise ExperimentAuthorizationError(
                "full execution authorization scope is invalid"
            ) from None
        return _copy_dataset_input_binding(
            record.snapshot.dataset_input_bindings[index]
        )


def _issue_reservation(**values: object) -> FullExecutionReservation:
    reservation = object.__new__(FullExecutionReservation)
    for name, value in values.items():
        object.__setattr__(reservation, name, value)
    return reservation


def _reservation_for(
    authority: object, reservation: object
) -> tuple[_AuthorizationRecord, _ReservationRecord]:
    record = _validate_authorization(authority, require_active=False)
    if not isinstance(reservation, FullExecutionReservation):
        raise ExperimentAuthorizationError("full execution reservation is invalid")
    token = getattr(reservation, "_reservation_token", None)
    if type(token) is not str:
        raise ExperimentAuthorizationError("full execution reservation is invalid")
    item = record.active_reservations.get(token)
    try:
        reservation_upper_bound = _usd_decimal(reservation.upper_bound_usd)
    except ValueError:
        reservation_upper_bound = None
    if (
        item is None
        or item.issuer is not reservation
        or reservation._authorization_token != record.snapshot.issuance_token
        or reservation.scope_id != item.scope_id
        or reservation.kind != item.kind
        or reservation_upper_bound != item.upper_bound_usd
    ):
        raise ExperimentAuthorizationError("full execution reservation is invalid")
    return record, item


def reserve_full_execution_operation(
    authority: FullExecutionAuthorization, scope_id: str, kind: str
) -> FullExecutionReservation:
    """Atomically reserve a bounded agent or judge operation."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        _validate_scope_output(record, scope_id)
        if scope_id not in record.consumed_scopes:
            raise ExperimentAuthorizationError(
                "full execution authorization scope is not consumed"
            )
        if kind == "agent":
            reserved = record.reserved_agent_operations
            completed = record.completed_agent_operations
            limit = record.snapshot.max_agent_operations
            upper_bound_value = (
                record.snapshot.max_agent_cost_per_operation_usd
            )
            label = "Agent"
        elif kind == "judge":
            reserved = record.reserved_judge_operations
            completed = record.completed_judge_operations
            limit = record.snapshot.max_judge_operations
            upper_bound_value = (
                record.snapshot.max_judge_cost_per_operation_usd
            )
            label = "Judge"
        else:
            raise ExperimentAuthorizationError("full execution operation kind is invalid")
        if reserved + completed >= limit:
            raise ExperimentAuthorizationError(
                f"full execution {label} operation budget is exhausted"
            )
        configured_upper_bound = _usd_decimal(upper_bound_value)
        remaining = (
            _usd_decimal(record.snapshot.max_cost_usd)
            - record.actual_cost_usd
            - record.reserved_cost_usd
        )
        if configured_upper_bound > remaining and (
            record.active_reservations
            or configured_upper_bound
            != _usd_decimal(record.snapshot.max_cost_usd)
        ):
            raise ExperimentAuthorizationError("full execution USD budget is exhausted")
        upper_bound = min(configured_upper_bound, remaining)
        if upper_bound <= 0:
            raise ExperimentAuthorizationError("full execution USD budget is exhausted")
        issued_upper_bound = float(upper_bound)
        issued_upper_bound_decimal = _usd_decimal(issued_upper_bound)
        if issued_upper_bound_decimal > remaining:
            issued_upper_bound = math.nextafter(issued_upper_bound, 0.0)
            issued_upper_bound_decimal = _usd_decimal(issued_upper_bound)
        if issued_upper_bound_decimal <= 0 or issued_upper_bound_decimal > remaining:
            raise ExperimentAuthorizationError("full execution USD budget is exhausted")
        token = secrets.token_hex(32)
        reservation = _issue_reservation(
            scope_id=scope_id,
            kind=kind,
            upper_bound_usd=issued_upper_bound,
            _authorization_token=record.snapshot.issuance_token,
            _reservation_token=token,
        )
        record.active_reservations[token] = _ReservationRecord(
            reservation, scope_id, kind, issued_upper_bound_decimal
        )
        if kind == "agent":
            record.reserved_agent_operations += 1
        else:
            record.reserved_judge_operations += 1
        record.reserved_cost_usd += issued_upper_bound_decimal
        return reservation


def _settle_reservation(
    record: _AuthorizationRecord,
    reservation: FullExecutionReservation,
    item: _ReservationRecord,
    actual_cost_usd: Decimal,
) -> None:
    token = reservation._reservation_token
    del record.active_reservations[token]
    record.settled_reservations[token] = _SettledReservationRecord(reservation)
    record.reserved_cost_usd -= item.upper_bound_usd
    if item.kind == "agent":
        record.reserved_agent_operations -= 1
        record.completed_agent_operations += 1
    else:
        record.reserved_judge_operations -= 1
        record.completed_judge_operations += 1
    record.actual_cost_usd += actual_cost_usd


def reconcile_full_execution_operation(
    authority: FullExecutionAuthorization,
    reservation: FullExecutionReservation,
    actual_cost_usd: float,
) -> None:
    """Record a completed operation's bounded actual spend exactly once."""

    with _AUTHORIZATION_LOCK:
        record, item = _reservation_for(authority, reservation)
        try:
            actual_cost = _usd_decimal(actual_cost_usd)
        except ValueError:
            actual_cost = Decimal("-1")
        if actual_cost < 0 or actual_cost > item.upper_bound_usd:
            _settle_reservation(
                record, reservation, item, item.upper_bound_usd
            )
            record.cancelled = True
            raise ExperimentAuthorizationError("full execution actual cost is invalid")
        _settle_reservation(record, reservation, item, actual_cost)


def fail_full_execution_operation(
    authority: FullExecutionAuthorization,
    reservation: FullExecutionReservation,
) -> None:
    """Conservatively settle a failed operation and close the authority."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority, require_active=False)
        if not isinstance(reservation, FullExecutionReservation):
            raise ExperimentAuthorizationError("full execution reservation is invalid")
        token = getattr(reservation, "_reservation_token", None)
        if type(token) is not str:
            raise ExperimentAuthorizationError("full execution reservation is invalid")
        settled = record.settled_reservations.get(token)
        if (
            settled is not None
            and settled.issuer is reservation
            and reservation._authorization_token == record.snapshot.issuance_token
        ):
            return
        record, item = _reservation_for(authority, reservation)
        _settle_reservation(record, reservation, item, item.upper_bound_usd)
        record.cancelled = True


def cancel_full_execution_authorization(
    authority: FullExecutionAuthorization,
) -> None:
    """Prevent future reservations while retaining every active spend bound."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority, require_active=False)
        if record.finalized:
            raise ExperimentAuthorizationError(
                "full execution authorization is inactive"
            )
        record.cancelled = True


def _consumed_authorized_output_identity(
    authorization: FullExecutionAuthorization,
    scope_id: str,
) -> tuple[Path, int, int]:
    """Return one exact child identity after its capability is consumed."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authorization)
        output = _validate_scope_output(record, scope_id)
        if scope_id not in record.consumed_scopes:
            raise ExperimentAuthorizationError(
                "full execution authorization is invalid"
            )
        return output.path, output.device, output.inode


def consumed_full_execution_authorization_snapshot(
    authorization: FullExecutionAuthorization,
) -> dict[str, object]:
    """Return a body-free receipt after every scope and reservation is settled."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authorization, require_active=False)
        snapshot = record.snapshot
        if record.consumed_scopes != set(snapshot.authorized_scope_ids):
            raise ExperimentAuthorizationError(
                "full execution authorization is not fully consumed"
            )
        for scope_id in snapshot.authorized_scope_ids:
            _validate_scope_output(record, scope_id)
        _validate_output_identity(record.manifest_output, "manifest output")
        if (
            record.active_reservations
            or record.reserved_agent_operations
            or record.reserved_judge_operations
            or record.reserved_cost_usd
        ):
            raise ExperimentAuthorizationError(
                "full execution authorization has active reservations"
            )
        record.finalized = True
        record.settled_reservations.clear()
        return _full_execution_receipt(
            record,
            schema="dci.full-execution-authorization-receipt/v1",
        )


def cancel_full_execution_authorization_snapshot(
    authorization: FullExecutionAuthorization,
) -> dict[str, object]:
    """Cancel an authority and return its conservative body-free cost ledger."""

    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authorization, require_active=False)
        if record.finalized:
            raise ExperimentAuthorizationError(
                "full execution authorization is inactive"
            )
        cost_evidence = "upper-bound" if record.active_reservations else "actual"
        for item in tuple(record.active_reservations.values()):
            _settle_reservation(record, item.issuer, item, item.upper_bound_usd)
        record.cancelled = True
        snapshot = record.snapshot
        for scope_id in snapshot.authorized_scope_ids:
            _validate_scope_output(record, scope_id)
        _validate_output_identity(record.manifest_output, "manifest output")
        record.finalized = True
        record.settled_reservations.clear()
        receipt = _full_execution_receipt(
            record,
            schema="dci.full-execution-authorization-cancellation-receipt/v1",
        )
        receipt["cost_evidence"] = cost_evidence
        return receipt


def _full_execution_receipt(
    record: _AuthorizationRecord,
    *,
    schema: str,
) -> dict[str, object]:
    snapshot = record.snapshot
    return {
            "schema": schema,
            "profile_id": snapshot.profile_id,
            "profile_sha256": snapshot.profile_sha256,
            "dataset_inventory_sha256": snapshot.dataset_inventory_sha256,
            "experiment_scopes_sha256": snapshot.experiment_scopes_sha256,
            "authorized_scope_ids": list(snapshot.authorized_scope_ids),
            "selected_ids_sha256": list(snapshot.selected_ids_sha256),
            "bounded_selected_ids_sha256": list(
                snapshot.bounded_selected_ids_sha256
            ),
            "selected_query_counts": list(snapshot.selected_query_counts),
            "planned_agent_operations": snapshot.planned_agent_operations,
            "planned_judge_operations": snapshot.planned_judge_operations,
            "output_root_device": snapshot.output_root_device,
            "output_root_inode": snapshot.output_root_inode,
            "estimated_budget_usd": snapshot.estimated_budget_usd,
            "invocation_authorized": snapshot.invocation_authorized,
            "max_agent_operations": snapshot.max_agent_operations,
            "max_judge_operations": snapshot.max_judge_operations,
            "max_cost_usd": snapshot.max_cost_usd,
            "max_agent_cost_per_operation_usd": (
                snapshot.max_agent_cost_per_operation_usd
            ),
            "max_judge_cost_per_operation_usd": (
                snapshot.max_judge_cost_per_operation_usd
            ),
            "ledger": {
                "reserved_agent_operations": record.reserved_agent_operations,
                "reserved_judge_operations": record.reserved_judge_operations,
                "completed_agent_operations": record.completed_agent_operations,
                "completed_judge_operations": record.completed_judge_operations,
                "reserved_cost_usd": float(record.reserved_cost_usd),
                "actual_cost_usd": float(record.actual_cost_usd),
                "cancelled": record.cancelled,
                "finalized": record.finalized,
            },
        }
