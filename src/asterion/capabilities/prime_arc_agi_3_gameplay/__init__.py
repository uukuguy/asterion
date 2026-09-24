"""Independent scoreless ARC-AGI-3 gameplay capability package."""

from .host import (
    PrimeArcAgi3GameplayEvidence,
    PrimeArcAgi3GameplayEvidenceAccessor,
    PrimeArcAgi3GameplayEvidenceError,
    canonical_gameplay_evidence_sha256,
    validate_prime_arc_agi_3_gameplay_evidence,
)
from .provider import create_prime_arc_agi_3_gameplay_package

__all__ = (
    "PrimeArcAgi3GameplayEvidence",
    "PrimeArcAgi3GameplayEvidenceAccessor",
    "PrimeArcAgi3GameplayEvidenceError",
    "canonical_gameplay_evidence_sha256",
    "validate_prime_arc_agi_3_gameplay_evidence",
    "create_prime_arc_agi_3_gameplay_package",
)
