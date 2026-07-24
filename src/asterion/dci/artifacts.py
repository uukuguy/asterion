"""Durable native artifacts for an independent Asterion DCI run."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import socket
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from asterion.adapters.pi import PiProtocolAdapter, map_pi_capabilities
from asterion.dci.config import DciPaths
from asterion.dci.provenance import collect_pi_provenance
from asterion.dci.run import (
    DciRunRequest,
    prelude_questions_fingerprint,
    validate_dci_run_request,
)
from asterion.runtime.host import RunEvent
from asterion.runtime.protocol import (
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
    validate_event_stream,
    validate_run_request,
)

if TYPE_CHECKING:
    from asterion.dci.context_extension import ResolvedContextExtension
    from asterion.dci.context_profiles import DciContextProfile

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]


_PAPER_REPORT_KEYS = {
    "schema",
    "mode",
    "provider",
    "model",
    "judge",
    "pi_revision",
    "pi_tracked_status_sha256",
    "agent_operations",
    "judge_operations",
    "external_operations",
    "api_request_multiplicity",
    "operation_order",
    "full_dataset_ran",
    "resources",
    "operations",
}
_PAPER_OPERATION_KEYS = {
    "operation_id",
    "kind",
    "accepted",
    "artifact_digests",
}
_PAPER_OPERATION_PLAN = ("qa-agent", "qa-judge", "ir-agent")
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
_PUBLIC_EVIDENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*")


class DciArtifactError(RuntimeError):
    """Safe failure at the native artifact filesystem boundary."""


_POLICY_STATE_KEYS = {
    "accumulatedOriginalToolCharacters",
    "truncatedResults",
    "compactionCount",
    "preservedTurns",
    "compactionPending",
    "summaryAttempts",
    "summarySuccesses",
    "consecutiveSummaryFailures",
    "summarySuppressed",
}
_POLICY_NUMERIC_KEYS = _POLICY_STATE_KEYS - {
    "compactionPending",
    "summarySuppressed",
    "preservedTurns",
}


def _validated_policy_state(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _POLICY_STATE_KEYS:
        raise DciArtifactError("DCI context policy evidence is invalid")
    if any(
        isinstance(value.get(key), bool)
        or not isinstance(value.get(key), int)
        or value[key] < 0
        for key in _POLICY_NUMERIC_KEYS
    ) or not (
        value.get("preservedTurns") is None
        or (
            not isinstance(value.get("preservedTurns"), bool)
            and isinstance(value.get("preservedTurns"), int)
            and value["preservedTurns"] >= 0
        )
    ) or any(
        not isinstance(value.get(key), bool)
        for key in ("compactionPending", "summarySuppressed")
    ):
        raise DciArtifactError("DCI context policy evidence is invalid")
    return dict(value)


@dataclass(frozen=True)
class DciContextTelemetry:
    """One body-free, schema-closed policy counter snapshot."""

    event: str
    profile: str
    contract_version: str
    extension_version: str
    state: dict[str, object]

    @classmethod
    def from_mapping(cls, value: object) -> DciContextTelemetry:
        expected = _POLICY_STATE_KEYS | {
            "schema",
            "event",
            "profile",
            "contractVersion",
            "extensionVersion",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise DciArtifactError("DCI context policy evidence is invalid")
        if (
            value.get("schema") != "dci.context-telemetry/v2"
            or not isinstance(value.get("event"), str)
            or not value["event"]
            or value.get("profile")
            not in {"level0", "level1", "level2", "level3", "level4"}
            or not isinstance(value.get("contractVersion"), str)
            or not isinstance(value.get("extensionVersion"), str)
        ):
            raise DciArtifactError("DCI context policy evidence is invalid")
        state = _validated_policy_state(
            {key: value[key] for key in _POLICY_STATE_KEYS}
        )
        return cls(
            event=value["event"],
            profile=value["profile"],
            contract_version=value["contractVersion"],
            extension_version=value["extensionVersion"],
            state=state,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": "dci.context-telemetry/v2",
            "event": self.event,
            "profile": self.profile,
            "contractVersion": self.contract_version,
            "extensionVersion": self.extension_version,
            **self.state,
        }


@dataclass(frozen=True)
class DciContextPolicyEvidence:
    """Validated policy identity and telemetry used for safe public projection."""

    profile: DciContextProfile
    extension_version: str
    extension_sha256: str
    telemetry: tuple[DciContextTelemetry, ...]

    def public_summary(self) -> dict[str, object]:
        if not self.telemetry:
            raise DciArtifactError("DCI context policy evidence is invalid")
        latest = self.telemetry[-1].state
        return {
            "schema": "dci.context-policy-evidence/v2",
            "profile": self.profile.name,
            "contract_version": self.profile.contract_version,
            "extension_version": self.extension_version,
            "extension_sha256": self.extension_sha256,
            "truncated_results": latest["truncatedResults"],
            "compactions": latest["compactionCount"],
            "preserved_turns": latest["preservedTurns"],
            "summary_attempts": latest["summaryAttempts"],
            "summary_successes": latest["summarySuccesses"],
            "summary_suppressed": latest["summarySuppressed"],
        }


def _reject_symlink(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise DciArtifactError(f"DCI {label} must not be a symlink")


def _open_flags(flags: int) -> int:
    return flags | getattr(os, "O_NOFOLLOW", 0)


def _validate_leaf_name(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise DciArtifactError("DCI artifact name is invalid")


def _read_json_object_at(directory_fd: int, name: str) -> dict[str, Any]:
    _validate_leaf_name(name)
    descriptor: int | None = None
    try:
        descriptor = os.open(name, _open_flags(os.O_RDONLY), dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DciArtifactError("DCI artifact JSON is invalid")
        handle = os.fdopen(descriptor, encoding="utf-8")
        descriptor = None
        with handle:
            value = json.load(handle)
    except DciArtifactError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DciArtifactError("DCI artifact JSON is invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise DciArtifactError("DCI artifact JSON is invalid")
    return value


def _read_optional_json_object_at(
    directory_fd: int, name: str
) -> dict[str, Any] | None:
    _validate_leaf_name(name)
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return _read_json_object_at(directory_fd, name)


def _read_optional_json_document_at(
    directory_fd: int, name: str
) -> tuple[dict[str, Any], bytes] | None:
    _validate_leaf_name(name)
    try:
        descriptor = os.open(name, _open_flags(os.O_RDONLY), dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    try:
        entry = os.fstat(descriptor)
        if not stat.S_ISREG(entry.st_mode) or stat.S_IMODE(entry.st_mode) != 0o600:
            raise DciArtifactError("DCI artifact JSON is invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read()
        value = json.loads(raw.decode("utf-8"))
    except DciArtifactError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DciArtifactError("DCI artifact JSON is invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise DciArtifactError("DCI artifact JSON is invalid")
    return value, raw


def json_document_bytes(payload: Any) -> bytes:
    """Serialize one native private JSON document exactly as the recorder writes it."""

    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _prepare_json_at(directory_fd: int, target: str, payload: Any) -> str:
    _validate_leaf_name(target)
    _reject_symlink_at(directory_fd, target, label="JSON target")
    temporary = f".{target}.{secrets.token_hex(16)}.evaluation-tmp"
    descriptor = os.open(
        temporary,
        _open_flags(os.O_CREAT | os.O_EXCL | os.O_WRONLY),
        0o600,
        dir_fd=directory_fd,
    )
    completed = False
    try:
        os.fchmod(descriptor, 0o600)
        data = json_document_bytes(payload)
        _write_prepared_bytes(descriptor, data)
        completed = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not completed:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    return temporary


def _write_prepared_bytes(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("DCI evaluation prepare write failed")
        offset += written
    os.fsync(descriptor)


def _publish_prepared_at(directory_fd: int, temporary: str, target: str) -> None:
    _validate_leaf_name(temporary)
    _validate_leaf_name(target)
    _reject_symlink_at(directory_fd, target, label="JSON target")
    os.replace(temporary, target, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)


def _fsync_directory(directory_fd: int) -> None:
    os.fsync(directory_fd)


def _reject_symlink_at(directory_fd: int, name: str, *, label: str) -> None:
    _validate_leaf_name(name)
    try:
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(entry.st_mode):
        raise DciArtifactError(f"DCI {label} must not be a symlink")


def _atomic_write_json_at(directory_fd: int, name: str, payload: Any) -> None:
    _validate_leaf_name(name)
    _reject_symlink_at(directory_fd, name, label="JSON target")
    temporary = f".{name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            _open_flags(os.O_CREAT | os.O_EXCL | os.O_WRONLY),
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        try:
            os.fsync(directory_fd)
        except OSError:
            # Some filesystems do not support directory fsync; the file itself is durable.
            pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _open_directory(path: Path) -> int:
    _reject_symlink(path, label="directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        return os.open(path, _open_flags(flags))
    except OSError as exc:
        raise DciArtifactError("DCI artifact directory is invalid") from exc


def _open_private_directory_at(parent_fd: int, name: str) -> int:
    _validate_leaf_name(name)
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(name, _open_flags(flags), dir_fd=parent_fd)
    except OSError as exc:
        raise DciArtifactError("DCI artifact directory is invalid") from exc
    try:
        os.fchmod(descriptor, 0o700)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_existing_directory_at(parent_fd: int, name: str) -> int:
    _validate_leaf_name(name)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(name, _open_flags(flags), dir_fd=parent_fd)
    except OSError as exc:
        raise DciArtifactError("DCI artifact directory is invalid") from exc
    return descriptor


def _read_text_at(directory_fd: int, name: str) -> str:
    _validate_leaf_name(name)
    descriptor: int | None = None
    try:
        descriptor = os.open(name, _open_flags(os.O_RDONLY), dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DciArtifactError("DCI artifact file is invalid")
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = None
            return handle.read()
    except DciArtifactError:
        raise
    except (OSError, UnicodeError) as exc:
        raise DciArtifactError("DCI artifact file is invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_jsonl_at(directory_fd: int, name: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in _read_text_at(directory_fd, name).splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DciArtifactError("DCI artifact JSONL is invalid") from exc
        if not isinstance(value, dict):
            raise DciArtifactError("DCI artifact JSONL is invalid")
        values.append(value)
    return values


def _write_exclusive_text_at(directory_fd: int, name: str, value: str) -> None:
    _validate_leaf_name(name)
    try:
        descriptor = os.open(
            name,
            _open_flags(os.O_CREAT | os.O_EXCL | os.O_WRONLY),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(value)
            handle.flush()
    except OSError as exc:
        raise DciArtifactError("DCI attempt evidence already exists") from exc


def _write_exclusive_json_at(directory_fd: int, name: str, payload: Any) -> None:
    _write_exclusive_text_at(
        directory_fd,
        name,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically replace one private JSON document in its existing directory."""

    destination = Path(path)
    parent = destination.parent
    _reject_symlink(parent, label="JSON parent")
    try:
        resolved_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise DciArtifactError("DCI JSON parent is invalid") from exc
    if not resolved_parent.is_dir():
        raise DciArtifactError("DCI JSON parent is invalid")
    directory_fd = _open_directory(resolved_parent)
    try:
        _atomic_write_json_at(directory_fd, destination.name, payload)
    finally:
        os.close(directory_fd)


def _read_json_object(path: Path) -> dict[str, Any]:
    directory_fd = _open_directory(path.parent)
    try:
        return _read_json_object_at(directory_fd, path.name)
    finally:
        os.close(directory_fd)


def _validate_lock_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"pid", "hostname", "created_at", "owner_token"}:
        raise DciArtifactError("DCI run lock is invalid")
    pid = payload["pid"]
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise DciArtifactError("DCI run lock is invalid")
    if not isinstance(payload["hostname"], str) or not payload["hostname"]:
        raise DciArtifactError("DCI run lock is invalid")
    if not isinstance(payload["owner_token"], str) or not payload["owner_token"]:
        raise DciArtifactError("DCI run lock is invalid")
    created_at = payload["created_at"]
    if not isinstance(created_at, str):
        raise DciArtifactError("DCI run lock is invalid")
    try:
        timestamp = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise DciArtifactError("DCI run lock is invalid") from exc
    if timestamp.tzinfo is None:
        raise DciArtifactError("DCI run lock is invalid")
    return payload


def _lock_payload_at(directory_fd: int, name: str) -> dict[str, Any]:
    return _validate_lock_payload(_read_json_object_at(directory_fd, name))


def _lock_payload(path: Path) -> dict[str, Any]:
    return _validate_lock_payload(_read_json_object(path))


