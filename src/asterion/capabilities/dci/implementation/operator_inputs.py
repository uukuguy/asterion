"""Operator-owned private inputs for DCI benchmark task bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType


_RESOURCE_PATHS = {
    "bcplus.level3": (
        "data/bcplus_qa.jsonl",
        "corpus/bc_plus_docs",
    ),
    "bcplus.main": (
        "data/bcplus_qa.jsonl",
        "corpus/bc_plus_docs",
    ),
    "beir.arguana": (
        "data/dci-bench/data/beir_arguana/test.jsonl",
        "corpus/beir/arguana",
    ),
    "beir.scifact": (
        "data/dci-bench/data/beir_scifact/test.jsonl",
        "corpus/beir/scifact",
    ),
    "bright.biology": (
        "data/dci-bench/data/bright_biology/bright_biology.jsonl",
        "corpus/bright_corpus/biology",
    ),
    "bright.earth-science": (
        "data/dci-bench/data/bright_earth_science/bright_earth_science.jsonl",
        "corpus/bright_corpus/earth_science",
    ),
    "bright.economics": (
        "data/dci-bench/data/bright_economics/economics_full.jsonl",
        "corpus/bright_corpus/economics",
    ),
    "bright.robotics": (
        "data/dci-bench/data/bright_robotics/bright_robotics.jsonl",
        "corpus/bright_corpus/robotics",
    ),
    "qa.2wikimultihopqa": (
        "data/dci-bench/data/2wikimultihopqa/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.bamboogle.github-sample50": (
        "data/dci-bench/data/bamboogle/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.bamboogle.paper-full125": (
        "paper-full/data/bamboogle/test-125.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.hotpotqa": (
        "data/dci-bench/data/hotpotqa/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.musique": (
        "data/dci-bench/data/musique/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.nq": (
        "data/dci-bench/data/nq/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.triviaqa": (
        "data/dci-bench/data/triviaqa/test.jsonl",
        "corpus/wiki_corpus",
    ),
}


class DciBenchmarkOperatorInputError(ValueError):
    """Raised when private DCI benchmark inputs are malformed."""


@dataclass(frozen=True, slots=True)
class DciBenchmarkOperatorInputs:
    """Immutable operator inputs that never enter portable or public values."""

    dataset_roots: Mapping[str, Path] = field(repr=False)
    corpus_roots: Mapping[str, Path] = field(repr=False)
    private_environment: Mapping[str, str] = field(repr=False)
    amount: Decimal | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dataset_roots",
            _snapshot_paths(self.dataset_roots),
        )
        object.__setattr__(
            self,
            "corpus_roots",
            _snapshot_paths(self.corpus_roots),
        )
        object.__setattr__(
            self,
            "private_environment",
            _snapshot_environment(self.private_environment),
        )
        if self.amount is not None and (
            type(self.amount) is not Decimal
            or not self.amount.is_finite()
            or self.amount < 0
        ):
            raise DciBenchmarkOperatorInputError(
                "DCI benchmark operator input is invalid"
            )

    @classmethod
    def from_resource_root(
        cls,
        resource_root: Path,
        *,
        private_environment: Mapping[str, str],
        amount: Decimal | None = None,
    ) -> DciBenchmarkOperatorInputs:
        """Bind canonical DCI dataset and corpus contracts below one private root."""

        root = _absolute_path(resource_root)
        return cls(
            dataset_roots={
                task_id: root / dataset
                for task_id, (dataset, _) in _RESOURCE_PATHS.items()
            },
            corpus_roots={
                task_id: root / corpus
                for task_id, (_, corpus) in _RESOURCE_PATHS.items()
            },
            private_environment=private_environment,
            amount=amount,
        )


def create_local_fixture_operator_inputs(
    private_root: Path,
) -> DciBenchmarkOperatorInputs:
    """Create deterministic descriptor-only inputs without reading external data."""

    root = _absolute_path(private_root) / "fixture-inputs"
    return DciBenchmarkOperatorInputs(
        dataset_roots={
            task_id: root / task_id / "dataset.jsonl"
            for task_id in _RESOURCE_PATHS
        },
        corpus_roots={
            task_id: root / task_id / "corpus"
            for task_id in _RESOURCE_PATHS
        },
        private_environment={},
    )


def _snapshot_paths(values: Mapping[str, Path]) -> Mapping[str, Path]:
    if not isinstance(values, Mapping):
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        )
    try:
        snapshot = {
            key: _absolute_path(value)
            for key, value in sorted(values.items())
            if type(key) is str and key
        }
    except DciBenchmarkOperatorInputError:
        raise
    except Exception:
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        ) from None
    if len(snapshot) != len(values):
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        )
    return MappingProxyType(snapshot)


def _snapshot_environment(values: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(values, Mapping):
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        )
    try:
        snapshot = {
            key: value
            for key, value in sorted(values.items())
            if type(key) is str
            and key
            and "\x00" not in key
            and type(value) is str
            and "\x00" not in value
        }
    except Exception:
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        ) from None
    if len(snapshot) != len(values):
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        )
    return MappingProxyType(snapshot)


def _absolute_path(value: object) -> Path:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or ".." in value.parts
    ):
        raise DciBenchmarkOperatorInputError(
            "DCI benchmark operator input is invalid"
        )
    return value


__all__ = (
    "DciBenchmarkOperatorInputError",
    "DciBenchmarkOperatorInputs",
    "create_local_fixture_operator_inputs",
)
