from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE = PROJECT / "src/asterion/benchmarks"
_OBSOLETE_DCI_BENCHMARK_SURFACES = (
    "tools/dci_benchmark_orchestrator.py",
    "tools/run_dci_benchmarks.py",
    "scripts/run_dci_benchmarks.sh",
    "scripts/bcplus_eval/run_L3.sh",
    "scripts/bcplus_eval/run_bcplus_eval_openai.sh",
    "scripts/beir/benchmark_arguana.sh",
    "scripts/beir/benchmark_scifact.sh",
    "scripts/bright/run_bio.sh",
    "scripts/bright/run_earth_science.sh",
    "scripts/bright/run_economics.sh",
    "scripts/bright/run_robotics.sh",
    "scripts/qa/run_2wikimultihopqa_dev_sample50.sh",
    "scripts/qa/run_bamboogle_test_sample50.sh",
    "scripts/qa/run_hotpotqa_dev_sample50.sh",
    "scripts/qa/run_musique_dev_sample50.sh",
    "scripts/qa/run_nq_test_sample50.sh",
    "scripts/qa/run_triviaqa_test_sample50.sh",
    "tests/test_dci_benchmark_orchestrator.py",
)
_OBSOLETE_DCI_BENCHMARK_TOKENS = (
    "tools/dci_benchmark_orchestrator.py",
    "tools/run_dci_benchmarks.py",
    "scripts/run_dci_benchmarks.sh",
    "dci_benchmark_orchestrator",
    "run_dci_benchmarks.py",
    "run_dci_benchmarks.sh",
    "scripts/bcplus_eval/run_L3.sh",
    "scripts/bcplus_eval/run_bcplus_eval_openai.sh",
    "scripts/beir/benchmark_arguana.sh",
    "scripts/beir/benchmark_scifact.sh",
    "scripts/bright/run_bio.sh",
    "scripts/bright/run_earth_science.sh",
    "scripts/bright/run_economics.sh",
    "scripts/bright/run_robotics.sh",
    "scripts/qa/run_2wikimultihopqa_dev_sample50.sh",
    "scripts/qa/run_bamboogle_test_sample50.sh",
    "scripts/qa/run_hotpotqa_dev_sample50.sh",
    "scripts/qa/run_musique_dev_sample50.sh",
    "scripts/qa/run_nq_test_sample50.sh",
    "scripts/qa/run_triviaqa_test_sample50.sh",
    '"launcher"',
    "launcher_origin",
)
_ACTIVE_BOUNDARY_ROOTS = (
    "README.md",
    "Makefile",
    "docs/README.md",
    "docs/architecture.md",
    "docs/cli.md",
    "docs/architecture",
    "docs/guides",
    "docs/operator",
    "docs/verification",
    "src",
    "tests",
)
_HISTORICAL_SUPERPOWERS_DOC_ROOTS = (
    "docs/superpowers/plans",
    "docs/superpowers/specs",
)
_ACTIVE_DCI_LAUNCHER_DELETION_CONTRACT = (
    "docs/superpowers/plans/2026-07-27-dci-capability-package-migration.md"
)
_ACTIVE_DCI_LAUNCHER_DELETION_HEADING = (
    "### Task 5: Remove global DCI benchmark orchestration and launchers"
)

_FORBIDDEN_IMPORT_PREFIXES = (
    "asterion.dci",
    "asterion.capabilities.dci",
)
_DCI_LITERAL_IDENTIFIERS = frozenset(
    {
        "beir.arguana",
        "beir.scifact",
        "bcplus.level3",
        "bcplus.main",
        "bcplus.openai",
        "bright.biology",
        "bright.earth-science",
        "bright.economics",
        "bright.robotics",
        "browsecomp-plus",
        "qa.2wikimultihopqa",
        "qa.bamboogle",
        "qa.hotpotqa",
        "qa.musique",
        "qa.nq",
        "qa.triviaqa",
    }
)
_DCI_LITERAL_PATTERN = re.compile(
    r"(?<![a-z0-9])dci(?:[._-]|$)",
    re.IGNORECASE,
)
_DISCOVERY_IMPORT_PREFIXES = (
    "asterion.applications.discovery",
    "asterion.capability_packages.sources",
    "importlib.metadata",
)
_DISCOVERY_CALLS = frozenset(
    {
        "discover_metadata",
        "entry_points",
        "load_application_provider",
        "load_provider",
        "open_payload",
    }
)
_PROCESS_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.popen",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
    }
)
_GENERIC_SERIALIZERS = frozenset(
    {
        "asdict",
        "dataclasses.asdict",
        "model_dump",
        "vars",
    }
)
_SERIALIZATION_CALLS = frozenset({"json.dump", "json.dumps"})
_PRIVATE_SERIALIZATION_NAMES = frozenset(
    {
        "__dict__",
        "argv",
        "cwd",
        "environment",
        "evidence_root",
        "output_directory",
        "path",
        "private_payload",
        "stderr",
        "stdout",
    }
)


