# Task 1 report: Prime P1 fixed application-resource admission

## Scope delivered

- Added `authority_application_resources.py`, an opaque, idempotently closeable
  admission proof for the exact eight P1 application inputs.
- Added the canonical packaged descriptor
  `resources/prime-p1-application-resource-lock.json`.  It accepts only the
  locked protocol, exact identity key set, exact contract identities, and the
  fixed ordered resource paths/digests.
- Implemented bounded descriptor-relative no-follow reads with pre/post `fstat`
  identity checks, regular/single-link/non-writable checks, and constant-time
  SHA-256 comparisons.  Rejections use only
  `PrimeP1AuthorityResourceError` without retained exception context.
- Added the child to production aggregate admission directly after authority
  artifacts and before static/Docker-related admission.  It is exact-type
  checked and closed once in reverse acquisition order.
- Added the verifier to the authority artifact lock and updated affected lock
  digests.

## TDD evidence

RED was run before the verifier existed:

```text
uv run python -m unittest -v tests.test_prime_p1_authority_application_resources tests.test_prime_p1_authority_resources
ModuleNotFoundError: No module named 'asterion.applications.prime_agent.operator.authority_application_resources'
```

GREEN verification after implementation:

```text
uv run python -m unittest -v tests.test_prime_p1_authority_application_resources tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_process tests.test_prime_p1_authority_docker_socket
Ran 87 tests in 2.478s
OK (skipped=2)

uv run ruff check src/asterion/applications/prime_agent/operator/authority_application_resources.py src/asterion/applications/prime_agent/operator/authority_resources.py src/asterion/applications/prime_agent/operator/authority_artifact_lock.py tests/test_prime_p1_authority_application_resources.py tests/test_prime_p1_authority_resources.py
All checks passed!

git diff --check
exit 0
```

The two skips are platform-specific existing tests for unavailable Linux atomic
socket/SCM_RIGHTS facilities, not application-resource tests.

## Safety and limits

No Docker, network, subprocess, model, readiness, or execution operation was
performed.  This is static resource admission only and does not make a
production claim.

During focused verification, one authority-process test exposed global mocking
of `os.close`; the verifier now captures the close primitive at import time,
matching the existing artifact-lock verifier and preserving descriptor cleanup
test isolation.

## Review-fix evidence (2026-09-05)

- RED: the added lexical-order assertions failed before the fix because both
  declared tuples were non-lexical. The application tuple put capability paths
  before application image paths; the artifact tuple put
  `authority_artifact_lock.py` before
  `authority_application_resources.py`.
- GREEN:

```text
uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock tests.test_prime_p1_authority_application_resources tests.test_prime_p1_authority_request_contract tests.test_prime_p1_authority_resources
Ran 41 tests in 0.069s
OK

uv run ruff check src/asterion/applications/prime_agent/operator/authority_application_resources.py src/asterion/applications/prime_agent/operator/authority_artifact_lock.py tests/test_prime_p1_authority_application_resources.py tests/test_prime_p1_authority_resources.py
All checks passed!

authority artifact digests: verified
git diff --check
exit 0
```

- Regression coverage now asserts sorted code/JSON paths, descriptor schema,
  identity, and digest mutation rejection, hardlink creation during a read,
  and aggregate acquisition/cleanup ordering with the application child
  immediately after/before the artifact child respectively.
