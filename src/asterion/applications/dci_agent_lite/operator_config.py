"""Application-owned translation of private DCI operator configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import os
from pathlib import Path
from types import MappingProxyType

from dotenv import dotenv_values

from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)


_COVERAGE_TASK_IDS = (
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
)
_DOTENV_RELATIVE_PATH_KEYS = (
    "ASTERION_DCI_PI_AGENT_DIR",
    "ASTERION_DCI_PI_DIR",
    "ASTERION_DCI_PI_PACKAGE_DIR",
    "DCI_PI_AGENT_DIR",
    "DCI_PI_DIR",
    "DCI_PI_PACKAGE_DIR",
)


@dataclass(frozen=True, slots=True)
class DciOperatorConfig:
    """Private inputs and host options resolved by the DCI application."""

    repo_root: Path = field(repr=False)
    benchmark_inputs: DciBenchmarkOperatorInputs = field(repr=False)
    host_service_options: Mapping[str, Mapping[str, str]] = field(repr=False)
    max_native_attempts: int | None = None

    def public_summary(self) -> dict[str, object]:
        """Return a body-free readiness summary safe for public presentation."""

        return {
            "amount_configured": self.benchmark_inputs.amount is not None,
            "benchmark_task_count": len(self.benchmark_inputs.dataset_roots),
            "host_service_ids": sorted(self.host_service_options),
            "max_native_attempts": self.max_native_attempts,
        }


def load_operator_config(
    repo_root: Path,
    *,
    env_file: Path | None = None,
    environment: Mapping[str, str] | None = None,
    resource_root: Path | None = None,
    amount: Decimal | None = None,
    max_native_attempts: int | None = None,
) -> DciOperatorConfig:
    """Translate DCI environment aliases into private package and host inputs."""

    if max_native_attempts is not None and (
        type(max_native_attempts) is not int or max_native_attempts != 1
    ):
        raise ValueError("DCI operator native attempt limit is invalid")
    root = Path(repo_root).resolve()
    process = dict(os.environ if environment is None else environment)
    env_path = root / ".env" if env_file is None else Path(env_file).resolve()
    if env_file is None and not env_path.is_file():
        resource_value = process.get("ASTERION_DCI_RESOURCE_ROOT", "").strip()
        if resource_value:
            resource_root = Path(resource_value).expanduser()
            if not resource_root.is_absolute():
                resource_root = root / resource_root
            resource_env = resource_root.resolve() / ".env"
            if resource_env.is_file():
                env_path = resource_env
    dotenv = (
        {
            key: value
            for key, value in dotenv_values(env_path).items()
            if value is not None
        }
        if env_path.is_file()
        else {}
    )
    merged = {**dotenv, **process}
    for name in _DOTENV_RELATIVE_PATH_KEYS:
        if name not in dotenv or (
            name in process and process[name] != dotenv[name]
        ):
            continue
        value = merged[name].strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = env_path.parent / path
        merged[name] = os.path.normpath(path)
    private_environment = dict(merged)
    selected_root = (
        resource_root
        if resource_root is not None
        else Path(merged.get("ASTERION_DCI_RESOURCE_ROOT", root))
    )
    if not selected_root.is_absolute():
        selected_root = root / selected_root
    selected_root = selected_root.resolve()
    benchmark_inputs = DciBenchmarkOperatorInputs.from_resource_root(
        selected_root,
        private_environment=private_environment,
        amount=amount,
    )
    coverage_value = merged.get("ASTERION_DCI_COVERAGE_ROOT")
    if coverage_value is not None and coverage_value.strip():
        coverage_root = Path(coverage_value)
        if not coverage_root.is_absolute():
            coverage_root = root / coverage_root
        coverage_root = Path(
            os.path.abspath(os.path.normpath(coverage_root))
        )
        benchmark_inputs = DciBenchmarkOperatorInputs(
            dataset_roots=benchmark_inputs.dataset_roots,
            corpus_roots=benchmark_inputs.corpus_roots,
            private_environment=benchmark_inputs.private_environment,
            coverage_registry_roots={
                task_id: coverage_root / task_id / "registry.json"
                for task_id in _COVERAGE_TASK_IDS
            },
            amount=benchmark_inputs.amount,
        )
    corpus_root = _configured_path(
        merged.get("ASTERION_DCI_CORPUS_ROOT"),
        default=selected_root / "corpus",
        relative_to=root,
    )
    return DciOperatorConfig(
        repo_root=root,
        benchmark_inputs=benchmark_inputs,
        host_service_options=MappingProxyType(
            {"corpus.local-root": MappingProxyType({"root": str(corpus_root)})}
        ),
        max_native_attempts=max_native_attempts,
    )


def _configured_path(
    value: str | None,
    *,
    default: Path,
    relative_to: Path,
) -> Path:
    path = default if value is None or not value.strip() else Path(value)
    if not path.is_absolute():
        path = relative_to / path
    return path.resolve()


__all__ = (
    "DciOperatorConfig",
    "load_operator_config",
)
