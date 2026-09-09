"""Versioned, evidence-cited interpretation of normalized ARC run facts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from .model import RunStoryError, SCHEMA, canonical_json, content_id
from .storage import digest_bytes, publish_directory, rebuild_catalog


NARRATION_SCHEMA = "asterion.prime.arc-agi-3-run-story-narration/v1"
_CONFIDENCE = {"fact", "strong-inference", "tentative"}
_UNDERSTANDING_KEYS = {
    "controlled_object",
    "movement_behavior",
    "visual_relationship",
    "completion_condition",
}


@dataclass(frozen=True, repr=False, slots=True)
class RunStoryNarrationRequest:
    schema: str
    run: Mapping[str, object]
    actions: tuple[Mapping[str, object], ...]
    frames: tuple[Mapping[str, object], ...]
    diffs: tuple[Mapping[str, object], ...]
    reasoning_evidence: tuple[Mapping[str, object], ...]


class RunStoryNarrator(Protocol):
    model_id: str

    def generate(
        self, request: RunStoryNarrationRequest
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis_root: Path
    analysis_id: str
    status: str
    story: Mapping[str, object]


def _load_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RunStoryError("artifact-invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RunStoryError("artifact-invalid") from None
    if not isinstance(value, dict):
        raise RunStoryError("artifact-invalid")
    return value


def _load_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    if path.is_symlink() or not path.is_file():
        raise RunStoryError("artifact-invalid")
    try:
        values = tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RunStoryError("artifact-invalid") from None
    if any(not isinstance(value, dict) for value in values):
        raise RunStoryError("artifact-invalid")
    return values  # type: ignore[return-value]


def _load_bundle(bundle_root: Path) -> tuple[dict[str, object], tuple[dict[str, object], ...], tuple[dict[str, object], ...], tuple[dict[str, object], ...], tuple[dict[str, object], ...], str]:
    artifact = _load_json(bundle_root / "artifact.json")
    if artifact.get("schema") != SCHEMA or type(artifact.get("bundle_sha256")) is not str:
        raise RunStoryError("artifact-invalid")
    files = artifact.get("files")
    if not isinstance(files, dict):
        raise RunStoryError("artifact-invalid")
    for name, descriptor in files.items():
        if type(name) is not str or not isinstance(descriptor, dict):
            raise RunStoryError("artifact-invalid")
        path = bundle_root / name
        if path.is_symlink() or not path.is_file() or digest_bytes(path.read_bytes()) != descriptor.get("sha256"):
            raise RunStoryError("artifact-invalid")
    return (
        _load_json(bundle_root / "data" / "run.json"),
        _load_jsonl(bundle_root / "data" / "actions.jsonl"),
        _load_jsonl(bundle_root / "data" / "frames.jsonl"),
        _load_jsonl(bundle_root / "data" / "diffs.jsonl"),
        _load_jsonl(bundle_root / "data" / "reasoning-index.jsonl"),
        artifact["bundle_sha256"],  # type: ignore[return-value]
    )


def _bounded_text(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 1024 or "\x00" in value:
        raise RunStoryError("narration-invalid:text")
    return value


def _citations(
    value: object, *, action_count: int, frame_count: int
) -> dict[str, list[int]]:
    if not isinstance(value, Mapping) or set(value) != {"actions", "frames"}:
        raise RunStoryError("narration-invalid:citations-shape")
    actions = value["actions"]
    frames = value["frames"]
    if (
        type(actions) is not list
        or type(frames) is not list
        or not actions
        or not frames
        or any(type(item) is not int or not 1 <= item <= action_count for item in actions)
        or any(type(item) is not int or not 0 <= item < frame_count for item in frames)
        or actions != sorted(set(actions))
        or frames != sorted(set(frames))
    ):
        raise RunStoryError("narration-invalid:citations-range")
    return {"actions": list(actions), "frames": list(frames)}


def validate_story(
    value: object, *, action_count: int, frame_count: int
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "kind",
        "title",
        "summary",
        "episodes",
        "understanding",
    }:
        raise RunStoryError("narration-invalid:top-level")
    if value["schema"] != NARRATION_SCHEMA or value["kind"] != "narrated":
        raise RunStoryError("narration-invalid:identity")
    _bounded_text(value["title"])
    _bounded_text(value["summary"])
    episodes = value["episodes"]
    if type(episodes) is not list or not 1 <= len(episodes) <= 12:
        raise RunStoryError("narration-invalid:episodes")
    episode_keys = {
        "step_start",
        "step_end",
        "title",
        "observation",
        "hypothesis",
        "experiment",
        "result",
        "model_update",
        "consequence",
        "citations",
        "confidence",
        "decisive",
    }
    for episode in episodes:
        if not isinstance(episode, Mapping) or set(episode) != episode_keys:
            raise RunStoryError("narration-invalid:episode-shape")
        start, end = episode["step_start"], episode["step_end"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 1 <= start <= end <= action_count
        ):
            raise RunStoryError("narration-invalid:episode-steps")
        if episode["confidence"] not in _CONFIDENCE:
            raise RunStoryError("narration-invalid:episode-confidence")
        if type(episode["decisive"]) is not bool:
            raise RunStoryError("narration-invalid:episode-decisive")
        for field in (
            "title",
            "observation",
            "hypothesis",
            "experiment",
            "result",
            "model_update",
            "consequence",
        ):
            _bounded_text(episode[field])
        _citations(
            episode["citations"],
            action_count=action_count,
            frame_count=frame_count,
        )
    understanding = value["understanding"]
    if not isinstance(understanding, Mapping) or set(understanding) != _UNDERSTANDING_KEYS:
        raise RunStoryError("narration-invalid:understanding-shape")
    for item in understanding.values():
        if (
            not isinstance(item, Mapping)
            or set(item) != {"resolved", "answer", "confidence", "citations"}
            or type(item["resolved"]) is not bool
            or item["confidence"] not in _CONFIDENCE
        ):
            raise RunStoryError("narration-invalid:understanding-item")
        _bounded_text(item["answer"])
        _citations(item["citations"], action_count=action_count, frame_count=frame_count)
    return MappingProxyType(json.loads(canonical_json(value)))


def _fallback(run: Mapping[str, object], actions: tuple[Mapping[str, object], ...]) -> Mapping[str, object]:
    action_count = int(run["action_count"])
    frame_count = int(run["frame_count"])
    citations = {"actions": list(range(1, action_count + 1)), "frames": [0, frame_count - 1]}
    unresolved = {
        "resolved": False,
        "answer": "现有规范化事实不足以确定。",
        "confidence": "tentative",
        "citations": citations,
    }
    story = {
        "schema": NARRATION_SCHEMA,
        "kind": "factual-fallback",
        "title": "ARC-AGI-3 运行事实记录",
        "summary": f"本次运行执行 {action_count} 个动作；解释模型未提供可验证讲解。",
        "episodes": [
            {
                "step_start": 1,
                "step_end": action_count,
                "title": "完整动作序列",
                "observation": "报告保留了初始画面和全部动作后画面。",
                "hypothesis": "未记录可公开验证的假设。",
                "experiment": "按时间顺序回放全部动作。",
                "result": f"环境终态为 {run['terminal_reason']}。",
                "model_update": "仅呈现已验证事实，不补写内部推理。",
                "consequence": "可在后续分析版本中加入带引用的解释。",
                "citations": citations,
                "confidence": "fact",
                "decisive": bool(run["levels_completed"]),
            }
        ],
        "understanding": {
            "controlled_object": dict(unresolved),
            "movement_behavior": dict(unresolved),
            "visual_relationship": dict(unresolved),
            "completion_condition": {
                "resolved": bool(run["levels_completed"]),
                "answer": "最后记录的动作使环境报告关卡完成。"
                if run["levels_completed"]
                else "运行没有达到完成状态。",
                "confidence": "fact",
                "citations": citations,
            },
        },
    }
    del actions
    return MappingProxyType(story)


def _artifact_root(bundle_root: Path) -> Path:
    try:
        return bundle_root.parents[3]
    except IndexError:
        raise RunStoryError("artifact-invalid") from None


def analyze_bundle(
    bundle_root: Path, narrator: RunStoryNarrator | None
) -> AnalysisResult:
    run, actions, frames, diffs, reasoning, bundle_sha256 = _load_bundle(bundle_root)
    fallback = _fallback(run, actions)
    story: Mapping[str, object] = fallback
    status = "unavailable"
    model_id: str | None = None
    rejection_code: str | None = None
    if narrator is not None:
        model_id = narrator.model_id
        try:
            candidate = narrator.generate(
                RunStoryNarrationRequest(
                    NARRATION_SCHEMA,
                    MappingProxyType(run),
                    tuple(MappingProxyType(item) for item in actions),
                    tuple(MappingProxyType(item) for item in frames),
                    tuple(MappingProxyType(item) for item in diffs),
                    tuple(MappingProxyType(item) for item in reasoning),
                )
            )
            story = validate_story(
                candidate,
                action_count=int(run["action_count"]),
                frame_count=int(run["frame_count"]),
            )
            status = "accepted"
        except Exception as error:
            story = fallback
            status = "rejected"
            rejection_code = (
                str(error)
                if isinstance(error, RunStoryError)
                and str(error).startswith("narration-invalid:")
                else "narration-invalid"
            )
    story_bytes = canonical_json(story)
    identity = {
        "schema": SCHEMA,
        "bundle_sha256": bundle_sha256,
        "contract_version": NARRATION_SCHEMA,
        "model_id": model_id,
        "status": status,
        "rejection_code": rejection_code,
        "story_sha256": digest_bytes(story_bytes),
    }
    analysis_id = content_id("analysis", identity)
    destination = bundle_root / "analyses" / analysis_id
    publish_directory(
        destination,
        {
            "analysis.json": canonical_json({**identity, "analysis_id": analysis_id}),
            "story.json": story_bytes,
        },
    )
    rebuild_catalog(_artifact_root(bundle_root))
    return AnalysisResult(destination, analysis_id, status, story)


__all__ = (
    "AnalysisResult",
    "NARRATION_SCHEMA",
    "RunStoryNarrationRequest",
    "RunStoryNarrator",
    "analyze_bundle",
    "validate_story",
)
