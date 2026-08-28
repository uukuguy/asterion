"""Verify or install the explicitly selected pinned Prime source checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType


LOCK_FORMAT = "asterion.prime-artifact-lock/v1"
HARNESS_MODULE_LOCK_FORMAT = "asterion.prime-harness-module-lock/v1"
ECOSYSTEM_MODULE_LOCK_FORMAT = "asterion.prime-ecosystem-module-lock/v1"
OPERATIONAL_MODULE_LOCK_FORMAT = "asterion.prime-operational-module-lock/v1"
PINNED_PRIME_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c"
PRIME_HARNESS_REQUIRED_EXPORTS = (
    "applyRefinementProposal",
    "loadHarnessState",
    "saveHarnessState",
)
PRIME_ECOSYSTEM_REQUIRED_EXPORTS = (
    "inspectResources",
    "resolvePackage",
    "runExtensionLifecycle",
    "runMcpFixture",
)
PRIME_ECOSYSTEM_MODULE_IDS = (
    "diagnostics",
    "extension-loader",
    "extension-runner",
    "mcp-manager",
    "mcp-oauth",
    "model-registry",
    "package-manager",
    "prompt-templates",
    "resource-loader",
    "skills",
)
PRIME_OPERATIONAL_SOURCE_ANCHORS = (
    "packages/coding-agent/src/core/agent-session.ts",
    "packages/coding-agent/src/core/auth-storage.ts",
    "packages/coding-agent/src/core/diagnostics.ts",
    "packages/coding-agent/src/core/keybindings.ts",
    "packages/coding-agent/src/core/settings-manager.ts",
    "packages/coding-agent/src/core/telemetry.ts",
    "packages/coding-agent/src/core/usage.ts",
    "packages/coding-agent/src/package-manager-cli.ts",
)
PRIME_OPERATIONAL_BUILT_ANCHORS = tuple(
    path.replace("/src/", "/dist/").removesuffix(".ts") + ".js"
    for path in PRIME_OPERATIONAL_SOURCE_ANCHORS
)
_PRIME_ECOSYSTEM_MODULE_PATHS = {
    "diagnostics": (
        "packages/coding-agent/src/core/diagnostics.ts",
        "packages/coding-agent/dist/core/diagnostics.js",
    ),
    "extension-loader": (
        "packages/coding-agent/src/core/extensions/loader.ts",
        "packages/coding-agent/dist/core/extensions/loader.js",
    ),
    "extension-runner": (
        "packages/coding-agent/src/core/extensions/runner.ts",
        "packages/coding-agent/dist/core/extensions/runner.js",
    ),
    "mcp-manager": (
        "packages/coding-agent/src/core/mcp/mcp-manager.ts",
        "packages/coding-agent/dist/core/mcp/mcp-manager.js",
    ),
    "mcp-oauth": (
        "packages/ai/src/mcp/oauth.ts",
        "packages/ai/dist/mcp/oauth.js",
    ),
    "model-registry": (
        "packages/coding-agent/src/core/model-registry.ts",
        "packages/coding-agent/dist/core/model-registry.js",
    ),
    "package-manager": (
        "packages/coding-agent/src/core/package-manager.ts",
        "packages/coding-agent/dist/core/package-manager.js",
    ),
    "prompt-templates": (
        "packages/coding-agent/src/core/prompt-templates.ts",
        "packages/coding-agent/dist/core/prompt-templates.js",
    ),
    "resource-loader": (
        "packages/coding-agent/src/core/resource-loader.ts",
        "packages/coding-agent/dist/core/resource-loader.js",
    ),
    "skills": (
        "packages/coding-agent/src/core/skills.ts",
        "packages/coding-agent/dist/core/skills.js",
    ),
}
MINIMUM_NODE_VERSION = (22, 8, 0)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_STATIC_LOCAL_ESM_IMPORT = re.compile(
    r"^import(?:[\s\S]*?\sfrom)?\s*[\"'](\.[^\"']+)[\"']",
    re.MULTILINE,
)
_ENTRY_DYNAMIC_LOCAL_ESM_IMPORT = re.compile(
    r"\bawait\s+import\(\s*[\"'](\.[^\"']+)[\"']"
)
_LINE_DYNAMIC_LOCAL_ESM_IMPORT = re.compile(
    r"^\s*import\(\s*[\"'](\.[^\"']+)[\"']", re.MULTILINE
)
_STATIC_ESM_IMPORT = re.compile(
    r"^import[^\n]*\sfrom\s*[\"']([^\"']+)[\"']\s*;?\s*$", re.MULTILINE
)
_ANY_ESM_IMPORT = re.compile(r"^\s*import\b", re.MULTILINE)
_DYNAMIC_ESM_IMPORT = re.compile(r"\bimport\s*\(")
_EXPORTED_ESM_FUNCTION = re.compile(
    r"^export\s+(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE,
)
_ANY_ESM_EXPORT = re.compile(r"^export\s+", re.MULTILINE)
_OFFLINE_BUILD_COMMANDS = (
    ("npm", "--prefix", "packages/tui", "run", "build"),
    (
        "node_modules/.bin/tsgo",
        "-p",
        "packages/ai/tsconfig.build.json",
    ),
    ("npm", "--prefix", "packages/agent", "run", "build"),
    ("npm", "--prefix", "packages/coding-agent", "run", "build"),
)

Runner = Callable[
    [tuple[str, ...], Path, dict[str, str]], subprocess.CompletedProcess[str]
]


class PrimeSetupError(RuntimeError):
    """Raised without provider output or private paths when setup is unsafe."""


class OperationalHarnessError(RuntimeError):
    """Raised when the locked real-Prime operation boundary is unsafe."""


@dataclass(frozen=True, repr=False)
class PrimeRlmRuntimeLock:
    entry: str
    binding_chunk: str
    closure: Mapping[str, str]
    derived_closure: Mapping[str, str]
    patch_sha256: str


@dataclass(frozen=True, repr=False)
class PrimeArtifactLock:
    source_commit: str
    package_name: str
    package_version: str
    daemon_protocol: int
    daemon_schema_revision: int
    daemon_schema_id: str
    files: Mapping[str, str]
    rlm_runtime: PrimeRlmRuntimeLock | None


@dataclass(frozen=True, repr=False)
class PrimeHarnessModuleLock:
    source_commit: str
    entry: str
    source_files: Mapping[str, str]
    built_modules: Mapping[str, str]
    required_exports: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class PrimeEcosystemModuleRecord:
    module_id: str
    source_path: str
    built_path: str
    sha256: str


@dataclass(frozen=True, repr=False)
class PrimeEcosystemModuleLock:
    source_commit: str
    artifact_lock_sha256: str
    bundle_sha256: str
    modules: tuple[PrimeEcosystemModuleRecord, ...]


@dataclass(frozen=True, repr=False)
class OperationalHarnessLocks:
    source_commit: str
    node_runtime: str
    runtime_digest: str
    module_digest: str
    dependency_lock_digest: str
    workspace_digest: str
    source_anchor_digests: Mapping[str, str]
    built_anchor_digests: Mapping[str, str]


@dataclass(frozen=True, repr=False)
class ResolvedPrimeEcosystemModule:
    source_commit: str
    artifact_lock_sha256: str
    bundle_sha256: str
    module_ids: tuple[str, ...]
    built_paths: Mapping[str, Path]
    bundle_path: Path


@dataclass(frozen=True)
class PrimeSetupReport:
    source_commit: str
    package_version: str
    daemon_protocol: int
    daemon_schema_revision: int
    installed: bool


def _default_runner(
    command: tuple[str, ...], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )


def default_lock_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-artifact-lock.json"
    )
    return Path(str(packaged))


def default_rlm_shim_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-rlm-host-shim.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-rlm-host-shim.json"
    )
    return Path(str(packaged))


def default_harness_module_lock_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-harness-module-lock.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-harness-module-lock.json"
    )
    return Path(str(packaged))


def default_ecosystem_module_lock_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-ecosystem-module-lock.json"
    )
    return Path(str(packaged))


def default_operational_module_lock_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-operational-module-lock.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-operational-module-lock.json"
    )
    return Path(str(packaged))


def _parse_digest_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict) or not value:
        raise TypeError
    normalized: dict[str, str] = {}
    for relative, digest in value.items():
        candidate = Path(relative)
        if (
            not isinstance(relative, str)
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.as_posix() != relative
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise TypeError
        normalized[relative] = digest
    if tuple(normalized) != tuple(sorted(normalized)):
        raise TypeError
    return MappingProxyType(normalized)


def _operational_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _canonical_operational_json(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_canonical_operational_json(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _canonical_operational_json(value[key])
            for key in sorted(value)
        }
    raise TypeError


def _load_operational_harness_locks(resource_root: Path) -> OperationalHarnessLocks:
    try:
        root = resource_root.resolve(strict=True)
        if resource_root.is_symlink() or not root.is_dir():
            raise OSError
        lock_path = root / "prime-operational-module-lock.json"
        module_path = root / "prime-operational-module.mjs"
        lock_body = _read_locked_regular_file(lock_path)
        module_body = _read_locked_regular_file(module_path)
        value = json.loads(
            lock_body.decode("utf-8"), object_pairs_hook=_operational_pairs
        )
        canonical = (
            json.dumps(
                _canonical_operational_json(value),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        if lock_body != canonical:
            raise TypeError
        if not isinstance(value, dict) or set(value) != {
            "built_anchor_digests",
            "dependency_lock_sha256",
            "format",
            "module_digest",
            "node_runtime",
            "runtime_digest",
            "source_anchor_digests",
            "source_commit",
            "workspace_digest",
        }:
            raise TypeError
        source = _parse_digest_mapping(value["source_anchor_digests"])
        built = _parse_digest_mapping(value["built_anchor_digests"])
        if (
            tuple(source) != PRIME_OPERATIONAL_SOURCE_ANCHORS
            or tuple(built) != PRIME_OPERATIONAL_BUILT_ANCHORS
            or value["format"] != OPERATIONAL_MODULE_LOCK_FORMAT
            or value["source_commit"] != PINNED_PRIME_COMMIT
            or value["node_runtime"] != "v22.23.2"
            or not all(
                isinstance(value[key], str) and _SHA256.fullmatch(value[key])
                for key in (
                    "dependency_lock_sha256",
                    "module_digest",
                    "runtime_digest",
                    "workspace_digest",
                )
            )
            or value["module_digest"] != hashlib.sha256(module_body).hexdigest()
            or value["runtime_digest"]
            != hashlib.sha256(value["node_runtime"].encode("utf-8")).hexdigest()
        ):
            raise TypeError
        return OperationalHarnessLocks(
            source_commit=value["source_commit"],
            node_runtime=value["node_runtime"],
            runtime_digest=value["runtime_digest"],
            module_digest=value["module_digest"],
            dependency_lock_digest=value["dependency_lock_sha256"],
            workspace_digest=value["workspace_digest"],
            source_anchor_digests=source,
            built_anchor_digests=built,
        )
    except (OSError, RuntimeError, TypeError, UnicodeDecodeError, ValueError):
        raise OperationalHarnessError("Prime operational harness is invalid") from None


def verify_operational_locks(
    source_root: Path,
    resource_root: Path,
    *,
    node_executable: Path | None = None,
) -> OperationalHarnessLocks:
    """Verify the exact unimported real-Prime operation anchor boundary."""

    try:
        locks = _load_operational_harness_locks(resource_root)
        root = _source_root(source_root)
        resources = resource_root.resolve(strict=True)
        temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        try:
            relative_source = root.relative_to(temporary_root)
            relative_resources = resources.relative_to(temporary_root)
        except ValueError:
            raise OSError
        if not relative_source.parts or not relative_resources.parts:
            raise OSError
        if root == resources or root in resources.parents or resources in root.parents:
            raise OSError
        if _is_asterion_project_tree_ancestor(root):
            raise OSError
        for relative_path in (relative_source, relative_resources):
            current = temporary_root
            for part in relative_path.parts:
                current = current / part
                if current.is_symlink() or not current.is_dir():
                    raise OSError
        node_path = node_executable or _resolve_operational_node()
        if not node_path.is_file() or not node_path.resolve(strict=True).is_file():
            raise OSError
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-node-") as temporary:
            node = subprocess.run(
                (str(node_path), "--version"),
                cwd=root,
                env=_closed_environment(Path(temporary)),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if node.returncode != 0 or node.stdout.strip() != locks.node_runtime:
                raise OSError
        _verify_locked_file_beneath(
            root, "package-lock.json", locks.dependency_lock_digest
        )
        _verify_locked_file_beneath(
            root, "packages/coding-agent/package.json", locks.workspace_digest
        )
        for relative, digest in locks.source_anchor_digests.items():
            _verify_locked_file_beneath(root, relative, digest)
        for relative, digest in locks.built_anchor_digests.items():
            _verify_locked_file_beneath(root, relative, digest)
        git_metadata = root / ".git"
        if git_metadata.is_symlink() or not (git_metadata.is_dir() or git_metadata.is_file()):
            raise OSError
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-check-") as temporary:
            environment = _closed_environment(Path(temporary))
            top_level = _run(
                _default_runner, ("git", "rev-parse", "--show-toplevel"), root, environment
            )
            head = _run(_default_runner, ("git", "rev-parse", "HEAD"), root, environment)
            status = _run(
                _default_runner,
                ("git", "status", "--porcelain", "--untracked-files=normal"),
                root,
                environment,
            )
            if (
                not _is_exact_git_root(top_level, root)
                or head.returncode != 0
                or head.stdout.strip() != locks.source_commit
                or status.returncode != 0
                or status.stdout.strip()
            ):
                raise OSError
        return locks
    except (OSError, RuntimeError, PrimeSetupError, subprocess.SubprocessError):
        raise OperationalHarnessError("Prime operational harness is invalid") from None


def _is_asterion_project_tree_ancestor(root: Path) -> bool:
    current = root
    while True:
        try:
            pyproject = current / "pyproject.toml"
            schemas = current / "schemas"
            packages = current / "packages"
            if (
                not pyproject.is_symlink()
                and pyproject.is_file()
                and not schemas.is_symlink()
                and schemas.is_dir()
                and not packages.is_symlink()
                and packages.is_dir()
                and re.search(
                    r'^\[project\][\s\S]*?^name\s*=\s*["\']asterion["\']\s*$',
                    pyproject.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                is not None
            ):
                return True
        except (OSError, UnicodeDecodeError):
            pass
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _resolve_operational_node() -> Path:
    configured = os.environ.get("ASTERION_PRIME_NODE")
    candidates = [Path(configured)] if configured else []
    npm_environment = {
        key: value
        for key in ("HOME", "PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    try:
        completed = subprocess.run(
            ("npm", "exec", "--offline", "--yes", "--package=node@22", "--", "which", "node"),
            cwd=Path(__file__).resolve().parents[1],
            env=npm_environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            candidates.append(Path(completed.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        try:
            completed = subprocess.run(
                (str(candidate), "--version"),
                cwd=Path(__file__).resolve().parents[1],
                env=npm_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0 and _supported_node(completed.stdout.strip()):
                return candidate.resolve(strict=True)
        except (OSError, subprocess.SubprocessError):
            continue
    raise OperationalHarnessError("Prime operational Node runtime is unavailable")


def _parse_rlm_runtime_lock(value: object) -> PrimeRlmRuntimeLock | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "entry",
        "binding_chunk",
        "closure",
        "derived_closure",
        "patch_sha256",
    }:
        raise TypeError
    closure = _parse_digest_mapping(value["closure"])
    derived = _parse_digest_mapping(value["derived_closure"])
    entry = value["entry"]
    binding = value["binding_chunk"]
    if (
        not isinstance(entry, str)
        or not isinstance(binding, str)
        or entry not in closure
        or binding not in closure
        or tuple(closure) != tuple(derived)
        or not isinstance(value["patch_sha256"], str)
        or _SHA256.fullmatch(value["patch_sha256"]) is None
    ):
        raise TypeError
    return PrimeRlmRuntimeLock(
        entry=entry,
        binding_chunk=binding,
        closure=closure,
        derived_closure=derived,
        patch_sha256=value["patch_sha256"],
    )


def load_prime_artifact_lock(path: Path | None = None) -> PrimeArtifactLock:
    try:
        value = json.loads((path or default_lock_path()).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) not in ({
            "format",
            "source_commit",
            "package_name",
            "package_version",
            "daemon_protocol",
            "daemon_schema_revision",
            "daemon_schema_id",
            "files",
        }, {
            "format",
            "source_commit",
            "package_name",
            "package_version",
            "daemon_protocol",
            "daemon_schema_revision",
            "daemon_schema_id",
            "files",
            "rlm_runtime",
        }):
            raise TypeError
        files = value["files"]
        if (
            value["format"] != LOCK_FORMAT
            or not isinstance(value["source_commit"], str)
            or _COMMIT.fullmatch(value["source_commit"]) is None
            or value["package_name"] != "@earendil-works/pi-coding-agent"
            or not isinstance(value["package_version"], str)
            or value["daemon_protocol"] != 7
            or value["daemon_schema_revision"] != 14
            or not isinstance(value["daemon_schema_id"], str)
            or not isinstance(files, dict)
            or not files
        ):
            raise TypeError
        normalized: dict[str, str] = {}
        for relative, digest in files.items():
            candidate = Path(relative)
            if (
                not isinstance(relative, str)
                or candidate.is_absolute()
                or ".." in candidate.parts
                or candidate.as_posix() != relative
                or not isinstance(digest, str)
                or _SHA256.fullmatch(digest) is None
            ):
                raise TypeError
            normalized[relative] = digest
        if tuple(normalized) != tuple(sorted(normalized)):
            raise TypeError
        runtime = _parse_rlm_runtime_lock(value.get("rlm_runtime"))
        return PrimeArtifactLock(
            source_commit=value["source_commit"],
            package_name=value["package_name"],
            package_version=value["package_version"],
            daemon_protocol=value["daemon_protocol"],
            daemon_schema_revision=value["daemon_schema_revision"],
            daemon_schema_id=value["daemon_schema_id"],
            files=MappingProxyType(normalized),
            rlm_runtime=runtime,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise PrimeSetupError("Prime artifact lock is invalid") from None


def load_prime_harness_module_lock(
    path: Path | None = None,
) -> PrimeHarnessModuleLock:
    try:
        value = json.loads(
            (path or default_harness_module_lock_path()).read_text(encoding="utf-8")
        )
        if not isinstance(value, dict) or set(value) != {
            "format",
            "source_commit",
            "entry",
            "source_files",
            "built_modules",
            "required_exports",
        }:
            raise TypeError
        entry = value["entry"]
        source_files = _parse_digest_mapping(value["source_files"])
        built_modules = _parse_digest_mapping(value["built_modules"])
        exports = value["required_exports"]
        if (
            value["format"] != HARNESS_MODULE_LOCK_FORMAT
            or not isinstance(value["source_commit"], str)
            or _COMMIT.fullmatch(value["source_commit"]) is None
            or not isinstance(entry, str)
            or entry not in built_modules
            or Path(entry).name != "index.js"
            or not isinstance(exports, list)
            or tuple(exports) != PRIME_HARNESS_REQUIRED_EXPORTS
        ):
            raise TypeError
        return PrimeHarnessModuleLock(
            source_commit=value["source_commit"],
            entry=entry,
            source_files=source_files,
            built_modules=built_modules,
            required_exports=tuple(exports),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise PrimeSetupError("Prime harness module is invalid") from None


def load_prime_ecosystem_module_lock(
    path: Path | None = None,
) -> PrimeEcosystemModuleLock:
    try:
        lock_path = path or default_ecosystem_module_lock_path()
        value = json.loads(_read_locked_regular_file(lock_path))
        if not isinstance(value, dict) or set(value) != {
            "format",
            "source_commit",
            "artifact_lock_sha256",
            "bundle_sha256",
            "modules",
        }:
            raise TypeError
        modules = value["modules"]
        if (
            value["format"] != ECOSYSTEM_MODULE_LOCK_FORMAT
            or value["source_commit"] != PINNED_PRIME_COMMIT
            or not isinstance(value["artifact_lock_sha256"], str)
            or _SHA256.fullmatch(value["artifact_lock_sha256"]) is None
            or not isinstance(value["bundle_sha256"], str)
            or _SHA256.fullmatch(value["bundle_sha256"]) is None
            or not isinstance(modules, list)
            or len(modules) != len(PRIME_ECOSYSTEM_MODULE_IDS)
        ):
            raise TypeError
        parsed: list[PrimeEcosystemModuleRecord] = []
        source_paths: set[str] = set()
        built_paths: set[str] = set()
        for item in modules:
            if not isinstance(item, dict) or set(item) != {
                "module_id",
                "source_path",
                "built_path",
                "sha256",
            }:
                raise TypeError
            module_id = item["module_id"]
            source_path = item["source_path"]
            built_path = item["built_path"]
            digest = item["sha256"]
            if (
                not isinstance(module_id, str)
                or not isinstance(source_path, str)
                or not isinstance(built_path, str)
                or not isinstance(digest, str)
                or _SHA256.fullmatch(digest) is None
                or not _safe_relative_path(source_path, suffix=".ts")
                or not _safe_relative_path(built_path, suffix=".js")
                or (source_path, built_path)
                != _PRIME_ECOSYSTEM_MODULE_PATHS.get(module_id)
                or source_path in source_paths
                or built_path in built_paths
            ):
                raise TypeError
            source_paths.add(source_path)
            built_paths.add(built_path)
            parsed.append(
                PrimeEcosystemModuleRecord(
                    module_id=module_id,
                    source_path=source_path,
                    built_path=built_path,
                    sha256=digest,
                )
            )
        if tuple(item.module_id for item in parsed) != PRIME_ECOSYSTEM_MODULE_IDS:
            raise TypeError
        return PrimeEcosystemModuleLock(
            source_commit=value["source_commit"],
            artifact_lock_sha256=value["artifact_lock_sha256"],
            bundle_sha256=value["bundle_sha256"],
            modules=tuple(parsed),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, PrimeSetupError):
        raise PrimeSetupError("Prime ecosystem module is invalid") from None


def resolve_prime_harness_module(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    runner: Runner = _default_runner,
) -> Path:
    """Resolve the exact provider-free Prime refinement module."""

    try:
        lock = load_prime_harness_module_lock(lock_path)
        root = _source_root(source_root)
        files = {**lock.source_files, **lock.built_modules}
        _verify_digest_mapping(root, files)
        git_metadata = root / ".git"
        if git_metadata.is_symlink() or not (
            git_metadata.is_dir() or git_metadata.is_file()
        ):
            raise OSError
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-harness-check-"
        ) as temporary:
            environment = _closed_environment(Path(temporary))
            top_level = _run(
                runner, ("git", "rev-parse", "--show-toplevel"), root, environment
            )
            head = _run(runner, ("git", "rev-parse", "HEAD"), root, environment)
            status = _run(
                runner,
                ("git", "status", "--porcelain", "--untracked-files=normal"),
                root,
                environment,
            )
            if (
                not _is_exact_git_root(top_level, root)
                or head.returncode != 0
                or head.stdout.strip() != lock.source_commit
                or status.returncode != 0
                or status.stdout.strip()
            ):
                raise OSError
        return (root / lock.entry).resolve(strict=True)
    except (OSError, RuntimeError, ValueError, PrimeSetupError):
        raise PrimeSetupError("Prime harness module is invalid") from None


def resolve_prime_ecosystem_module(
    source_root: Path,
    lock_path: Path | None = None,
    *,
    artifact_lock_path: Path | None = None,
    bundle_path: Path | None = None,
    runner: Runner = _default_runner,
) -> ResolvedPrimeEcosystemModule:
    """Resolve the exact provider-free Prime ecosystem module without importing it."""

    try:
        selected_lock_path = lock_path or default_ecosystem_module_lock_path()
        lock = load_prime_ecosystem_module_lock(selected_lock_path)
        selected_artifact_path = artifact_lock_path or selected_lock_path.with_name(
            "prime-artifact-lock.json"
        )
        selected_bundle_path = bundle_path or selected_lock_path.with_name(
            "prime-ecosystem-module.mjs"
        )
        artifact_bytes = _read_locked_regular_file(selected_artifact_path)
        if hashlib.sha256(artifact_bytes).hexdigest() != lock.artifact_lock_sha256:
            raise OSError
        artifact = load_prime_artifact_lock(selected_artifact_path)
        if artifact.source_commit != lock.source_commit:
            raise OSError
        bundle_bytes = _read_locked_regular_file(selected_bundle_path)
        if hashlib.sha256(bundle_bytes).hexdigest() != lock.bundle_sha256:
            raise OSError

        root = _source_root(source_root)
        built_paths: dict[str, Path] = {}
        for module in lock.modules:
            source_digest = artifact.files.get(module.source_path)
            built_digest = artifact.files.get(module.built_path)
            if (
                source_digest is None
                or built_digest is None
                or built_digest != module.sha256
            ):
                raise OSError
            _verify_locked_file_beneath(root, module.source_path, source_digest)
            built_paths[module.module_id] = _verify_locked_file_beneath(
                root, module.built_path, module.sha256
            )

        bundle_text = bundle_bytes.decode("utf-8")
        exports = _EXPORTED_ESM_FUNCTION.findall(bundle_text)
        if (
            len(_ANY_ESM_EXPORT.findall(bundle_text)) != len(
                PRIME_ECOSYSTEM_REQUIRED_EXPORTS
            )
            or tuple(sorted(exports)) != PRIME_ECOSYSTEM_REQUIRED_EXPORTS
        ):
            raise OSError
        imports = _STATIC_ESM_IMPORT.findall(bundle_text)
        if (
            len(_ANY_ESM_IMPORT.findall(bundle_text)) != len(imports)
            or _DYNAMIC_ESM_IMPORT.search(bundle_text) is not None
        ):
            raise OSError
        expected_imports = tuple(built_paths.values())
        resolved_imports = tuple(
            _resolve_locked_bundle_import(selected_bundle_path, specifier)
            for specifier in imports
        )
        if len(resolved_imports) != len(expected_imports) or set(
            resolved_imports
        ) != set(expected_imports):
            raise OSError

        git_metadata = root / ".git"
        if git_metadata.is_symlink() or not (
            git_metadata.is_dir() or git_metadata.is_file()
        ):
            raise OSError
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-ecosystem-check-"
        ) as temporary:
            environment = _closed_environment(Path(temporary))
            top_level = _run(
                runner, ("git", "rev-parse", "--show-toplevel"), root, environment
            )
            head = _run(runner, ("git", "rev-parse", "HEAD"), root, environment)
            status = _run(
                runner,
                ("git", "status", "--porcelain", "--untracked-files=normal"),
                root,
                environment,
            )
            if (
                not _is_exact_git_root(top_level, root)
                or head.returncode != 0
                or head.stdout.strip() != PINNED_PRIME_COMMIT
                or status.returncode != 0
                or status.stdout.strip()
            ):
                raise OSError

        return ResolvedPrimeEcosystemModule(
            source_commit=lock.source_commit,
            artifact_lock_sha256=lock.artifact_lock_sha256,
            bundle_sha256=lock.bundle_sha256,
            module_ids=tuple(built_paths),
            built_paths=MappingProxyType(built_paths),
            bundle_path=selected_bundle_path.resolve(strict=True),
        )
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        PrimeSetupError,
    ):
        raise PrimeSetupError("Prime ecosystem module is invalid") from None


def verify_prime_source(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    node_executable: str = "node",
    runner: Runner = _default_runner,
) -> PrimeSetupReport:
    report = verify_prime_checkout(
        source_root,
        lock_path=lock_path,
        runner=runner,
    )
    root = _source_root(source_root)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-check-") as temporary:
        environment = _closed_environment(Path(temporary))
        node = _run(runner, (node_executable, "--version"), root, environment)
        if node.returncode != 0 or not _supported_node(node.stdout.strip()):
            raise PrimeSetupError(
                "Prime setup requires compatible Node.js 22.8.0 through 22.x"
            )
    return report


def verify_prime_checkout(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    runner: Runner = _default_runner,
) -> PrimeSetupReport:
    """Verify the pinned clean checkout without testing a Node runtime."""

    lock = load_prime_artifact_lock(lock_path)
    root = _source_root(source_root)
    _verify_files(root, lock)
    git_metadata = root / ".git"
    if git_metadata.is_symlink() or not (
        git_metadata.is_dir() or git_metadata.is_file()
    ):
        raise PrimeSetupError("Prime source checkout is unavailable")
    with tempfile.TemporaryDirectory(prefix="asterion-prime-check-") as temporary:
        environment = _closed_environment(Path(temporary))
        top_level = _run(
            runner, ("git", "rev-parse", "--show-toplevel"), root, environment
        )
        head = _run(runner, ("git", "rev-parse", "HEAD"), root, environment)
        status = _run(
            runner,
            ("git", "status", "--porcelain", "--untracked-files=normal"),
            root,
            environment,
        )
        if (
            not _is_exact_git_root(top_level, root)
            or head.returncode != 0
            or head.stdout.strip() != lock.source_commit
            or status.returncode != 0
            or status.stdout.strip()
        ):
            raise PrimeSetupError(
                "Prime source checkout is not the pinned clean revision"
            )
    return _report(lock, installed=False)


def setup_prime_source(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    rlm_shim_path: Path | None = None,
    node_executable: str = "node",
    runner: Runner = _default_runner,
) -> PrimeSetupReport:
    report = verify_prime_source(
        source_root,
        lock_path=lock_path,
        node_executable=node_executable,
        runner=runner,
    )
    root = _source_root(source_root)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-npm-") as temporary:
        completed = _run(
            runner,
            ("npm", "ci"),
            root,
            _closed_environment(Path(temporary)),
        )
    if completed.returncode != 0:
        raise PrimeSetupError("Prime dependency installation failed")
    verify_prime_source(
        root,
        lock_path=lock_path,
        node_executable=node_executable,
        runner=runner,
    )
    with tempfile.TemporaryDirectory(prefix="asterion-prime-build-") as temporary:
        environment = _closed_environment(Path(temporary))
        for command in _OFFLINE_BUILD_COMMANDS:
            built = _run(runner, command, root, environment)
            if built.returncode != 0:
                raise PrimeSetupError("Prime source build failed")
    verify_prime_source(
        root,
        lock_path=lock_path,
        node_executable=node_executable,
        runner=runner,
    )
    lock = load_prime_artifact_lock(lock_path)
    if lock.rlm_runtime is not None:
        derive_prime_rlm_runtime(
            root,
            lock_path=lock_path,
            shim_path=rlm_shim_path,
            runner=runner,
        )
    return PrimeSetupReport(
        source_commit=report.source_commit,
        package_version=report.package_version,
        daemon_protocol=report.daemon_protocol,
        daemon_schema_revision=report.daemon_schema_revision,
        installed=True,
    )


def derive_prime_rlm_runtime(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    shim_path: Path | None = None,
    runner: Runner = _default_runner,
) -> Path:
    """Derive the exact ignored Prime daemon bundle without changing source."""

    lock = load_prime_artifact_lock(lock_path)
    runtime = lock.rlm_runtime
    if runtime is None:
        raise PrimeSetupError("Prime RLM runtime lock is unavailable")
    root = _source_root(source_root)
    verify_prime_checkout(root, lock_path=lock_path, runner=runner)
    shim = _read_regular_file(shim_path or default_rlm_shim_path())
    if hashlib.sha256(shim).hexdigest() != runtime.patch_sha256:
        raise PrimeSetupError("Prime RLM shim is incompatible")
    closure = _resolve_local_esm_closure(root, runtime.entry)
    if tuple(closure) != tuple(runtime.closure):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    digests = _closure_digests(root, closure)
    if digests == dict(runtime.derived_closure):
        return root / runtime.entry
    if digests != dict(runtime.closure):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    target, patches = _parse_rlm_shim(shim, runtime)
    original = _read_regular_file_beneath(root, target)
    derived = original
    for anchor, replacement in patches:
        if (
            original.count(anchor) != 1
            or replacement in original
            or anchor in replacement
            or replacement in derived
        ):
            raise PrimeSetupError("Prime RLM shim is incompatible")
        derived = derived.replace(anchor, replacement)
    _atomic_replace_regular_file(root / target, derived)
    if _closure_digests(root, closure) != dict(runtime.derived_closure):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    verify_prime_checkout(root, lock_path=lock_path, runner=runner)
    return root / runtime.entry


def _source_root(value: Path) -> Path:
    try:
        if not isinstance(value, Path) or value.is_symlink():
            raise OSError
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise OSError
        return root
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime source checkout is unavailable") from None


def _safe_relative_path(value: str, *, suffix: str) -> bool:
    candidate = Path(value)
    return (
        bool(value)
        and not candidate.is_absolute()
        and ".." not in candidate.parts
        and candidate.as_posix() == value
        and candidate.suffix == suffix
    )


def _read_locked_regular_file(path: Path) -> bytes:
    try:
        if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
            raise OSError
        metadata = path.stat()
        if metadata.st_mode & 0o002:
            raise OSError
        return path.read_bytes()
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime ecosystem module is invalid") from None


def _verify_locked_file_beneath(root: Path, relative: str, digest: str) -> Path:
    try:
        path = root / relative
        current = root
        for part in Path(relative).parts[:-1]:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                raise OSError
        if path.is_symlink() or not path.is_file():
            raise OSError
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        metadata = resolved.stat()
        if metadata.st_mode & 0o002:
            raise OSError
        contents = resolved.read_bytes()
        if hashlib.sha256(contents).hexdigest() != digest:
            raise OSError
        return resolved
    except (OSError, RuntimeError, ValueError):
        raise PrimeSetupError("Prime ecosystem module is invalid") from None


def _resolve_locked_bundle_import(bundle_path: Path, specifier: str) -> Path:
    try:
        candidate = Path(specifier)
        if (
            not specifier.startswith(".")
            or candidate.is_absolute()
            or candidate.suffix != ".js"
        ):
            raise OSError
        target = bundle_path.parent / candidate
        if target.is_symlink() or not target.is_file():
            raise OSError
        return target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime ecosystem module is invalid") from None


def _verify_files(root: Path, lock: PrimeArtifactLock) -> None:
    try:
        _verify_digest_mapping(root, lock.files)
    except PrimeSetupError:
        raise PrimeSetupError(
            "Prime source artifact does not match the lock"
        ) from None


def _verify_digest_mapping(root: Path, files: Mapping[str, str]) -> None:
    for relative, expected in files.items():
        try:
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise OSError
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if any(parent.is_symlink() for parent in path.parents if parent != root):
                raise OSError
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if digest != expected:
                raise OSError
        except (OSError, RuntimeError, ValueError):
            raise PrimeSetupError("Prime source artifact is invalid") from None


def _read_regular_file(path: Path) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        return path.read_bytes()
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _read_regular_file_beneath(root: Path, relative: str) -> bytes:
    try:
        target = root / relative
        if target.is_symlink() or not target.is_file():
            raise OSError
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
        if any(parent.is_symlink() for parent in target.parents if parent != root):
            raise OSError
        return resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _resolve_local_esm_closure(root: Path, entry: str) -> tuple[str, ...]:
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None
    pending = [entry]
    resolved: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in resolved:
            continue
        contents = _read_regular_file_beneath(root, relative).decode("utf-8")
        resolved.add(relative)
        parent = Path(relative).parent
        imports = _STATIC_LOCAL_ESM_IMPORT.findall(contents)
        if relative == entry:
            imports += _ENTRY_DYNAMIC_LOCAL_ESM_IMPORT.findall(contents)
        else:
            imports += _LINE_DYNAMIC_LOCAL_ESM_IMPORT.findall(contents)
        for imported in imports:
            candidate = Path(imported)
            if candidate.suffix != ".js" or ".." in candidate.parts:
                raise PrimeSetupError("Prime RLM shim is incompatible")
            child = (parent / candidate).as_posix()
            if child.startswith("./"):
                child = child[2:]
            pending.append(child)
    return tuple(sorted(resolved))


def _closure_digests(root: Path, closure: Sequence[str]) -> dict[str, str]:
    return {
        relative: hashlib.sha256(_read_regular_file_beneath(root, relative)).hexdigest()
        for relative in closure
    }


def _parse_rlm_shim(
    bytes_value: bytes, runtime: PrimeRlmRuntimeLock
) -> tuple[str, tuple[tuple[bytes, bytes], ...]]:
    try:
        value = json.loads(bytes_value)
        if not isinstance(value, dict) or set(value) != {
            "format",
            "target",
            "patches",
        }:
            raise TypeError
        target = value["target"]
        patches = value["patches"]
        if (
            value["format"] != "asterion.prime-rlm-host-shim/v1"
            or target != runtime.binding_chunk
            or not isinstance(patches, list)
            or not patches
        ):
            raise TypeError
        parsed: list[tuple[bytes, bytes]] = []
        seen_anchors: set[str] = set()
        seen_replacements: set[str] = set()
        for patch in patches:
            if not isinstance(patch, dict) or set(patch) != {"anchor", "replacement"}:
                raise TypeError
            anchor = patch["anchor"]
            replacement = patch["replacement"]
            if (
                not isinstance(anchor, str)
                or not isinstance(replacement, str)
                or not anchor
                or not replacement
                or anchor == replacement
                or anchor in seen_anchors
                or replacement in seen_replacements
            ):
                raise TypeError
            seen_anchors.add(anchor)
            seen_replacements.add(replacement)
            parsed.append((anchor.encode("utf-8"), replacement.encode("utf-8")))
        return target, tuple(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _atomic_replace_regular_file(path: Path, value: bytes) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(value)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _is_exact_git_root(completed: subprocess.CompletedProcess[str], root: Path) -> bool:
    if completed.returncode != 0:
        return False
    value = completed.stdout.strip()
    candidate = Path(value)
    if not value or not candidate.is_absolute():
        return False
    try:
        return candidate.resolve(strict=True) == root
    except (OSError, RuntimeError):
        return False


def _closed_environment(private_home: Path) -> dict[str, str]:
    environment: dict[str, str] = {
        "HOME": str(private_home),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
        "npm_config_userconfig": os.devnull,
    }
    for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _run(
    runner: Runner,
    command: tuple[str, ...],
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(command, cwd, environment)
    except (OSError, subprocess.SubprocessError):
        raise PrimeSetupError("Prime setup command could not run") from None


def _supported_node(value: str) -> bool:
    match = _VERSION.fullmatch(value)
    if match is None:
        return False
    version = tuple(int(part) for part in match.groups())
    return version[0] == 22 and version >= MINIMUM_NODE_VERSION


def _report(lock: PrimeArtifactLock, *, installed: bool) -> PrimeSetupReport:
    return PrimeSetupReport(
        source_commit=lock.source_commit,
        package_version=lock.package_version,
        daemon_protocol=lock.daemon_protocol,
        daemon_schema_revision=lock.daemon_schema_revision,
        installed=installed,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--node-executable", default="node")
    arguments = parser.parse_args(argv)
    try:
        report = (
            verify_prime_source(
                arguments.source_root,
                node_executable=arguments.node_executable,
            )
            if arguments.check
            else setup_prime_source(
                arguments.source_root,
                node_executable=arguments.node_executable,
            )
        )
    except PrimeSetupError as error:
        print(f"Prime setup failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_commit": report.source_commit,
                "package_version": report.package_version,
                "daemon_protocol": report.daemon_protocol,
                "daemon_schema_revision": report.daemon_schema_revision,
                "dependencies_installed": report.installed,
                "provider_operations": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
