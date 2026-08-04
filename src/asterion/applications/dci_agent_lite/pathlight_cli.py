"""Provider-free recovery and diagnosis commands for historical DCI evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from asterion.benchmarks.cli import BenchmarkCommandHost
from asterion.capability_packages.sources.base import CapabilityPackageSource

from asterion.capabilities.dci.implementation.pathlight.conversion import (
    recovered_run_to_evaluation_bundle,
    recovered_run_to_experiment,
)
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    AUTHORIZATION_GATE_REPORT_FILENAME,
    DCI_DIAGNOSIS_REPORT_FILENAME,
    DciCoverageExperimentObservation,
    coverage_evaluation_values,
    diagnose_recommended_pack,
    read_authorization_gate_report,
    read_dci_diagnosis_report,
    render_chinese_diagnosis,
    write_authorization_gate_report,
    write_dci_diagnosis_report,
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
    read_diagnosis_bundle,
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


def main(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    repo_root: Path | None = None,
    env_file: Path | None = None,
    environment: Mapping[str, str] | None = None,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
    experiment_host_factory: Callable[..., BenchmarkCommandHost] | None = None,
    coverage_experiment: DciCoverageExperimentObservation | None = None,
) -> int:
    """Run one fixed DCI Pathlight command without touching application providers."""

    try:
        values = tuple(arguments)
        if not values:
            raise ValueError
        if values[0] == "experiment":
            from asterion.applications.dci_agent_lite.pathlight_experiment_cli import (
                main as experiment_main,
            )

            return experiment_main(
                values[1:],
                stdout=stdout,
                stderr=stderr,
                repo_root=(Path.cwd() if repo_root is None else repo_root),
                env_file=env_file,
                environment=environment,
                package_sources=package_sources,
                host_factory=experiment_host_factory,
            )
        if values[0] == "optimization":
            from asterion.applications.dci_agent_lite.pathlight_optimization_cli import (
                main as optimization_main,
            )

            return optimization_main(
                values[1:],
                stdout=stdout,
                stderr=stderr,
                repo_root=(Path.cwd() if repo_root is None else repo_root),
                env_file=env_file,
                environment=environment,
                package_sources=package_sources,
            )
        if values[0] == "recover":
            output = _recover(values[1:])
        elif values[0] == "diagnose":
            output = _diagnose(
                values[1:], coverage_experiment=coverage_experiment
            )
        else:
            raise ValueError
        stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except BaseException:
        stderr.write(_ERROR)
        return 2


def _recover(arguments: tuple[str, ...]) -> dict[str, object]:
    options = _exact_options(
        arguments, {"--instance", "--evidence-root", "--output-root"}
    )
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
    staging_root = _create_staging_root(output_root)
    staging_targets = _recovery_targets(staging_root)
    failed = False
    try:
        write_recovered_run(recovered, staging_targets["recovery"])
        write_experiment_bundle(experiment, staging_targets["experiment"])
        write_evaluation_bundle(
            staging_targets["evaluations"],
            evaluations.evaluations,
            evaluations.metric_contracts,
        )
        _read_verified_recovery(staging_root)
        _publish_staged_outputs(
            output_root, staging_root, tuple(path.name for path in targets.values())
        )
    except BaseException:
        failed = True
    try:
        _cleanup_staging(
            output_root,
            staging_root,
            tuple(path.name for path in staging_targets.values()),
        )
    except BaseException:
        failed = True
    if failed:
        raise RuntimeError from None
    return {
        "case_count": recovered.selected_count,
        "dataset_digest": recovered.dataset_snapshot_sha256,
        "output_bundle_digest": experiment.bundle_sha256,
    }


def _diagnose(
    arguments: tuple[str, ...],
    *,
    coverage_experiment: DciCoverageExperimentObservation | None = None,
) -> dict[str, object]:
    roots, output_root = _diagnose_arguments(arguments)
    targets = {
        "diagnosis": output_root / DIAGNOSIS_BUNDLE_FILENAME,
        "markdown": output_root / _MARKDOWN_FILENAME,
    }
    if coverage_experiment is not None:
        targets["evaluations"] = output_root / EVALUATION_BUNDLE_FILENAME
        if coverage_experiment.complete:
            targets["gate"] = output_root / AUTHORIZATION_GATE_REPORT_FILENAME
            targets["report"] = output_root / DCI_DIAGNOSIS_REPORT_FILENAME
    _require_absent(tuple(targets.values()))
    recovered = tuple(_read_verified_recovery(root) for root in roots)
    if tuple(sorted(run.dataset_id for run in recovered)) != _TARGET_DATASET_IDS:
        raise ValueError
    report = diagnose_recommended_pack(
        recovered, coverage_experiment=coverage_experiment
    )
    coverage_values = (
        None
        if coverage_experiment is None
        else coverage_evaluation_values(coverage_experiment)
    )
    markdown = render_chinese_diagnosis(report)
    staging_root = _create_staging_root(output_root)
    staging_targets = {
        "diagnosis": staging_root / DIAGNOSIS_BUNDLE_FILENAME,
        "markdown": staging_root / _MARKDOWN_FILENAME,
    }
    if coverage_experiment is not None:
        staging_targets["evaluations"] = staging_root / EVALUATION_BUNDLE_FILENAME
        if coverage_experiment.complete:
            staging_targets["gate"] = staging_root / AUTHORIZATION_GATE_REPORT_FILENAME
            staging_targets["report"] = staging_root / DCI_DIAGNOSIS_REPORT_FILENAME
    failed = False
    try:
        write_diagnosis_bundle(report.diagnosis_bundle, staging_targets["diagnosis"])
        write_private_file(staging_targets["markdown"], markdown.encode("utf-8"))
        if coverage_values is not None:
            contract, evaluations = coverage_values
            write_evaluation_bundle(
                staging_targets["evaluations"], evaluations, (contract,)
            )
        if coverage_experiment is not None and coverage_experiment.complete:
            write_dci_diagnosis_report(report, staging_targets["report"])
            write_authorization_gate_report(report, staging_targets["gate"])
        if read_diagnosis_bundle(
            staging_targets["diagnosis"]
        ) != report.diagnosis_bundle or not hmac.compare_digest(
            read_private_file(staging_targets["markdown"], 1 << 20),
            markdown.encode("utf-8"),
        ):
            raise ValueError
        if coverage_values is not None:
            stored = read_evaluation_bundle(staging_targets["evaluations"])
            if (
                stored.evaluations != coverage_values[1]
                or stored.metric_contracts != (coverage_values[0],)
            ):
                raise ValueError
        if coverage_experiment is not None and coverage_experiment.complete:
            stored_report = read_dci_diagnosis_report(staging_targets["report"])
            gate = read_authorization_gate_report(staging_targets["gate"])
            if (
                stored_report != report
                or stored_report.diagnosis_bundle != report.diagnosis_bundle
                or gate["diagnosis_bundle_sha256"]
                != report.diagnosis_bundle.bundle_sha256
                or gate["diagnosis_report_sha256"] != report.report_sha256
            ):
                raise ValueError
        _publish_staged_outputs(
            output_root, staging_root, tuple(path.name for path in targets.values())
        )
    except BaseException:
        failed = True
    try:
        _cleanup_staging(
            output_root,
            staging_root,
            tuple(path.name for path in staging_targets.values()),
        )
    except BaseException:
        failed = True
    if failed:
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
    if not hmac.compare_digest(
        _canonical_bytes(stored_experiment.to_mapping()),
        _canonical_bytes(experiment.to_mapping()),
    ) or not hmac.compare_digest(
        _canonical_bytes(_stored_evaluations_to_mapping(stored_evaluations)),
        _canonical_bytes(_stored_evaluations_to_mapping(evaluations)),
    ):
        raise ValueError
    for path, expected in (
        (targets["recovery"], recovered.to_mapping()),
        (targets["experiment"], experiment.to_mapping()),
        (targets["evaluations"], _stored_evaluations_to_mapping(evaluations)),
    ):
        if not hmac.compare_digest(
            read_private_file(path, _RECOVERY_LIMIT), _canonical_bytes(expected)
        ):
            raise ValueError
    return recovered


def _require_experiment_evaluation_closure(
    experiment: object, evaluations: object
) -> None:
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
        or any(
            record.metric_contract_sha256 != contracts[0].metric_contract_sha256
            for record in experiment_records
        )
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
        if (
            type(name) is not str
            or type(value) is not str
            or name not in names
            or name in values
            or not value
        ):
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
        if (
            not isinstance(path, Path)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ValueError


def _create_staging_root(root: Path) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=".pathlight-publish-", dir=root))
    try:
        staging.chmod(0o700)
        return _operator_root(str(staging))
    except BaseException:
        try:
            staging.rmdir()
        except Exception:
            pass
        raise RuntimeError from None


def _publish_staged_outputs(root: Path, staging: Path, names: Sequence[str]) -> None:
    root_descriptor = -1
    staging_descriptor = -1
    published: list[tuple[str, int, int]] = []
    failed = False
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
        root_descriptor = os.open(root, flags)
        staging_descriptor = os.open(staging, flags)
        _verify_open_directory(root_descriptor, root)
        _verify_open_directory(staging_descriptor, staging)
        for name in names:
            if type(name) is not str or not name or "/" in name:
                raise OSError
            source = os.stat(name, dir_fd=staging_descriptor, follow_symlinks=False)
            if (
                not stat.S_ISREG(source.st_mode)
                or stat.S_IMODE(source.st_mode) != 0o600
            ):
                raise OSError
            os.link(
                name,
                name,
                src_dir_fd=staging_descriptor,
                dst_dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            published.append((name, source.st_dev, source.st_ino))
            target = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
            if (target.st_dev, target.st_ino) != (source.st_dev, source.st_ino):
                raise OSError
    except BaseException:
        failed = True
    finally:
        for descriptor in (staging_descriptor, root_descriptor):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except Exception:
                    failed = True
    if failed:
        try:
            _rollback_published(root, published)
        except BaseException:
            pass
        raise RuntimeError from None


def _rollback_published(root: Path, published: Sequence[tuple[str, int, int]]) -> None:
    descriptor = -1
    failed = False
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
        descriptor = os.open(root, flags)
        _verify_open_directory(descriptor, root)
        for name, device, inode in published:
            try:
                target = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (target.st_dev, target.st_ino) == (device, inode):
                os.unlink(name, dir_fd=descriptor)
    except BaseException:
        failed = True
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                failed = True
    if failed:
        raise RuntimeError from None


def _cleanup_staging(root: Path, staging: Path, names: Sequence[str]) -> None:
    root_descriptor = -1
    staging_descriptor = -1
    failed = False
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
        root_descriptor = os.open(root, flags)
        staging_descriptor = os.open(staging.name, flags, dir_fd=root_descriptor)
        _verify_open_directory(root_descriptor, root)
        _verify_open_directory(staging_descriptor, staging)
        for name in names:
            if type(name) is not str or not name or "/" in name:
                raise OSError
            try:
                os.unlink(name, dir_fd=staging_descriptor)
            except FileNotFoundError:
                pass
        os.rmdir(staging.name, dir_fd=root_descriptor)
    except BaseException:
        failed = True
    finally:
        for descriptor in (staging_descriptor, root_descriptor):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except Exception:
                    failed = True
    if failed:
        raise RuntimeError from None


def _publish_staged_tree(root: Path, staging: Path) -> None:
    """Exclusively hard-link one private staged tree with inode-safe rollback."""

    root_descriptor = -1
    staging_descriptor = -1
    published: list[tuple[str, int, str, int, int]] = []
    failed = False

    def publish(source_fd: int, target_fd: int) -> None:
        for name in sorted(os.listdir(source_fd)):
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                raise OSError
            source = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            if stat.S_ISDIR(source.st_mode):
                if stat.S_IMODE(source.st_mode) != 0o700:
                    raise OSError
                os.mkdir(name, 0o700, dir_fd=target_fd)
                target = os.stat(name, dir_fd=target_fd, follow_symlinks=False)
                published.append(
                    ("directory", os.dup(target_fd), name, target.st_dev, target.st_ino)
                )
                source_child = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag(),
                    dir_fd=source_fd,
                )
                target_child = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag(),
                    dir_fd=target_fd,
                )
                try:
                    publish(source_child, target_child)
                    os.fsync(target_child)
                finally:
                    os.close(target_child)
                    os.close(source_child)
            elif stat.S_ISREG(source.st_mode) and stat.S_IMODE(source.st_mode) in {
                0o400,
                0o600,
            }:
                os.link(
                    name,
                    name,
                    src_dir_fd=source_fd,
                    dst_dir_fd=target_fd,
                    follow_symlinks=False,
                )
                target = os.stat(name, dir_fd=target_fd, follow_symlinks=False)
                if (target.st_dev, target.st_ino) != (source.st_dev, source.st_ino):
                    raise OSError
                published.append(
                    ("file", os.dup(target_fd), name, source.st_dev, source.st_ino)
                )
            else:
                raise OSError

    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
        root_descriptor = os.open(root, flags)
        staging_descriptor = os.open(staging.name, flags, dir_fd=root_descriptor)
        _verify_open_directory(root_descriptor, root)
        _verify_open_directory(staging_descriptor, staging)
        publish(staging_descriptor, root_descriptor)
        os.fsync(root_descriptor)
    except BaseException:
        failed = True
    if failed:
        for kind, parent_fd, name, device, inode in reversed(published):
            try:
                target = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (target.st_dev, target.st_ino) != (device, inode):
                    continue
                if kind == "file":
                    os.unlink(name, dir_fd=parent_fd)
                else:
                    os.rmdir(name, dir_fd=parent_fd)
            except (FileNotFoundError, OSError):
                pass
    for _kind, parent_fd, _name, _device, _inode in published:
        try:
            os.close(parent_fd)
        except OSError:
            failed = True
    for descriptor in (staging_descriptor, root_descriptor):
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                failed = True
    if failed:
        raise RuntimeError from None


def _cleanup_staging_tree(root: Path, staging: Path) -> None:
    """Remove a command-owned private staging tree through directory descriptors."""

    root_descriptor = -1
    staging_descriptor = -1
    failed = False

    def remove(directory_fd: int) -> None:
        for name in sorted(os.listdir(directory_fd)):
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag(),
                    dir_fd=directory_fd,
                )
                try:
                    remove(child)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=directory_fd)
            elif stat.S_ISREG(metadata.st_mode):
                os.unlink(name, dir_fd=directory_fd)
            else:
                raise OSError

    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
        root_descriptor = os.open(root, flags)
        staging_descriptor = os.open(staging.name, flags, dir_fd=root_descriptor)
        _verify_open_directory(root_descriptor, root)
        _verify_open_directory(staging_descriptor, staging)
        remove(staging_descriptor)
        os.rmdir(staging.name, dir_fd=root_descriptor)
    except BaseException:
        failed = True
    finally:
        for descriptor in (staging_descriptor, root_descriptor):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    failed = True
    if failed:
        raise RuntimeError from None


def _verify_open_directory(descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    entry = os.stat(path, follow_symlinks=False)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o700
        or opened.st_uid != os.getuid()
        or (opened.st_dev, opened.st_ino) != (entry.st_dev, entry.st_ino)
    ):
        raise OSError


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