def _benchmark_trees() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple(
        (
            path,
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
        )
        for path in sorted(BENCHMARK_SOURCE.glob("*.py"))
    )


def _imported_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (
            node.module,
            *(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            ),
        )
    return ()


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return node.attr if parent is None else f"{parent}.{node.attr}"
    return None


def _names_below(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            names.add(child.value)
    return frozenset(names)


def _active_boundary_files() -> tuple[Path, ...]:
    files: set[Path] = set()
    for root_name in _ACTIVE_BOUNDARY_ROOTS:
        root = PROJECT / root_name
        if not root.exists():
            continue
        if root.is_file():
            files.add(root)
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {
                ".json",
                ".md",
                ".py",
                ".sh",
                ".toml",
                ".yaml",
                ".yml",
            }:
                files.add(path)
    return tuple(sorted(files))


def _historical_superpowers_docs() -> tuple[Path, ...]:
    files: set[Path] = set()
    for root_name in _HISTORICAL_SUPERPOWERS_DOC_ROOTS:
        root = PROJECT / root_name
        if not root.exists():
            continue
        files.update(path for path in root.rglob("*.md") if path.is_file())
    return tuple(sorted(files))


def _top_level_notice(text: str) -> str:
    lines = text.splitlines()
    try:
        body_start = next(
            index + 1 for index, line in enumerate(lines) if line.startswith("# ")
        )
    except StopIteration:
        body_start = 0
    notice_lines: list[str] = []
    for line in lines[body_start:]:
        if line.startswith("## "):
            break
        notice_lines.append(line)
    return "\n".join(notice_lines).lower()


class GenericBenchmarkProjectBoundaryTests(unittest.TestCase):
    def test_obsolete_global_dci_benchmark_surfaces_are_absent(self) -> None:
        existing = tuple(
            relative
            for relative in _OBSOLETE_DCI_BENCHMARK_SURFACES
            if (PROJECT / relative).exists()
        )
        self.assertEqual(existing, ())

    def test_active_tree_has_no_per_task_benchmark_launcher_references(self) -> None:
        violations: list[tuple[str, str]] = []
        for path in _active_boundary_files():
            relative = path.relative_to(PROJECT).as_posix()
            if relative == "tests/test_project_boundaries.py":
                continue
            text = path.read_text(encoding="utf-8")
            for token in _OBSOLETE_DCI_BENCHMARK_TOKENS:
                if token in text:
                    violations.append((relative, token))
        self.assertEqual(violations, [])

    def test_historical_docs_with_retired_dci_launchers_are_superseded(self) -> None:
        violations: list[tuple[str, str]] = []
        for path in _historical_superpowers_docs():
            relative = path.relative_to(PROJECT).as_posix()
            text = path.read_text(encoding="utf-8")
            matched_tokens = tuple(
                token for token in _OBSOLETE_DCI_BENCHMARK_TOKENS if token in text
            )
            if not matched_tokens:
                continue
            if relative == _ACTIVE_DCI_LAUNCHER_DELETION_CONTRACT:
                if _ACTIVE_DCI_LAUNCHER_DELETION_HEADING not in text:
                    violations.append(
                        (
                            relative,
                            "active deletion contract missing Task 5 heading",
                        )
                    )
                continue
            notice = _top_level_notice(text)
            if (
                "superseded" not in notice
                or "generic benchmark host" not in notice
                or "plan 4 task 5" not in notice
            ):
                violations.append(
                    (
                        relative,
                        ", ".join(matched_tokens),
                    )
                )
        self.assertEqual(violations, [])

    def test_deleted_orchestrator_security_behaviors_are_mapped_to_generic_tests(
        self,
    ) -> None:
        import tests.test_benchmark_evidence as evidence_tests
        import tests.test_benchmark_execution as execution_tests

        coverage = {
            "private directories and evidence file modes": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_every_created_directory_and_file_is_private_under_permissive_umask",
            ),
            "preexisting symlinked run directory rejection": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_preexisting_symlinked_run_directory_is_rejected",
            ),
            "symlink replacement between validation and write": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_symlink_replacement_between_validation_and_write_is_rejected",
            ),
            "nonregular or multiply linked evidence member rejection": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_nonregular_or_multiply_linked_evidence_member_is_rejected",
            ),
            "atomic descriptor-bound evidence replacement": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_atomic_fsync_replace_stays_inside_the_opened_run_descriptor",
            ),
            "body-free public serialization": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_only_allowlisted_descriptors_statuses_and_digests_are_serialized",
            ),
            "resume accepts only exact complete identity": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_resume_accepts_only_the_exact_complete_plan_identity",
            ),
            "corrupt or extended resume evidence rejection": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_resume_rejects_missing_incomplete_corrupt_or_extended_evidence",
            ),
            "noncontiguous and mismatched lifecycle rejection": (
                evidence_tests.BenchmarkEvidenceTests,
                "test_lifecycle_rejects_noncontiguous_or_mismatched_updates",
            ),
            "sequential stop after first task failure": (
                execution_tests.BenchmarkExecutionTests,
                "test_first_failure_stops_later_tasks",
            ),
            "pre-task cancellation starts no child work": (
                execution_tests.BenchmarkExecutionTests,
                "test_pre_task_cancellation_starts_nothing",
            ),
            "mid-task cancellation stops later tasks": (
                execution_tests.BenchmarkExecutionTests,
                "test_mid_task_cancellation_reaches_executor_and_stops_later_tasks",
            ),
            "executor exceptions are redacted": (
                execution_tests.BenchmarkExecutionTests,
                "test_executor_exception_becomes_one_redacted_failed_result",
            ),
            "process execution uses clean bounded environment": (
                execution_tests.AuthorizedProcessTaskExecutorTests,
                "test_direct_process_uses_clean_environment_and_bounded_output",
            ),
            "deadline kills process group": (
                execution_tests.AuthorizedProcessTaskExecutorTests,
                "test_deadline_stops_the_process_group_and_returns_failed",
            ),
            "cancellation terminates and reaps process tree": (
                execution_tests.AuthorizedProcessTaskExecutorTests,
                "test_cancellation_terminates_and_reaps_the_real_process_tree",
            ),
        }
        missing = tuple(
            behavior
            for behavior, (case, method_name) in coverage.items()
            if getattr(case, method_name, None) is None
        )
        self.assertEqual(missing, ())

    def test_generic_modules_do_not_import_dci_product_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            for node in ast.walk(tree):
                for name in _imported_names(node):
                    if any(
                        name == prefix or name.startswith(f"{prefix}.")
                        for prefix in _FORBIDDEN_IMPORT_PREFIXES
                    ):
                        violations.append((path.name, node.lineno, name))
        self.assertEqual(violations, [])

    def test_generic_modules_do_not_embed_dci_identifiers(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                ):
                    continue
                value = node.value.casefold()
                if (
                    _DCI_LITERAL_PATTERN.search(value) is not None
                    or any(
                        value == identifier
                        or value.startswith(f"{identifier}.")
                        or value.startswith(f"{identifier}/")
                        for identifier in _DCI_LITERAL_IDENTIFIERS
                    )
                ):
                    violations.append((path.name, node.lineno, node.value))
        self.assertEqual(violations, [])

    def test_runner_does_not_discover_packages_or_providers(self) -> None:
        path = BENCHMARK_SOURCE / "execution.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            for name in _imported_names(node):
                if any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in _DISCOVERY_IMPORT_PREFIXES
                ):
                    violations.append((node.lineno, name))
            if isinstance(node, ast.Call):
                name = _qualified_name(node.func)
                if name is not None and name.rsplit(".", 1)[-1] in _DISCOVERY_CALLS:
                    violations.append((node.lineno, name))
        self.assertEqual(violations, [])

    def test_subprocess_use_is_confined_to_process_module(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            if path.name == "process.py":
                continue
            for node in ast.walk(tree):
                for name in _imported_names(node):
                    if name == "subprocess" or name.startswith("subprocess."):
                        violations.append((path.name, node.lineno, name))
                if isinstance(node, ast.Call):
                    name = _qualified_name(node.func)
                    if name in _PROCESS_CALLS or (
                        name is not None and name.startswith("os.spawn")
                    ):
                        violations.append((path.name, node.lineno, name))
        self.assertEqual(violations, [])

    def test_public_serialization_is_allowlisted_not_recursive_or_private(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for path, tree in _benchmark_trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "__dict__":
                    violations.append((path.name, node.lineno, "__dict__"))
                if not isinstance(node, ast.Call):
                    continue
                name = _qualified_name(node.func)
                if name in _GENERIC_SERIALIZERS:
                    violations.append((path.name, node.lineno, name))
                if (
                    name not in _SERIALIZATION_CALLS
                    and (
                        name is None
                        or name.rsplit(".", 1)[-1] not in {"dump", "dumps"}
                    )
                ):
                    continue
                serialized = (
                    *node.args,
                    *(keyword.value for keyword in node.keywords),
                )
                private_names = set().union(
                    *(_names_below(value) for value in serialized)
                ) & _PRIVATE_SERIALIZATION_NAMES
                for private_name in sorted(private_names):
                    violations.append(
                        (path.name, node.lineno, private_name)
                    )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
