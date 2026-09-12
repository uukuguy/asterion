# Prime P1 Docker Socket Contract Implementation Plan

Goal: Extend private Prime P1 operator config with exact Docker socket policy and expected server projection, without connecting Docker.

Architecture: The closed service-manager config is sole source of socket ownership/mode and expected daemon version. Parsing is platform-neutral and private. Linux socket admission is a later task; no manifest, protocol, receipt, CLI, or product output gets these values.

## Global Constraints

- Add exactly five private keys: ASTERION_PRIME_P1_DOCKER_SOCKET_OWNER_UID, ASTERION_PRIME_P1_DOCKER_SOCKET_GROUP_GID, ASTERION_PRIME_P1_DOCKER_SOCKET_MODE, ASTERION_PRIME_P1_DOCKER_SERVER_API_VERSION, ASTERION_PRIME_P1_DOCKER_SERVER_VERSION.
- UID/GID: decimal 0..4294967294 with no leading zero except 0. Mode: 0600 or 0660. API version: bounded canonical decimal.decimal. Server version: safe ASCII token, 1..64 chars.
- No defaults, host inference, environment, manifest, receipt, or CLI knobs. No Docker connect/spawn/model/network/basic change.

---

### Task 1: Parse the closed Docker socket policy contract

Files:

- Modify: src/asterion/applications/prime_agent/operator/authority_config.py
- Modify: tests/test_prime_p1_operator_config.py
- Modify existing Prime P1 config fixtures in authority resources, seccomp, process, and receipt tests.

Interfaces:

- PrimeP1OperatorConfig remains opaque. Its private mapping holds new values only after exact parse.
- load_operator_config rejects any missing/extra field or malformed socket policy/version as PrimeP1OperatorConfigError.

- [ ] Step 1: Write failing tests.

Add a subTest matrix for each new field: UID/GID leading zero, negative, overflow; mode 0644/0666/short; API missing dot, leading zero, extra component; server version empty, >64, whitespace/control. For every of five keys delete it from otherwise-valid bytes and assert config load fails. Update valid fixture only after RED is observed.

- [ ] Step 2: Verify RED.

Run: uv run python -m unittest -v tests.test_prime_p1_operator_config

Expected: current legacy valid fixture passes without the five required fields.

- [ ] Step 3: Minimal implementation.

Add exact keys to closed _KEYS. Add tight validators under authority_config.py and call them from _parse_verified_bytes. Store raw canonical strings privately. Do not expose an accessor. Update every config fixture with canonical owner UID 0, group GID 0, mode 0600, API 1.41, server version 26.1.4.

- [ ] Step 4: Verify GREEN.

Run focused operator-config, authority resource/seccomp/process/receipt tests; Ruff authority_config plus test; diff check.

- [ ] Step 5: Commit.

Commit only authority_config and affected config fixture tests with message Add Prime P1 Docker socket policy contract.

## Self-Review

This is a private closed-schema contract only. It makes later socket trust explicit without admitting, connecting, or using a daemon. Parser redaction and reject-extra semantics remain mandatory.

## Execution Handoff

Execute Task 1 with Terra, then independent Sol contract review before socket admission.
