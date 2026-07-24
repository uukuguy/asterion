"""Executable five-stage DCI application implementations."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from collections.abc import Mapping

from asterion.dci.analysis import aggregate_results
from asterion.dci.provenance import dci_complete_implementation_identity
from asterion.dci.services import AnswerJudgeService, LocalCorpusService
from asterion.packages.execution import (
    InProcessArtifactPayload,
    PackageExecutionError,
    PackageExecutionResult,
    PackageInvocation,
    project_public_value,
)
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream


INPUT_PROTOCOL = "asterion.dci.complete-input/v1"
IMPLEMENTATION_PROTOCOL = "asterion.dci.complete-application/v1"


def complete_application_identity() -> str:
    """Digest the exact shipped implementation and portable application resources."""

    return dci_complete_implementation_identity()


def _envelope(value: str) -> tuple[str, str]:
    try:
        document = json.loads(value)
    except (TypeError, ValueError):
        raise PackageExecutionError("complete application input is invalid") from None
    if not isinstance(document, dict) or set(document) != {
        "protocol",
        "question",
        "gold_answer",
    }:
        raise PackageExecutionError("complete application input is invalid")
    question = document.get("question")
    gold = document.get("gold_answer")
    if (
        document.get("protocol") != INPUT_PROTOCOL
        or not isinstance(question, str)
        or not question.strip()
        or not isinstance(gold, str)
        or not gold.strip()
    ):
        raise PackageExecutionError("complete application input is invalid")
    return question, gold


def _artifact(invocation: PackageInvocation, media_type: str) -> dict[str, object]:
    matches = [
        item
        for item in invocation.upstream_artifacts
        if item.get("media_type") == media_type
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("value"), Mapping):
        raise PackageExecutionError("complete application upstream evidence is invalid")
    value = dict(matches[0]["value"])
    if (
        value.get("schema") != IMPLEMENTATION_PROTOCOL
        or value.get("implementation_sha256") != complete_application_identity()
    ):
        raise PackageExecutionError("complete application upstream evidence is invalid")
    return value


def _result(
    *, stage: str, media_type: str, value: Mapping[str, object]
) -> PackageExecutionResult:
    return PackageExecutionResult(
        events=({"type": f"{stage}.completed", "payload": {"status": "completed"}},),
        artifacts=({
            "artifact_id": f"dci-{stage}-result",
            "media_type": media_type,
            "value": {
                "schema": IMPLEMENTATION_PROTOCOL,
                "implementation_sha256": complete_application_identity(),
                "status": "completed",
                **value,
            },
        },),
    )


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


class DciCompleteResearchImplementation:
    async def execute(self, invocation: PackageInvocation) -> PackageExecutionResult:
        _require_local_corpus(invocation)
        question, gold = _envelope(invocation.input_text)
        try:
            required = invocation.manifest["requires_capabilities"]
            if not isinstance(required, tuple) or not all(
                isinstance(capability, str) for capability in required
            ):
                raise TypeError
            request = RunRequest(
                run_id=invocation.run_id,
                input_text=question,
                requested_capabilities=required,
            )
            events = [
                event.to_mapping()
                async for event in invocation.runtime.run(
                    request, signal=invocation.signal
                )
            ]
            validate_event_stream(events)
        except (ProtocolError, RuntimeError, TypeError, ValueError):
            raise PackageExecutionError("complete research execution failed") from None
        answer_artifacts = [
            event["payload"]["artifact"]
            for event in events
            if event.get("type") == "artifact.created"
            and isinstance(event.get("payload"), Mapping)
            and isinstance(event["payload"].get("artifact"), Mapping)
            and event["payload"]["artifact"].get("kind") == "answer"
        ]
        if len(answer_artifacts) != 1:
            raise PackageExecutionError("complete research evidence is unavailable")
        answer_artifact = answer_artifacts[0]
        answer = answer_artifact.get("uri")
        answer_artifact_id = answer_artifact.get("artifact_id")
        if answer != "final.txt" or not isinstance(answer_artifact_id, str):
            raise PackageExecutionError("complete research evidence is unavailable")
        completed_run_dir = getattr(invocation.runtime, "completed_run_dir", None)
        output_dir = (
            completed_run_dir(invocation.run_id)
            if callable(completed_run_dir)
            else None
        )
        if not isinstance(output_dir, Path):
            raise PackageExecutionError("complete research evidence is unavailable")
        try:
            final_path = output_dir / answer
            metadata = final_path.lstat()
            if (
                final_path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise OSError
            raw_answer = final_path.read_bytes()
            predicted_answer = raw_answer.decode("utf-8").rstrip("\n")
        except (OSError, UnicodeError):
            raise PackageExecutionError("complete research evidence is unavailable") from None
        if not predicted_answer:
            raise PackageExecutionError("complete research evidence is unavailable")
        stage_data = InProcessArtifactPayload(
            private_value={
                "question": question,
                "gold_answer": gold,
                "predicted_answer": predicted_answer,
                "output_dir": output_dir,
            },
            public_projection={
                "status": "completed",
                "question_sha256": _text_sha256(question),
                "gold_answer_sha256": _text_sha256(gold),
                "prediction_sha256": _text_sha256(predicted_answer),
                "evidence_sha256": hashlib.sha256(raw_answer).hexdigest(),
                "artifact_ids": (answer_artifact_id,),
            },
        )
        return _result(
            stage="research",
            media_type="application/vnd.dci.research+json",
            value={"stage_data": stage_data},
        )


def _require_local_corpus(invocation: PackageInvocation) -> Path:
    try:
        service = invocation.host_services.get("corpus.local-root")
        if not isinstance(service, LocalCorpusService):
            raise TypeError
        root = service.root
    except Exception:
        raise PackageExecutionError("local corpus service is unavailable") from None
    if not isinstance(root, Path):
        raise PackageExecutionError("local corpus service is unavailable")
    return root


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    raw = json.dumps(_plain(payload), ensure_ascii=False, indent=2).encode() + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class DciCompleteEvaluationImplementation:
    async def execute(self, invocation: PackageInvocation) -> PackageExecutionResult:
        research = _artifact(invocation, "application/vnd.dci.research+json")
        private = _research_private_value(research)
        judge = _require_answer_judge(invocation)
        try:
            identity = project_public_value(judge.public_identity)
            identity_sha256 = hashlib.sha256(
                json.dumps(
                    identity,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            verdict = await judge.judge(
                question=str(private["question"]),
                gold_answer=str(private["gold_answer"]),
                predicted_answer=str(private["predicted_answer"]),
                signal=invocation.signal,
            )
            output_dir = private["output_dir"]
            if not isinstance(output_dir, Path):
                raise TypeError
            _write_private_json(output_dir / "eval_result.json", verdict)
        except Exception:
            raise PackageExecutionError("complete evaluation failed") from None
        is_correct = verdict.get("is_correct")
        fingerprint = verdict.get("judge_request_fingerprint")
        if not isinstance(is_correct, bool) or not isinstance(fingerprint, str):
            raise PackageExecutionError("complete evaluation evidence is invalid")
        return _result(
            stage="evaluation",
            media_type="application/vnd.dci.verdict+json",
            value={
                "is_correct": is_correct,
                "judge_request_fingerprint": fingerprint,
                "judge_identity_sha256": identity_sha256,
            },
        )


def _research_private_value(
    research: Mapping[str, object],
) -> Mapping[str, object]:
    try:
        stage_data = research["stage_data"]
        if not isinstance(stage_data, InProcessArtifactPayload):
            raise TypeError
        private = stage_data.private_value
        if set(private) != {
            "question",
            "gold_answer",
            "predicted_answer",
            "output_dir",
        }:
            raise TypeError
        if (
            not all(
                isinstance(private[name], str) and private[name]
                for name in ("question", "gold_answer", "predicted_answer")
            )
            or not isinstance(private["output_dir"], Path)
        ):
            raise TypeError
        return private
    except Exception:
        raise PackageExecutionError(
            "complete evaluation evidence is unavailable"
        ) from None


def _require_answer_judge(invocation: PackageInvocation) -> AnswerJudgeService:
    try:
        service = invocation.host_services.get("evaluation.answer-judge")
        if not isinstance(service, AnswerJudgeService):
            raise TypeError
        public_identity = service.public_identity
        if not isinstance(public_identity, Mapping):
            raise TypeError
    except Exception:
        raise PackageExecutionError("answer judge service is unavailable") from None
    return service


class DciCompleteBenchmarkImplementation:
    async def execute(self, invocation: PackageInvocation) -> PackageExecutionResult:
        verdict = _artifact(invocation, "application/vnd.dci.verdict+json")
        is_correct = verdict.get("is_correct")
        if not isinstance(is_correct, bool):
            raise PackageExecutionError("complete benchmark evidence is invalid")
        return _result(
            stage="benchmark",
            media_type="application/vnd.dci.benchmark+json",
            value={"total": 1, "judged": 1, "correct": int(is_correct), "failed": 0},
        )


class DciCompleteAnalysisImplementation:
    async def execute(self, invocation: PackageInvocation) -> PackageExecutionResult:
        benchmark = _artifact(invocation, "application/vnd.dci.benchmark+json")
        correct = benchmark.get("correct")
        if type(correct) is not int or correct not in {0, 1}:
            raise PackageExecutionError("complete analysis evidence is invalid")
        aggregate = aggregate_results(({"is_correct": bool(correct), "run_status": "completed"},))
        return _result(
            stage="analysis",
            media_type="application/vnd.dci.analysis+json",
            value={"aggregate": aggregate},
        )


class DciCompleteExportImplementation:
    async def execute(self, invocation: PackageInvocation) -> PackageExecutionResult:
        analysis = _artifact(invocation, "application/vnd.dci.analysis+json")
        aggregate = analysis.get("aggregate")
        if not isinstance(aggregate, Mapping):
            raise PackageExecutionError("complete export evidence is invalid")
        digest = hashlib.sha256(
            json.dumps(_plain(aggregate), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        counts = aggregate.get("counts")
        if not isinstance(counts, Mapping) or type(counts.get("total")) is not int:
            raise PackageExecutionError("complete export evidence is invalid")
        return _result(
            stage="export",
            media_type="application/vnd.dci.export+json",
            value={"analysis_sha256": digest, "total": counts["total"]},
        )


def complete_dci_bindings() -> tuple[tuple[object, object], ...]:
    from asterion.packages.catalog import PackageRef

    return (
        (PackageRef("dci.research", "1.0.0"), DciCompleteResearchImplementation()),
        (PackageRef("dci.evaluation", "1.0.0"), DciCompleteEvaluationImplementation()),
        (PackageRef("dci.benchmark", "1.0.0"), DciCompleteBenchmarkImplementation()),
        (PackageRef("dci.analysis", "1.0.0"), DciCompleteAnalysisImplementation()),
        (PackageRef("dci.export", "1.0.0"), DciCompleteExportImplementation()),
    )


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
