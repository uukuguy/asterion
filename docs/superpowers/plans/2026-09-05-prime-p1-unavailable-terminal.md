# Prime P1 Signed Unavailable Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After one authenticated Prime P1 execute frame, emit one authority-signed `UNAVAILABLE` terminal frame without exposing a receipt key or granting execution.

**Architecture:** `authority_receipt.py` remains the sole owner of the receipt HMAC and can issue only an unavailable receipt from private, immutable authority bindings. `authority_protocol.py` owns IPC sequencing and can only consume a one-use issued receipt whose session/run/application/resource bindings match. Production wiring stays disabled until admission produces all authoritative identity material; neither task calls Docker, a provider, a network service, or a subprocess.

**Tech Stack:** Python 3.12, `unittest`, canonical JSON/HMAC already implemented by `authority_protocol.py`.

## Global Constraints

- No raw receipt key, generic signer, mutable receipt mapping, prompt, provider payload, or path may cross the authority receipt boundary.
- The only new status/reason pair is `UNAVAILABLE` / `unavailable`; it must encode zero execution facts and cannot represent PASS.
- Tests are representative development-boundary checks: custody/one-use, binding mismatch, happy IPC state sequence, and cleanup/no-external-effect. Do not exhaust every field permutation.
- Existing production process remains unavailable until real authority executable/config/application identity material exists. Never manufacture zero, fixture, or arbitrary hashes as production material.
- Refresh the packaged authority artifact lock whenever any authority source module changes.

### Task 1: One-use opaque unavailable receipt issuer

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_receipt.py`
- Modify: `tests/test_prime_p1_authority_receipt.py`

**Interfaces:**

- Consumes: `_AuthorityReceiptIssuer` and its private `WeakKeyDictionary` custody from `authority_receipt.py`.
- Produces: private immutable `_AuthorityTerminalBinding`, `_UnavailableReceiptMaterial`, and `_IssuedAuthorityReceipt`; `_issue_unavailable_receipt(issuer, binding, material)` consumes an issuer once and returns an immutable one-use receipt carrying only an exact unavailable terminal payload.

- [ ] **Step 1: Write failing custody and one-use tests.**

  Add a test that creates an issuer through `_new_authority_receipt_issuer`, gives it valid private binding/material fixtures, issues one receipt, and asserts: its private payload has `UNAVAILABLE`/`unavailable`, zero worker/model/tool counts and false success booleans; the issuer and result render redacted; a second issue attempt raises the public-safe error. Add one representative altered binding/material rejection and assert neither sentinel key nor config secret appears in the exception. HMAC verification through `SupervisorSession` belongs to Task 2, where a valid session state exists.

- [ ] **Step 2: Run RED.**

  Run: `uv run python -m unittest -v tests.test_prime_p1_authority_receipt`

  Expected: failure because the private binding/material/issue API does not exist.

- [ ] **Step 3: Implement the smallest authority-only issuer.**

  Add slot-based private value types, native-value validation, canonical digest/HMAC construction, and an atomic `pop` of the issuer key before construction. The issue function accepts only exact private types, validates all binding identities, creates protocol-defined “not-created” digests using domain-separated hashes, and returns a receipt object which cannot be copied/pickled or converted to a generic signing capability. Do not import the issuer from public application code and do not add a `sign` method.

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run python -m unittest -v tests.test_prime_p1_authority_receipt tests.test_prime_p1_authority_protocol && uv run ruff check src/asterion/applications/prime_agent/operator/authority_receipt.py tests/test_prime_p1_authority_receipt.py && uv run pyright src/asterion/applications/prime_agent/operator/authority_receipt.py tests/test_prime_p1_authority_receipt.py`

  Expected: PASS. Commit: `feat: issue one-use Prime P1 unavailable receipts`.

### Task 2: Protocol consumes only a bound issued terminal

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_protocol.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Modify: `tests/test_prime_p1_authority_protocol.py`

**Interfaces:**

- Consumes: private issued receipt and binding from Task 1.
- Produces: `AuthoritySession.reserve_terminal_binding()` and `AuthoritySession.terminal_packet(issued)`; no `receipt_hmac_key` constructor parameter remains.

- [ ] **Step 1: Write failing state-machine tests.**

  Add a live ready→execute test which reserves the terminal binding, receives an issuer-created unavailable receipt, sends it through `terminal_packet`, and confirms `SupervisorSession` parses a single `UNAVAILABLE`. Add representative rejections for raw receipt mapping, binding mismatch, terminal before execute, and second terminal.

- [ ] **Step 2: Run RED.**

  Run: `uv run python -m unittest -v tests.test_prime_p1_authority_protocol`

  Expected: failure because `reserve_terminal_binding` and issued-receipt consumption do not exist.

- [ ] **Step 3: Implement minimal state ownership.**

  Remove raw receipt-key storage from `AuthoritySession`; after a valid execute, reserve exactly one private binding and transition to `terminal-reserved`. `terminal_packet` accepts only a receipt object issued by the receipt module, verifies its one-time binding against session/run/application/resource, marks it consumed, and frames its immutable payload at sequence one. It neither constructs nor validates receipt HMACs. Preserve cancellation semantics and poison latching.

- [ ] **Step 4: Refresh authority source lock and run GREEN.**

  Regenerate the exact digest entry for changed authority files using the repository’s existing lock-materialization convention. Run: `uv run python -m unittest -v tests.test_prime_p1_authority_protocol tests.test_prime_p1_authority_receipt && uv run ruff check src/asterion/applications/prime_agent/operator/authority_protocol.py src/asterion/applications/prime_agent/operator/authority_receipt.py tests/test_prime_p1_authority_protocol.py tests/test_prime_p1_authority_receipt.py && uv run pyright src/asterion/applications/prime_agent/operator/authority_protocol.py src/asterion/applications/prime_agent/operator/authority_receipt.py tests/test_prime_p1_authority_protocol.py tests/test_prime_p1_authority_receipt.py && git diff --check`

  Expected: PASS. Commit: `feat: bind Prime P1 terminal receipts to IPC session`.

### Task 3: Deferred production wiring gate

**Files:**

- Modify later, not in Tasks 1–2: `src/asterion/applications/prime_agent/operator/authority_process.py`

**Gate:** Do not implement this task until resource admission has authoritative values for authority executable digest, config-binding HMAC, and every identity hash required by the receipt. At that point, write a RED process test which proves valid execute produces exactly one terminal, invalid execute never invokes issuer, and neither Docker/provider/network/subprocess is invoked by the test double. This is deliberately not bundled with the protocol slice.

## Self-review

- The plan keeps key custody in one module and eliminates the raw-key protocol API.
- The plan does not create a production receipt from arbitrary/fake values.
- Test scope covers meaningful state/custody boundaries without field-combination exhaustiveness.
