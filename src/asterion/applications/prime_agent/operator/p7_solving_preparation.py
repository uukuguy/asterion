"""Preparation lock and verifier for the independent P7 solving route."""

from __future__ import annotations

from hashlib import sha256
from importlib import resources
import json
from pathlib import Path
import stat
import subprocess
from typing import Callable

from .p7_development_workload import (
    P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256,
    P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256,
)
from .p7_solving_resource_lock import verify_p7_solving_resources

_FORMAT = "asterion.prime-p7-solving-preparation-lock/v1"
_MESSAGE = "P7 solving preparation is unavailable"
_MAX_OUTPUT = 4096
_TIMEOUT = 120


class P7SolvingPreparationError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__(_MESSAGE)


def _bytes() -> bytes:
    try:
        return (
            resources.files("asterion.applications.prime_agent.operator.resources")
            .joinpath("prime-p7-solving-preparation-lock.json")
            .read_bytes()
        )
    except OSError:
        raise P7SolvingPreparationError() from None


def p7_solving_preparation_lock() -> dict[str, object]:
    try:
        lock = json.loads(_bytes())
        required = {
            "format", "gateway_outputs", "gateway_outputs_sha256", "image",
            "license_sha256", "prompt_sha256", "runtime_wheels", "source_inputs",
            "source_inputs_sha256", "upstream_commit",
        }
        if type(lock) is not dict or set(lock) != required or lock["format"] != _FORMAT:
            raise ValueError
        for name in ("gateway_outputs", "source_inputs"):
            values = lock[name]
            if (
                type(values) is not list or values != sorted(set(values)) or not values
                or any(type(value) is not str or Path(value).is_absolute() or ".." in Path(value).parts for value in values)
            ):
                raise ValueError
        for name in ("gateway_outputs_sha256", "source_inputs_sha256", "license_sha256", "prompt_sha256"):
            value = lock[name]
            if type(value) is not str or len(value.removeprefix("sha256:")) != 64:
                raise ValueError
        image = lock["image"]
        if type(image) is not dict or set(image) != {"context", "digest", "dockerfile", "platforms", "tag"}:
            raise ValueError
        if image["platforms"] != ["linux/amd64", "linux/arm64"]:
            raise ValueError
        if type(lock["runtime_wheels"]) is not dict or set(lock["runtime_wheels"]) != {"arc_agi", "arcengine"}:
            raise ValueError
        return lock
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise P7SolvingPreparationError() from None


def _digest(path: Path) -> str:
    try:
        details = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(details.st_mode):
            raise ValueError
        return sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        raise P7SolvingPreparationError() from None


def _aggregate(root: Path, names: object) -> str:
    if type(names) is not list:
        raise P7SolvingPreparationError()
    return sha256(json.dumps(
        [{"path": name, "sha256": _digest(root / name)} for name in names],
        separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()


def _run(argv: list[str], runner: Callable[..., object]) -> object:
    try:
        result = runner(argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=_TIMEOUT, env={"PATH": "/usr/bin:/bin"})
        if any(type(getattr(result, name, b"")) is not bytes or len(getattr(result, name, b"")) > _MAX_OUTPUT for name in ("stdout", "stderr")):
            raise ValueError
        return result
    except Exception:
        raise P7SolvingPreparationError() from None


def _prepare_image(repo: Path, image: object, runner: Callable[..., object]) -> str:
    try:
        if (
            type(image) is not dict
            or type(image.get("tag")) is not str
            or type(image.get("digest")) is not str
            or type(image.get("dockerfile")) is not str
            or type(image.get("context")) is not str
            or image.get("platforms") != ["linux/amd64", "linux/arm64"]
        ):
            raise ValueError
        result = _run(
            ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", image["tag"]],
            runner,
        )
        if getattr(result, "stdout", b"").decode("ascii", "strict").strip() != image["digest"]:
            raise ValueError
        return sha256(json.dumps(
            [image["tag"], image["digest"]], separators=(",", ":")
        ).encode()).hexdigest()
    except BaseException:
        raise P7SolvingPreparationError() from None


def prepare_p7_solving(repo_root: Path, *, runner: Callable[..., object] = subprocess.run) -> dict[str, str]:
    """Build and verify only P7 solving's gateway resources and local inputs."""

    try:
        repo = repo_root.resolve(strict=True)
        lock = p7_solving_preparation_lock()
        gateway = repo / "packages" / "typescript" / "prime-gateway"
        if lock["runtime_wheels"] != {
            "arc_agi": P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256,
            "arcengine": P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256,
        }:
            raise ValueError
        if _aggregate(gateway, lock["source_inputs"]) != lock["source_inputs_sha256"]:
            raise ValueError
        if _aggregate(gateway, lock["gateway_outputs"]) != lock["gateway_outputs_sha256"]:
            _run(["npm", "--prefix", "packages/typescript/prime-gateway", "run", "build"], runner)
        if _aggregate(gateway, lock["gateway_outputs"]) != lock["gateway_outputs_sha256"]:
            raise ValueError
        image_sha256 = _prepare_image(repo, lock["image"], runner)
        external = repo.parent / "external-prime" / "arc-agi-3"
        identities = verify_p7_solving_resources(external)
        return {
            **identities,
            "p7_solving_lock_sha256": sha256(_bytes()).hexdigest(),
            "p7_solving_gateway_sha256": lock["gateway_outputs_sha256"],  # type: ignore[dict-item]
            "p7_solving_image_sha256": image_sha256,
        }
    except BaseException:
        raise P7SolvingPreparationError() from None


__all__ = ("P7SolvingPreparationError", "p7_solving_preparation_lock", "prepare_p7_solving")
