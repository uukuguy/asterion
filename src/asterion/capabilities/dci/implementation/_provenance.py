"""Package-owned DCI complete implementation identity."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from importlib import resources
from pathlib import PurePosixPath


DCI_COMPLETE_IMPLEMENTATION_RESOURCES: tuple[str, ...] = tuple(sorted((
    "capabilities/dci/implementation/_analysis.py",
    "capabilities/dci/implementation/_artifacts.py",
    "capabilities/dci/implementation/_provenance.py",
    "capabilities/dci/implementation/_runtime.py",
    "capabilities/dci/implementation/complete.py",
    "capabilities/dci/implementation/implementation.py",
    "capabilities/dci/implementation/pathlight/coverage.py",
    "capabilities/dci/implementation/reproduction/ablation.py",
    "capabilities/dci/implementation/evaluation/analysis.py",
    "capabilities/dci/implementation/evaluation/artifacts.py",
    "capabilities/dci/implementation/evaluation/benchmark.py",
    "capabilities/dci/implementation/runtime/bridge.py",
    "capabilities/dci/implementation/config.py",
    "capabilities/dci/implementation/research/context_extension.py",
    "capabilities/dci/implementation/research/context_profiles.py",
    "capabilities/dci/implementation/datasets.py",
    "capabilities/dci/implementation/evaluation/evaluation.py",
    "capabilities/dci/implementation/research/experiment_profiles.py",
    "capabilities/dci/implementation/evaluation/judge.py",
    "capabilities/dci/implementation/evaluation/metrics.py",
    "capabilities/dci/implementation/reproduction/paper_benchmarks.py",
    "capabilities/dci/implementation/runtime/pi_rpc.py",
    "capabilities/dci/implementation/research/prompts.py",
    "capabilities/dci/implementation/reproduction/provenance.py",
    "capabilities/dci/implementation/reproduction/reproduction.py",
    "capabilities/dci/implementation/evaluation/resolution_metrics.py",
    "capabilities/dci/payload/capabilities/dci-analysis.json",
    "capabilities/dci/payload/capabilities/dci-benchmark.json",
    "capabilities/dci/payload/capabilities/dci-evaluation.json",
    "capabilities/dci/payload/capabilities/dci-export.json",
    "capabilities/dci/payload/capabilities/dci-research.json",
    "capabilities/dci/payload/capabilities/local-corpus-policy.json",
    "capabilities/dci/resources/batch-profiles.json",
    "capabilities/dci/resources/context-profile.schema.json",
    "capabilities/dci/resources/context-profiles.json",
    "capabilities/dci/resources/experiment-profile.schema.json",
    "capabilities/dci/resources/experiment-profiles.json",
    "capabilities/dci/resources/gold-document-manifest.schema.json",
    "capabilities/dci/resources/gold-document-registry.schema.json",
    "capabilities/dci/resources/retrieval-coverage-manifest.schema.json",
    "capabilities/dci/resources/retrieval-coverage-registry.schema.json",
    "capabilities/dci/resources/paper-ablation-matrix.json",
    "capabilities/dci/resources/paper-ablation.schema.json",
    "capabilities/dci/resources/paper-benchmark.schema.json",
    "capabilities/dci/resources/paper-benchmarks.json",
    "capabilities/dci/resources/paper-bounded-corpus-manifests.json",
    "capabilities/dci/resources/paper-bounded-fixtures.json",
    "capabilities/dci/resources/paper-experiment-scope.schema.json",
    "capabilities/dci/resources/paper-experiment-scopes.json",
    "capabilities/dci/resources/paper-fixtures/corpora/base-plus-one/distractor-1.txt",
    "capabilities/dci/resources/paper-fixtures/corpora/base-plus-one/doc.txt",
    "capabilities/dci/resources/paper-fixtures/corpora/base-plus-two/distractor-1.txt",
    "capabilities/dci/resources/paper-fixtures/corpora/base-plus-two/distractor-2.txt",
    "capabilities/dci/resources/paper-fixtures/corpora/base-plus-two/doc.txt",
    "capabilities/dci/resources/paper-fixtures/corpora/base/doc.txt",
    "capabilities/dci/resources/paper-fixtures/corpus/doc.txt",
    "capabilities/dci/resources/paper-fixtures/gold/qa-manifest.json",
    "capabilities/dci/resources/paper-fixtures/gold/qa-registry.json",
    "capabilities/dci/resources/paper-fixtures/ir.jsonl",
    "capabilities/dci/resources/paper-fixtures/qa.jsonl",
    "capabilities/dci/resources/paper-selected-id-manifests.json",
    "capabilities/dci/resources/pi/context-extension-manifest.json",
    "capabilities/dci/resources/pi/dci-context-extension.ts",
    "capabilities/dci/resources/pi/dci-pathlight-observation.ts",
    "capabilities/dci/resources/pi/pathlight-observation-manifest.json",
    "capabilities/dci/resources/reproduction-result.schema.json",
    "capabilities/dci/resources/reproduction-target.schema.json",
    "capabilities/dci/resources/reproduction-targets.json",
    "capabilities/dci/resources/trajectory-resolution.schema.json",
    "capabilities/dci/resources/trajectory-resolution-coverage-summary.schema.json",
    "capabilities/dci/implementation/runtime/run.py",
    "capabilities/dci/implementation/services.py",
    "capabilities/dci/implementation/research/trajectory_resolution.py",
    "capabilities/dci/implementation/reproduction/verification.py",
)))
_IMPLEMENTATION_IDENTITY_DOMAIN = b"asterion.dci.implementation/v1\x00"


def dci_complete_implementation_identity(
    *,
    resource_reader: Callable[[str], bytes] | None = None,
    resource_names: Iterable[str] = DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
) -> str:
    try:
        names = tuple(resource_names)
    except Exception:
        raise ValueError("DCI implementation resource closure is invalid") from None
    if (
        len(names) != len(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)
        or any(not _canonical_resource_name(name) for name in names)
        or len(set(names)) != len(names)
        or set(names) != set(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)
    ):
        raise ValueError("DCI implementation resource closure is invalid")
    reader = resource_reader or _read_implementation_resource
    digest = hashlib.sha256(_IMPLEMENTATION_IDENTITY_DOMAIN)
    try:
        for name in sorted(names):
            raw = reader(name)
            if type(raw) is not bytes:
                raise TypeError
            encoded = name.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    except Exception:
        raise ValueError(
            "DCI implementation resource closure is unavailable"
        ) from None
    return digest.hexdigest()


def _canonical_resource_name(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _read_implementation_resource(name: str) -> bytes:
    return resources.files("asterion").joinpath(name).read_bytes()


__all__ = (
    "DCI_COMPLETE_IMPLEMENTATION_RESOURCES",
    "dci_complete_implementation_identity",
)
