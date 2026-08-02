"""Provider-free recovery and diagnosis commands for historical DCI evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from asterion.capabilities.dci.implementation.pathlight.conversion import (
    recovered_run_to_evaluation_bundle,
    recovered_run_to_experiment,
)
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    diagnose_recommended_pack,
    render_chinese_diagnosis,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DCI_RECOVERY_FILENAME,
    DciRecoveredRun,
    read_completed_dci_run,
    read_recovered_run,
    validate_recovered_run,
    write_recovered_run,
)
from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.diagnosis import (
    DIAGNOSIS_BUNDLE_FILENAME,
    write_diagnosis_bundle,
)
from asterion.pathlight.evaluation import (
    EVALUATION_BUNDLE_FILENAME,
    EvaluationBundle,
    read_evaluation_bundle,
    write_evaluation_bundle,
)
from asterion.pathlight.experiment import (
    EXPERIMENT_BUNDLE_FILENAME,
    read_experiment_bundle,
    write_experiment_bundle,
)


_ERROR = "asterion-dci: command failed\n"
_MARKDOWN_FILENAME = "pathlight-dci-diagnosis.zh-CN.md"
_RECOVERY_LIMIT = 1 << 20
_TARGET_DATASETS = {
    "dci.beir.scifact@1.0.0": "beir.scifact",
    "dci.bright.biology@1.0.0": "bright.biology",
    "dci.bright.earth-science@1.0.0": "bright.earth-science",
    "dci.bright.economics@1.0.0": "bright.economics",
    "dci.bright.robotics@1.0.0": "bright.robotics",
    "dci.qa.bamboogle@1.0.0": "qa.bamboogle",
}
_TARGET_DATASET_IDS = tuple(sorted(_TARGET_DATASETS.values()))


def main(arguments: Sequence[str], *, stdout: TextIO, stderr: TextIO) -> int:
    """Run one fixed DCI Pathlight command without touching application providers."""

    try:
        values = tuple(arguments)
        if not values:
            raise ValueError
        if values[0] == "recover":
            output = _recover(values[1:])
        elif values[0] == "diagnose":
            output = _diagnose(values[1:])
        else:
            raise ValueError
        stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except BaseException:
        stderr.write(_ERROR)
        return 2


def _recover(arguments: tuple[str, ...]) -> dict[str, object]:
    options = _exact_options(arguments, {"--instance", "--evidence-root", "--output-root"})
    instance = options["--instance"]
    expected_dataset_id = _TARGET_DATASETS.get(instance)
    if expected_dataset_id is None:
        raise ValueError
    evidence_root = _absolute_path(options["--evidence-root"])
    output_root = _operator_root(options["--output-root"])
    targets = _recovery_targets(output_root)
    _require_absent(tuple(targets.values()))
    recovered = read_completed_dci_run(evidence_root, expected_dataset_id)
    recovered = validate_recovered_run(recovered.to_mapping())
    experiment = recovered_run_to_experiment(recovered)
    evaluations = recovered_run_to_evaluation_bundle(recovered)
    _require_experiment_evaluation_closure(experiment, evaluations)
    try:
        write_recovered_run(recovered, targets["recovery"])
        write_experiment_bundle(experiment, targets["experiment"])
        write_evaluation_bundle(
            targets["evaluations"], evaluations.evaluations, evaluations.metric_contracts
        )
    except BaseException:
        _rollback_outputs(output_root, tuple(targets.values()))
        raise RuntimeError from None
    return {
        "case_count": recovered.selected_count,
        "dataset_digest": recovered.dataset_snapshot_sha256,
        "output_bundle_digest": experiment.bundle_sha256,
    }


def _diagnose(arguments: tuple[str, ...]) -> dict[str, object]:
    roots, output_root = _diagnose_arguments(arguments)
    targets = {
        "diagnosis": output_root / DIAGNOSIS_BUNDLE_FILENAME,
        "markdown": output_root / _MARKDOWN_FILENAME,
    }
    _require_absent(tuple(targets.values()))
    recovered = tuple(_read_verified_recovery(root) for root in roots)
    if tuple(sorted(run.dataset_id for run in recovered)) != _TARGET_DATASET_IDS:
        raise ValueError
    report = diagnose_recommended_pack(recovered)
    markdown = render_chinese_diagnosis(report)
    try:
        write_diagnosis_bundle(report.diagnosis_bundle, targets["diagnosis"])
        write_private_file(targets["markdown"], markdown.encode("utf-8"))
    except BaseException:
        _rollback_outputs(output_root, tuple(targets.values()))
        raise RuntimeError from None
    return {
        "case_count": report.total_case_count,
        "dataset_digest": _cohort_digest(recovered),
        "output_bundle_digest": report.diagnosis_bundle.bundle_sha256,
    }


def _read_verified_recovery(root: Path):
    targets = _recovery_targets(root)
    _require_private_files(tuple(targets.values()))
    recovered = read_recovered_run(targets["recovery"])
    recovered = validate_recovered_run(recovered.to_mapping())
    experiment = recovered_run_to_experiment(recovered)
    evaluations = recovered_run_to_evaluation_bundle(recovered)
    _require_experiment_evaluation_closure(experiment, evaluations)
    stored_experiment = read_experiment_bundle(targets["experiment"])
    stored_evaluations = read_evaluation_bundle(targets["evaluations"])
    if (
        not hmac.compare_digest(
            _canonical_bytes(stored_experiment.to_mapping()),
            _canonical_bytes(experiment.to_mapping()),
        )
        or not hmac.compare_digest(
            _canonical_bytes(_stored_evaluations_to_mapping(stored_evaluations)),
            _canonical_bytes(_stored_evaluations_to_mapping(evaluations)),
        )
    ):
        raise ValueError
    for path, expected in (
        (targets["recovery"], recovered.to_mapping()),
        (targets["experiment"], experiment.to_mapping()),
        (targets["evaluations"], _stored_evaluations_to_mapping(evaluations)),
    ):
        if not hmac.compare_digest(read_private_file(path, _RECOVERY_LIMIT), _canonical_bytes(expected)):
            raise ValueError
    return recovered


def _require_experiment_evaluation_closure(experiment: object, evaluations: object) -> None:
    experiment_records = getattr(experiment, "evaluations", None)
    evaluation_records = getattr(evaluations, "evaluations", None)
    contracts = getattr(evaluations, "metric_contracts", None)
    if (
        type(experiment_records) is not tuple
        or type(evaluation_records) is not tuple
        or type(contracts) is not tuple
        or tuple(record.evaluation_sha256 for record in experiment_records)
        != tuple(record.evaluation_sha256 for record in evaluation_records)
        or len(contracts) != 1
        or any(record.metric_contract_sha256 != contracts[0].metric_contract_sha256 for record in experiment_records)
    ):
        raise ValueError


def _recovery_targets(root: Path) -> dict[str, Path]:
    return {
        "recovery": root / DCI_RECOVERY_FILENAME,
        "experiment": root / EXPERIMENT_BUNDLE_FILENAME,
        "evaluations": root / EVALUATION_BUNDLE_FILENAME,
    }


def _exact_options(arguments: tuple[str, ...], names: set[str]) -> dict[str, str]:
    if len(arguments) != len(names) * 2:
        raise ValueError
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name, value = arguments[index], arguments[index + 1]
        if type(name) is not str or type(value) is not str or name not in names or name in values or not value:
            raise ValueError
        values[name] = value
    if set(values) != names:
        raise ValueError
    return values


def _diagnose_arguments(arguments: tuple[str, ...]) -> tuple[tuple[Path, ...], Path]:
    if len(arguments) != 14:
        raise ValueError
    roots: list[Path] = []
    output: Path | None = None
    for index in range(0, len(arguments), 2):
        name, value = arguments[index], arguments[index + 1]
        if type(name) is not str or type(value) is not str or not value:
            raise ValueError
        if name == "--recovery-root":
            roots.append(_operator_root(value))
        elif name == "--output-root" and output is None:
            output = _operator_root(value)
        else:
            raise ValueError
    if output is None or len(roots) != 6 or len({str(root) for root in roots}) != 6:
        raise ValueError
    return tuple(roots), output


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if "\x00" in value or not path.is_absolute() or path != path.resolve():
        raise ValueError
    return path


def _operator_root(value: str) -> Path:
    path = _absolute_path(value)
    metadata = os.stat(path, follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or path.is_symlink()
    ):
        raise ValueError
    return path


def _require_absent(paths: Sequence[Path]) -> None:
    for path in paths:
        if not isinstance(path, Path) or path.exists() or path.is_symlink():
            raise ValueError


def _require_private_files(paths: Sequence[Path]) -> None:
    for path in paths:
        metadata = os.stat(path, follow_symlinks=False)
        if not isinstance(path, Path) or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError


def _rollback_outputs(root: Path, targets: Sequence[Path]) -> None:
    """Remove only this command's exact preflight-absent output names."""

    descriptor = -1
    failed = False
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
        descriptor = os.open(root, flags)
        before = os.fstat(descriptor)
        entry = os.stat(root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != os.getuid()
            or (before.st_dev, before.st_ino) != (entry.st_dev, entry.st_ino)
        ):
            raise OSError
        for target in targets:
            if not isinstance(target, Path) or target.parent != root or not target.name:
                raise OSError
            try:
                os.unlink(target.name, dir_fd=descriptor)
            except FileNotFoundError:
                pass
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise OSError
    except Exception:
        failed = True
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                failed = True
    if failed:
        raise RuntimeError from None


def _nofollow_flag() -> int:
    value = getattr(os, "O_NOFOLLOW", None)
    if type(value) is not int:
        raise OSError
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _stored_evaluations_to_mapping(bundle: EvaluationBundle) -> dict[str, object]:
    return {
        "schema": "asterion.pathlight-evaluations/v1",
        "metric_contracts": [item.to_mapping() for item in bundle.metric_contracts],
        "evaluations": [item.to_mapping() for item in bundle.evaluations],
        "bundle_sha256": bundle.bundle_sha256,
    }


def _cohort_digest(runs: tuple[DciRecoveredRun, ...]) -> str:
    return hashlib.sha256(
        _canonical_bytes(tuple(sorted(run.recovered_run_sha256 for run in runs)))
    ).hexdigest()


__all__ = ("main",)
