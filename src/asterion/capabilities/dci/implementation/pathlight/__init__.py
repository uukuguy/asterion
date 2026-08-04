"""Safe Pathlight recovery of historical DCI evidence."""

from .recovery import (
    DciRecoveredCase,
    DciRecoveredRun,
    DciRecoveredVariant,
    DciRecoveryError,
    DCI_RECOVERY_FILENAME,
    read_recovered_run,
    read_completed_dci_run,
    validate_recovered_run,
    write_recovered_run,
)
from .conversion import (
    DciConversionError,
    DciReferenceComparison,
    load_paper_reference,
    recovered_run_to_experiment,
    recovered_run_to_evaluation_bundle,
)
from .diagnosis import (
    DciAggregateWorkflowMetrics,
    DciComponentComparison,
    DciDatasetObservation,
    DciDiagnosisError,
    DciDiagnosisReport,
    DciProposalSummary,
    DciWorkflowMetrics,
    diagnose_recommended_pack,
    render_chinese_diagnosis,
)
from .provider_call_recovery import (
    DciProviderCallRecoveryError,
    recover_provider_call_companion,
)
from .optimization import (
    BRIGHT_OPTIMIZATION_CRITERIA,
    BrightNativeBatch,
    BrightOptimizationClosure,
    DciBrightOptimizationError,
    finalize_bright_optimization,
    read_native_case_lineage,
    render_bright_optimization_chinese,
)

__all__ = (
    "DciRecoveredCase",
    "DciRecoveredRun",
    "DciRecoveredVariant",
    "DciRecoveryError",
    "DCI_RECOVERY_FILENAME",
    "DciConversionError",
    "DciReferenceComparison",
    "read_completed_dci_run",
    "read_recovered_run",
    "validate_recovered_run",
    "write_recovered_run",
    "load_paper_reference",
    "recovered_run_to_experiment",
    "recovered_run_to_evaluation_bundle",
    "DciComponentComparison",
    "DciAggregateWorkflowMetrics",
    "DciDatasetObservation",
    "DciDiagnosisError",
    "DciDiagnosisReport",
    "DciProposalSummary",
    "DciWorkflowMetrics",
    "diagnose_recommended_pack",
    "render_chinese_diagnosis",
    "DciProviderCallRecoveryError",
    "recover_provider_call_companion",
    "BRIGHT_OPTIMIZATION_CRITERIA",
    "BrightNativeBatch",
    "BrightOptimizationClosure",
    "DciBrightOptimizationError",
    "finalize_bright_optimization",
    "read_native_case_lineage",
    "render_bright_optimization_chinese",
)