def _acquire_directory_fd(path: Path, *, create: bool, wait: bool = False) -> int:
    """Open, verify, privatize, and exclusively lock one run directory."""

    if fcntl is None:
        raise DciArtifactError("DCI run locking is unavailable")
    _reject_symlink(path, label="output directory")
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    _reject_symlink(path, label="output directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, _open_flags(flags))
    except OSError as exc:
        raise DciArtifactError("DCI output directory is invalid") from exc
    try:
        os.fchmod(descriptor, 0o700)
        operation = fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
        fcntl.flock(descriptor, operation)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise DciArtifactError("DCI run directory is locked") from exc
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise DciArtifactError("DCI run locking failed") from exc
    return descriptor


def _acquire_existing_directory_fd_nofollow(path: Path, *, wait: bool) -> int:
    """Walk every existing directory component without following links, then lock it."""

    if fcntl is None:
        raise DciArtifactError("DCI run locking is unavailable")
    absolute = Path(os.path.abspath(path))
    descriptor = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for component in absolute.parts[1:]:
            next_descriptor = _open_existing_directory_at(descriptor, component)
            os.close(descriptor)
            descriptor = next_descriptor
        os.fchmod(descriptor, 0o700)
        fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        return descriptor
    except BlockingIOError as exc:
        os.close(descriptor)
        raise DciArtifactError("DCI run directory is locked") from exc
    except BaseException:
        os.close(descriptor)
        raise


def _validate_lock_metadata_at(directory_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    metadata = _lock_payload_at(directory_fd, name)
    if metadata["hostname"] != socket.gethostname():
        raise DciArtifactError("DCI run lock metadata is foreign")


@dataclass
class DciRunLock:
    """OS-backed exclusive lock plus diagnostic metadata for one run directory."""

    LOCK_NAME = ".dci-run.lock"
    EVALUATION_TRANSACTION_NAME = ".dci-evaluation-transaction.json"

    path: Path
    owner_token: str
    _directory_fd: int
    _released: bool = False

    @classmethod
    def acquire_fd(
        cls, directory_fd: int, *, path: Path, wait: bool = False
    ) -> DciRunLock:
        """Acquire writer authority from an already-open directory inode."""

        if fcntl is None:
            raise DciArtifactError("DCI run locking is unavailable")
        descriptor = os.dup(directory_fd)
        try:
            os.fchmod(descriptor, 0o700)
            operation = fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
            fcntl.flock(descriptor, operation)
            _validate_lock_metadata_at(descriptor, cls.LOCK_NAME)
            owner_token = secrets.token_hex(32)
            _atomic_write_json_at(
                descriptor,
                cls.LOCK_NAME,
                {
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "owner_token": owner_token,
                },
            )
            return cls(
                path=Path(path) / cls.LOCK_NAME,
                owner_token=owner_token,
                _directory_fd=descriptor,
            )
        except BaseException:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(descriptor)
            raise

    @classmethod
    def acquire(cls, output_dir: Path, *, create: bool = True) -> DciRunLock:
        directory = Path(output_dir)
        descriptor = _acquire_directory_fd(directory, create=create)
        try:
            lock_path = directory.absolute() / cls.LOCK_NAME
            owner_token = secrets.token_hex(32)
            payload = {
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "owner_token": owner_token,
            }
            _validate_lock_metadata_at(descriptor, cls.LOCK_NAME)
            _atomic_write_json_at(descriptor, cls.LOCK_NAME, payload)
            return cls(
                path=lock_path, owner_token=owner_token, _directory_fd=descriptor
            )
        except BaseException:
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            finally:
                os.close(descriptor)
            raise

    @classmethod
    def acquire_existing(cls, output_dir: Path, *, wait: bool = True) -> DciRunLock:
        """Acquire the recorder's writer authority without creating run evidence."""

        directory = Path(output_dir)
        descriptor = _acquire_existing_directory_fd_nofollow(directory, wait=wait)
        try:
            _validate_lock_metadata_at(descriptor, cls.LOCK_NAME)
            metadata = _lock_payload_at(descriptor, cls.LOCK_NAME)
            return cls(
                path=directory.absolute() / cls.LOCK_NAME,
                owner_token=str(metadata["owner_token"]),
                _directory_fd=descriptor,
            )
        except BaseException:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
            raise

    def read_json(self, name: str) -> dict[str, Any]:
        return _read_json_object_at(self._directory_fd, name)

    def read_optional_json(self, name: str) -> dict[str, Any] | None:
        return _read_optional_json_object_at(self._directory_fd, name)

    def read_optional_json_document(
        self, name: str
    ) -> tuple[dict[str, Any], bytes] | None:
        return _read_optional_json_document_at(self._directory_fd, name)

    def read_text(self, name: str) -> str:
        return _read_text_at(self._directory_fd, name)

    def read_jsonl(self, name: str) -> list[dict[str, Any]]:
        return _read_jsonl_at(self._directory_fd, name)

    def write_json(self, name: str, payload: Any) -> None:
        _atomic_write_json_at(self._directory_fd, name, payload)

    def publish_json_pair(
        self,
        *,
        state: dict[str, Any],
        evaluation: dict[str, Any],
    ) -> None:
        """Publish state binding first and the evaluation commit document last."""

        state_tmp: str | None = None
        evaluation_tmp: str | None = None
        manifest_tmp: str | None = None
        manifest_visible = False
        state_bytes = json_document_bytes(state)
        evaluation_bytes = json_document_bytes(evaluation)
        commit_id = evaluation.get("evaluation_commit_id")
        fingerprint = evaluation.get("judge_request_fingerprint")
        if (
            not isinstance(commit_id, str)
            or not isinstance(fingerprint, str)
            or state.get("evaluation", {}).get("evaluation_commit_id") != commit_id
        ):
            raise DciArtifactError("DCI evaluation transaction is invalid")
        try:
            evaluation_tmp = _prepare_json_at(
                self._directory_fd, "eval_result.json", evaluation
            )
            state_tmp = _prepare_json_at(self._directory_fd, "state.json", state)
            manifest = {
                "schema": "dci.evaluation-transaction/v1",
                "commit_id": commit_id,
                "judge_request_fingerprint": fingerprint,
                "state_temp": state_tmp,
                "evaluation_temp": evaluation_tmp,
                "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
                "evaluation_sha256": hashlib.sha256(evaluation_bytes).hexdigest(),
            }
            manifest_tmp = _prepare_json_at(
                self._directory_fd, self.EVALUATION_TRANSACTION_NAME, manifest
            )
            _publish_prepared_at(
                self._directory_fd,
                manifest_tmp,
                self.EVALUATION_TRANSACTION_NAME,
            )
            manifest_tmp = None
            manifest_visible = True
            _fsync_directory(self._directory_fd)
            _publish_prepared_at(self._directory_fd, state_tmp, "state.json")
            state_tmp = None
            _fsync_directory(self._directory_fd)
            _publish_prepared_at(self._directory_fd, evaluation_tmp, "eval_result.json")
            evaluation_tmp = None
            _fsync_directory(self._directory_fd)
            self._clear_evaluation_manifest(manifest)
            manifest_visible = False
        finally:
            if not manifest_visible:
                for temporary in (state_tmp, evaluation_tmp, manifest_tmp):
                    if temporary is not None:
                        try:
                            os.unlink(temporary, dir_fd=self._directory_fd)
                        except FileNotFoundError:
                            pass

    def recover_evaluation_transaction(
        self,
        *,
        validate_candidate: Callable[
            [tuple[dict[str, Any], bytes], tuple[dict[str, Any], bytes]], bool
        ],
    ) -> bool:
        """Validate and finish one explicitly owned pending pair transaction."""

        document = self.read_optional_json_document(self.EVALUATION_TRANSACTION_NAME)
        if document is None:
            return False
        manifest, _ = document
        expected_names = {
            "schema",
            "commit_id",
            "judge_request_fingerprint",
            "state_temp",
            "evaluation_temp",
            "state_sha256",
            "evaluation_sha256",
        }
        if (
            set(manifest) != expected_names
            or manifest["schema"] != "dci.evaluation-transaction/v1"
            or not all(
                isinstance(manifest[name], str) and manifest[name]
                for name in expected_names - {"schema"}
            )
            or re.fullmatch(r"[0-9a-f]{64}", manifest["commit_id"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", manifest["judge_request_fingerprint"])
            is None
            or re.fullmatch(r"[0-9a-f]{64}", manifest["state_sha256"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", manifest["evaluation_sha256"]) is None
            or re.fullmatch(
                r"\.state\.json\.[0-9a-f]{32}\.evaluation-tmp",
                manifest["state_temp"],
            )
            is None
            or re.fullmatch(
                r"\.eval_result\.json\.[0-9a-f]{32}\.evaluation-tmp",
                manifest["evaluation_temp"],
            )
            is None
        ):
            raise DciArtifactError("DCI evaluation transaction is invalid")
        state_temp = _read_optional_json_document_at(
            self._directory_fd, manifest["state_temp"]
        )
        evaluation_temp = _read_optional_json_document_at(
            self._directory_fd, manifest["evaluation_temp"]
        )
        state_target = _read_optional_json_document_at(self._directory_fd, "state.json")
        evaluation_target = _read_optional_json_document_at(
            self._directory_fd, "eval_result.json"
        )
        state_source = _select_transaction_document(
            state_temp,
            state_target,
            digest=manifest["state_sha256"],
            commit_id=manifest["commit_id"],
            state=True,
        )
        evaluation_source = _select_transaction_document(
            evaluation_temp,
            evaluation_target,
            digest=manifest["evaluation_sha256"],
            commit_id=manifest["commit_id"],
            state=False,
        )
        if (
            state_target is None
            or _state_without_evaluation(state_source[0])
            != _state_without_evaluation(state_target[0])
            or not validate_candidate(state_source, evaluation_source)
            or (
                evaluation_source[0].get("judge_request_fingerprint")
                != manifest["judge_request_fingerprint"]
            )
        ):
            raise DciArtifactError("DCI evaluation transaction is invalid")
        if state_temp is not None:
            _publish_prepared_at(
                self._directory_fd, manifest["state_temp"], "state.json"
            )
        _fsync_directory(self._directory_fd)
        if evaluation_temp is not None:
            _publish_prepared_at(
                self._directory_fd,
                manifest["evaluation_temp"],
                "eval_result.json",
            )
        _fsync_directory(self._directory_fd)
        self._clear_evaluation_manifest(manifest)
        return True

    def _clear_evaluation_manifest(self, manifest: dict[str, Any]) -> None:
        os.unlink(self.EVALUATION_TRANSACTION_NAME, dir_fd=self._directory_fd)
        try:
            _fsync_directory(self._directory_fd)
        except OSError:
            _atomic_write_json_at(
                self._directory_fd, self.EVALUATION_TRANSACTION_NAME, manifest
            )
            raise

    def open_directory(self, name: str) -> int:
        return _open_existing_directory_at(self._directory_fd, name)

    def release(self) -> None:
        if self._released:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._directory_fd, fcntl.LOCK_UN)
        finally:
            try:
                os.close(self._directory_fd)
            except OSError:
                pass
            self._released = True


def _select_transaction_document(
    temporary: tuple[dict[str, Any], bytes] | None,
    target: tuple[dict[str, Any], bytes] | None,
    *,
    digest: str,
    commit_id: str,
    state: bool,
) -> tuple[dict[str, Any], bytes]:
    candidate = temporary if temporary is not None else target
    if candidate is None or hashlib.sha256(candidate[1]).hexdigest() != digest:
        raise DciArtifactError("DCI evaluation transaction is invalid")
    actual_commit = (
        candidate[0].get("evaluation", {}).get("evaluation_commit_id")
        if state and isinstance(candidate[0].get("evaluation"), dict)
        else candidate[0].get("evaluation_commit_id")
    )
    if actual_commit != commit_id:
        raise DciArtifactError("DCI evaluation transaction is invalid")
    return candidate


def _state_without_evaluation(value: dict[str, Any]) -> dict[str, Any]:
    projected = dict(value)
    projected.pop("evaluation", None)
    return projected


def validate_completed_run_evidence(
    lock: DciRunLock,
) -> tuple[dict[str, Any], str, str]:
    """Validate a completed native run from the held descriptor authority."""

    state = lock.read_json("state.json")
    question_text = lock.read_text("question.txt")
    final_text = lock.read_text("final.txt")
    raw_events = lock.read_jsonl("events.jsonl")
    conversation = lock.read_json("conversation.json")
    conversation_full = lock.read_json("conversation_full.json")
    latest_context = lock.read_json("latest_model_context.json")
    lock.read_text("stderr.txt")
    question = state.get("question")
    attempts = state.get("attempts")
    answer = state.get("assistant_text")
    run_id = state.get("run_id")
    tools = state.get("tools")
    if (
        state.get("status") != "completed"
        or not isinstance(question, str)
        or not question
        or question_text != f"{question}\n"
        or not isinstance(answer, str)
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(tools, str)
        or final_text != (answer if answer.endswith("\n") else f"{answer}\n")
        or not isinstance(attempts, list)
        or not attempts
        or state.get("resume_count") != len(attempts) - 1
        or state.get("event_count") != len(raw_events)
        or state.get("last_event_type")
        != (raw_events[-1].get("type") if raw_events else None)
        or conversation.get("status") != "completed"
        or conversation_full.get("status") != "completed"
        or latest_context.get("status") != "completed"
        or conversation_full.get("question") != question
        or latest_context.get("question") != question
        or conversation_full.get("final_text") != answer
        or conversation_full.get("conversation_features")
        != state.get("conversation_features")
        or latest_context.get("conversation_features")
        != state.get("conversation_features")
        or conversation_full.get("notes") != state.get("notes")
        or latest_context.get("notes") != state.get("notes")
        or conversation_full.get("pi_source_attempts")
        != state.get("pi_source_attempts")
        or latest_context.get("pi_source_attempts") != state.get("pi_source_attempts")
    ):
        raise DciArtifactError("DCI completed run evidence is invalid")
    _validate_completed_view_shapes(
        lock._directory_fd,
        state,
        conversation,
        conversation_full,
        latest_context,
        raw_events,
    )
    protocol_fd = lock.open_directory("protocol")
    try:
        expected_names: set[str] = set()
        protocol_attempt_texts: list[str] = []
        protocol_projection: list[tuple[str, dict[str, Any]]] = []
        for number, raw_attempt in enumerate(attempts, 1):
            attempt = _validate_attempt_record(raw_attempt, number)
            stem = f"attempt-{number:04d}"
            request_name = f"{stem}.request.json"
            events_name = f"{stem}.events.jsonl"
            expected_names.update((request_name, events_name))
            protocol_request = _read_json_object_at(protocol_fd, request_name)
            validate_run_request(protocol_request)
            expected_request: dict[str, object] = {
                "protocol": PROTOCOL_VERSION,
                "run_id": f"{run_id}-attempt-{number:04d}",
                "input": {"text": question},
                "requested_capabilities": map_pi_capabilities(tools),
            }
            timeout = attempt["timeout_seconds"]
            if timeout is not None and timeout > 0:
                deadline_ms = int(round(timeout * 1000))
                if deadline_ms <= MAX_DEADLINE_MS:
                    expected_request["deadline_ms"] = max(1, deadline_ms)
            if protocol_request != expected_request:
                raise DciArtifactError("DCI completed run evidence is invalid")
            protocol_events = _read_jsonl_at(protocol_fd, events_name)
            validate_event_stream(protocol_events)
            attempt_text = "".join(
                event["payload"]["text"]
                for event in protocol_events
                if event.get("type") == "text.delta"
                and isinstance(event.get("payload"), dict)
                and isinstance(event["payload"].get("text"), str)
            )
            protocol_attempt_texts.append(attempt_text)
            protocol_projection.extend(
                (event["type"], event["payload"])
                for event in protocol_events
                if event.get("type")
                in {"text.delta", "tool.call", "tool.result", "usage.reported"}
            )
            if not protocol_events or any(
                event.get("run_id") != protocol_request.get("run_id")
                for event in protocol_events
            ):
                raise DciArtifactError("DCI completed run evidence is invalid")
            terminal = protocol_events[-1]
            expected_status = (
                "completed" if number == len(attempts) else attempt["status"]
            )
            if (
                attempt["status"] != expected_status
                or (
                    number == len(attempts)
                    and (
                        terminal.get("type") != "run.completed"
                        or terminal.get("payload") != {"status": "completed"}
                    )
                )
                or (
                    number < len(attempts)
                    and (
                        attempt["status"] not in {"failed", "incomplete"}
                        or terminal.get("type") != "run.failed"
                    )
                )
            ):
                raise DciArtifactError("DCI completed run evidence is invalid")
            if number == len(attempts):
                artifacts = [
                    event.get("payload", {}).get("artifact")
                    for event in protocol_events
                    if event.get("type") == "artifact.created"
                    and isinstance(event.get("payload"), dict)
                ]
                expected_digest = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
                if (
                    len(artifacts) != 1
                    or not isinstance(artifacts[0], dict)
                    or (
                        artifacts[0].get("uri") != "final.txt"
                        or artifacts[0].get("sha256") != expected_digest
                    )
                ):
                    raise DciArtifactError("DCI completed run evidence is invalid")
        if set(os.listdir(protocol_fd)) != expected_names:
            raise DciArtifactError("DCI completed run evidence is invalid")
        raw_answer = _raw_text_delta_projection(raw_events)
        if (
            protocol_attempt_texts[-1] != answer
            or "".join(protocol_attempt_texts) != raw_answer
            or protocol_projection != _raw_protocol_projection(raw_events)
        ):
            raise DciArtifactError("DCI completed run evidence is invalid")
    except (DciArtifactError, ValueError):
        raise
    except (OSError, TypeError) as exc:
        raise DciArtifactError("DCI completed run evidence is invalid") from exc
    finally:
        os.close(protocol_fd)
    return state, question, final_text.rstrip("\n")


def validate_resumable_run_evidence(
    lock: DciRunLock,
    request: DciRunRequest,
    paths: DciPaths,
) -> tuple[dict[str, Any], str, str, str, dict[str, Any]]:
    """Validate one finalized failed/incomplete run without mutating its evidence."""

    state = lock.read_json("state.json")
    if state.get("status") not in {"failed", "incomplete"}:
        raise DciArtifactError("DCI resumable run evidence is invalid")
    _validate_recorder_resume_state(state, request, paths)
    protocol_fd: int | None = None
    try:
        protocol_fd, _conversation_full, latest_context = _resume_preflight(
            lock._directory_fd, state, request
        )
        question = lock.read_text("question.txt")
        final = (
            lock.read_text("final.txt").rstrip("\n")
            if isinstance(state.get("assistant_text"), str)
            and state["assistant_text"]
            else ""
        )
        stderr = lock.read_text("stderr.txt")
        return state, question, final, stderr, latest_context
    except DciArtifactError:
        raise
    except (OSError, ValueError) as error:
        raise DciArtifactError("DCI resumable run evidence is invalid") from error
    finally:
        if protocol_fd is not None:
            os.close(protocol_fd)


def _validate_completed_view_shapes(
    directory_fd: int,
    state: dict[str, Any],
    conversation: dict[str, Any],
    conversation_full: dict[str, Any],
    latest_context: dict[str, Any],
    raw_events: list[dict[str, Any]],
) -> None:
    base_names = {
        "status",
        "question",
        "cwd",
        "provider",
        "model",
        "conversation_features",
        "messages",
        "pending_message",
        "final_text",
        "notes",
        "pi_source_attempts",
    }
    latest_names = {
        "status",
        "question",
        "cwd",
        "provider",
        "model",
        "conversation_features",
        "request_count",
        "runtime_context_management",
        "latest",
        "notes",
        "pi_source_attempts",
    }
    if (
        set(conversation) != base_names
        or set(conversation_full) != base_names
        or set(latest_context) != latest_names
        or any(
            not isinstance(state.get(name), list)
            for name in ("messages", "tool_calls", "notes", "pi_source_attempts")
        )
        or any(not isinstance(item, dict) for item in state["messages"])
        or any(not isinstance(item, dict) for item in state["tool_calls"])
        or not isinstance(state.get("paths"), dict)
        or not isinstance(conversation["messages"], list)
        or not isinstance(conversation_full["messages"], list)
        or any(not isinstance(item, dict) for item in conversation["messages"])
        or any(not isinstance(item, dict) for item in conversation_full["messages"])
        or conversation["pending_message"] is not None
        or conversation_full["pending_message"] is not None
        or not isinstance(conversation["notes"], list)
        or not isinstance(conversation["pi_source_attempts"], list)
        or not isinstance(latest_context["notes"], list)
        or not isinstance(latest_context["pi_source_attempts"], list)
        or isinstance(latest_context["request_count"], bool)
        or not isinstance(latest_context["request_count"], int)
        or latest_context["request_count"] < 0
        or (
            latest_context["latest"] is not None
            and not isinstance(latest_context["latest"], dict)
        )
    ):
        raise DciArtifactError("DCI completed run evidence is invalid")
    shared = (
        "status",
        "question",
        "cwd",
        "provider",
        "model",
        "conversation_features",
        "notes",
        "pi_source_attempts",
    )
    if any(
        conversation[name] != conversation_full[name]
        or conversation_full[name] != latest_context[name]
        or conversation_full[name] != state.get(name)
        for name in shared
    ):
        raise DciArtifactError("DCI completed run evidence is invalid")
    features = DciConversationFeatures.from_mapping(state["conversation_features"])
    expected_state_messages = [
        {"event": event["type"], "message": event.get("message")}
        for event in raw_events
        if event.get("type") in {"message_start", "message_end"}
    ]
    if (
        state["messages"] != expected_state_messages
        or conversation["final_text"] != state["assistant_text"]
        or conversation_full["final_text"] != state["assistant_text"]
    ):
        raise DciArtifactError("DCI completed run evidence is invalid")
    timings = _tool_timing_projection(raw_events, state["tool_calls"])
    _validate_full_conversation_projection(
        state, raw_events, conversation_full, timings
    )
    _validate_processed_conversation_projection(
        directory_fd, conversation_full, conversation, features
    )
    _validate_latest_context_projection(raw_events, latest_context, timings)


def _raw_text_delta_projection(raw_events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in raw_events:
        assistant = event.get("assistantMessageEvent")
        if (
            event.get("type") == "message_update"
            and isinstance(assistant, dict)
            and assistant.get("type") == "text_delta"
            and isinstance(assistant.get("delta"), str)
        ):
            parts.append(assistant["delta"])
    return "".join(parts)


def _raw_protocol_projection(
    raw_events: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    projected: list[tuple[str, dict[str, Any]]] = []
    for event in raw_events:
        event_type = event.get("type")
        if event_type == "message_update":
            assistant = event.get("assistantMessageEvent")
            if (
                isinstance(assistant, dict)
                and assistant.get("type") == "text_delta"
                and isinstance(assistant.get("delta"), str)
                and assistant["delta"]
            ):
                projected.append(("text.delta", {"text": assistant["delta"]}))
        elif event_type == "tool_execution_start":
            raw_args = event.get("args")
            arguments = raw_args if isinstance(raw_args, dict) else {"value": raw_args}
            projected.append(
                (
                    "tool.call",
                    {
                        "call_id": event.get("toolCallId"),
                        "name": event.get("toolName"),
                        "arguments": arguments,
                    },
                )
            )
        elif event_type == "tool_execution_end":
            projected.append(
                (
                    "tool.result",
                    {
                        "call_id": event.get("toolCallId"),
                        "output": event.get("result"),
                        "is_error": event.get("isError"),
                    },
                )
            )
        elif event_type == "message_end":
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            usage = message.get("usage")
            if isinstance(usage, dict):
                projected.append(
                    (
                        "usage.reported",
                        {
                            "input_tokens": usage.get("input"),
                            "output_tokens": usage.get("output"),
                        },
                    )
                )
    return projected


def _tool_timing_projection(
    raw_events: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> dict[str, dict[str, object]]:
    raw_tool_events = [
        event
        for event in raw_events
        if event.get("type") in {"tool_execution_start", "tool_execution_end"}
    ]
    if len(raw_tool_events) != len(tool_calls):
        raise DciArtifactError("DCI completed run evidence is invalid")
    timings: dict[str, dict[str, object]] = {}
    pending: dict[str, str] = {}
    expected_names = {
        "recorded_at",
        "event",
        "toolCallId",
        "toolName",
        "args",
        "isError",
        "result",
        "started_at",
        "finished_at",
        "duration_seconds",
    }
    for raw, entry in zip(raw_tool_events, tool_calls, strict=True):
        recorded_at = entry.get("recorded_at")
        call_id = entry.get("toolCallId")
        event_type = raw.get("type")
        if (
            set(entry) != expected_names
            or not _valid_timestamp(recorded_at)
            or entry.get("event") != event_type
            or call_id != raw.get("toolCallId")
            or entry.get("toolName") != raw.get("toolName")
            or entry.get("args") != raw.get("args")
            or entry.get("isError") != raw.get("isError")
            or entry.get("result") != raw.get("result")
            or not isinstance(call_id, str)
            or not call_id
        ):
            raise DciArtifactError("DCI completed run evidence is invalid")
        if event_type == "tool_execution_start":
            if (
                entry.get("started_at") != recorded_at
                or entry.get("finished_at") is not None
                or entry.get("duration_seconds") is not None
            ):
                raise DciArtifactError("DCI completed run evidence is invalid")
            pending[call_id] = recorded_at
            continue
        started = pending.pop(call_id, None)
        finished = recorded_at
        if entry.get("started_at") != started or entry.get("finished_at") != finished:
            raise DciArtifactError("DCI completed run evidence is invalid")
        duration = _duration_seconds(started, finished)
        if (
            duration is None
            or not isinstance(started, str)
            or not isinstance(finished, str)
        ):
            continue
        expected = {
            "tool_call_id": call_id,
            "status": "completed",
            "started_at": started,
            "finished_at": finished,
            "duration_seconds": duration,
            "duration_ms": int(round(duration * 1000)),
        }
        if entry.get("duration_seconds") != duration:
            raise DciArtifactError("DCI completed run evidence is invalid")
        timings[call_id] = expected
    return timings


def _annotated_message_projection(
    message: object, timings: dict[str, dict[str, object]]
) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    result = json.loads(json.dumps(message))
    call_id = result.get("toolCallId")
    if result.get("role") == "toolResult" and isinstance(call_id, str):
        timing = timings.get(call_id)
        if timing is not None:
            result["tool_execution"] = json.loads(json.dumps(timing))
    return result


def _validate_full_conversation_projection(
    state: dict[str, Any],
    raw_events: list[dict[str, Any]],
    conversation_full: dict[str, Any],
    timings: dict[str, dict[str, object]],
) -> None:
    expected_messages = [
        annotated
        for event in raw_events
        if event.get("type") == "message_end"
        for annotated in [_annotated_message_projection(event.get("message"), timings)]
        if annotated is not None
    ]
    actual = conversation_full["messages"]
    prefix_count = len(actual) - len(expected_messages)
    expected_prefix = (
        1
        if (
            state.get("system_prompt_file") is not None
            or state.get("append_system_prompt_file") is not None
        )
        else 0
    )
    if prefix_count != expected_prefix or actual[prefix_count:] != expected_messages:
        raise DciArtifactError("DCI completed run evidence is invalid")
    if expected_prefix:
        system = actual[0]
        if (
            system.get("role") != "system"
            or system.get("sources")
            != {
                "system_prompt_file": state.get("system_prompt_file"),
                "append_system_prompt_file": state.get("append_system_prompt_file"),
            }
            or not isinstance(system.get("content"), list)
            or len(system["content"]) != 1
            or not isinstance(system["content"][0], dict)
            or system["content"][0].get("type") != "text"
            or not isinstance(system["content"][0].get("text"), str)
        ):
            raise DciArtifactError("DCI completed run evidence is invalid")


def _validate_processed_conversation_projection(
    directory_fd: int,
    full: dict[str, Any],
    processed: dict[str, Any],
    features: DciConversationFeatures,
) -> None:
    expected = json.loads(json.dumps(full))
    messages = expected["messages"]
    actual_messages = processed["messages"]
    tool_indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "toolResult"
    ]
    names = DciRunRecorder._tool_result_names(
        [messages[index] for index in tool_indexes]
    )
    externalized_documents: dict[str, dict[str, Any]] = {}
    if features.externalize_tool_results and names:
        tool_results_fd = _open_existing_directory_at(directory_fd, "tool_results")
        try:
            entry = os.fstat(tool_results_fd)
            if stat.S_IMODE(entry.st_mode) != 0o700 or set(
                os.listdir(tool_results_fd)
            ) != set(names):
                raise DciArtifactError("DCI completed run evidence is invalid")
            for name in names:
                document = _read_optional_json_document_at(tool_results_fd, name)
                if document is None:
                    raise DciArtifactError("DCI completed run evidence is invalid")
                externalized_documents[name] = document[0]
        finally:
            os.close(tool_results_fd)
    if len(actual_messages) != len(messages):
        raise DciArtifactError("DCI completed run evidence is invalid")
    for tool_position, (index, name) in enumerate(
        zip(tool_indexes, names, strict=True)
    ):
        message = messages[index]
        actual = actual_messages[index]
        original_message = json.loads(json.dumps(message))
        clear_count = max(0, len(tool_indexes) - features.clear_tool_results_keep_last)
        will_clear = features.clear_tool_results and tool_position < clear_count
        context = (
            DciRunRecorder._tool_result_context(message)
            if features.externalize_tool_results or will_clear
            else None
        )
        if features.externalize_tool_results:
            externalized_document = externalized_documents[name]
            actual_externalized = (
                actual.get("context_management", {})
                .get("tool_result", {})
                .get("externalized")
            )
            stats = DciRunRecorder._tool_result_stats(message)
            if (
                not isinstance(actual_externalized, dict)
                or set(externalized_document) != {"saved_at", "message"}
                or externalized_document.get("message") != original_message
                or externalized_document.get("saved_at")
                != actual_externalized.get("saved_at")
                or actual_externalized.get("path") != f"tool_results/{name}"
                or actual_externalized.get("stats") != stats
                or not _valid_timestamp(actual_externalized.get("saved_at"))
            ):
                raise DciArtifactError("DCI completed run evidence is invalid")
            assert context is not None
            context["externalized"] = json.loads(json.dumps(actual_externalized))
        if will_clear:
            assert context is not None
            actual_tool_context = actual.get("context_management", {}).get(
                "tool_result", {}
            )
            if not _valid_timestamp(actual_tool_context.get("cleared_at")):
                raise DciArtifactError("DCI completed run evidence is invalid")
            stats = context.get("externalized", {}).get(
                "stats"
            ) or DciRunRecorder._tool_result_stats(message)
            context.update(
                {
                    "status": "cleared",
                    "stats": stats,
                    "cleared_at": actual_tool_context["cleared_at"],
                    "keep_last": features.clear_tool_results_keep_last,
                }
            )
            summary = [
                "[tool result cleared from conversation context]",
                f"tool={message.get('toolName', 'unknown')}",
                f"chars={stats.get('chars', 0)}",
                f"lines={stats.get('lines', 0)}",
            ]
            externalized = context.get("externalized")
            if isinstance(externalized, dict) and externalized.get("path"):
                summary.append(f"full_output={externalized['path']}")
            message["content"] = [{"type": "text", "text": "\n".join(summary)}]
    for message in messages:
        if message.get("role") == "assistant":
            if features.strip_thinking and isinstance(message.get("content"), list):
                message["content"] = [
                    part
                    for part in message["content"]
                    if isinstance(part, dict) and part.get("type") != "thinking"
                ]
            if features.strip_usage:
                message.pop("usage", None)
    if expected != processed:
        raise DciArtifactError("DCI completed run evidence is invalid")


def _validate_latest_context_projection(
    raw_events: list[dict[str, Any]],
    latest_context: dict[str, Any],
    timings: dict[str, dict[str, object]],
) -> None:
    provider_events = [
        event for event in raw_events if event.get("type") == "provider_request_context"
    ]
    if not provider_events:
        if (
            latest_context["request_count"] != 0
            or latest_context["runtime_context_management"] is not None
            or latest_context["latest"] is not None
        ):
            raise DciArtifactError("DCI completed run evidence is invalid")
        return
    last = provider_events[-1]
    indexes = [
        event.get("requestIndex")
        for event in provider_events
        if isinstance(event.get("requestIndex"), int)
        and not isinstance(event.get("requestIndex"), bool)
    ]
    expected_count = max([0, *indexes])
    messages = last.get("messages")
    annotated = (
        [
            _annotated_message_projection(message, timings) or message
            for message in messages
        ]
        if isinstance(messages, list)
        else []
    )
    runtime = json.loads(json.dumps(last.get("runtimeContextManagement")))
    latest = latest_context["latest"]
    if (
        latest_context["request_count"] != expected_count
        or latest_context["runtime_context_management"] != runtime
        or not isinstance(latest, dict)
        or not _valid_timestamp(latest.get("captured_at"))
        or {name: value for name, value in latest.items() if name != "captured_at"}
        != {
            "request_index": last.get("requestIndex"),
            "model": last.get("model"),
            "runtime_context_management": runtime,
            "message_count": len(annotated),
            "messages": annotated,
            "payload": json.loads(json.dumps(last.get("payload"))),
        }
    ):
        raise DciArtifactError("DCI completed run evidence is invalid")


def validate_latest_context_evidence(
    raw_events: list[dict[str, Any]],
    latest_context: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> None:
    """Bind a final model-context projection to recorder-owned raw events."""

    if (
        not isinstance(raw_events, list)
        or any(not isinstance(event, dict) for event in raw_events)
        or not isinstance(latest_context, dict)
        or not isinstance(tool_calls, list)
        or any(not isinstance(call, dict) for call in tool_calls)
    ):
        raise DciArtifactError("DCI completed run evidence is invalid")
    timings = _tool_timing_projection(raw_events, tool_calls)
    _validate_latest_context_projection(raw_events, latest_context, timings)


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


@dataclass(frozen=True)
class DciConversationFeatures:
    """Opt-in processing controls for the investigator-facing conversation view."""

    clear_tool_results: bool = False
    clear_tool_results_keep_last: int = 3
    externalize_tool_results: bool = False
    strip_thinking: bool = False
    strip_usage: bool = False

    def __post_init__(self) -> None:
        for name in (
            "clear_tool_results",
            "externalize_tool_results",
            "strip_thinking",
            "strip_usage",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        keep_last = self.clear_tool_results_keep_last
        if (
            isinstance(keep_last, bool)
            or not isinstance(keep_last, int)
            or keep_last < 0
        ):
            raise ValueError("clear_tool_results_keep_last must be >= 0")

    def to_mapping(self) -> dict[str, object]:
        return {
            "clear_tool_results": self.clear_tool_results,
            "clear_tool_results_keep_last": self.clear_tool_results_keep_last,
            "externalize_tool_results": self.externalize_tool_results,
            "strip_thinking": self.strip_thinking,
            "strip_usage": self.strip_usage,
        }

    @classmethod
    def from_mapping(cls, value: object) -> DciConversationFeatures:
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("DCI conversation features are invalid")
        known = {
            "clear_tool_results",
            "clear_tool_results_keep_last",
            "externalize_tool_results",
            "strip_thinking",
            "strip_usage",
        }
        if unknown := set(value) - known:
            raise ValueError(
                f"DCI conversation features contain unknown fields: {', '.join(sorted(unknown))}"
            )
        return cls(
            clear_tool_results=value.get("clear_tool_results", False),
            clear_tool_results_keep_last=value.get("clear_tool_results_keep_last", 3),
            externalize_tool_results=value.get("externalize_tool_results", False),
            strip_thinking=value.get("strip_thinking", False),
            strip_usage=value.get("strip_usage", False),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(started_at: object, finished_at: object) -> float | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        duration = datetime.fromisoformat(finished_at) - datetime.fromisoformat(
            started_at
        )
    except ValueError:
        return None
    return max(0.0, duration.total_seconds())


def _safe_tool_stem(value: object) -> str:
    text = value if isinstance(value, str) else "event"
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text.replace("\\", "/"))
    text = text.strip(".-_") or "event"
    return text[:80]


def _bounded_text_tail(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    return encoded[-maximum_bytes:].decode("utf-8", errors="ignore")


def extra_args_fingerprint(values: tuple[str, ...]) -> str:
    """Return a stable identity for private Pi arguments without persisting their values."""

    if not isinstance(values, tuple) or any(
        not isinstance(value, str) for value in values
    ):
        raise ValueError("DCI extra arguments are invalid")
    payload = json.dumps(
        list(values), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _same_typed_value(actual: object, expected: object) -> bool:
    if expected is None:
        return actual is None
    return type(actual) is type(expected) and actual == expected


def _valid_timeout(value: object) -> bool:
    return value is None or (
        isinstance(value, float) and math.isfinite(value) and value >= 0
    )


def _context_policy_identity(
    request: DciRunRequest,
    extension: ResolvedContextExtension | None,
) -> dict[str, object] | None:
    profile = request.context_profile
    if profile is None:
        if extension is not None:
            raise DciArtifactError("DCI context policy identity is invalid")
        return None
    if extension is None:
        from asterion.dci.context_extension import (
            ContextExtensionError,
            resolve_context_extension,
        )

        try:
            with resolve_context_extension() as resolved:
                return _context_policy_identity(request, resolved)
        except ContextExtensionError as error:
            raise DciArtifactError("DCI context policy identity is invalid") from error
    from asterion.dci.context_profiles import context_policy_identity

    try:
        return context_policy_identity(profile, extension)
    except ValueError:
        raise DciArtifactError("DCI context policy identity is invalid")


def _validate_recorder_resume_state(
    state: dict[str, Any],
    request: DciRunRequest,
    paths: DciPaths,
    context_extension: ResolvedContextExtension | None = None,
) -> None:
    if state.get("status") not in {"failed", "incomplete", "running"}:
        raise DciArtifactError("DCI resume state is invalid")
    if (
        request.pi_package_dir is not None
        and request.pi_package_dir != paths.pi.package_dir
    ):
        raise DciArtifactError("DCI resume state is invalid")
    if request.pi_agent_dir is not None and request.pi_agent_dir != paths.pi.agent_dir:
        raise DciArtifactError("DCI resume state is invalid")
    expected = {
        "run_id": request.run_id,
        "question": request.question,
        "prelude_question_count": len(request.prelude_questions),
        "prelude_questions_fingerprint": prelude_questions_fingerprint(
            request.prelude_questions
        ),
        "cwd": str(request.cwd),
        "provider": request.provider,
        "model": request.model,
        "tools": request.tools,
        "max_turns": request.max_turns,
        "runtime_context_control": _context_policy_identity(
            request, context_extension
        ),
        "runtime_context_level": request.runtime_context_level,
        "pi_context_session": (
            {
                "session_file": str(request.pi_session_file),
                "session_id": request.pi_session_id,
            }
            if request.pi_session_file is not None
            else None
        ),
        "thinking_level": request.thinking_level,
        "node_max_old_space_size_mb": request.node_max_old_space_size_mb,
        "keep_session": request.keep_session,
        "extra_args_count": len(request.extra_args),
        "extra_args_fingerprint": extra_args_fingerprint(request.extra_args),
        "show_tools": request.show_tools,
        "system_prompt_file": (
            str(request.system_prompt_file)
            if request.system_prompt_file is not None
            else None
        ),
        "append_system_prompt_file": (
            str(request.append_system_prompt_file)
            if request.append_system_prompt_file is not None
            else None
        ),
        "stream_text": request.stream_text,
        "pi_package_dir": str(paths.pi.package_dir),
        "pi_agent_dir": str(paths.pi.agent_dir),
    }
    if any(
        name not in state or not _same_typed_value(state[name], value)
        for name, value in expected.items()
    ):
        raise DciArtifactError("DCI resume state is invalid")
    if "timeout_seconds" not in state or not _valid_timeout(state["timeout_seconds"]):
        raise DciArtifactError("DCI resume state is invalid")


def _write_private_text_at(
    directory_fd: int,
    name: str,
    value: str,
    *,
    append: bool = False,
    durable: bool = False,
) -> None:
    _validate_leaf_name(name)
    _reject_symlink_at(directory_fd, name, label="artifact target")
    flags = os.O_CREAT | os.O_WRONLY | (os.O_APPEND if append else os.O_TRUNC)
    descriptor = os.open(name, _open_flags(flags), 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a" if append else "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _write_private_text(path: Path, value: str, *, append: bool = False) -> None:
    destination = Path(path)
    directory_fd = _open_directory(destination.parent)
    try:
        _write_private_text_at(directory_fd, destination.name, value, append=append)
    finally:
        os.close(directory_fd)


def _protocol_request_for_attempt(
    request: DciRunRequest,
    *,
    attempt: int,
    timeout_seconds: float | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "run_id": f"{request.run_id}-attempt-{attempt:04d}",
        "input": {"text": request.question},
        "requested_capabilities": map_pi_capabilities(request.tools),
    }
    if timeout_seconds is not None and timeout_seconds > 0:
        deadline_ms = int(round(timeout_seconds * 1000))
        if deadline_ms <= MAX_DEADLINE_MS:
            payload["deadline_ms"] = max(1, deadline_ms)
    return payload


def _validate_attempt_record(value: object, number: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "attempt",
        "status",
        "command_summary",
        "timeout_seconds",
        "stderr_tail_characters",
    }:
        raise DciArtifactError("DCI resume evidence is invalid")
    timeout = value["timeout_seconds"]
    stderr_characters = value["stderr_tail_characters"]
    summary = value["command_summary"]
    if not isinstance(summary, dict) or set(summary) != {
        "executable",
        "mode",
        "option_names",
        "configured_extra_argument_groups",
        "typed_extra_argument_count",
    }:
        raise DciArtifactError("DCI resume evidence is invalid")
    extra_count = summary["configured_extra_argument_groups"]
    typed_count = summary["typed_extra_argument_count"]
    if (
        value["attempt"] != number
        or isinstance(value["attempt"], bool)
        or value["status"] not in {"running", "failed", "incomplete", "completed"}
        or summary["executable"] != "node"
        or summary["mode"] != "rpc"
        or not isinstance(summary["option_names"], list)
        or not all(isinstance(item, str) and item for item in summary["option_names"])
        or isinstance(extra_count, bool)
        or not isinstance(extra_count, int)
        or extra_count < 0
        or isinstance(typed_count, bool)
        or not isinstance(typed_count, int)
        or typed_count < 0
        or not _valid_timeout(timeout)
        or isinstance(stderr_characters, bool)
        or not isinstance(stderr_characters, int)
        or stderr_characters < 0
    ):
        raise DciArtifactError("DCI resume evidence is invalid")
    return value


def _resume_preflight(
    root_fd: int,
    state: dict[str, Any],
    request: DciRunRequest,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """Validate all prior durable evidence and return the locked protocol descriptor."""

    if _read_text_at(root_fd, "question.txt") != f"{request.question}\n":
        raise DciArtifactError("DCI resume evidence is invalid")
    _read_jsonl_at(root_fd, "events.jsonl")
    conversation = _read_json_object_at(root_fd, "conversation.json")
    conversation_full = _read_json_object_at(root_fd, "conversation_full.json")
    latest_context = _read_json_object_at(root_fd, "latest_model_context.json")
    _read_text_at(root_fd, "stderr.txt")
    if (
        not isinstance(state.get("event_count"), int)
        or isinstance(state.get("event_count"), bool)
        or state["event_count"] < 0
        or not isinstance(state.get("assistant_text"), str)
        or not all(
            isinstance(state.get(name), list)
            for name in ("messages", "tool_calls", "notes", "pi_source_attempts")
        )
        or not isinstance(conversation.get("messages"), list)
        or not isinstance(conversation_full.get("messages"), list)
        or not isinstance(conversation_full.get("notes"), list)
        or not isinstance(conversation_full.get("pi_source_attempts"), list)
        or not isinstance(latest_context.get("request_count"), int)
        or isinstance(latest_context.get("request_count"), bool)
        or latest_context["request_count"] < 0
        or not isinstance(latest_context.get("notes"), list)
        or not isinstance(latest_context.get("pi_source_attempts"), list)
    ):
        raise DciArtifactError("DCI resume evidence is invalid")
    answer = state["assistant_text"]
    if answer:
        expected_final = answer if answer.endswith("\n") else f"{answer}\n"
        if _read_text_at(root_fd, "final.txt") != expected_final:
            raise DciArtifactError("DCI resume evidence is invalid")
    else:
        try:
            os.stat("final.txt", dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise DciArtifactError("DCI resume evidence is invalid")
    attempts = state.get("attempts")
    resume_count = state.get("resume_count")
    if (
        not isinstance(attempts, list)
        or not attempts
        or isinstance(resume_count, bool)
        or not isinstance(resume_count, int)
        or resume_count < 0
        or len(attempts) != resume_count + 1
    ):
        raise DciArtifactError("DCI resume evidence is invalid")
    if (
        not isinstance(attempts[-1], dict)
        or attempts[-1].get("status") != state.get("status")
        or conversation.get("status") != state.get("status")
        or conversation_full.get("status") != state.get("status")
        or latest_context.get("status") != state.get("status")
        or conversation_full.get("question") != request.question
        or latest_context.get("question") != request.question
    ):
        raise DciArtifactError("DCI resume evidence is invalid")
    protocol_fd = _open_existing_directory_at(root_fd, "protocol")
    try:
        expected_names: set[str] = set()
        stale_terminal: tuple[str, dict[str, object]] | None = None
        for number, attempt in enumerate(attempts, 1):
            attempt = _validate_attempt_record(attempt, number)
            if attempt["status"] == "running" and number != len(attempts):
                raise DciArtifactError("DCI resume evidence is invalid")
            stem = f"attempt-{number:04d}"
            request_name = f"{stem}.request.json"
            events_name = f"{stem}.events.jsonl"
            expected_names.update((request_name, events_name))
            prior_request = _read_json_object_at(protocol_fd, request_name)
            validate_run_request(prior_request)
            expected_request = _protocol_request_for_attempt(
                request,
                attempt=number,
                timeout_seconds=attempt["timeout_seconds"],
            )
            if prior_request != expected_request:
                raise DciArtifactError("DCI resume evidence is invalid")
            prior_events = _read_jsonl_at(protocol_fd, events_name)
            expected_run_id = expected_request["run_id"]
            if any(event.get("run_id") != expected_run_id for event in prior_events):
                raise DciArtifactError("DCI resume evidence is invalid")
            terminal_type = prior_events[-1].get("type") if prior_events else None
            status = attempt["status"]
            if status == "completed" or terminal_type == "run.completed":
                raise DciArtifactError("DCI resume evidence is invalid")
            if status in {"failed", "incomplete"}:
                if terminal_type != "run.failed":
                    raise DciArtifactError("DCI resume evidence is invalid")
            elif status == "running":
                if terminal_type in {"run.completed", "run.failed"}:
                    raise DciArtifactError("DCI resume evidence is invalid")
                if not prior_events:
                    raise DciArtifactError("DCI resume evidence is invalid")
                terminal = {
                    "protocol": PROTOCOL_VERSION,
                    "run_id": expected_run_id,
                    "sequence": len(prior_events) + 1,
                    "type": "run.failed",
                    "payload": {
                        "code": "stale_attempt",
                        "message": "Prior attempt ended before finalization.",
                    },
                }
                prior_events.append(terminal)
                stale_terminal = (events_name, terminal)
            validate_event_stream(prior_events)
        if set(os.listdir(protocol_fd)) != expected_names:
            raise DciArtifactError("DCI resume evidence is invalid")
        if stale_terminal is not None:
            events_name, terminal = stale_terminal
            _write_private_text_at(
                protocol_fd,
                events_name,
                json.dumps(terminal, ensure_ascii=False, separators=(",", ":")) + "\n",
                append=True,
                durable=True,
            )
            attempts[-1]["status"] = "failed"
            state["status"] = "failed"
            conversation["status"] = "failed"
            conversation_full["status"] = "failed"
            conversation_full["pending_message"] = None
            latest_context["status"] = "failed"
            _atomic_write_json_at(root_fd, "state.json", state)
            _atomic_write_json_at(root_fd, "conversation.json", conversation)
            _atomic_write_json_at(root_fd, "conversation_full.json", conversation_full)
            _atomic_write_json_at(root_fd, "latest_model_context.json", latest_context)
        return protocol_fd, conversation_full, latest_context
    except BaseException:
        os.close(protocol_fd)
        raise


class DciRunRecorder:
    """Persist raw and processed DCI run evidence without crossing product boundaries."""

    def __init__(
        self,
        *,
        output_dir: Path,
        request: DciRunRequest,
        paths: DciPaths,
        features: DciConversationFeatures | None = None,
        resume: bool = False,
        directory_fd: int | None = None,
        context_extension: ResolvedContextExtension | None = None,
    ) -> None:
        validate_dci_run_request(request, paths)
        self.context_extension = context_extension
        self.context_identity = _context_policy_identity(request, context_extension)
        self.output_dir = Path(output_dir)
        self.request = request
        self.paths = paths
        self.features = features or DciConversationFeatures()
        self.lock = (
            DciRunLock.acquire(self.output_dir, create=not resume)
            if directory_fd is None
            else DciRunLock.acquire_fd(
                directory_fd, path=self.output_dir, wait=False
            )
        )
        self._root_fd = self.lock._directory_fd
        self._protocol_fd: int | None = None
        self._closed = False
        self._finalized = False
        self._finalization_started = False
        self.events_path = self.output_dir / "events.jsonl"
        self.state_path = self.output_dir / "state.json"
        self.question_path = self.output_dir / "question.txt"
        self.final_path = self.output_dir / "final.txt"
        self.stderr_path = self.output_dir / "stderr.txt"
        self.conversation_full_path = self.output_dir / "conversation_full.json"
        self.conversation_path = self.output_dir / "conversation.json"
        self.latest_model_context_path = self.output_dir / "latest_model_context.json"
        self.context_policy_path = self.output_dir / "context-policy.json"
        self.protocol_dir = self.output_dir / "protocol"
        try:
            if resume:
                self.state = _read_json_object_at(self._root_fd, "state.json")
                _validate_recorder_resume_state(
                    self.state, request, paths, context_extension
                )
                if "conversation_features" not in self.state:
                    raise DciArtifactError("DCI resume state is invalid")
                persisted_features = DciConversationFeatures.from_mapping(
                    self.state.get("conversation_features")
                )
                if features is None:
                    self.features = persisted_features
                elif self.features != persisted_features:
                    raise DciArtifactError("DCI resume state is invalid")
                self._protocol_fd, self.conversation_full, self.latest_model_context = (
                    _resume_preflight(self._root_fd, self.state, request)
                )
                prior_resume_count = self.state.get("resume_count", 0)
                if isinstance(prior_resume_count, bool) or not isinstance(
                    prior_resume_count, int
                ):
                    raise DciArtifactError("DCI resume state is invalid")
                attempt = prior_resume_count + 2
                self.state["resume_count"] = prior_resume_count + 1
                self.state["status"] = "running"
                self.state["finished_at"] = None
                self.state["timeout_seconds"] = request.timeout_seconds
                self.conversation_full["status"] = "running"
                self.latest_model_context["status"] = "running"
                self.conversation_full["pending_message"] = None
            else:
                existing_names = set(os.listdir(self._root_fd))
                if existing_names - {DciRunLock.LOCK_NAME}:
                    raise DciArtifactError("DCI output directory is not empty")
                attempt = 1
                _write_private_text_at(self._root_fd, "events.jsonl", "")
                _write_private_text_at(
                    self._root_fd, "question.txt", f"{request.question}\n"
                )
                _write_private_text_at(self._root_fd, "stderr.txt", "")
                self.state = {
                    "run_id": request.run_id,
                    "status": "running",
                    "question_path": str(self.question_path),
                    "final_path": str(self.final_path),
                    "events_path": str(self.events_path),
                    "stderr_path": str(self.stderr_path),
                    "question": request.question,
                    "prelude_question_count": len(request.prelude_questions),
                    "prelude_questions_fingerprint": prelude_questions_fingerprint(
                        request.prelude_questions
                    ),
                    "cwd": str(request.cwd),
                    "provider": request.provider,
                    "model": request.model,
                    "tools": request.tools,
                    "max_turns": request.max_turns,
                    "timeout_seconds": request.timeout_seconds,
                    "runtime_context_level": request.runtime_context_level,
                    "runtime_context_control": self.context_identity,
                    "pi_context_session": None,
                    "context_policy": (
                        {
                            "artifact": "context-policy.json",
                            "sha256": None,
                            "public_summary": None,
                        }
                        if self.context_identity is not None
                        else None
                    ),
                    "thinking_level": request.thinking_level,
                    "node_max_old_space_size_mb": request.node_max_old_space_size_mb,
                    "keep_session": request.keep_session,
                    "extra_args_count": len(request.extra_args),
                    "extra_args_fingerprint": extra_args_fingerprint(
                        request.extra_args
                    ),
                    "show_tools": request.show_tools,
                    "system_prompt_file": (
                        str(request.system_prompt_file)
                        if request.system_prompt_file
                        else None
                    ),
                    "append_system_prompt_file": (
                        str(request.append_system_prompt_file)
                        if request.append_system_prompt_file
                        else None
                    ),
                    "stream_text": request.stream_text,
                    "pi_package_dir": str(paths.pi.package_dir),
                    "pi_agent_dir": str(paths.pi.agent_dir),
                    "conversation_features": self.features.to_mapping(),
                    "started_at": _utc_now(),
                    "finished_at": None,
                    "event_count": 0,
                    "last_event_type": None,
                    "assistant_text": "",
                    "messages": [],
                    "tool_calls": [],
                    "notes": [],
                    "attempts": [],
                    "resume_count": 0,
                    "paths": {
                        "events_jsonl": str(self.events_path),
                        "conversation_full_json": str(self.conversation_full_path),
                        "conversation_json": str(self.conversation_path),
                        "latest_model_context_json": str(
                            self.latest_model_context_path
                        ),
                        "final_txt": str(self.final_path),
                        "stderr_txt": str(self.stderr_path),
                        **(
                            {"context_policy_json": str(self.context_policy_path)}
                            if self.context_identity is not None
                            else {}
                        ),
                    },
                }
                self.conversation_full = {
                    "status": "running",
                    "question": request.question,
                    "cwd": str(request.cwd),
                    "provider": request.provider,
                    "model": request.model,
                    "conversation_features": self.features.to_mapping(),
                    "messages": [],
                    "pending_message": None,
                    "final_text": None,
                    "notes": [],
                    "pi_source_attempts": [],
                }
                self._add_system_prompt()
                self.latest_model_context = {
                    "status": "running",
                    "question": request.question,
                    "cwd": str(request.cwd),
                    "provider": request.provider,
                    "model": request.model,
                    "conversation_features": self.features.to_mapping(),
                    "request_count": 0,
                    "runtime_context_management": None,
                    "latest": None,
                    "notes": [],
                    "pi_source_attempts": [],
                }
                self._protocol_fd = _open_private_directory_at(
                    self._root_fd, "protocol"
                )
            attempt_stem = f"attempt-{attempt:04d}"
            self._attempt_stem = attempt_stem
            self.pi_source = collect_pi_provenance(
                paths.pi.package_dir,
                paths.repo_root / "pi-revision.txt",
                os.environ.get("DCI_PI_REVISION") or None,
            )
            for artifact in (
                self.state,
                self.conversation_full,
                self.latest_model_context,
            ):
                snapshots = artifact.setdefault("pi_source_attempts", [])
                if not isinstance(snapshots, list):
                    raise DciArtifactError("DCI resume state is invalid")
                snapshots.append(json.loads(json.dumps(self.pi_source)))
            attempts = self.state.setdefault("attempts", [])
            if not isinstance(attempts, list):
                raise DciArtifactError("DCI resume state is invalid")
            self._attempt_index = len(attempts)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "running",
                    "command_summary": self._command_summary(),
                    "timeout_seconds": request.timeout_seconds,
                    "stderr_tail_characters": 0,
                }
            )
            self._initialize_context_policy(attempt=attempt, resume=resume)
            self._protocol_request_name = f"{attempt_stem}.request.json"
            self._protocol_events_name = f"{attempt_stem}.events.jsonl"
            self.protocol_request_path = self.protocol_dir / self._protocol_request_name
            self.protocol_events_path = self.protocol_dir / self._protocol_events_name
            _write_exclusive_text_at(self._protocol_fd, self._protocol_events_name, "")
            self.normalized: list[dict[str, object]] = []
            self._restore_tool_timing_indexes()
            capabilities = map_pi_capabilities(request.tools)
            protocol_request = _protocol_request_for_attempt(
                request,
                attempt=attempt,
                timeout_seconds=request.timeout_seconds,
            )
            validate_run_request(protocol_request)
            _write_exclusive_json_at(
                self._protocol_fd, self._protocol_request_name, protocol_request
            )
            self.adapter = PiProtocolAdapter(
                run_id=str(protocol_request["run_id"]),
                capabilities=capabilities,
                emit=self._emit_normalized,
            )
            self.adapter.start()
            self._write()
        except BaseException:
            self.close()
            raise

    def _initialize_context_policy(self, *, attempt: int, resume: bool) -> None:
        self.context_entry_cursor = None
        if self.context_identity is None:
            self.context_policy = None
            return
        profile = self.request.context_profile
        extension = self.context_extension
        if profile is None or extension is None:
            raise DciArtifactError("DCI context policy identity is invalid")
        if resume:
            reference = self.state.get("context_policy")
            document = _read_optional_json_document_at(
                self._root_fd, "context-policy.json"
            )
            if (
                not isinstance(reference, dict)
                or set(reference) != {"artifact", "sha256", "public_summary"}
                or reference.get("artifact") != "context-policy.json"
                or document is None
                or hashlib.sha256(document[1]).hexdigest() != reference.get("sha256")
            ):
                raise DciArtifactError("DCI resume state is invalid")
            policy = document[0]
            if (
                set(policy)
                != {
                    "schema",
                    "profile",
                    "extension_version",
                    "extension_sha256",
                    "attempts",
                }
                or policy.get("schema") != "dci.context-policy-evidence/v2"
                or policy.get("profile") != profile.identity_payload()
                or policy.get("extension_version") != extension.version
                or policy.get("extension_sha256") != extension.sha256
                or not isinstance(policy.get("attempts"), list)
                or len(policy["attempts"]) != attempt - 1
                or not policy["attempts"]
                or not isinstance(policy["attempts"][-1], dict)
                or policy["attempts"][-1].get("latest_state") is None
            ):
                raise DciArtifactError("DCI resume state is invalid")
            self.context_policy = policy
            prior_entries = policy["attempts"][-1].get("entries")
            if (
                not isinstance(prior_entries, list)
                or not prior_entries
                or not isinstance(prior_entries[-1], dict)
                or not isinstance(prior_entries[-1].get("id"), str)
                or not prior_entries[-1]["id"]
            ):
                raise DciArtifactError("DCI resume state is invalid")
            self.context_entry_cursor = prior_entries[-1]["id"]
        else:
            self.context_policy = {
                "schema": "dci.context-policy-evidence/v2",
                "profile": profile.identity_payload(),
                "extension_version": extension.version,
                "extension_sha256": extension.sha256,
                "attempts": [],
            }
        self.context_policy["attempts"].append(
            {
                "attempt": attempt,
                "status": "running",
                "telemetry": [],
                "latest_state": None,
                "entries": [],
            }
        )

    def _write_context_policy(self) -> None:
        if self.context_policy is None:
            return
        _atomic_write_json_at(
            self._root_fd, "context-policy.json", self.context_policy
        )
        reference = self.state.get("context_policy")
        if not isinstance(reference, dict):
            raise DciArtifactError("DCI context policy evidence is invalid")
        reference["sha256"] = hashlib.sha256(
            json_document_bytes(self.context_policy)
        ).hexdigest()

    def record_context_policy(
        self, entries: tuple[dict[str, object], ...]
    ) -> None:
        """Persist one attempt's validated, body-free Pi policy entries."""

        self._ensure_open()
        if self.context_policy is None or self.context_extension is None:
            raise DciArtifactError("DCI context policy evidence is invalid")
        profile = self.request.context_profile
        if profile is None:
            raise DciArtifactError("DCI context policy evidence is invalid")
        telemetry: list[DciContextTelemetry] = []
        states: list[dict[str, object]] = []
        safe_entries: list[dict[str, object]] = []
        wrapper_keys = {"id", "parentId", "timestamp", "type", "customType", "data"}
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or set(entry) != wrapper_keys
                or entry.get("type") != "custom"
                or entry.get("customType")
                not in {"dci-context-telemetry", "dci-context-state"}
                or not isinstance(entry.get("id"), str)
                or not isinstance(entry.get("timestamp"), str)
            ):
                raise DciArtifactError("DCI context policy evidence is invalid")
            data = entry.get("data")
            if entry["customType"] == "dci-context-telemetry":
                item = DciContextTelemetry.from_mapping(data)
                if (
                    item.profile != profile.name
                    or item.contract_version != profile.contract_version
                    or item.extension_version != self.context_extension.version
                ):
                    raise DciArtifactError("DCI context policy evidence is invalid")
                telemetry.append(item)
            else:
                if (
                    not isinstance(data, dict)
                    or set(data)
                    != {"schema", "profile", "contractVersion", "state"}
                    or data.get("schema") != "dci.context-state/v2"
                    or data.get("profile") != profile.name
                    or data.get("contractVersion") != profile.contract_version
                ):
                    raise DciArtifactError("DCI context policy evidence is invalid")
                _validated_policy_state(data.get("state"))
                states.append(json.loads(json.dumps(data)))
            safe_entries.append(json.loads(json.dumps(entry)))
        if (
            not telemetry
            or not states
            or sum(item.event == "startup" for item in telemetry) != 1
        ):
            raise DciArtifactError("DCI context policy evidence is invalid")
        evidence = DciContextPolicyEvidence(
            profile=profile,
            extension_version=self.context_extension.version,
            extension_sha256=self.context_extension.sha256,
            telemetry=tuple(telemetry),
        )
        attempt = self.context_policy["attempts"][self._attempt_index]
        if not isinstance(attempt, dict) or attempt.get("status") != "running":
            raise DciArtifactError("DCI context policy evidence is invalid")
        attempt["telemetry"] = [item.to_mapping() for item in telemetry]
        attempt["latest_state"] = states[-1]
        attempt["entries"] = safe_entries
        reference = self.state.get("context_policy")
        if not isinstance(reference, dict):
            raise DciArtifactError("DCI context policy evidence is invalid")
        reference["public_summary"] = evidence.public_summary()
        self._write()

    def record_context_session(self, session_file: Path, session_id: str) -> None:
        """Bind one verified Pi session identity before the provider request."""

        self._ensure_open()
        if (
            self.context_identity is None
            or not self.request.keep_session
            or not isinstance(session_file, Path)
            or not session_file.is_absolute()
            or not isinstance(session_id, str)
            or not session_id
        ):
            raise DciArtifactError("DCI context session identity is invalid")
        identity = {"session_file": str(session_file), "session_id": session_id}
        existing = self.state.get("pi_context_session")
        if self.request.resume:
            if existing != identity:
                raise DciArtifactError("DCI resume state is invalid")
        elif existing is not None:
            raise DciArtifactError("DCI context session identity is invalid")
        else:
            self.state["pi_context_session"] = identity
        self._write()

    def _emit_normalized(self, event: dict[str, object]) -> None:
        self.normalized.append(dict(event))
        self._append_at(
            self._protocol_directory_fd(), self._protocol_events_name, event
        )

    def record_event(self, event: dict[str, object]) -> None:
        self._ensure_open()
        try:
            self._append_at(self._root_fd, "events.jsonl", event)
            self.adapter.consume(event)
            self.state["event_count"] += 1
            event_type = event.get("type")
            self.state["last_event_type"] = event_type
            recorded_at = _utc_now()
            if event_type in {"message_start", "message_end"}:
                message = event.get("message")
                self.state["messages"].append(
                    {"event": event_type, "message": json.loads(json.dumps(message))}
                )
                if event_type == "message_start":
                    self.conversation_full["pending_message"] = self._annotate_message(
                        message
                    )
                elif isinstance(message, dict):
                    self.conversation_full["messages"].append(
                        self._annotate_message(message)
                    )
                    self.conversation_full["pending_message"] = None
            elif event_type == "message_update":
                assistant = event.get("assistantMessageEvent")
                if (
                    isinstance(assistant, dict)
                    and assistant.get("type") == "text_delta"
                ):
                    delta = assistant.get("delta")
                    if isinstance(delta, str):
                        self.state["assistant_text"] += delta
                    partial = assistant.get("partial")
                    if isinstance(partial, dict):
                        self.conversation_full["pending_message"] = (
                            self._annotate_message(partial)
                        )
            elif event_type in {"tool_execution_start", "tool_execution_end"}:
                self._record_tool_timing(event, recorded_at=recorded_at)
            elif event_type == "provider_request_context":
                self._record_latest_model_context(event)
            self._write()
        except BaseException:
            self.close()
            raise

    def finalize(
        self,
        *,
        status: str,
        final_text: str = "",
        stderr_text: str = "",
        release_lock: bool = True,
    ) -> tuple[RunEvent, ...]:
        self._ensure_open()
        if self._finalization_started:
            raise DciArtifactError("DCI run recorder is finalized")
        self._finalization_started = True
        try:
            answer = final_text or self.state["assistant_text"]
            if answer:
                _write_private_text_at(
                    self._root_fd,
                    "final.txt",
                    answer if answer.endswith("\n") else f"{answer}\n",
                )
            stderr_tail = _bounded_text_tail(stderr_text, 16384)
            stderr_section = f"[{self._attempt_stem} status={status}]\n{stderr_tail}"
            if stderr_tail and not stderr_tail.endswith("\n"):
                stderr_section += "\n"
            _write_private_text_at(
                self._root_fd,
                "stderr.txt",
                stderr_section,
                append=self._attempt_index > 0,
            )
            attempt_record = self.state["attempts"][self._attempt_index]
            attempt_record["status"] = status
            attempt_record["stderr_tail_characters"] = len(stderr_tail)
            if self.context_policy is not None:
                policy_attempt = self.context_policy["attempts"][self._attempt_index]
                if not isinstance(policy_attempt, dict):
                    raise DciArtifactError("DCI context policy evidence is invalid")
                if status == "completed" and policy_attempt.get("latest_state") is None:
                    raise DciArtifactError("DCI context policy evidence is invalid")
                policy_attempt["status"] = status
            self.state["status"] = status
            self.state["finished_at"] = _utc_now()
            self.state["assistant_text"] = answer
            self.conversation_full["status"] = status
            self.conversation_full["final_text"] = answer
            self.conversation_full["pending_message"] = None
            self.latest_model_context["status"] = status
            if status == "completed":
                artifact = None
                if answer:
                    digest = hashlib.sha256(
                        answer.encode("utf-8")
                        + (b"" if answer.endswith("\n") else b"\n")
                    ).hexdigest()
                    artifact = {
                        "artifact_id": "final-answer",
                        "kind": "answer",
                        "media_type": "text/plain",
                        "uri": "final.txt",
                        "sha256": digest,
                    }
                self.adapter.complete(artifact=artifact)
            else:
                self.adapter.fail()
            validate_event_stream(self.normalized)
            self._write()
            self._finalized = True
            return tuple(RunEvent.from_mapping(event) for event in self.normalized)
        finally:
            if release_lock:
                self.close()

    def add_note(self, note: str) -> None:
        """Persist one caller-generated safe diagnostic note in every native view."""

        self._ensure_open()
        for artifact in (self.state, self.conversation_full, self.latest_model_context):
            notes = artifact.setdefault("notes", [])
            if not isinstance(notes, list):
                raise DciArtifactError("DCI artifact notes are invalid")
            notes.append(note)
        self._write()

    def close(self) -> None:
        """Idempotently release this recorder's owned writer lock."""

        if self._closed:
            return
        if self._protocol_fd is not None:
            try:
                os.close(self._protocol_fd)
            except OSError:
                pass
            self._protocol_fd = None
        self.lock.release()
        self._closed = True

    def __enter__(self) -> DciRunRecorder:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise DciArtifactError("DCI run recorder is closed")

    def _command_summary(self) -> dict[str, object]:
        option_names = ["--mode"]
        if self.request.provider is not None:
            option_names.append("--provider")
        if self.request.model is not None:
            option_names.append("--model")
        if self.request.tools:
            option_names.append("--tools")
        if self.request.system_prompt_file is not None:
            option_names.append("--system-prompt")
        if self.request.append_system_prompt_file is not None:
            option_names.append("--append-system-prompt")
        if not self.request.keep_session:
            option_names.append("--no-session")
        typed_count = 1 if self.request.thinking_level is not None else 0
        return {
            "executable": "node",
            "mode": "rpc",
            "option_names": option_names,
            "configured_extra_argument_groups": len(self.request.extra_args),
            "typed_extra_argument_count": typed_count,
        }

    def _write(self) -> None:
        self._write_context_policy()
        _atomic_write_json_at(self._root_fd, "state.json", self.state)
        _atomic_write_json_at(
            self._root_fd, "conversation_full.json", self.conversation_full
        )
        _atomic_write_json_at(
            self._root_fd,
            "latest_model_context.json",
            self.latest_model_context,
        )
        _atomic_write_json_at(
            self._root_fd,
            "conversation.json",
            self._processed_conversation(),
        )

    def _processed_conversation(self) -> dict[str, Any]:
        conversation = json.loads(json.dumps(self.conversation_full))
        messages = conversation.get("messages", [])
        if not isinstance(messages, list):
            return conversation
        tool_messages = [
            message for message in messages if message.get("role") == "toolResult"
        ]
        tool_names = self._tool_result_names(tool_messages)
        if self.features.externalize_tool_results and tool_messages:
            tool_results_fd = _open_private_directory_at(self._root_fd, "tool_results")
            try:
                for message, name in zip(tool_messages, tool_names, strict=True):
                    stats = self._tool_result_stats(message)
                    payload = {
                        "saved_at": _utc_now(),
                        "message": json.loads(json.dumps(message)),
                    }
                    _atomic_write_json_at(tool_results_fd, name, payload)
                    context = self._tool_result_context(message)
                    context["externalized"] = {
                        "path": f"tool_results/{name}",
                        "saved_at": payload["saved_at"],
                        "stats": stats,
                    }
            finally:
                os.close(tool_results_fd)
        if self.features.clear_tool_results:
            clear_count = max(
                0, len(tool_messages) - self.features.clear_tool_results_keep_last
            )
            for message in tool_messages[:clear_count]:
                self._clear_tool_result(message)
        for message in messages:
            self._strip_processed_assistant_fields(message)
        pending = conversation.get("pending_message")
        if isinstance(pending, dict):
            self._strip_processed_assistant_fields(pending)
        return conversation

    def _add_system_prompt(self) -> None:
        parts: list[str] = []
        for path in (
            self.request.system_prompt_file,
            self.request.append_system_prompt_file,
        ):
            if path is not None:
                parts.append(Path(path).read_text(encoding="utf-8").strip("\n"))
        if not parts:
            return
        self.conversation_full["messages"].append(
            {
                "role": "system",
                "content": [{"type": "text", "text": "\n\n".join(parts)}],
                "sources": {
                    "system_prompt_file": (
                        str(self.request.system_prompt_file)
                        if self.request.system_prompt_file
                        else None
                    ),
                    "append_system_prompt_file": (
                        str(self.request.append_system_prompt_file)
                        if self.request.append_system_prompt_file
                        else None
                    ),
                },
            }
        )

    def _restore_tool_timing_indexes(self) -> None:
        self._pending_tool_starts: dict[str, str] = {}
        self._completed_tool_timings: dict[str, dict[str, object]] = {}
        for entry in self.state.get("tool_calls", []):
            if not isinstance(entry, dict):
                continue
            call_id = entry.get("toolCallId")
            if not isinstance(call_id, str) or not call_id:
                continue
            if entry.get("event") == "tool_execution_start" and isinstance(
                entry.get("recorded_at"), str
            ):
                self._pending_tool_starts[call_id] = str(entry["recorded_at"])
            elif entry.get("event") == "tool_execution_end":
                timing = self._tool_timing(
                    call_id,
                    entry.get("started_at"),
                    entry.get("finished_at") or entry.get("recorded_at"),
                )
                if timing is not None:
                    self._completed_tool_timings[call_id] = timing
                self._pending_tool_starts.pop(call_id, None)
        self._refresh_tool_annotations()

    def _record_tool_timing(
        self, event: dict[str, object], *, recorded_at: str
    ) -> None:
        call_id = event.get("toolCallId")
        started_at: str | None = None
        finished_at: str | None = None
        timing: dict[str, object] | None = None
        if isinstance(call_id, str) and call_id:
            if event.get("type") == "tool_execution_start":
                started_at = recorded_at
                self._pending_tool_starts[call_id] = recorded_at
            else:
                started_at = self._pending_tool_starts.pop(call_id, None)
                finished_at = recorded_at
                timing = self._tool_timing(call_id, started_at, finished_at)
                if timing is not None:
                    self._completed_tool_timings[call_id] = timing
        self.state["tool_calls"].append(
            {
                "recorded_at": recorded_at,
                "event": event.get("type"),
                "toolCallId": call_id,
                "toolName": event.get("toolName"),
                "args": event.get("args"),
                "isError": event.get("isError"),
                "result": event.get("result"),
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": timing.get("duration_seconds") if timing else None,
            }
        )
        self._refresh_tool_annotations()

    @staticmethod
    def _tool_timing(
        call_id: str, started_at: object, finished_at: object
    ) -> dict[str, object] | None:
        duration = _duration_seconds(started_at, finished_at)
        if (
            duration is None
            or not isinstance(started_at, str)
            or not isinstance(finished_at, str)
        ):
            return None
        return {
            "tool_call_id": call_id,
            "status": "completed",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration,
            "duration_ms": int(round(duration * 1000)),
        }

    def _annotate_message(self, message: object) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return None
        result = json.loads(json.dumps(message))
        call_id = result.get("toolCallId")
        if result.get("role") == "toolResult" and isinstance(call_id, str):
            timing = self._completed_tool_timings.get(call_id)
            if timing is not None:
                result["tool_execution"] = json.loads(json.dumps(timing))
        return result

    def _refresh_tool_annotations(self) -> None:
        messages = self.conversation_full.get("messages", [])
        if isinstance(messages, list):
            self.conversation_full["messages"] = [
                self._annotate_message(message) or message for message in messages
            ]
        pending = self.conversation_full.get("pending_message")
        if isinstance(pending, dict):
            self.conversation_full["pending_message"] = self._annotate_message(pending)
        latest = (
            self.latest_model_context.get("latest")
            if hasattr(self, "latest_model_context")
            else None
        )
        if isinstance(latest, dict) and isinstance(latest.get("messages"), list):
            latest["messages"] = [
                self._annotate_message(message) or message
                for message in latest["messages"]
            ]

    def _record_latest_model_context(self, event: dict[str, object]) -> None:
        messages = event.get("messages")
        annotated = (
            [self._annotate_message(message) or message for message in messages]
            if isinstance(messages, list)
            else []
        )
        index = event.get("requestIndex")
        prior = self.latest_model_context.get("request_count", 0)
        self.latest_model_context["request_count"] = max(
            prior if isinstance(prior, int) else 0,
            index if isinstance(index, int) else 0,
        )
        runtime = json.loads(json.dumps(event.get("runtimeContextManagement")))
        self.latest_model_context["runtime_context_management"] = runtime
        self.latest_model_context["latest"] = {
            "captured_at": _utc_now(),
            "request_index": index,
            "model": event.get("model"),
            "runtime_context_management": runtime,
            "message_count": len(annotated),
            "messages": annotated,
            "payload": json.loads(json.dumps(event.get("payload"))),
        }

    @staticmethod
    def _tool_result_context(message: dict[str, Any]) -> dict[str, Any]:
        context = message.setdefault("context_management", {})
        return context.setdefault("tool_result", {})

    @staticmethod
    def _tool_result_stats(message: dict[str, Any]) -> dict[str, int]:
        texts = [
            part.get("text", "")
            for part in message.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n\n".join(value for value in texts if isinstance(value, str))
        return {
            "chars": len(text),
            "lines": len(text.splitlines()) if text else 0,
            "content_blocks": len(message.get("content", [])),
        }

    @staticmethod
    def _tool_result_names(messages: list[dict[str, Any]]) -> list[str]:
        next_suffix: dict[str, int] = {}
        reserved: set[str] = set()
        names: list[str] = []
        for message in messages:
            stem = _safe_tool_stem(message.get("toolCallId"))
            stem_key = stem.casefold()
            suffix_number = next_suffix.get(stem_key, 1)
            while True:
                suffix = "" if suffix_number == 1 else f"-{suffix_number}"
                candidate = f"{stem[: 80 - len(suffix)]}{suffix}.json"
                if candidate.casefold() not in reserved:
                    break
                suffix_number += 1
            reserved.add(candidate.casefold())
            next_suffix[stem_key] = suffix_number + 1
            names.append(candidate)
        return names

    def _clear_tool_result(self, message: dict[str, Any]) -> None:
        context = self._tool_result_context(message)
        stats = context.get("externalized", {}).get("stats") or self._tool_result_stats(
            message
        )
        context.update(
            {
                "status": "cleared",
                "stats": stats,
                "cleared_at": _utc_now(),
                "keep_last": self.features.clear_tool_results_keep_last,
            }
        )
        summary = [
            "[tool result cleared from conversation context]",
            f"tool={message.get('toolName', 'unknown')}",
            f"chars={stats.get('chars', 0)}",
            f"lines={stats.get('lines', 0)}",
        ]
        externalized = context.get("externalized")
        if isinstance(externalized, dict) and externalized.get("path"):
            summary.append(f"full_output={externalized['path']}")
        message["content"] = [{"type": "text", "text": "\n".join(summary)}]

    def _strip_processed_assistant_fields(self, message: dict[str, Any]) -> None:
        if message.get("role") != "assistant":
            return
        if self.features.strip_thinking and isinstance(message.get("content"), list):
            message["content"] = [
                part for part in message["content"] if part.get("type") != "thinking"
            ]
        if self.features.strip_usage:
            message.pop("usage", None)

    def _protocol_directory_fd(self) -> int:
        if self._protocol_fd is None:
            raise DciArtifactError("DCI run recorder is closed")
        return self._protocol_fd

    @staticmethod
    def _append_at(directory_fd: int, name: str, value: dict[str, object]) -> None:
        _write_private_text_at(
            directory_fd,
            name,
            json.dumps(value, ensure_ascii=False) + "\n",
            append=True,
        )


def _read_private_evidence(path: Path) -> bytes:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("paper benchmark evidence path is invalid")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValueError("paper benchmark evidence file is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _paper_clean_pi_identity(pi_dir: Path) -> tuple[str, str]:
    revision = subprocess.run(
        ["git", "-C", str(pi_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        [
            "git",
            "-C",
            str(pi_dir),
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
        ],
        check=True,
        capture_output=True,
    ).stdout
    if status:
        raise ValueError("paper benchmark Pi worktree must be clean")
    return revision, hashlib.sha256(status).hexdigest()


def _atomic_public_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bind_paper_benchmark_evidence(
    report_path: Path,
    *,
    state_dir: Path,
    pi_dir: Path,
    hypothesis_id: str = "AF-320-H-004",
) -> str:
    """Rehash bounded evidence and atomically create the terminal Climb result."""

    from asterion.dci.verification import (
        PAPER_BENCHMARK_REPORT_SCHEMA,
        paper_benchmark_resource_digests,
        paper_judge_identity,
    )
    from asterion.dci.judge import JudgeConfig

    report_path = Path(report_path)
    raw = _read_private_evidence(report_path)
    try:
        report = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("paper benchmark evidence report is invalid") from None
    revision, status_sha256 = _paper_clean_pi_identity(Path(pi_dir))
    if (
        not isinstance(report, dict)
        or set(report) != _PAPER_REPORT_KEYS
        or report.get("schema") != PAPER_BENCHMARK_REPORT_SCHEMA
        or report.get("mode") != "bounded-provider-backed"
        or report.get("pi_revision") != revision
        or report.get("pi_tracked_status_sha256") != status_sha256
        or report.get("agent_operations") != 2
        or report.get("judge_operations") != 1
        or report.get("external_operations") != 3
        or report.get("api_request_multiplicity") != "externally ambiguous"
        or report.get("operation_order") != list(_PAPER_OPERATION_PLAN)
        or report.get("full_dataset_ran") is not False
        or report.get("resources") != dict(paper_benchmark_resource_digests())
        or _PUBLIC_EVIDENCE_ID.fullmatch(str(report.get("provider"))) is None
        or _PUBLIC_EVIDENCE_ID.fullmatch(str(report.get("model"))) is None
    ):
        raise ValueError("paper benchmark evidence report is invalid")
    judge = report.get("judge")
    judge_public_keys = set(JudgeConfig().public_dict())
    if not isinstance(judge, dict) or set(judge) != judge_public_keys | {
        "prompt_contract_sha256"
    }:
        raise ValueError("paper benchmark Judge identity is invalid")
    if (
        any(
            type(judge[name]) is not str
            for name in (
                "judge_base_url",
                "judge_api",
                "judge_model",
                "judge_api_key_env",
            )
        )
        or any(
            type(judge[name]) is not int
            for name in ("judge_timeout_seconds", "judge_max_output_tokens")
        )
        or any(
            type(judge[name]) is not bool
            for name in (
                "judge_json_mode",
                "judge_strict_json_schema",
                "judge_responses_store",
            )
        )
        or not (
            judge["judge_thinking"] is None
            or type(judge["judge_thinking"]) is str
        )
        or any(
            isinstance(judge[name], bool)
            or not isinstance(judge[name], (int, float))
            for name in (
                "judge_input_price_per_1m",
                "judge_cached_input_price_per_1m",
                "judge_output_price_per_1m",
            )
        )
        or _HEX_SHA256.fullmatch(str(judge["prompt_contract_sha256"])) is None
    ):
        raise ValueError("paper benchmark Judge identity is invalid")
    try:
        reconstructed_judge = JudgeConfig(
            base_url=judge["judge_base_url"],
            api=judge["judge_api"],
            model=judge["judge_model"],
            timeout_seconds=judge["judge_timeout_seconds"],
            max_output_tokens=judge["judge_max_output_tokens"],
            json_mode=judge["judge_json_mode"],
            strict_json_schema=judge["judge_strict_json_schema"],
            responses_store=judge["judge_responses_store"],
            thinking=judge["judge_thinking"] or "omit",
            input_price_per_1m=judge["judge_input_price_per_1m"],
            cached_input_price_per_1m=judge["judge_cached_input_price_per_1m"],
            output_price_per_1m=judge["judge_output_price_per_1m"],
            api_key_env=judge["judge_api_key_env"],
        )
    except (AttributeError, TypeError, ValueError):
        raise ValueError("paper benchmark Judge identity is invalid") from None
    if dict(paper_judge_identity(reconstructed_judge)) != judge:
        raise ValueError("paper benchmark Judge identity is invalid")
    operations = report.get("operations")
    if not isinstance(operations, list) or len(operations) != 3:
        raise ValueError("paper benchmark evidence report is invalid")
    for index, operation in enumerate(operations):
        operation_id = _PAPER_OPERATION_PLAN[index]
        kind = "judge" if operation_id == "qa-judge" else "agent"
        if (
            not isinstance(operation, dict)
            or set(operation) != _PAPER_OPERATION_KEYS
            or operation.get("operation_id") != operation_id
            or operation.get("kind") != kind
            or operation.get("accepted") is not True
            or not isinstance(operation.get("artifact_digests"), dict)
            or not operation["artifact_digests"]
        ):
            raise ValueError("paper benchmark evidence report is invalid")
        for name, expected in operation["artifact_digests"].items():
            path = Path(name) if isinstance(name, str) else Path("/")
            if (
                not isinstance(name, str)
                or not name
                or path.is_absolute()
                or ".." in path.parts
                or _HEX_SHA256.fullmatch(str(expected)) is None
            ):
                raise ValueError("paper benchmark evidence report is invalid")
            operation_root = report_path.parent / operation_id
            current = operation_root
            if current.is_symlink():
                raise ValueError("paper benchmark evidence path is invalid")
            for part in path.parts:
                current /= part
                if current.is_symlink():
                    raise ValueError("paper benchmark evidence path is invalid")
            artifact = current
            actual = hashlib.sha256(_read_private_evidence(artifact)).hexdigest()
            if actual != expected:
                raise ValueError("paper benchmark evidence artifact digest is invalid")

    judge_artifacts = operations[1]["artifact_digests"]
    if set(judge_artifacts) != {"evaluation-evidence.json"}:
        raise ValueError("paper benchmark Judge evidence is invalid")
    try:
        judge_evidence = json.loads(
            _read_private_evidence(
                report_path.parent / "qa-judge/evaluation-evidence.json"
            )
        )
        evaluation_raw = _read_private_evidence(
            report_path.parent / "qa-agent/eval_result.json"
        )
        evaluation = json.loads(evaluation_raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("paper benchmark Judge evidence is invalid") from None
    if (
        not isinstance(judge_evidence, dict)
        or set(judge_evidence)
        != {"schema", "accepted", "evaluation_sha256"}
        or judge_evidence.get("schema")
        != "asterion.dci.paper-judge-evidence/v1"
        or judge_evidence.get("accepted") is not True
        or judge_evidence.get("evaluation_sha256")
        != hashlib.sha256(evaluation_raw).hexdigest()
        or not isinstance(evaluation, dict)
        or evaluation.get("is_correct") is not True
        or any(evaluation.get(name) != judge[name] for name in judge_public_keys)
        or _HEX_SHA256.fullmatch(
            str(evaluation.get("judge_request_fingerprint"))
        )
        is None
    ):
        raise ValueError("paper benchmark Judge evidence is invalid")

    report_sha256 = hashlib.sha256(raw).hexdigest()
    record = {
        "schema": "dci.climb.paper-benchmark-evidence/v2",
        "hypothesis_id": hypothesis_id,
        "report_sha256": report_sha256,
        "pi_revision": revision,
        "pi_worktree_clean": True,
        "pi_tracked_status_sha256": status_sha256,
        "agent_operations": 2,
        "judge_operations": 1,
        "external_operations": 3,
        "api_request_multiplicity": "externally ambiguous",
        "operation_order": list(_PAPER_OPERATION_PLAN),
        "full_dataset_ran": False,
        "judge": judge,
        "resources": report["resources"],
        "operations": operations,
    }
    record_raw = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
    record_sha256 = hashlib.sha256(record_raw).hexdigest()
    relative = f"provider-evidence/{hypothesis_id.lower()}.json"
    evidence_path = Path(state_dir) / relative
    hypotheses = Path(state_dir) / "hypotheses.yaml"
    text = hypotheses.read_text(encoding="utf-8")
    start = text.index(f"- id: {hypothesis_id}\n")
    end = text.find("\n- id: ", start + 1)
    end = len(text) if end < 0 else end
    section = text[start:end]
    binding = (
        "    provider_evidence:\n"
        f"      path: {relative}\n"
        f"      sha256: {record_sha256}\n"
        f"      report_sha256: {report_sha256}"
    )
    if "  status: confirmed\n" in section:
        if binding not in section or not evidence_path.is_file():
            raise ValueError("paper benchmark evidence is already bound differently")
        if evidence_path.read_bytes() != record_raw:
            raise ValueError("bound paper benchmark evidence is invalid")
        return record_sha256
    if (
        section.count("  status: pending\n") != 1
        or section.count("  results: []") != 1
        or evidence_path.exists()
    ):
        raise ValueError("terminal Climb hypothesis is invalid")
    result = (
        "  results:\n"
        "  - session: 2026-07-17-af-320-paper-benchmark-metric-parity\n"
        "    cycle: 95\n"
        "    run: af320-paper-benchmark-acceptance\n"
        "    local: 4\n"
        "    local_per_task:\n"
        "      deterministic_matrix: 1\n"
        "      product_parity: 1\n"
        "      exact_operation_bound: 1\n"
        "      immutable_evidence: 1\n"
        "    online: null\n"
        "    verdict: confirmed 4/4\n"
        "    decision_reason: digest-bound bounded provider acceptance\n"
        f"{binding}"
    )
    section = section.replace("  status: pending\n", "  status: confirmed\n")
    section = section.replace("  results: []", result)
    updated = (text[:start] + section + text[end:]).encode()
    _atomic_public_bytes(evidence_path, record_raw)
    try:
        _atomic_public_bytes(hypotheses, updated)
    except BaseException:
        evidence_path.unlink(missing_ok=True)
        raise
    return record_sha256
