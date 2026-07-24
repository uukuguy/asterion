"""Cache-safe evaluation of durable independent Asterion DCI run directories."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from asterion.dci.artifacts import (
    DciArtifactError,
    DciRunLock,
    json_document_bytes,
    validate_completed_run_evidence,
)
from asterion.dci.judge import (
    DciJudgeError,
    JudgeConfig,
    estimate_judge_cost,
    judge_answer_sync,
    judge_request_fingerprint,
)


class DciEvaluationError(RuntimeError):
    """Safe public error for native-run evaluation failures."""


def evaluate_run_directory(
    output_dir: Path,
    *,
    gold_answer: str,
    judge_config: JudgeConfig,
    predicted_answer: str | None = None,
    _cancel_event: threading.Event | None = None,
    _directory_fd: int | None = None,
) -> dict[str, object]:
    """Evaluate one completed native run under its recorder writer authority."""

    if not isinstance(gold_answer, str) or not gold_answer.strip():
        raise DciEvaluationError("DCI evaluation input is invalid")
    lock: DciRunLock | None = None
    try:
        lock = (
            DciRunLock.acquire_existing(Path(output_dir), wait=True)
            if _directory_fd is None
            else DciRunLock.acquire_fd(
                _directory_fd, path=Path(output_dir), wait=True
            )
        )
        state, question, durable_prediction = validate_completed_run_evidence(lock)
        if lock.recover_evaluation_transaction(
            validate_candidate=_valid_transaction_candidate
        ):
            state, question, durable_prediction = validate_completed_run_evidence(lock)
        prediction = (
            predicted_answer if predicted_answer is not None else durable_prediction
        )
        if not isinstance(prediction, str):
            raise DciEvaluationError("DCI evaluation input is invalid")
        fingerprint = judge_request_fingerprint(
            config=judge_config,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=prediction,
        )
        cached = _load_reusable_result(lock, state, fingerprint, judge_config)
        if cached is not None:
            return cached
        if _cancel_event is not None and _cancel_event.is_set():
            raise DciEvaluationError("DCI evaluation was cancelled")
        judged = judge_answer_sync(
            config=judge_config,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=prediction,
            cancel_event=_cancel_event,
        )
        result = dict(judged)
        result["judge_request_fingerprint"] = fingerprint
        result["evaluation_commit_id"] = secrets.token_hex(32)
        if not _valid_verdict(result, fingerprint, judge_config):
            raise DciEvaluationError("DCI evaluation failed")
        evaluation_digest = hashlib.sha256(json_document_bytes(result)).hexdigest()
        state["evaluation"] = _evaluation_summary(result, evaluation_digest)
        lock.publish_json_pair(state=state, evaluation=result)
        return result
    except DciEvaluationError:
        raise
    except (DciArtifactError, DciJudgeError, OSError, ValueError) as error:
        raise DciEvaluationError("DCI evaluation failed") from error
    finally:
        if lock is not None:
            lock.release()


async def evaluate_run_directory_async(
    output_dir: Path,
    *,
    gold_answer: str,
    judge_config: JudgeConfig,
    predicted_answer: str | None = None,
    _directory_fd: int | None = None,
) -> dict[str, object]:
    """Evaluate asynchronously, draining a started blocking transport on cancellation."""

    cancel_event = threading.Event()
    work = asyncio.create_task(
        asyncio.to_thread(
            evaluate_run_directory,
            output_dir,
            gold_answer=gold_answer,
            judge_config=judge_config,
            predicted_answer=predicted_answer,
            _cancel_event=cancel_event,
            _directory_fd=_directory_fd,
        )
    )
    try:
        await asyncio.wait({work})
        return work.result()
    except asyncio.CancelledError:
        cancel_event.set()
        await _drain_cancelled_work(work)
        raise


async def _drain_cancelled_work(work: asyncio.Task[object]) -> None:
    while not work.done():
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        try:
            await asyncio.wait({work})
        except asyncio.CancelledError:
            continue
    try:
        work.result()
    except Exception:
        pass


def _load_reusable_result(
    lock: DciRunLock,
    state: dict[str, Any],
    fingerprint: str,
    config: JudgeConfig,
) -> dict[str, object] | None:
    document = lock.read_optional_json_document("eval_result.json")
    if document is None:
        return None
    value, raw = document
    if not _valid_verdict(value, fingerprint, config):
        return None
    digest = hashlib.sha256(raw).hexdigest()
    if state.get("evaluation") != _evaluation_summary(value, digest):
        return None
    return value


def _valid_verdict(
    value: dict[str, Any], fingerprint: str, config: JudgeConfig
) -> bool:
    expected_keys = set(config.public_dict()) | {
        "judged_at",
        "attempts",
        "judge_request_fingerprint",
        "is_correct",
        "normalized_prediction",
        "reason",
        "usage",
        "cost_estimate_usd",
        "evaluation_commit_id",
    }
    judged_at = value.get("judged_at")
    try:
        timestamp = (
            datetime.fromisoformat(judged_at) if isinstance(judged_at, str) else None
        )
    except ValueError:
        timestamp = None
    attempts = value.get("attempts")
    return (
        set(value) == expected_keys
        and value.get("judge_request_fingerprint") == fingerprint
        and isinstance(value.get("is_correct"), bool)
        and isinstance(value.get("normalized_prediction"), str)
        and isinstance(value.get("reason"), str)
        and isinstance(value.get("evaluation_commit_id"), str)
        and re.fullmatch(r"[0-9a-f]{64}", value["evaluation_commit_id"])
        and timestamp is not None
        and timestamp.tzinfo is not None
        and isinstance(attempts, int)
        and not isinstance(attempts, bool)
        and 1 <= attempts <= 3
        and _valid_usage(value.get("usage"))
        and _valid_cost(value.get("cost_estimate_usd"), value.get("usage"), config)
        and all(
            value.get(name) == expected
            for name, expected in config.public_dict().items()
        )
    )


def _valid_usage(value: object) -> bool:
    required = {"input_tokens", "output_tokens", "total_tokens"}
    allowed = required | {"input_tokens_details"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - allowed
    ):
        return False
    numbers = [value[name] for name in required]
    details = value.get("input_tokens_details")
    if details is not None:
        if not isinstance(details, dict) or set(details) != {"cached_tokens"}:
            return False
        numbers.append(details["cached_tokens"])
    if not all(
        isinstance(number, (int, float))
        and not isinstance(number, bool)
        and math.isfinite(number)
        and number >= 0
        for number in numbers
    ):
        return False
    return value["total_tokens"] == value["input_tokens"] + value["output_tokens"] and (
        details is None or details["cached_tokens"] <= value["input_tokens"]
    )


def _valid_cost(value: object, usage: object, config: JudgeConfig) -> bool:
    names = {"input_cost", "cached_input_cost", "output_cost", "total_cost"}
    if (
        not isinstance(value, dict)
        or set(value) != names
        or not isinstance(usage, dict)
    ):
        return False
    if not all(
        isinstance(value[name], (int, float))
        and not isinstance(value[name], bool)
        and math.isfinite(value[name])
        and value[name] >= 0
        and not (value[name] == 0 and math.copysign(1.0, value[name]) < 0)
        for name in names
    ):
        return False
    expected = estimate_judge_cost(usage, config)
    return all(value[name] == expected[name] for name in names)


def _evaluation_summary(
    result: dict[str, Any], evaluation_digest: str
) -> dict[str, object]:
    return {
        name: result.get(name)
        for name in (
            "judge_model",
            "judge_base_url",
            "judge_api",
            "judged_at",
            "judge_request_fingerprint",
            "is_correct",
            "normalized_prediction",
            "reason",
            "usage",
            "cost_estimate_usd",
            "evaluation_commit_id",
        )
    } | {"eval_result_sha256": evaluation_digest}


def _valid_transaction_candidate(
    state_document: tuple[dict[str, Any], bytes],
    evaluation_document: tuple[dict[str, Any], bytes],
) -> bool:
    state, _ = state_document
    result, raw = evaluation_document
    thinking = result.get("judge_thinking")
    try:
        config = JudgeConfig(
            base_url=result["judge_base_url"],
            api=result["judge_api"],
            model=result["judge_model"],
            timeout_seconds=result["judge_timeout_seconds"],
            max_output_tokens=result["judge_max_output_tokens"],
            json_mode=result["judge_json_mode"],
            strict_json_schema=result["judge_strict_json_schema"],
            responses_store=result["judge_responses_store"],
            thinking="omit" if thinking is None else thinking,
            input_price_per_1m=result["judge_input_price_per_1m"],
            cached_input_price_per_1m=result["judge_cached_input_price_per_1m"],
            output_price_per_1m=result["judge_output_price_per_1m"],
            api_key_env=result["judge_api_key_env"],
        )
        fingerprint = result["judge_request_fingerprint"]
    except (KeyError, TypeError, ValueError):
        return False
    digest = hashlib.sha256(raw).hexdigest()
    return (
        isinstance(fingerprint, str)
        and _valid_verdict(result, fingerprint, config)
        and state.get("evaluation") == _evaluation_summary(result, digest)
    )
