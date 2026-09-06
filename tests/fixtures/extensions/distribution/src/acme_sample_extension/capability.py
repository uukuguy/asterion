"""Selected capability package for the public-extension reference."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

from asterion.application_sdk import RunRequest, parse_event_stream
from asterion.capability_sdk import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


PACKAGE_REF = CapabilityPackageRef("acme.sample", "1.0.0")
_PAYLOAD_ROOT = "asterion_capability_packages/acme.sample/1.0.0/payload"


if os.environ.get("ASTERION_TEST_FORBID_CAPABILITY_IMPORT") == "1":
    raise RuntimeError("acme capability provider imported")


class _ResearchImplementation:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        request = RunRequest(
            invocation.run_id,
            invocation.input_text,
            (),
        )
        events = [
            event
            async for event in invocation.runtime.run(request, signal=invocation.signal)
        ]
        parsed = parse_event_stream(event.to_mapping() for event in events)
        if (
            len(parsed) != 3
            or tuple(event.type for event in parsed)
            != ("run.started", "text.delta", "run.completed")
            or parsed[0].payload != {"capabilities": []}
            or not isinstance(parsed[1].payload.get("text"), str)
            or not parsed[1].payload["text"]
            or parsed[2].payload != {"status": "completed"}
        ):
            raise CapabilityExecutionError("acme runtime event stream is invalid")
        return CapabilityExecutionResult(
            events=(
                {"type": "acme.research.completed", "payload": {"status": "completed"}},
            ),
            artifacts=(
                {
                    "artifact_id": "acme-research-result",
                    "media_type": "application/vnd.acme.research+json",
                    "value": {"status": "completed"},
                },
            ),
        )


def create_package() -> InstalledCapabilityPackage:
    distribution = metadata.distribution("asterion-acme-sample-extension")
    payload_root = Path(str(distribution.locate_file(_PAYLOAD_ROOT))).resolve()
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="acme.sample.python-distribution",
        source_kind="python-distribution",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=(
            CapabilityImplementationBinding(
                CapabilityRef("acme.research", "1.0.0"), _ResearchImplementation()
            ),
        ),
        benchmark_bindings=(),
    )
