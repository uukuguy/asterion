"""Credential-safe source provenance for an external Pi checkout."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import subprocess
from collections.abc import Callable, Iterable
from importlib import resources
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlsplit


DCI_COMPLETE_IMPLEMENTATION_RESOURCES: tuple[str, ...] = (
    "applications/dci_agent_lite/assemblies/dci-complete-application-claude.json",
    "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
    "capabilities/dci_research/complete.py",
    "capabilities/dci_research/implementation.py",
    "capabilities/dci_research/manifests/dci-analysis.json",
    "capabilities/dci_research/manifests/dci-benchmark.json",
    "capabilities/dci_research/manifests/dci-evaluation.json",
    "capabilities/dci_research/manifests/dci-export.json",
    "capabilities/dci_research/manifests/dci-research.json",
    "capabilities/dci_research/manifests/local-corpus-policy.json",
    "dci/analysis.py",
    "dci/benchmark.py",
    "dci/bridge.py",
    "dci/evaluation.py",
    "dci/judge.py",
    "dci/provenance.py",
    "dci/run.py",
    "dci/services.py",
)
_IMPLEMENTATION_IDENTITY_DOMAIN = b"asterion.dci.implementation/v1\x00"


def dci_complete_implementation_identity(
    *,
    resource_reader: Callable[[str], bytes] | None = None,
    resource_names: Iterable[str] = DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
) -> str:
    """Hash the canonical exact-byte DCI product implementation closure."""

    try:
        names = tuple(resource_names)
    except Exception:
        raise ValueError("DCI implementation resource closure is invalid") from None
    if (
        len(names) != len(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)
        or any(not _canonical_resource_name(name) for name in names)
        or len(set(names)) != len(names)
        or set(names) != set(DCI_COMPLETE_IMPLEMENTATION_RESOURCES)
    ):
        raise ValueError("DCI implementation resource closure is invalid")
    reader = resource_reader or _read_implementation_resource
    digest = hashlib.sha256(_IMPLEMENTATION_IDENTITY_DOMAIN)
    try:
        for name in sorted(names):
            raw = reader(name)
            if type(raw) is not bytes:
                raise TypeError
            encoded = name.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    except Exception:
        raise ValueError(
            "DCI implementation resource closure is unavailable"
        ) from None
    return digest.hexdigest()


def _canonical_resource_name(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _read_implementation_resource(name: str) -> bytes:
    return resources.files("asterion").joinpath(name).read_bytes()


_REVISION_PATTERN = re.compile(r"[0-9a-fA-F]{40,64}")
_SCP_ORIGIN_PATTERN = re.compile(
    r"^(?:[^@/:]+@)?(?P<host>\[[^]]+\]|[^/:]+):(?P<path>.+)$"
)
_NUMERIC_COMPONENT_PATTERN = re.compile(r"(?:[0-9]+|0[xX][0-9A-Fa-f]+)")
_REMOTE_ORIGIN_SCHEMES = frozenset({"git", "http", "https", "ssh"})


def _safe_revision(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate.lower() if _REVISION_PATTERN.fullmatch(candidate) else None


def _git_output(package_dir: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(package_dir), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _sanitized_origin(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme.lower() not in _REMOTE_ORIGIN_SCHEMES:
            return None
        host = parsed.hostname
        if not _is_remote_host(host) or "\\" in parsed.path:
            return None
        return {"host": str(host).lower(), "path": parsed.path or "/"}
    if value.startswith(("/", "./", "../", "~", "\\")):
        return None
    scp_match = _SCP_ORIGIN_PATTERN.fullmatch(value)
    if scp_match is None:
        return None
    host = scp_match.group("host")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    path = scp_match.group("path").split("?", 1)[0].split("#", 1)[0]
    if not _is_remote_host(host) or "\\" in path:
        return None
    return {"host": host.lower(), "path": f"/{path.lstrip('/')}"}


def _is_remote_host(value: str | None) -> bool:
    if not value:
        return False
    host = value.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _looks_numeric(host):
            return True
        address = _parse_legacy_ipv4(host)
        if address is None:
            return False
    return not (address.is_loopback or address.is_unspecified)


def _looks_numeric(host: str) -> bool:
    if not host:
        return False
    parts = host.split(".")
    if all(_NUMERIC_COMPONENT_PATTERN.fullmatch(part) is not None for part in parts):
        return True
    return all(
        part == ""
        or part.lower() == "0x"
        or _NUMERIC_COMPONENT_PATTERN.fullmatch(part) is not None
        for part in parts
    ) and any(part for part in parts)


def _parse_legacy_ipv4(host: str) -> ipaddress.IPv4Address | None:
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    values: list[int] = []
    for part in parts:
        value = _parse_legacy_ipv4_component(part)
        if value is None:
            return None
        values.append(value)
    limits = {
        1: (0xFFFFFFFF,),
        2: (0xFF, 0xFFFFFF),
        3: (0xFF, 0xFF, 0xFFFF),
        4: (0xFF, 0xFF, 0xFF, 0xFF),
    }[len(values)]
    if any(value > limit for value, limit in zip(values, limits, strict=True)):
        return None
    if len(values) == 1:
        integer = values[0]
    elif len(values) == 2:
        integer = (values[0] << 24) | values[1]
    elif len(values) == 3:
        integer = (values[0] << 24) | (values[1] << 16) | values[2]
    else:
        integer = (
            (values[0] << 24) | (values[1] << 16) | (values[2] << 8) | values[3]
        )
    return ipaddress.IPv4Address(integer)


def _parse_legacy_ipv4_component(component: str) -> int | None:
    if not component:
        return None
    lowered = component.lower()
    if lowered.startswith("0x"):
        digits = component[2:]
        base = 16
        valid = bool(digits) and all(character in "0123456789abcdefABCDEF" for character in digits)
    elif len(component) > 1 and component.startswith("0"):
        digits = component[1:]
        base = 8
        valid = all(character in "01234567" for character in digits)
    else:
        digits = component
        base = 10
        valid = component.isascii() and component.isdigit()
    if not valid:
        return None
    return int(digits or "0", base)


def collect_pi_provenance(
    package_dir: Path,
    lock_file: Path,
    revision_override: str | None,
) -> dict[str, object]:
    """Describe a Pi checkout without retaining credentials or arbitrary Git output."""

    lock_revision: str | None = None
    try:
        lock_revision = _safe_revision(Path(lock_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        pass

    repository = _git_output(Path(package_dir), "rev-parse", "--show-toplevel")
    commit = (
        _safe_revision(_git_output(Path(package_dir), "rev-parse", "HEAD"))
        if repository is not None
        else None
    )
    status = (
        _git_output(Path(package_dir), "status", "--porcelain", "--untracked-files=normal")
        if repository is not None
        else None
    )
    origin = (
        _sanitized_origin(_git_output(Path(package_dir), "remote", "get-url", "origin"))
        if repository is not None
        else None
    )
    safe_override = _safe_revision(revision_override)
    expected_revision = safe_override if revision_override is not None else lock_revision
    expected_source = "DCI_PI_REVISION" if revision_override is not None else "pi-revision.txt"
    return {
        "managed_git_checkout": repository is not None,
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "origin": origin,
        "lock_revision": lock_revision,
        "lock_match": commit == lock_revision if commit and lock_revision else None,
        "expected_revision": expected_revision,
        "expected_revision_source": expected_source,
        "expected_match": (
            commit == expected_revision if commit and expected_revision else None
        ),
    }


def format_pi_revision_warning(provenance: dict[str, object]) -> str | None:
    """Return a safe non-blocking warning for an exact revision mismatch."""

    if provenance.get("expected_match") is not False:
        return None
    commit = provenance.get("commit")
    expected = provenance.get("expected_revision")
    source = provenance.get("expected_revision_source")
    if not isinstance(commit, str) or not isinstance(expected, str):
        return None
    if source not in {"DCI_PI_REVISION", "pi-revision.txt"}:
        return None
    return (
        f"Pi source warning: actual commit {commit} does not match expected revision "
        f"{expected} from {source}; continuing with recorded provenance."
    )
