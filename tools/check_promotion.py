from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__:
    from tools.setup_prime_agent import (
        PrimeArtifactLock,
        PrimeSetupError,
        load_prime_artifact_lock,
        resolve_prime_ecosystem_module,
        verify_prime_checkout,
    )
else:
    from setup_prime_agent import (
        PrimeArtifactLock,
        PrimeSetupError,
        load_prime_artifact_lock,
        resolve_prime_ecosystem_module,
        verify_prime_checkout,
    )


Runner = Callable[[tuple[str, ...], Path], subprocess.CompletedProcess[str]]

WHEEL_CWD_SHIM_SMOKE = r"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from asterion.runtime.cwd_exec import trusted_script_path

helper = trusted_script_path()
assert helper.is_absolute()
assert helper.name == 'cwd_exec.py'
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    shadow = root / 'shadow'
    fake_runtime = shadow / 'asterion/runtime'
    fake_runtime.mkdir(parents=True)
    (shadow / 'asterion/__init__.py').write_text('')
    (fake_runtime / '__init__.py').write_text('')
    marker = root / 'shadow-executed'
    attack = (
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['MALICIOUS_MARKER']).write_text('executed')\n"
    )
    (fake_runtime / 'cwd_exec.py').write_text(attack)
    (shadow / 'sitecustomize.py').write_text(attack)
    cases = (
        (
            ('PYTHONHOME', '/definitely/not/a/python/home'),
            ('EXACT', 'python-home'),
        ),
        (
            ('PYTHONPATH', str(shadow)),
            ('PYTHONUSERBASE', str(root / 'user-base')),
            ('PYTHONSTARTUP', str(root / 'startup.py')),
            ('PYTHONWARNINGS', 'ignore'),
            ('PYTHONDONTWRITEBYTECODE', '1'),
            ('PYTHONHASHSEED', '7'),
            ('MALICIOUS_MARKER', str(marker)),
        ),
    )
    cwd_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for pairs in cases:
            payload = json.dumps(
                list(pairs), ensure_ascii=True, separators=(',', ':')
            ).encode('ascii')
            with tempfile.TemporaryFile() as transport:
                transport.write(payload)
                transport.seek(0)
                environment_descriptor = transport.fileno()
                completed = subprocess.run(
                    [
                        sys.executable,
                        '-I', '-S',
                        str(helper),
                        '--fd', str(cwd_descriptor),
                        '--env-fd', str(environment_descriptor),
                        '--',
                        '/usr/bin/env', '-0',
                    ],
                    cwd='/',
                    env=dict(pairs),
                    pass_fds=(cwd_descriptor, environment_descriptor),
                    capture_output=True,
                    check=False,
                )
            expected = b''.join(
                key.encode() + b'=' + value.encode() + b'\0'
                for key, value in pairs
            )
            assert completed.returncode == 0
            assert completed.stdout == expected
    finally:
        os.close(cwd_descriptor)
    assert not marker.exists()
"""

WHEEL_PROTOCOL_RESOURCE_SMOKE = r"""
import hashlib
import json
import subprocess
from importlib import resources
from pathlib import Path

