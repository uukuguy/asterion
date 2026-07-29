"""Application-owned translation of private DCI operator configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from dotenv import dotenv_values

from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)


_PRIVATE_PREFIXES = ("ASTERION_DCI_", "DCI_")


@dataclass(frozen=True, slots=True)
class DciOperatorConfig:
    """Private inputs and host options resolved by the DCI application."""

    benchmark_inputs: DciBenchmarkOperatorInputs = field(repr=False)
    host_service_options: Mapping[str, Mapping[str, str]] = field(repr=False)

    def public_summary(self) -> dict[str, object]:
        """Return a body-free readiness summary safe for public presentation."""

        return {
            "amount_configured": self.benchmark_inputs.amount is not None,
            "benchmark_task_count": len(
                self.benchmark_inputs.dataset_roots
            ),
            "host_service_ids": sorted(self.host_service_options),
        }


def load_operator_config(
    repo_root: Path,
    *,
    env_file: Path | None = None,
    environment: Mapping[str, str] | None = None,
    resource_root: Path | None = None,
    amount: Decimal | None = None,
) -> DciOperatorConfig:
    """Translate DCI environment aliases into private package and host inputs."""

    root = Path(repo_root).resolve()
    env_path = root / ".env" if env_file is None else Path(env_file).resolve()
    dotenv = (
        {
            key: value
            for key, value in dotenv_values(env_path).items()
            if value is not None
        }
        if env_path.is_file()
        else {}
    )
    process = {} if environment is None else dict(environment)
    merged = {**dotenv, **process}
    private_environment = {
        key: value
        for key, value in merged.items()
        if key.startswith(_PRIVATE_PREFIXES)
    }
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
    corpus_root = _configured_path(
        merged.get("ASTERION_DCI_CORPUS_ROOT"),
        default=selected_root / "corpus",
        relative_to=root,
    )
    return DciOperatorConfig(
        benchmark_inputs=benchmark_inputs,
        host_service_options=MappingProxyType(
            {
                "corpus.local-root": MappingProxyType(
                    {"root": str(corpus_root)}
                )
            }
        ),
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
