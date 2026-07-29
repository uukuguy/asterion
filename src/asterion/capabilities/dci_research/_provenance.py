"""Package-owned DCI complete implementation identity."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from importlib import resources
from pathlib import PurePosixPath


DCI_COMPLETE_IMPLEMENTATION_RESOURCES: tuple[str, ...] = (
    "applications/dci_agent_lite/assemblies/dci-complete-application-claude.json",
    "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
    "capabilities/dci/payload/capabilities/dci-analysis.json",
    "capabilities/dci/payload/capabilities/dci-benchmark.json",
    "capabilities/dci/payload/capabilities/dci-evaluation.json",
    "capabilities/dci/payload/capabilities/dci-export.json",
    "capabilities/dci/payload/capabilities/dci-research.json",
    "capabilities/dci/payload/capabilities/local-corpus-policy.json",
    "capabilities/dci_research/complete.py",
    "capabilities/dci_research/implementation.py",
    "dci/ablation.py",
    "dci/analysis.py",
    "dci/artifacts.py",
    "dci/benchmark.py",
    "dci/bridge.py",
    "dci/config.py",
    "dci/context_extension.py",
    "dci/context_profiles.py",
    "dci/datasets.py",
    "dci/evaluation.py",
    "dci/experiment_profiles.py",
    "dci/judge.py",
    "dci/metrics.py",
    "dci/paper_benchmarks.py",
    "dci/pi_rpc.py",
    "dci/prompts.py",
    "dci/provenance.py",
    "dci/reproduction.py",
    "dci/resolution_metrics.py",
    "dci/resources/batch-profiles.json",
    "dci/resources/context-profile.schema.json",
    "dci/resources/context-profiles.json",
    "dci/resources/experiment-profile.schema.json",
    "dci/resources/experiment-profiles.json",
    "dci/resources/gold-document-manifest.schema.json",
    "dci/resources/gold-document-registry.schema.json",
    "dci/resources/paper-ablation-matrix.json",
    "dci/resources/paper-ablation.schema.json",
    "dci/resources/paper-benchmark.schema.json",
    "dci/resources/paper-benchmarks.json",
    "dci/resources/paper-bounded-corpus-manifests.json",
    "dci/resources/paper-bounded-fixtures.json",
    "dci/resources/paper-experiment-scope.schema.json",
    "dci/resources/paper-experiment-scopes.json",
    "dci/resources/paper-fixtures/corpora/base-plus-one/distractor-1.txt",
    "dci/resources/paper-fixtures/corpora/base-plus-one/doc.txt",
    "dci/resources/paper-fixtures/corpora/base-plus-two/distractor-1.txt",
    "dci/resources/paper-fixtures/corpora/base-plus-two/distractor-2.txt",
    "dci/resources/paper-fixtures/corpora/base-plus-two/doc.txt",
    "dci/resources/paper-fixtures/corpora/base/doc.txt",
    "dci/resources/paper-fixtures/corpus/doc.txt",
    "dci/resources/paper-fixtures/gold/qa-manifest.json",
    "dci/resources/paper-fixtures/gold/qa-registry.json",
    "dci/resources/paper-fixtures/ir.jsonl",
    "dci/resources/paper-fixtures/qa.jsonl",
    "dci/resources/paper-selected-id-manifests.json",
    "dci/resources/pi/context-extension-manifest.json",
    "dci/resources/pi/dci-context-extension.ts",
    "dci/resources/reproduction-result.schema.json",
    "dci/resources/reproduction-target.schema.json",
    "dci/resources/reproduction-targets.json",
    "dci/resources/trajectory-resolution.schema.json",
    "dci/run.py",
    "dci/services.py",
    "dci/trajectory_resolution.py",
    "dci/verification.py",
)
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