root = Path(str(resources.files('asterion')))
schema_paths = (
    'asterion/schemas/agent-client/v1/intent.schema.json',
    'asterion/schemas/agent-client/v1/event.schema.json',
    'asterion/schemas/agent-system/v1/agent-system.schema.json',
    'asterion/schemas/control-plane/v1/control-plane-manifest.schema.json',
    'asterion/schemas/agent-control/v1/command.schema.json',
    'asterion/schemas/agent-control/v1/event.schema.json',
    'asterion/schemas/session-context/v1/command.schema.json',
    'asterion/schemas/session-context/v1/receipt.schema.json',
    'asterion/schemas/operation/v1/auth-request.schema.json',
    'asterion/schemas/operation/v1/model-selection-request.schema.json',
    'asterion/schemas/operation/v1/operation-request-descriptor.schema.json',
    'asterion/schemas/operation/v1/operation-transaction.schema.json',
    'asterion/schemas/operation/v1/operation-receipt.schema.json',
)
for name in schema_paths:
    path = root.parent / name
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload.get('$id', '').endswith(name.removeprefix('asterion/')), name
prime_root = root / 'control/providers/prime/resources'
prime_lock = json.loads(
    (prime_root / 'prime-artifact-lock.json').read_text(encoding='utf-8')
)
assert prime_lock['format'] == 'asterion.prime-artifact-lock/v1'
assert len(prime_lock['source_commit']) == 40
client_lock = json.loads(
    (prime_root / 'prime-client-module-lock.json').read_text(encoding='utf-8')
)
assert client_lock['format'] == 'asterion.prime-client-module-lock/v1'
assert client_lock['source_commit'] == prime_lock['source_commit']
assert (prime_root / 'prime-client-module.mjs').is_file()
external_prime_root = (Path.cwd() / '3th-party/prime-agent').resolve()
module_path = (prime_root / 'prime-client-module.mjs').resolve()
frame = {
    'artifactLockDigest': hashlib.sha256(
        (prime_root / 'prime-artifact-lock.json').read_bytes()
    ).hexdigest(),
    'format': 'asterion.prime-client-frame/v1',
    'moduleLockDigest': hashlib.sha256(
        (prime_root / 'prime-client-module-lock.json').read_bytes()
    ).hexdigest(),
    'package': 'core',
    'primeRoot': str(external_prime_root),
    'sourceCommit': prime_lock['source_commit'],
}
module_smoke = (
    "import {pathToFileURL} from 'node:url';"
    f"const module = await import(pathToFileURL({str(module_path)!r}).href);"
    f"const receipt = await module.runClientPackage(Object.freeze({json.dumps(frame)}));"
    "if (receipt.package !== 'core' || receipt.providerOperations !== 0 || "
    "receipt.credentialReads !== 0 || receipt.networkRequests !== 0 || "
    "receipt.retainedProcesses !== 0 || receipt.privateReads !== 0 || "
    "receipt.unauthorizedUploads !== 0 || receipt.stdoutWrites !== 0 || "
    "receipt.scenarioEvidence.length !== 11) process.exit(1);"
)
module_result = subprocess.run(
    ('node', '--input-type=module', '--eval', module_smoke),
    cwd='/', capture_output=True, text=True, check=False,
)
assert module_result.returncode == 0
assert (prime_root / 'control-plane.json').is_file()
assert (prime_root / 'skills/asterion-control/SKILL.md').is_file()
assert (prime_root / 'skills/asterion-control/pyproject.toml').is_file()
expected = {
    'applications/controlled_code/assemblies/controlled-code-validation.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-complete-application-claude.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-complete-application-pi.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-local-benchmark-application-claude.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-local-benchmark-application-pi.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-local-research.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-research-capability-claude.json':
        'asterion.application-assembly/v1',
    'applications/dci_agent_lite/assemblies/dci-research-capability.json':
        'asterion.application-assembly/v1',
    'capabilities/controlled_code/capability-package.json':
        'asterion.capability-package/v1',
    'capabilities/controlled_code/manifests/code-quality-evaluation.json':
        'asterion.capability/v1',
    'capabilities/controlled_code/manifests/code-quality-workflow.json':
        'asterion.capability/v1',
    'capabilities/controlled_code/manifests/controlled-code-policy.json':
        'asterion.capability/v1',
    'capabilities/controlled_code/manifests/execution-audit-observability.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capability-package.json':
        'asterion.capability-package/v1',
    'capabilities/dci/payload/capabilities/dci-analysis.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capabilities/dci-benchmark.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capabilities/dci-evaluation.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capabilities/dci-export.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capabilities/dci-research.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capabilities/local-corpus-policy.json':
        'asterion.capability/v1',
    'capabilities/dci/payload/capabilities/protocol-observability.json':
        'asterion.capability/v1',
}
descriptor_payload = json.loads(
    (root / 'capabilities/dci/payload/capability-package.json').read_text(
        encoding='utf-8'
    )
)
declared_suite_paths = set()
for suite_ref in descriptor_payload['benchmark_suites']:
    assert type(suite_ref) is dict
    assert set(suite_ref) == {'suite_id', 'version'}
    suite_id = suite_ref['suite_id']
    assert type(suite_id) is str and suite_id.startswith('dci.')
    assert type(suite_ref['version']) is str
    suite_path = (
        'capabilities/dci/payload/benchmark-suites/'
        + suite_id.removeprefix('dci.').replace('.', '-')
        + '.json'
    )
    assert suite_path not in declared_suite_paths
    declared_suite_paths.add(suite_path)
    expected[suite_path] = 'asterion.benchmark-suite/v1'
