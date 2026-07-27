"""Framework binding assembly for controlled-code implementations."""

from asterion.capabilities.controlled_code.implementation import (
    CodeQualityEvaluationImplementation,
    CodeQualityWorkflowImplementation,
    ExecutionAuditImplementation,
)
from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_sdk import CapabilityRef


def controlled_code_bindings() -> tuple[CapabilityImplementationBinding, ...]:
    """Return exact executable bindings for the controlled-code graph."""

    return (
        CapabilityImplementationBinding(
            capability_ref=CapabilityRef("workflow.code-quality", "1.0.0"),
            implementation=CodeQualityWorkflowImplementation(),
        ),
        CapabilityImplementationBinding(
            capability_ref=CapabilityRef("evaluation.code-quality", "1.0.0"),
            implementation=CodeQualityEvaluationImplementation(),
        ),
        CapabilityImplementationBinding(
            capability_ref=CapabilityRef("observability.execution-audit", "1.0.0"),
            implementation=ExecutionAuditImplementation(),
        ),
    )
