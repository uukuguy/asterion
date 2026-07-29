"""Deterministic implementations for the controlled-code application graph."""

from __future__ import annotations

from collections.abc import Mapping

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.services.controlled_executor import ControlledExecutionRequest


REPORT_MEDIA_TYPE = "application/vnd.dci.code-quality+json"


class CodeQualityWorkflowImplementation:
    async def execute(self, invocation: CapabilityInvocation) -> CapabilityExecutionResult:
        service = invocation.host_services.get("executor.controlled")
        execute = getattr(service, "execute", None)
        if not callable(execute):
            raise CapabilityExecutionError("controlled executor service is invalid")
        result = await execute(
            ControlledExecutionRequest(invocation.input_text), signal=invocation.signal
        )
        report = {
            "status": result.status,
            "exit_code": result.exit_code,
            "stdout_bytes": result.stdout_bytes,
            "stderr_bytes": result.stderr_bytes,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
            "duration_ms": result.duration_ms,
            "failure_class": result.failure_class,
        }
        return CapabilityExecutionResult(
            events=(
                {
                    "type": "workflow.code-quality.completed",
                    "payload": {"status": result.status},
                },
            ),
            artifacts=(
                {
                    "artifact_id": "code-quality-report",
                    "media_type": REPORT_MEDIA_TYPE,
                    "value": report,
                },
            ),
        )


class CodeQualityEvaluationImplementation:
    async def execute(self, invocation: CapabilityInvocation) -> CapabilityExecutionResult:
        report = _report(invocation)
        passed = report.get("status") == "succeeded" and report.get("exit_code") == 0
        return CapabilityExecutionResult(
            events=(),
            artifacts=(
                {
                    "artifact_id": "code-quality-verdict",
                    "media_type": "application/vnd.dci.code-quality-verdict+json",
                    "value": {"passed": passed, "status": report.get("status")},
                },
            ),
        )


class ExecutionAuditImplementation:
    async def execute(self, invocation: CapabilityInvocation) -> CapabilityExecutionResult:
        report = _report(invocation)
        return CapabilityExecutionResult(
            events=(
                {
                    "type": "audit.execution-recorded",
                    "payload": {"status": report.get("status")},
                },
            ),
            artifacts=(
                {
                    "artifact_id": "execution-audit",
                    "media_type": "application/vnd.dci.execution-audit+json",
                    "value": {
                        key: report.get(key)
                        for key in (
                            "status",
                            "exit_code",
                            "stdout_bytes",
                            "stderr_bytes",
                            "stdout_truncated",
                            "stderr_truncated",
                            "duration_ms",
                            "failure_class",
                        )
                    },
                },
            ),
        )


def controlled_code_bindings():
    """Return exact executable bindings for the controlled-code graph."""

    return (
        (
            CapabilityRef("workflow.code-quality", "1.0.0"),
            CodeQualityWorkflowImplementation(),
        ),
        (
            CapabilityRef("evaluation.code-quality", "1.0.0"),
            CodeQualityEvaluationImplementation(),
        ),
        (
            CapabilityRef("observability.execution-audit", "1.0.0"),
            ExecutionAuditImplementation(),
        ),
    )


def _report(invocation: CapabilityInvocation) -> Mapping[str, object]:
    matches = tuple(
        artifact["value"]
        for artifact in invocation.upstream_artifacts
        if artifact.get("media_type") == REPORT_MEDIA_TYPE
        and isinstance(artifact.get("value"), Mapping)
    )
    if len(matches) != 1:
        raise CapabilityExecutionError("controlled-code report is unavailable")
    return matches[0]
