from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path


Runner = Callable[[tuple[str, ...], Path], subprocess.CompletedProcess[str]]

ROOT_EXCLUDED_NAMES = frozenset(
    {
        "build",
        "corpora",
        "corpus",
        "data",
        "datasets",
        "dist",
        "logs",
        "outputs",
        "pi",
        "pi-mono",
        "runs",
    }
)
RECURSIVE_EXCLUDED_NAMES = frozenset(
    {
        ".env",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
    }
)
REQUIRED_ASSETS = (
    ".env.template",
    ".github/workflows/ci.yml",
    ".gitignore",
    "LICENSE",
    "Makefile",
    "README.md",
    "pi-revision.txt",
    "pyproject.toml",
    "scripts/setup_pi.sh",
    "tools/check_docs.py",
    "tools/check_promotion.py",
    "tools/setup_resources.py",
    "uv.lock",
)
TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".ini",
        ".json",
        ".jsonl",
        ".lock",
        ".md",
        ".mjs",
        ".py",
        ".rs",
        ".sh",
        ".template",
        ".toml",
        ".ts",
        ".txt",
        ".yaml",
        ".yml",
    }
)
TEXT_NAMES = frozenset({"Makefile", ".gitignore"})
FORBIDDEN = (
    "/Users/" + "sujiangwen/",
    "--project " + "asterion",
    "../src/" + "dci",
    "../tools/" + "verify_asterion_dci_product.py",
)
DCI_PARENT_PATTERN = re.compile(r"\.\./src/dci(?=$|[/\s`'\"\)])")


class PromotionError(RuntimeError):
    pass


def _default_runner(
    command: tuple[str, ...], cwd: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CARGO_REGISTRIES_CRATES_IO_PROTOCOL"] = "sparse"
    environment["CARGO_HOME"] = str(cwd.parent / "cargo-home")
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _reject_symlinks(source_root: Path) -> None:
    if source_root.is_symlink():
        raise PromotionError("source root must not be a symlink")
    for path in source_root.rglob("*"):
        relative = path.relative_to(source_root)
        if _is_excluded(relative):
            continue
        if path.is_symlink():
            raise PromotionError("standalone source contains a symlink")


def _is_excluded(relative: Path) -> bool:
    return (
        bool(relative.parts)
        and relative.parts[0] in ROOT_EXCLUDED_NAMES
        or any(part in RECURSIVE_EXCLUDED_NAMES for part in relative.parts)
    )


def _copy_ignore(source_root: Path) -> Callable[[str, list[str]], set[str]]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).resolve().relative_to(source_root)
        excluded = set(names) & RECURSIVE_EXCLUDED_NAMES
        if relative == Path("."):
            excluded.update(set(names) & ROOT_EXCLUDED_NAMES)
        return excluded

    return ignore


def _copy_project(source_root: Path, copy_root: Path) -> None:
    _reject_symlinks(source_root)
    shutil.copytree(
        source_root,
        copy_root,
        ignore=_copy_ignore(source_root),
    )


def _contains_forbidden(text: str, forbidden: str) -> bool:
    if forbidden == FORBIDDEN[2]:
        return DCI_PARENT_PATTERN.search(text) is not None
    return forbidden in text


def _audit_copy(copy_root: Path) -> None:
    missing = [name for name in REQUIRED_ASSETS if not (copy_root / name).is_file()]
    if missing:
        raise PromotionError("promotion copy is missing required repository assets")

    for path in sorted(copy_root.rglob("*")):
        if path.is_symlink():
            raise PromotionError("promotion copy contains a symlink")
        if not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise PromotionError("project-owned text file is not UTF-8") from error
        if any(_contains_forbidden(text, forbidden) for forbidden in FORBIDDEN):
            raise PromotionError("promotion copy contains a nonportable reference")


def _bounded_tail(completed: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )
    lines = combined.splitlines()[-20:]
    return "\n".join(lines)[-4000:]


def _run(
    runner: Runner, command: Sequence[str], copy_root: Path
) -> subprocess.CompletedProcess[str]:
    normalized = tuple(str(value) for value in command)
    try:
        completed = runner(normalized, copy_root)
    except OSError as error:
        raise PromotionError(f"promotion command could not start: {normalized[0]}") from error
    if completed.returncode != 0:
        tail = _bounded_tail(completed)
        message = f"promotion command failed: {shlex.join(normalized)}"
        if tail:
            message = f"{message}\n{tail}"
        raise PromotionError(message)
    return completed


def _assert_acceptance(stdout: str) -> None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise PromotionError("installed acceptance did not emit one JSON result") from error
    if (
        payload.get("status") != "PASS"
        or payload.get("provider_backed_operation_count") != 0
        or payload.get("full_dataset_ran") is not False
    ):
        raise PromotionError("installed acceptance violated the provider-free boundary")


def _venv_paths(venv_root: Path) -> tuple[Path, Path]:
    scripts = venv_root / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    asterion = scripts / ("asterion.exe" if os.name == "nt" else "asterion")
    return python, asterion


