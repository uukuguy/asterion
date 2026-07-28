"""Private operator configuration for the DCI application adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import replace
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
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilityPackageSource,
    BuiltinCapabilityRegistration,
)


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "builtin:dci@1.0.0"
SOURCE_KIND = "builtin"

_DATASET_PREFIX = "ASTERION_DCI_DATASET_"
_CORPUS_PREFIX = "ASTERION_DCI_CORPUS_"
_AMOUNT_KEY = "ASTERION_DCI_AMOUNT"
_REQUIRED_DATASET_ROOTS = ("bcplus", "beir", "bright", "paper-full", "qa")
_REQUIRED_CORPUS_ROOTS = ("bcplus", "beir", "bright", "wiki")


class DciOperatorConfigError(ValueError):
    """Raised when private DCI operator configuration is invalid."""


def create_capability_package_source(
    operator_inputs: DciBenchmarkOperatorInputs,
) -> BuiltinCapabilityPackageSource:
    """Create the generic built-in source registration for the DCI package."""

    if type(operator_inputs) is not DciBenchmarkOperatorInputs:
        raise DciOperatorConfigError("DCI operator inputs are invalid")
    payload_root = Path(__file__).resolve().parents[2] / "capabilities/dci/payload"

    def provider_factory() -> InstalledCapabilityPackage:
        installed = create_dci_provider()
        return replace(
            installed,
            source_id=SOURCE_ID,
            source_kind=SOURCE_KIND,
            benchmark_bindings=create_benchmark_bindings(operator_inputs),
        )

    return BuiltinCapabilityPackageSource(
        (
            BuiltinCapabilityRegistration(
                PACKAGE_REF,
                payload_root,
                provider_factory,
            ),
        )
    )


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
    loaded, env_root = _load_env(root, env_file)
    datasets = _path_roots(loaded, prefix=_DATASET_PREFIX, base=env_root)
    corpora = _path_roots(loaded, prefix=_CORPUS_PREFIX, base=env_root)
    datasets.update(_explicit_paths(dataset_roots, base=root))
    corpora.update(_explicit_paths(corpus_roots, base=root))
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
    _require_complete_roots(
        operator_inputs.dataset_roots,
        required=_REQUIRED_DATASET_ROOTS,
    )
    _require_complete_roots(
        operator_inputs.corpus_roots,
        required=_REQUIRED_CORPUS_ROOTS,
    )
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


def _load_env(root: Path, env_file: Path | None) -> tuple[dict[str, str], Path]:
    path = root / ".env" if env_file is None else Path(env_file).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    if not path.is_file():
        return {}, path.parent
    values = dotenv_values(path)
    return (
        {str(key): str(value) for key, value in values.items() if value is not None},
        path.parent,
    )


def _path_roots(
    values: Mapping[str, str],
    *,
    prefix: str,
    base: Path,
) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for name, value in values.items():
        if not name.startswith(prefix) or not value:
            continue
        roots[_root_key(name.removeprefix(prefix))] = _root_path(value, base=base)
    return roots


def _explicit_paths(
    values: Mapping[str, Path] | None,
    *,
    base: Path,
) -> dict[str, Path]:
    if values is None:
        return {}
    return {_root_key(key): _root_path(value, base=base) for key, value in values.items()}


def _root_path(value: Path | str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _require_complete_roots(
    roots: Mapping[str, Path],
    *,
    required: tuple[str, ...],
) -> None:
    if any(key not in roots for key in required):
        raise DciOperatorConfigError("DCI operator roots are incomplete")
    for key in required:
        if not _is_safe_directory(roots[key]):
            raise DciOperatorConfigError("DCI operator root is unavailable")


def _is_safe_directory(path: Path) -> bool:
    try:
        candidate = Path(path)
        return (
            not candidate.is_symlink()
            and candidate.is_dir()
            and os.access(candidate, os.R_OK | os.X_OK)
        )
    except (OSError, TypeError, ValueError):
        return False


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

    root = Path(operator_root).resolve()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(_DATASET_PREFIX)
        or key.startswith(_CORPUS_PREFIX)
        or key.startswith("ASTERION_DCI_")
        or key.startswith("DCI_")
    }
    datasets = _path_roots(environment, prefix=_DATASET_PREFIX, base=root)
    corpora = _path_roots(environment, prefix=_CORPUS_PREFIX, base=root)
    return DciBenchmarkOperatorInputs(
        dataset_roots=datasets,
        corpus_roots=corpora,
        private_environment=environment,
        amount=_amount(environment.get(_AMOUNT_KEY)),
    )
