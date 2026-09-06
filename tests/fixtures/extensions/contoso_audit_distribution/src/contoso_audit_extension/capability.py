import os
from importlib import metadata
from pathlib import Path
from asterion.capability_sdk import (
    CapabilityExecutionResult,
    CapabilityImplementationBinding,
    CapabilityInvocation,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


class Audit:
    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        _count("execute")
        if (
            len(invocation.upstream_events) != 1
            or invocation.upstream_events[0]
            != {"type": "acme.research.completed", "payload": {"status": "completed"}}
            or len(invocation.upstream_artifacts) != 1
            or invocation.upstream_artifacts[0].get("artifact_id")
            != "acme-research-result"
            or invocation.upstream_artifacts[0].get("media_type")
            != "application/vnd.acme.research+json"
            or invocation.upstream_artifacts[0].get("value") != {"status": "completed"}
        ):
            raise ValueError("acme result is invalid")
        return CapabilityExecutionResult(
            events=(
                {"type": "contoso.audit.completed", "payload": {"status": "completed"}},
            ),
            artifacts=(
                {
                    "artifact_id": "contoso-audit-result",
                    "media_type": "application/vnd.contoso.audit+json",
                    "value": {"status": "completed"},
                },
            ),
        )


def create_package() -> InstalledCapabilityPackage:
    _count("package")
    p = Path(
        str(
            metadata.distribution("asterion-contoso-audit-extension").locate_file(
                "asterion_capability_packages/contoso.audit/1.0.0/payload"
            )
        )
    ).resolve()
    x = open_portable_payload(p)
    return InstalledCapabilityPackage(
        CapabilityPackageRef("contoso.audit", "1.0.0"),
        x.payload_sha256,
        "contoso.audit.python-distribution",
        "python-distribution",
        (p / "capabilities",),
        (),
        (
            CapabilityImplementationBinding(
                CapabilityRef("contoso.audit-record", "1.0.0"), Audit()
            ),
        ),
        (),
    )


def _count(name: str) -> None:
    path = os.environ.get("CONTOSO_COUNT_FILE")
    if path:
        with Path(path).open("a", encoding="utf-8") as output:
            output.write(name + "\n")
