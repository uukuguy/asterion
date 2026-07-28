"""Framework binding assembly for transitional DCI implementations."""

from asterion.capabilities.dci.implementation.complete import (
    DciCompleteAnalysisImplementation,
    DciCompleteBenchmarkImplementation,
    DciCompleteEvaluationImplementation,
    DciCompleteExportImplementation,
    DciResearchImplementation,
)
from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_sdk import CapabilityRef


def complete_dci_bindings() -> tuple[CapabilityImplementationBinding, ...]:
    """Return exact executable bindings for the complete DCI graph."""

    return (
        CapabilityImplementationBinding(
            CapabilityRef("dci.research", "1.0.0"),
            DciResearchImplementation(),
        ),
        CapabilityImplementationBinding(
            CapabilityRef("dci.evaluation", "1.0.0"),
            DciCompleteEvaluationImplementation(),
        ),
        CapabilityImplementationBinding(
            CapabilityRef("dci.benchmark", "1.0.0"),
            DciCompleteBenchmarkImplementation(),
        ),
        CapabilityImplementationBinding(
            CapabilityRef("dci.analysis", "1.0.0"),
            DciCompleteAnalysisImplementation(),
        ),
        CapabilityImplementationBinding(
            CapabilityRef("dci.export", "1.0.0"),
            DciCompleteExportImplementation(),
        ),
    )
