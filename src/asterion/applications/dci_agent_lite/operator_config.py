"""Private operator configuration for the DCI application adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import dotenv_values

from asterion.capabilities.dci.implementation.benchmark_bindings import (
    create_benchmark_bindings,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)
from asterion.capabilities.dci_research.provider import (
    create_provider as create_dci_provider,
)
from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "dci.local"
SOURCE_KIND = "local-directory"

_DATASET_PREFIX = "ASTERION_DCI_DATASET_"
_CORPUS_PREFIX = "ASTERION_DCI_CORPUS_"
_AMOUNT_KEY = "ASTERION_DCI_AMOUNT"


class DciOperatorConfigError(ValueError):
    """Raised when private DCI operator configuration is invalid."""


@dataclass(frozen=True, slots=True)
class DciOperatorCapabilityPackageSource:
    """Exact local DCI package source carrying private benchmark inputs."""

    operator_inputs: DciBenchmarkOperatorInputs
    payload_root: Path

    @classmethod
    def create(
        cls,
        operator_inputs: DciBenchmarkOperatorInputs,
    ) -> "DciOperatorCapabilityPackageSource":
        payload_root = (
            Path(__file__).resolve().parents[2] / "capabilities/dci/payload"
        )
        return cls(operator_inputs=operator_inputs, payload_root=payload_root)

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        return (
            CapabilityPackageCandidate(
                package_ref=PACKAGE_REF,
                source_id=SOURCE_ID,
                source_kind=SOURCE_KIND,
                payload_sha256=None,
                metadata={},
            ),
        )

    def open_payload(
        self, candidate: CapabilityPackageCandidate
    ) -> PortableCapabilityPayload:
        self._require_candidate(candidate)
        payload = open_portable_payload(self.payload_root)
        self.validate_source_identity(candidate, payload)
        return payload

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        self._require_candidate(candidate)
        if (
            not isinstance(payload, PortableCapabilityPayload)
            or payload.manifest.package_ref != PACKAGE_REF
        ):
            raise DciOperatorConfigError("DCI package source identity is invalid")

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        self._require_candidate(candidate)
        installed = create_dci_provider()
        return replace(
            installed,
            benchmark_bindings=create_benchmark_bindings(self.operator_inputs),
        )

    def _require_candidate(self, candidate: CapabilityPackageCandidate) -> None:
        if (
            not isinstance(candidate, CapabilityPackageCandidate)
            or candidate.package_ref != PACKAGE_REF
            or candidate.source_id != SOURCE_ID
            or candidate.source_kind != SOURCE_KIND
            or candidate.payload_sha256 is not None
            or candidate.metadata
        ):
            raise DciOperatorConfigError("DCI package source selection is invalid")


def load_operator_inputs(
    *,
    operator_root: Path,
    env_file: Path | None = None,
    dataset_roots: Mapping[str, Path] | None = None,
    corpus_roots: Mapping[str, Path] | None = None,
    private_environment: Mapping[str, str] | None = None,
    amount: Decimal | str | None = None,
) -> DciBenchmarkOperatorInputs:
    """Translate DCI-specific private values into benchmark operator inputs."""

    root = Path(operator_root).resolve()
    loaded = _load_env(root, env_file)
    datasets = _path_roots(loaded, prefix=_DATASET_PREFIX)
    corpora = _path_roots(loaded, prefix=_CORPUS_PREFIX)
    datasets.update(_explicit_paths(dataset_roots))
    corpora.update(_explicit_paths(corpus_roots))
    private = dict(loaded)
    private.update({} if private_environment is None else private_environment)
    private_amount = _amount(amount if amount is not None else loaded.get(_AMOUNT_KEY))
    return DciBenchmarkOperatorInputs(
        dataset_roots=datasets,
        corpus_roots=corpora,
        private_environment=private,
        amount=private_amount,
    )


def preflight_host_services(
    operator_inputs: DciBenchmarkOperatorInputs,
) -> dict[str, object]:
    """Return a redacted readiness report for private DCI host values."""

    if type(operator_inputs) is not DciBenchmarkOperatorInputs:
        raise DciOperatorConfigError("DCI operator inputs are invalid")
    return {
        "schema": "asterion.dci.operator-preflight/v1",
        "status": "ready",
        "dataset_roots": sorted(operator_inputs.dataset_roots),
        "corpus_roots": sorted(operator_inputs.corpus_roots),
        "private_environment": sorted(operator_inputs.private_environment),
        "amount_present": operator_inputs.amount is not None,
    }


def render_preflight(report: Mapping[str, object]) -> str:
    """Render only public, redacted preflight fields."""

    return json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n"


def _load_env(root: Path, env_file: Path | None) -> dict[str, str]:
    path = root / ".env" if env_file is None else Path(env_file).expanduser()
    if not path.is_file():
        return {}
    values = dotenv_values(path)
    return {str(key): str(value) for key, value in values.items() if value is not None}


def _path_roots(values: Mapping[str, str], *, prefix: str) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for name, value in values.items():
        if not name.startswith(prefix) or not value:
            continue
        roots[_root_key(name.removeprefix(prefix))] = Path(value).expanduser()
    return roots


def _explicit_paths(values: Mapping[str, Path] | None) -> dict[str, Path]:
    if values is None:
        return {}
    return {_root_key(key): Path(value).expanduser() for key, value in values.items()}


def _root_key(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    if not key:
        raise DciOperatorConfigError("DCI operator root key is invalid")
    return key


def _amount(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise DciOperatorConfigError("DCI amount is invalid")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise DciOperatorConfigError("DCI amount is invalid") from None


def process_environment_inputs(operator_root: Path) -> DciBenchmarkOperatorInputs:
    """Create inputs from inherited environment without serializing values."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(_DATASET_PREFIX)
        or key.startswith(_CORPUS_PREFIX)
        or key.startswith("ASTERION_DCI_")
        or key.startswith("DCI_")
    }
    datasets = _path_roots(environment, prefix=_DATASET_PREFIX)
    corpora = _path_roots(environment, prefix=_CORPUS_PREFIX)
    return DciBenchmarkOperatorInputs(
        dataset_roots=datasets,
        corpus_roots=corpora,
        private_environment=environment,
        amount=_amount(environment.get(_AMOUNT_KEY)),
    )
