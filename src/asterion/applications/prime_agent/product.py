"""Provider-free product metadata and verification for Prime P1."""

from __future__ import annotations

from asterion.applications.product import (
    CapabilityFunction,
    CapabilityProductDescription,
    ConfigurationRequirement,
    InstalledCapabilityProduct,
    VerificationCheckResult,
    VerificationProfile,
    VerificationRequest,
    VerificationResult,
)
from asterion.applications.prime_agent.coding_fixture_receipt import (
    CodingFixtureObservation,
    CodingFixtureWitness,
    verify_prime_coding_fixture_receipt,
)
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerReceipt,
)
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt
from asterion.services.bounded_model_session import BoundedModelSessionRequest


_PRODUCT_ID = "prime.ipython-coding"
_CHALLENGE_DIGEST = "sha256:" + "a" * 64
_IMAGE_DIGEST = "sha256:" + "b" * 64
_WORKLOAD_DIGEST = "sha256:" + "c" * 64
_RESULT_DIGEST = "sha256:" + "d" * 64


PRIME_PRODUCT_DESCRIPTION = CapabilityProductDescription(
    product_id=_PRODUCT_ID,
    version="1.0.0",
    summary="Prime IPython coding provider-free fixture verification",
    functions=(
        CapabilityFunction(
            function_id="verify",
            summary="Verify the fixed IPython coding fixture",
            argv=(
                "asterion",
                "verify",
                "--provider",
                "prime-agent",
                "--level",
                "acceptance",
            ),
        ),
    ),
    configuration=(
        ConfigurationRequirement(
            name="PRIME_PRODUCT_AUTHORITY",
            purpose="Operator authorization for bounded verification",
            required_for=("basic",),
            secret=False,
            default=None,
            hint="Bounded verification remains unavailable until authority is supplied",
        ),
    ),
    profiles=(
        VerificationProfile(
            level="acceptance",
            summary="Validate the fixed provider-free IPython coding receipt",
            cost_class="provider-free",
            provider_backed_operation_count=0,
            full_dataset=False,
        ),
        VerificationProfile(
            level="basic",
            summary="Bounded provider verification is unavailable pending authority",
            cost_class="bounded-provider-backed",
            provider_backed_operation_count=0,
            full_dataset=False,
        ),
        VerificationProfile(
            level="preflight",
            summary="Check the fixed provider-free fixture contract",
            cost_class="provider-free",
            provider_backed_operation_count=0,
            full_dataset=False,
        ),
    ),
)


def _fixture_observation() -> CodingFixtureObservation:
    """Return the closed, body-free P1 fixture input without host interaction."""

    return CodingFixtureObservation(
        built_in_tools=("ipython",),
        model_tool_calls=("ipython", "ipython"),
        turn_count=2,
        compaction_turn=1,
        session_id="session-1",
        kernel_generation="kernel-1",
        image_digest=_IMAGE_DIGEST,
        witnesses=(
            CodingFixtureWitness("session-1", "kernel-1", 2, "cwd"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "function"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "import"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "namespace"),
            CodingFixtureWitness("session-1", "kernel-1", 2, "workspace-file"),
        ),
        child_session_opened=False,
        other_action_taken=False,
        oracle_initially_failed=True,
        oracle_eventually_passed=True,
        session_limits=BoundedModelSessionRequest(
            run_id="run-1",
            max_requests=2,
            max_input_tokens=32,
            max_output_tokens=32,
            max_input_bytes=32,
            max_output_bytes=32,
            max_cost_microunits=32,
            deadline_seconds=30,
        ),
        broker_receipt=PrimeModelBrokerReceipt(
            session_id="session-1",
            run_id="run-1",
            worker_id="worker-1",
            challenge_digest=_CHALLENGE_DIGEST,
            request_count=2,
            input_bytes=16,
            output_bytes=24,
            status="revoked",
        ),
        worker_receipt=PrimeWorkerBoundaryReceipt._admit(
            scenario_id="prime.ipython-coding/v1",
            role_id="prime.ipython-coding",
            worker_id="worker-1",
            run_id="run-1",
            challenge_digest=_CHALLENGE_DIGEST,
            workload_digest=_WORKLOAD_DIGEST,
            result_digest=_RESULT_DIGEST,
            image_digest=_IMAGE_DIGEST,
        ),
    )


def _result(level: str, status: str, check_id: str, summary: str) -> VerificationResult:
    return VerificationResult(
        product_id=_PRODUCT_ID,
        level=level,
        status=status,
        checks=(
            VerificationCheckResult(
                check_id=check_id,
                summary=summary,
                status=status,
            ),
        ),
        provider_backed_operation_count=0,
        full_dataset_ran=False,
    )


def verify_prime_product(request: VerificationRequest) -> VerificationResult:
    """Verify only the P1 provider-free fixture; never invoke a host or provider."""

    if request.level == "basic":
        return _result(
            "basic", "NOT RUN", "authority", "Bounded verification is unavailable"
        )
    try:
        receipt = verify_prime_coding_fixture_receipt(_fixture_observation())
    except (TypeError, ValueError):
        return _result(
            request.level,
            "FAIL",
            "fixture-contract" if request.level == "preflight" else "coding-fixture",
            "Provider-free fixture verification failed",
        )
    if receipt.scenario_id != "prime.ipython-coding/v1" or receipt.status != "PASS":
        return _result(
            request.level,
            "FAIL",
            "fixture-contract" if request.level == "preflight" else "coding-fixture",
            "Provider-free fixture verification failed",
        )
    if request.level == "preflight":
        return _result(
            "preflight", "PASS", "fixture-contract", "Fixture contract is valid"
        )
    return _result(
        "acceptance", "PASS", "coding-fixture", "IPython coding fixture is valid"
    )


def create_prime_product() -> InstalledCapabilityProduct:
    """Build the immutable Prime P1 product without verification side effects."""

    return InstalledCapabilityProduct(
        description=PRIME_PRODUCT_DESCRIPTION,
        verifier=verify_prime_product,
    )
