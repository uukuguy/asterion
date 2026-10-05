"""Versioned P7 research artifacts; declarations are never environment evidence."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re

from .score import canonical_bytes, digest

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OPERATIONS = {"analyze", "model", "validate", "search", "probe", "execute"}


def copy_json(value: object, *, limit: int = 1024 * 1024) -> object:
    """Thaw finite exports without retaining references into the kernel."""

    def thaw(item, depth=0):
        if depth > 32:
            raise ValueError("research value too deep")
        if isinstance(item, Mapping):
            if any(type(k) is not str for k in item):
                raise ValueError("research key invalid")
            return {k: thaw(v, depth + 1) for k, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [thaw(v, depth + 1) for v in item]
        if item is None or type(item) in (str, int, float, bool):
            return item
        raise ValueError("research value invalid")

    result = thaw(value)
    if len(canonical_bytes(result)) > limit:
        raise ValueError("research value too large")
    return result


def identifier(value: object) -> str:
    if (
        type(value) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}", value) is None
    ):
        raise ValueError("research identifier invalid")
    return value


def export_hash(record: Mapping) -> str:
    return digest({k: record[k] for k in ("name", "kind", "value", "source_call_id")})


def _text(value: object, *, limit: int = 600) -> str:
    if type(value) is not str or len(value) > limit:
        raise ValueError("research text invalid")
    return value


def _texts(value: object) -> list[str]:
    if type(value) is not list or len(value) > 32:
        raise ValueError("research text list invalid")
    return [_text(v) for v in value]


def evidence(value: object, latest: int) -> list[int]:
    if (
        type(value) is not list
        or len(value) > 128
        or any(type(v) is not int or not 0 <= v <= latest for v in value)
        or value != sorted(set(value))
    ):
        raise ValueError("research evidence invalid")
    return list(value)


def task(value: object) -> dict:
    if not isinstance(value, Mapping) or set(value) != {
        "goal",
        "obstacles",
        "question",
        "next_operation",
        "public_basis",
    }:
        raise ValueError("research task invalid")
    if value["next_operation"] not in _OPERATIONS:
        raise ValueError("research operation invalid")
    return {
        "goal": _text(value["goal"]),
        "obstacles": _texts(value["obstacles"]),
        "question": _text(value["question"]),
        "next_operation": value["next_operation"],
        "public_basis": _text(value["public_basis"]),
    }


def _atomic(path: Path, value: object) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("research path invalid")
    temporary = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class ResearchWorkspace:
    """Host-owned revisions and explicit, content-verified export copies."""

    def __init__(self, *, root: Path, scope: Mapping, kernel):
        self.scope = copy_json(scope)
        self.kernel = kernel
        self.root = Path(root) / digest(self.scope).removeprefix("sha256:")
        if Path(root).is_symlink() or self.root.is_symlink():
            raise ValueError("research root invalid")
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("artifacts", "revisions"):
            path = self.root / name
            if path.is_symlink():
                raise ValueError("research root invalid")
            path.mkdir(exist_ok=True)
        initial = {
            "scope": self.scope,
            "parent_revision": None,
            "worldmap": {
                "description_zh": "",
                "state_summary": "",
                "rules": [],
                "unknowns": [],
                "competing_hypotheses": [],
            },
            "task": {
                "goal": "",
                "obstacles": [],
                "question": "",
                "next_operation": "analyze",
                "public_basis": "",
            },
            "model": {
                "source_export_ids": [],
                "coverage": "unknown",
                "assumptions": [],
            },
            "reports": [],
            "evidence_sequences": [],
            "correction": {"changed": [], "retained": []},
        }
        self._artifacts: dict[str, dict] = {}
        self._checkpoint = None
        self.task_id = None
        current_path = self.root / "current.json"
        self.loaded = current_path.exists()
        if self.loaded:
            current = self._read(current_path)
            if set(current) != {"scope", "revision"} or current["scope"] != self.scope:
                raise ValueError("research scope mismatch")
            self.revision = current["revision"]
            revision = self.revision
            seen = set()
            while revision is not None:
                if revision in seen or len(seen) >= 16384:
                    raise ValueError("research revision ancestry invalid")
                seen.add(revision)
                snapshot = self.read(revision)
                model = snapshot["model"]
                for eid in [
                    *model["source_export_ids"],
                    *(r["export_id"] for r in snapshot["reports"]),
                    *([model["state_export_id"]] if "state_export_id" in model else []),
                ]:
                    self._load_artifact(eid)
                revision = snapshot["parent_revision"]
            checkpoint_path = self.root / "checkpoint.json"
            if checkpoint_path.exists():
                manifest = self._read(checkpoint_path)
                if (
                    manifest.get("scope") != self.scope
                    or manifest.get("revision") not in seen
                ):
                    raise ValueError("research checkpoint scope mismatch")
                for eid in [
                    *manifest["source_export_ids"],
                    *(
                        manifest[k]
                        for k in ("state_export_id", "frontier_export_id")
                        if k in manifest
                    ),
                ]:
                    self._load_artifact(eid)
                self._checkpoint = manifest
        else:
            self.revision = self._save_revision(initial)

    def _save_revision(self, value: dict) -> str:
        revision = digest(value)
        path = self.root / "revisions" / (revision[7:] + ".json")
        if not path.exists():
            _atomic(path, value)
        else:
            self._read(path, revision)
        _atomic(self.root / "current.json", {"scope": self.scope, "revision": revision})
        return revision

    def _read(self, path: Path, expected: str | None = None) -> dict:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("research artifact unavailable")
        value = json.loads(path.read_bytes())
        if expected is not None and digest(value) != expected:
            raise ValueError("research artifact corrupt")
        return copy_json(value)

    def read(self, revision: str | None = None) -> dict:
        revision = self.revision if revision is None else revision
        if type(revision) is not str or _HASH.fullmatch(revision) is None:
            raise ValueError("research revision invalid")
        value = self._read(self.root / "revisions" / (revision[7:] + ".json"), revision)
        if value["scope"] != self.scope:
            raise ValueError("research scope mismatch")
        return {"workspace_revision": revision, **value}

    def candidate(self, export_id: str, kind: str | None = None) -> dict:
        if type(export_id) is not str or _HASH.fullmatch(export_id) is None:
            raise ValueError("research export invalid")
        exported = self.kernel.read_export(export_id)
        record = {
            "name": exported.name,
            "kind": exported.kind,
            "value": copy_json(exported.value),
            "source_call_id": exported.source_call_id,
        }
        if (
            exported.export_id != export_id
            or export_hash(record) != export_id
            or record["kind"] not in {"json", "text"}
        ):
            raise ValueError("research export corrupt")
        if kind is not None and record["kind"] != kind:
            raise ValueError("research export kind mismatch")
        if record["kind"] == "text" and type(record["value"]) is not str:
            raise ValueError("research source invalid")
        return record

    def _admit(self, export_id: str, record: dict) -> None:
        path = self.root / "artifacts" / (export_id[7:] + ".json")
        stored = {"scope": self.scope, "export_id": export_id, **record}
        if path.exists():
            if self._read(path) != stored:
                raise ValueError("research artifact corrupt")
        else:
            _atomic(path, stored)
        self._artifacts[export_id] = copy_json(record)

    def _load_artifact(self, export_id: str) -> None:
        if type(export_id) is not str or _HASH.fullmatch(export_id) is None:
            raise ValueError("research export invalid")
        stored = self._read(self.root / "artifacts" / (export_id[7:] + ".json"))
        if (
            set(stored)
            != {"scope", "export_id", "name", "kind", "value", "source_call_id"}
            or stored["scope"] != self.scope
            or stored["export_id"] != export_id
            or export_hash(stored) != export_id
        ):
            raise ValueError("research artifact corrupt")
        self._artifacts[export_id] = {
            k: stored[k] for k in ("name", "kind", "value", "source_call_id")
        }

    def artifact(self, export_id: str):
        if export_id not in self._artifacts:
            raise ValueError("research artifact not admitted")
        stored = self._read(self.root / "artifacts" / (export_id[7:] + ".json"))
        if (
            stored["scope"] != self.scope
            or stored["export_id"] != export_id
            or export_hash(stored) != export_id
        ):
            raise ValueError("research artifact corrupt")
        return copy_json(stored["value"])

    def publish(
        self,
        *,
        base_revision: str,
        draft_export_id: str,
        latest: int,
        verify_report=None,
    ) -> dict:
        if base_revision != self.revision:
            raise ValueError("stale-workspace-revision")
        draft_record = self.candidate(draft_export_id, "json")
        value = draft_record["value"]
        if type(value) is not dict or set(value) != {
            "worldmap",
            "task",
            "model",
            "reports",
            "evidence_sequences",
            "correction",
        }:
            raise ValueError("research draft invalid")
        world = value["worldmap"]
        if type(world) is not dict or set(world) != {
            "description_zh",
            "state_summary",
            "rules",
            "unknowns",
            "competing_hypotheses",
        }:
            raise ValueError("research worldmap invalid")
        world = {
            "description_zh": _text(world["description_zh"], limit=8000),
            "state_summary": _text(world["state_summary"]),
            **{
                k: _texts(world[k])
                for k in ("rules", "unknowns", "competing_hypotheses")
            },
        }
        model = value["model"]
        if (
            type(model) is not dict
            or not {"source_export_ids", "coverage", "assumptions"} <= set(model)
            or not set(model)
            <= {"source_export_ids", "state_export_id", "coverage", "assumptions"}
        ):
            raise ValueError("research model invalid")
        sources = model["source_export_ids"]
        if (
            type(sources) is not list
            or len(sources) > 32
            or len(set(sources)) != len(sources)
        ):
            raise ValueError("research sources invalid")
        candidates = {eid: self.candidate(eid, "text") for eid in sources}
        _text(model["coverage"])
        _texts(model["assumptions"])
        if "state_export_id" in model:
            candidates[model["state_export_id"]] = self.candidate(
                model["state_export_id"], "json"
            )
        reports = value["reports"]
        if type(reports) is not list or len(reports) > 32:
            raise ValueError("research reports invalid")
        accepted_reports = []
        for report in reports:
            if (
                type(report) is not dict
                or set(report)
                != {"kind", "export_id", "evidence_sequences", "claim_status"}
                or report["kind"] not in {"projection", "dynamics", "goal", "search"}
                or report["claim_status"] not in {"reported", "checked", "unknown"}
            ):
                raise ValueError("research report invalid")
            candidates[report["export_id"]] = self.candidate(
                report["export_id"], "json"
            )
            report_evidence = evidence(report["evidence_sequences"], latest)
            validation = (
                verify_report(
                    report["kind"],
                    candidates[report["export_id"]]["value"],
                    report_evidence,
                )
                if verify_report is not None
                else {
                    "kind": report["kind"],
                    "status": "unknown",
                    "checked_count": 0,
                    "comparison_count": 0,
                    "first_counterexample_sequence": None,
                }
            )
            accepted_reports.append(
                {
                    **report,
                    "evidence_sequences": report_evidence,
                    "validation": validation,
                    "reported_claim_status": report["claim_status"],
                    "claim_status": "checked"
                    if validation["status"] == "checked"
                    else (
                        "unknown" if validation["status"] == "unknown" else "reported"
                    ),
                }
            )
        correction = value["correction"]
        if (
            type(correction) is not dict
            or not {"changed", "retained"} <= set(correction)
            or not set(correction) <= {"counterexample_sequence", "changed", "retained"}
        ):
            raise ValueError("research correction invalid")
        _texts(correction["changed"])
        _texts(correction["retained"])
        if "counterexample_sequence" in correction:
            evidence([correction["counterexample_sequence"]], latest)
        accepted = {
            "scope": self.scope,
            "parent_revision": self.revision,
            "worldmap": world,
            "task": task(value["task"]),
            "model": copy_json(model),
            "reports": accepted_reports,
            "evidence_sequences": evidence(value["evidence_sequences"], latest),
            "correction": copy_json(correction),
        }
        for eid, record in candidates.items():
            self._admit(eid, record)
        self._admit(draft_export_id, draft_record)
        self.revision = self._save_revision(accepted)
        return self.read()

    def focus(self, value: Mapping) -> dict:
        focused = task(value)
        self.task_id = digest({"revision": self.revision, "task": focused})
        self._focused = focused
        return {"task_id": self.task_id, "task": copy_json(focused)}

    def checkpoint(self, request: Mapping, *, latest: int, generation: object) -> dict:
        if request["revision"] != self.revision:
            raise ValueError("stale-workspace-revision")
        evidence([request["analyzed_through"]], latest)
        revision = self.read()
        sources = revision["model"]["source_export_ids"]
        for eid in sources:
            self.artifact(eid)
        candidates = {}
        for key in ("state_export_id", "frontier_export_id"):
            if key in request:
                candidates[request[key]] = self.candidate(request[key], "json")
        manifest = {
            "scope": self.scope,
            "revision": self.revision,
            "source_export_ids": list(sources),
            "analyzed_through": request["analyzed_through"],
            "generation": generation,
            **{
                key: request[key]
                for key in ("state_export_id", "frontier_export_id")
                if key in request
            },
        }
        for eid, record in candidates.items():
            self._admit(eid, record)
        _atomic(self.root / "checkpoint.json", manifest)
        self._checkpoint = manifest
        return copy_json(manifest)

    def checkpoint_manifest(self) -> dict | None:
        if self._checkpoint is None:
            return None
        manifest = self._read(self.root / "checkpoint.json")
        if manifest != self._checkpoint or manifest["scope"] != self.scope:
            raise ValueError("research checkpoint corrupt")
        for eid in [
            *manifest["source_export_ids"],
            *(
                manifest[k]
                for k in ("state_export_id", "frontier_export_id")
                if k in manifest
            ),
        ]:
            self.artifact(eid)
        return copy_json(manifest)
