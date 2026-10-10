"""Application-owned narration adapter for normalized ARC evidence."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from asterion.agents.prime.application import (
    PrimeApplicationSpec,
    PrimeOperatorContext,
    PrimeTextLimits,
    prepare_prime_application,
)
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.operator_config import resolve_pi_effort
from asterion.applications.prime.p7 import live
from asterion.applications.prime.p7.model_selection import resolve_model_selection

from .analysis import RunStoryNarrationRequest
from .model import RunStoryError, canonical_json


_DEADLINE_SECONDS = 300.0


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


def _parse_object(text: str) -> Mapping[str, object]:
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[7:-3].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        raise RunStoryError("narration-invalid") from None
    if not isinstance(value, dict):
        raise RunStoryError("narration-invalid")
    return value


def _normalize_candidate(value: Mapping[str, object]) -> Mapping[str, object]:
    """Normalize harmless JSON serialization variants, never factual ranges."""

    candidate = json.loads(canonical_json(value))
    aliases = {
        "fact": "fact",
        "factual": "fact",
        "strong": "strong-inference",
        "high": "strong-inference",
        "high-confidence": "strong-inference",
        "strong-inference": "strong-inference",
        "inference": "tentative",
        "medium": "tentative",
        "low": "tentative",
        "tentative": "tentative",
    }

    def confidence(value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
        return aliases.get(normalized, normalized)

    episodes = candidate.get("episodes")
    if isinstance(episodes, list):
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            for key in ("step_start", "step_end"):
                raw = episode.get(key)
                if isinstance(raw, str) and raw.isascii() and raw.isdigit():
                    episode[key] = int(raw)
            episode["confidence"] = confidence(episode.get("confidence"))
    understanding = candidate.get("understanding")
    if isinstance(understanding, dict):
        for item in understanding.values():
            if isinstance(item, dict):
                item["confidence"] = confidence(item.get("confidence"))
    return candidate


class RunStoryNarrator:
    """One-call structured narrator; private invocation details stay host-side."""

    __slots__ = ("model_id", "_invoke")

    def __init__(self, *, model_id: str, invoke: Callable[[str], str]) -> None:
        if type(model_id) is not str or not model_id or not callable(invoke):
            raise RunStoryError("narrator-unavailable")
        self.model_id = model_id
        self._invoke = invoke

    def __repr__(self) -> str:
        return "<RunStoryNarrator redacted>"

    def generate(self, request: RunStoryNarrationRequest) -> Mapping[str, object]:
        action_count = len(request.actions)
        frame_count = len(request.frames)
        frames = [dict(item) for item in request.frames]
        if not frames:
            raise RunStoryError("narration-invalid")
        initial_grid = frames[0].pop("grid", None)
        final_grid = frames[-1].get("grid")
        for frame in frames:
            frame.pop("grid", None)
        evidence = {
            "schema": request.schema,
            "run": dict(request.run),
            "actions": [dict(item) for item in request.actions],
            "frames": frames,
            "initial_grid": initial_grid,
            "final_grid": final_grid,
            "diffs": [dict(item) for item in request.diffs],
            "reasoning_evidence": [dict(item) for item in request.reasoning_evidence],
        }
        prompt = (
            "你是 ARC-AGI-3 解题记录分析器。只分析下列规范化证据，不声称知道未公开的思维链。"
            f"动作编号严格为 1–{action_count}，帧编号严格为 0–{frame_count - 1}；每一组 citations 的"
            "actions 和 frames 都必须是非空、升序、无重复的整数数组。"
            "输出且只输出一个 JSON 对象，禁止 Markdown，严格满足证据中的 schema，禁止增加任何字段。"
            "顶层字段只能是 schema,kind,title,summary,episodes,understanding；kind 必须为 narrated；"
            "包含 title、summary、1 至 6 个 episodes，以及 understanding；每段中文字段尽量不超过 220 字。"
            "initial_grid 加逐帧 diffs 可无损重建中间帧，final_grid 是终态。每个判断必须引用实际"
            " action 编号与 frame 编号；区分 fact、strong-inference、tentative。"
            "episodes 字段必须是 step_start, step_end, title, observation, hypothesis, experiment, "
            "result, model_update, consequence, citations, confidence, decisive。"
            "understanding 必须且只能含 controlled_object、movement_behavior、visual_relationship、"
            "completion_condition；每项必须且只能含 resolved、answer、confidence、citations。"
            "文字用简洁中文，重点解释如何通过动作后的画面变化逐步发现规则，以及完成后对题目的理解。\n"
            + canonical_json(evidence).decode("utf-8")
        )
        return _normalize_candidate(_parse_object(self._invoke(prompt)))


def load_operator_narrator(
    repo_root: Path, *, task_deadline: TaskDeadline | None = None,
) -> RunStoryNarrator:
    """Prepare the exact P7 text preset without creating a model effect."""

    try:
        if task_deadline is None:
            task_deadline = TaskDeadline(
                deadline_monotonic=time.monotonic() + _DEADLINE_SECONDS,
                deadline_epoch=time.time() + _DEADLINE_SECONDS,
            )
        root = repo_root.resolve(strict=True)
        environment = dict(live.load_operator_environment(root))
        selection = resolve_model_selection(environment)
        executable = live.resolve_node(environment)
        entry = live.resolve_pi_entry(environment)
        profile = live.resolve_pi_agent_dir(environment)
        environment["PI_CODING_AGENT_DIR"] = str(profile)
        limits = PrimeTextLimits(deadline_seconds=_DEADLINE_SECONDS)
        application = prepare_prime_application(
            PrimeApplicationSpec("prime.arc-agi-3-run-story", "1.0.0", "text-only"),
            PrimeOperatorContext(
                executable=executable, entry=entry, cwd=root,
                provider=selection.provider, model=selection.model,
                effort=resolve_pi_effort(environment, default="medium"),
                environment=environment, task_deadline=task_deadline,
            ),
            authorization=limits,
        )
    except Exception:
        raise RunStoryError("narrator-unavailable") from None

    async def text_once(prompt: str) -> str:
        try:
            reply = await application.text_once(
                key="narrator", text=prompt, limits=limits, signal=_NeverCancelled(),
            )
            return reply.text
        finally:
            receipt = await application.close()
            if getattr(receipt, "complete", None) is not True:
                raise RunStoryError("narrator-unavailable")

    def invoke(prompt: str) -> str:
        try:
            return asyncio.run(text_once(prompt))
        except Exception:
            raise RunStoryError("narrator-unavailable") from None

    return RunStoryNarrator(model_id=selection.model, invoke=invoke)


__all__ = ("RunStoryNarrator", "load_operator_narrator")
