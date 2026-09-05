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

## Review-fix evidence: aggregate admission order (2026-09-05)

- RED: before wiring admission mock side effects, the strengthened lifecycle
  assertion observed only reverse cleanup order and failed against the expected
  acquisition-plus-cleanup sequence.
- GREEN:

```text
uv run python -m unittest -v tests.test_prime_p1_authority_resources
Ran 26 tests in 0.061s
OK

uv run ruff check tests/test_prime_p1_authority_resources.py
All checks passed!

git diff --check
exit 0
```

The aggregate lifecycle test now records and asserts exact acquisition order
`artifacts, application, static, evidence, docker, socket`, followed by the
existing reverse close order. This specifically rejects swapping artifacts /
application or application / static.

## Resource-set identity delivery (2026-09-05)

### Scope delivered

- Added the private `AdmittedProductionAuthorityResources._resource_set_sha256()`
  aggregate. It requires the exact six admitted child types, rejects closed or
  substituted children, performs the Docker executable's retained-FD/byte
  revalidation and the Docker socket's descriptor-relative path revalidation
  before returning a digest, and redacts every failure as
  `PrimeP1AuthorityResourceError`.
- Bound all six existing retained private identities: authority artifact
  descriptor, application-resource descriptor, static image/seccomp resource,
  evidence-root FD inode, Docker executable identity plus byte digest, and
  Docker socket parent/socket identities plus its expected daemon version
  projection. No configured path, descriptor text, credential, prompt, or
  model output contributes to or is exposed by the digest.
- Encoding is SHA-256 over the fixed domain
  `asterion.prime-p1.resource-set/v1\\0`, followed by six fixed-order,
  length-delimited typed contributions. Each child contribution encodes sorted,
  unique field names and length-delimited field values.
- Refreshed the packaged authority artifact descriptor hashes after source
  stabilization; descriptor admission passes with the new source set.

### TDD evidence

RED was observed before implementation:

```text
uv run python -m unittest -v tests.test_prime_p1_resource_set_identity
ERROR: AdmittedProductionAuthorityResources has no attribute
_resource_set_sha256; exact child classes have no
_resource_set_contribution.
```

GREEN and focused regression verification:

```text
uv run ruff check src/asterion/applications/prime_agent/operator/authority_resources.py src/asterion/applications/prime_agent/operator/authority_artifact_lock.py src/asterion/applications/prime_agent/operator/authority_application_resources.py src/asterion/applications/prime_agent/operator/authority_evidence.py src/asterion/applications/prime_agent/operator/authority_docker_executable.py src/asterion/applications/prime_agent/operator/authority_docker_socket.py tests/test_prime_p1_authority_resources.py tests/test_prime_p1_resource_set_identity.py
All checks passed!

uv run python -m unittest -v tests.test_prime_p1_resource_set_identity tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_artifact_lock tests.test_prime_p1_authority_application_resources tests.test_prime_p1_authority_docker_executable tests.test_prime_p1_authority_docker_socket
Ran 71 tests in 2.377s
OK (skipped=1)

git diff --check
exit 0
```

The one skip is the existing platform-specific atomic-Linux-socket test.

### Safety and limits

## Resource-set identity review fix (2026-09-05)

- `authority_version` is now retained by the authority-artifact descriptor and
  included in its canonical identity input. A version-only descriptor mutation
  changes the admitted artifact identity.
- Resource-set assembly now collects and validates all six exact child
  contributions first; Docker executable and socket revalidation occur only
  immediately before the final SHA-256 computation. The socket contribution
  also path-revalidates, so a retained parent descriptor cannot mask a replaced
  socket path during contribution collection.
- The resource-set tests now use genuine exact child objects and contribution
  methods (with only the path revalidation seam suppressed where no real Docker
  socket is admitted). They cover every child closing, retained identity-value
  changes, final revalidation order, and isolated Docker/socket revalidation
  failures. This detects the previously omitted `authority_version`.

### TDD and verification evidence

RED, before the descriptor change:

```text
TypeError: _Descriptor.__init__() takes 2 positional arguments but 3 were given
```

GREEN:

```text
uv run python -m unittest -v tests.test_prime_p1_resource_set_identity
Ran 5 tests in 0.008s
OK

uv run python -m unittest -v tests.test_prime_p1_resource_set_identity \
  tests.test_prime_p1_authority_artifact_lock \
  tests.test_prime_p1_authority_docker_socket \
  tests.test_prime_p1_authority_docker_executable \
  tests.test_prime_p1_authority_resources
Ran 67 tests in 2.503s
OK (skipped=1: existing platform-specific atomic socket flag test)

uv run ruff check src/asterion/applications/prime_agent/operator/authority_artifact_lock.py \
  src/asterion/applications/prime_agent/operator/authority_resources.py \
  src/asterion/applications/prime_agent/operator/authority_docker_socket.py \
  tests/test_prime_p1_resource_set_identity.py
All checks passed!

git diff --check
exit 0
```

The authority-artifact descriptor hashes were refreshed after sources
stabilized. No Docker connection, daemon probe, network, subprocess, model,
readiness, or execution action was performed.

No Docker connection, daemon projection probe, subprocess, network request,
model invocation, readiness frame, execute request, or production claim was
performed. The new identity operation is a static retained-resource check;
later authority-process work must decide when it is consumed.