actual_paths = {
    str(path.relative_to(root))
    for pattern in (
        'applications/*/assemblies/*.json',
        'capabilities/*/capability-package.json',
        'capabilities/*/manifests/*.json',
        'capabilities/dci/payload/capability-package.json',
        'capabilities/dci/payload/benchmark-suites/*.json',
        'capabilities/dci/payload/capabilities/*.json',
    )
    for path in root.glob(pattern)
}
assert actual_paths == set(expected), sorted(actual_paths ^ set(expected))
for name in sorted(actual_paths):
    text = (root / name).read_text(encoding='utf-8')
    payload = json.loads(text)
    assert payload.get('protocol') == expected[name], name
    assert 'dci.' + 'agent-runtime/v1' not in text, name
    assert 'dci.' + 'package/v1' not in text, name
    assert 'dci.' + 'assembly/v1' not in text, name
template = root / 'capability_sdk/templates/minimal'
assert (template / 'provider.py').is_file()
template_files = {
    str(path.relative_to(template))
    for path in template.rglob('*')
    if path.is_file()
}
assert template_files == {
    'provider.py',
    'payload/benchmark-suites/suite.json',
    'payload/capabilities/research.json',
    'payload/capability-package.json',
    'payload/conformance/externalization.json',
    'payload/resources/example.conformance',
}
provider_text = (template / 'provider.py').read_text(encoding='utf-8')
assert 'from asterion.capability_sdk import' in provider_text
assert 'asterion.capability_packages.payload' not in provider_text
assert 'CapabilityImplementationBinding' not in provider_text
template_descriptor = template / 'payload/capability-package.json'
assert template_descriptor.is_file()
assert json.loads(template_descriptor.read_text()).get('protocol') == (
    'asterion.capability-package/v1'
)
"""

ROOT_EXCLUDED_NAMES = frozenset(
    {
        "3th-party",
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
        ".worktrees",
        "worktrees",
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
LOCAL_SDD_ARTIFACTS = (".superpowers", "sdd")
PRIME_SOURCE_ENV = "ASTERION_PRIME_SOURCE_ROOT"
DEFAULT_PRIME_SOURCE = Path("3th-party/prime-agent")
PRIME_PREPARE_COMMANDS = (
    ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"),
    ("npm", "--prefix", "packages/tui", "run", "build"),
    ("node_modules/.bin/tsgo", "-p", "packages/ai/tsconfig.build.json"),
    ("npm", "--prefix", "packages/agent", "run", "build"),
    ("npm", "--prefix", "packages/coding-agent", "run", "build"),
)


class PromotionError(RuntimeError):
    pass


def _default_runner(
    command: tuple[str, ...], cwd: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CARGO_REGISTRIES_CRATES_IO_PROTOCOL"] = "sparse"
    environment["CARGO_HOME"] = str(cwd.parent / "cargo-home")
    environment.pop(PRIME_SOURCE_ENV, None)
    isolated_prime = cwd / DEFAULT_PRIME_SOURCE
    if isolated_prime.is_dir() and not isolated_prime.is_symlink():
        environment[PRIME_SOURCE_ENV] = str(isolated_prime.resolve())
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
        or relative.parts[:2] == LOCAL_SDD_ARTIFACTS
    )


def _copy_ignore(source_root: Path) -> Callable[[str, list[str]], set[str]]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).resolve().relative_to(source_root)
        excluded = set(names) & RECURSIVE_EXCLUDED_NAMES
        if relative == Path("."):
            excluded.update(set(names) & ROOT_EXCLUDED_NAMES)
        if relative.parts == (".superpowers",):
            excluded.add("sdd")
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
        relative = path.relative_to(copy_root)
        if _is_excluded(relative):
            continue
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


def _external_prime_source_root(source_root: Path) -> Path | None:
    configured = os.environ.get(PRIME_SOURCE_ENV)
    candidate = Path(configured) if configured else source_root / DEFAULT_PRIME_SOURCE
    if configured and not candidate.is_absolute():
        candidate = source_root / candidate
    if not candidate.exists():
        if configured:
            raise PromotionError("external Prime source binding is unavailable")
        return None
    try:
        resolved = candidate.resolve(strict=True)
        verify_prime_checkout(resolved)
    except (OSError, RuntimeError, PrimeSetupError):
        raise PromotionError("external Prime source binding is invalid") from None
    return resolved


def _verify_locked_prime_runtime(target: Path, lock: PrimeArtifactLock) -> None:
    runtime = lock.rlm_runtime
    if runtime is None:
        return
    try:
        for relative, expected_digest in runtime.closure.items():
            candidate = Path(relative)
            if (
                not relative
                or candidate.is_absolute()
                or ".." in candidate.parts
                or candidate.as_posix() != relative
            ):
                raise OSError
            path = target / candidate
            if path.is_symlink() or not path.is_file():
                raise OSError
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
                raise OSError
    except (OSError, RuntimeError, ValueError):
        raise PromotionError("rebuilt Prime runtime is invalid") from None


def _run_prime_binding_command(command: tuple[str, ...], cwd: Path) -> None:
    environment = {
        key: value
        for key in ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError):
        raise PromotionError("external Prime checkout could not be created") from None
    if completed.returncode != 0:
        raise PromotionError("external Prime checkout could not be created")


def _prepare_external_prime_checkout(
    prime_source: Path,
    target: Path,
    source_commit: str,
) -> None:
    _run_prime_binding_command(
        (
            "git",
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            "--",
            str(prime_source),
            str(target),
        ),
        target.parent.parent,
    )
    _run_prime_binding_command(
        ("git", "checkout", "--detach", source_commit),
        target,
    )
    for command in PRIME_PREPARE_COMMANDS:
        _run_prime_binding_command(command, target)


def _bind_external_prime_source(copy_root: Path, source_root: Path) -> None:
    prime_source = _external_prime_source_root(source_root)
    if prime_source is None:
        return
    parent = copy_root / DEFAULT_PRIME_SOURCE.parent
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / DEFAULT_PRIME_SOURCE.name
    try:
        resource_root = (
            copy_root / "packages/typescript/prime-gateway/resources"
        )
        artifact_lock_path = resource_root / "prime-artifact-lock.json"
        lock = load_prime_artifact_lock(artifact_lock_path)
        _prepare_external_prime_checkout(prime_source, target, lock.source_commit)
        verify_prime_checkout(target, lock_path=artifact_lock_path)
        _verify_locked_prime_runtime(target, lock)
        resolve_prime_ecosystem_module(
            target,
            resource_root / "prime-ecosystem-module-lock.json",
            artifact_lock_path=artifact_lock_path,
            bundle_path=resource_root / "prime-ecosystem-module.mjs",
        )
    except (OSError, RuntimeError, PrimeSetupError):
        raise PromotionError("external Prime source binding could not be created") from None


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
            "capability",
            "init",
            ".promotion-capability-template",
            "--package-id",
            "acme.promotion",
        ),
        (
            "uv",
            "run",
            "asterion",
            "capability",
            "validate",
            ".promotion-capability-template/payload",
        ),
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
        ("npm", "ci", "--prefix", "packages/typescript/asterion-runtime"),
        ("npm", "run", "build", "--prefix", "packages/typescript/asterion-runtime"),
        ("npm", "ci", "--prefix", "packages/typescript/prime-gateway"),
        ("npm", "run", "build", "--prefix", "packages/typescript/prime-gateway"),
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
        (str(python), "-c", WHEEL_CWD_SHIM_SMOKE),
        (str(python), "-c", WHEEL_PROTOCOL_RESOURCE_SMOKE),
        (str(asterion), "list"),
        (
            str(asterion),
            "capability",
            "init",
            str(copy_root / ".wheel-capability-template"),
            "--package-id",
            "acme.wheel",
        ),
        (
            str(asterion),
            "capability",
            "validate",
            str(copy_root / ".wheel-capability-template/payload"),
        ),
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
        ("npm", "test", "--prefix", "packages/typescript/asterion-runtime"),
        ("npm", "test", "--prefix", "packages/typescript/dci-context-extension"),
        ("npm", "test", "--prefix", "packages/typescript/prime-gateway"),
        (
            "uv",
            "run",
            "python",
            "tools/verify_prime_loop.py",
            "--level",
            "provider-free",
        ),
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
        workspace = Path(temporary).resolve()
        copy_root = workspace / "project"
        _copy_project(source, copy_root)
        _bind_external_prime_source(copy_root, source)
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
        print(f"promotion check failed: {error}", file=sys.stderr)
        return 1
    mode = "quick" if arguments.quick else "full"
    print(
        f"promotion {mode} PASS commands={command_count} "
        "provider_operations=0 full_dataset=no"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