def _run_quick(copy_root: Path, runner: Runner) -> int:
    commands = (
        ("uv", "sync", "--frozen"),
        (
            "uv",
            "run",
            "python",
            "-m",
            "unittest",
            "-v",
            "tests.test_setup_pi",
            "tests.test_resource_setup",
            "tests.test_asterion_dci_verification",
        ),
        (
            "uv",
            "run",
            "python",
            "-m",
            "unittest",
            "-v",
            "tests.test_standalone_repository",
        ),
        ("uv", "run", "python", "-m", "compileall", "-q", "src", "tests", "tools"),
        ("uv", "run", "ruff", "check", "src", "tests", "tools"),
        ("uv", "run", "asterion", "list"),
        (
            "uv",
            "run",
            "asterion",
            "describe",
            "--provider",
            "dci-agent-lite",
            "--json",
        ),
        ("uv", "run", "python", "tools/check_docs.py"),
    )
    for command in commands:
        _run(runner, command, copy_root)
    acceptance = _run(
        runner,
        (
            "uv",
            "run",
            "asterion",
            "verify",
            "--provider",
            "dci-agent-lite",
            "--level",
            "acceptance",
            "--json",
        ),
        copy_root,
    )
    _assert_acceptance(acceptance.stdout)
    return len(commands) + 1


def _run_full(copy_root: Path, venv_root: Path, runner: Runner) -> int:
    initial_commands = (
        ("uv", "sync", "--frozen"),
        (
            "uv",
            "run",
            "python",
            "-m",
            "unittest",
            "-v",
            "tests.test_setup_pi",
            "tests.test_resource_setup",
            "tests.test_asterion_dci_verification",
        ),
        ("uv", "run", "python", "-m", "unittest", "discover", "-s", "tests", "-v"),
        ("uv", "run", "python", "-m", "compileall", "-q", "src", "tests", "tools"),
        ("uv", "run", "ruff", "check", "src", "tests", "tools"),
        ("uv", "build", "."),
    )
    for command in initial_commands:
        _run(runner, command, copy_root)

    wheels = tuple(sorted((copy_root / "dist").glob("*.whl")))
    if len(wheels) != 1:
        raise PromotionError("promotion build must produce exactly one wheel")
    python, asterion = _venv_paths(venv_root)
    installed_commands = (
        ("uv", "venv", str(venv_root)),
        ("uv", "pip", "install", "--python", str(python), str(wheels[0])),
        (str(asterion), "list"),
        (str(asterion), "describe", "--provider", "dci-agent-lite", "--json"),
    )
    for command in installed_commands:
        _run(runner, command, copy_root)
    acceptance = _run(
        runner,
        (
            str(asterion),
            "verify",
            "--provider",
            "dci-agent-lite",
            "--level",
            "acceptance",
            "--json",
        ),
        copy_root,
    )
    _assert_acceptance(acceptance.stdout)

    final_commands = (
        ("uv", "run", "python", "tools/check_docs.py"),
        ("npm", "ci", "--prefix", "packages/typescript/asterion-runtime"),
        ("npm", "test", "--prefix", "packages/typescript/asterion-runtime"),
        ("npm", "test", "--prefix", "packages/typescript/dci-context-extension"),
        (
            "cargo",
            "test",
            "--manifest-path",
            "packages/rust/controlled-executor/Cargo.toml",
        ),
        (
            "cargo",
            "fmt",
            "--manifest-path",
            "packages/rust/controlled-executor/Cargo.toml",
            "--",
            "--check",
        ),
        (
            "cargo",
            "clippy",
            "--manifest-path",
            "packages/rust/controlled-executor/Cargo.toml",
            "--",
            "-D",
            "warnings",
        ),
    )
    for command in final_commands:
        _run(runner, command, copy_root)
    return len(initial_commands) + len(installed_commands) + 1 + len(final_commands)


def run_promotion(
    *, source_root: Path, quick: bool = False, runner: Runner = _default_runner
) -> int:
    source = source_root.resolve()
    if not source.is_dir():
        raise PromotionError("standalone source root is unavailable")
    with tempfile.TemporaryDirectory(prefix="asterion-promotion-") as temporary:
        workspace = Path(temporary)
        copy_root = workspace / "project"
        _copy_project(source, copy_root)
        _audit_copy(copy_root)
        command_count = (
            _run_quick(copy_root, runner)
            if quick
            else _run_full(copy_root, workspace / "wheel-venv", runner)
        )
    return command_count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        command_count = run_promotion(
            source_root=Path(__file__).resolve().parents[1], quick=arguments.quick
        )
    except PromotionError as error:
        print(f"promotion check failed: {error}", file=os.sys.stderr)
        return 1
    mode = "quick" if arguments.quick else "full"
    print(
        f"promotion {mode} PASS commands={command_count} "
        "provider_operations=0 full_dataset=no"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
