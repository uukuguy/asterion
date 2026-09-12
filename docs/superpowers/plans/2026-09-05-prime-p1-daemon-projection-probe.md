# Prime P1 Docker Daemon Projection Probe Plan

Goal: Implement an authority-private async fake-daemon-testable Docker /version projection check on AdmittedPrimeP1DockerSocket, without wiring it to readiness or real Docker.

Constraints:

- Private API only: async _verify_daemon_projection(deadline: float) on exact admitted socket and aggregate delegator. No public path/FD/version/projection accessor.
- Fresh AF_UNIX SOCK_STREAM CLOEXEC NONBLOCK client. Fixed GET /version HTTP/1.1 request; absolute monotonic deadline, cancellation cleanup, one concurrent probe only.
- Revalidate socket path before connect, after connect, and before success. Client closes exactly once in every path.
- Strict bounded parser: 16KiB response, 4KiB headers, exact HTTP/1.1 200, CRLF, application/json, one CL or chunked framing, EOF required; strict UTF-8 JSON, no duplicate keys/NaN/trailing data; exact Version and ApiVersion compare against private config.
- Only fake Unix server tests; no real Docker connection, spawn, readiness, CLI, protocol, receipt, or basic changes.

### Task 1: Implement private daemon projection probe

Files:

- Modify src/asterion/applications/prime_agent/operator/authority_docker_socket.py
- Modify src/asterion/applications/prime_agent/operator/authority_resources.py
- Modify tests/test_prime_p1_authority_docker_socket.py
- Modify tests/test_prime_p1_authority_resources.py

Steps:

- [ ] Write async failing tests first using a fake Unix listener: fragmented Content-Length/chunked success and exact request bytes; extra fields accepted; version mismatch/missing/wrong type; framing and strict JSON failures; pre/post/pre-success revalidation races; concurrent/closed/cancel/deadline client cleanup; aggregate delegator redaction/type behavior. Assert static admission/ready/preflight never call probe.
- [ ] Observe RED before implementation.
- [ ] Implement bounded fixed request, lifecycle state, parser, no-context redacted errors, and aggregate exact-child delegator.
- [ ] Run focused socket/resource/process tests plus Ruff/diff. No real Docker.
- [ ] Commit focused files then independent security review.

Self-review: Passing fake-daemon probe is unit verification only; native Docker qualification remains separately authorized and basic stays unavailable.

