# Prime P1 Docker Socket Admission Plan

Goal: Admit the configured Docker Unix socket as opaque Linux authority resource without connecting it.

Constraints:

- Linux-only at invocation; imports stay platform neutral. No Docker connect/spawn/model/network/ready/basic changes.
- Walk an absolute canonical socket path descriptor-relatively from slash. Reject empty, dot, parent, symlink, abstract, and unsafe ancestor components.
- Final must be a Unix socket with exact configured UID/GID/mode. Record device/inode/mode/uid/gid and retain parent FD. Revalidation repeats chain and final child checks. All errors/reprs redacted.
- Exact type/token, noncopy/pickle, lock-protected exact-once close. No public path/FD/policy/projection accessor.

### Task 1: Static socket path admission

Files:

- Create src/asterion/applications/prime_agent/operator/authority_docker_socket.py
- Create tests/test_prime_p1_authority_docker_socket.py

Interfaces:

- admit_docker_socket(config: object) -> AdmittedPrimeP1DockerSocket
- AdmittedPrimeP1DockerSocket.revalidate_path() -> None and close() -> None

Steps:

- [ ] Add failing tests first: wrong config/non-Linux, relative/noncanonical/symlink/writable ancestor, regular/final symlink, UID/GID/mode mismatch, closed/replaced resource, redaction and exact-once close. Patch socket/connect/subprocess to fail if called.
- [ ] Verify RED via focused unittest import failure.
- [ ] Implement descriptor-relative parent walk with no-follow directory opens, final dir_fd stat without following links, exact policy/identity snapshot, retained parent FD and lock-protected revalidation/close.
- [ ] Verify focused unittest/Ruff/diff; no external operation.
- [ ] Commit implementation/test only.

Self-review: API/server version values may be parsed and privately retained but no dynamic daemon projection comparison happens until separately authorized connect slice.

### Task 2: Bind the socket into production aggregate

Files:

- Modify src/asterion/applications/prime_agent/operator/authority_resources.py
- Modify tests/test_prime_p1_authority_resources.py

Requirements:

- Import and admit exact AdmittedPrimeP1DockerSocket after exact static, evidence, and Docker executable admission.
- Extend AdmittedProductionAuthorityResources construction, slots, exact type checks, transfer, and close to own four children.
- On any partial/constructor failure close acquired exact children socket, executable, evidence, static; direct constructor rejection must not consume caller children.
- Add RED-first tests for socket lookalike/subclass rejection, socket admission failure, constructor failure and concurrent exact-once reverse close. Process tests must still prove unavailable and no connect/spawn.
- Run resource/socket/evidence/executable/process focused tests, Ruff, diff check; commit only aggregate source/test.
