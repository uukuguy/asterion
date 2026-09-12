# Prime P1 Operator Config Receipt Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind an admitted operator configuration to future Prime P1 receipts without retaining or exposing the receipt HMAC key.

**Architecture:** During the existing verified config-FD read, `authority_config.py` derives a domain-separated HMAC over canonical, exact parsed config values excluding `ASTERION_PRIME_P1_RECEIPT_HMAC_KEY`; it then transfers the raw key into the existing opaque issuer and retains only the derived digest. The config object exposes neither a generic MAC operation nor raw secret values.

**Tech Stack:** Python 3.12, standard-library `hmac`/`hashlib`/canonical `json`, `unittest`.

## Global Constraints

- Configuration admission remains FD-only, exact-key, redacted, and close-on-read; never read `.env` or process environment.
- The receipt HMAC key must not be present in `_values`, repr, exception/context/cause, public API, or a generic signing/HMAC interface.
- HMAC input is exact canonical JSON of every accepted config field except the receipt HMAC key, domain-separated as `asterion.prime-p1-operator-config/v1\0`.
- This is an identity derivation only: it does not invoke Docker, a provider, a network, a subprocess, or mint a PASS/terminal receipt.
- Use representative development checks: deterministic same input, one changed accepted field changes the binding, redaction, and invalid admission. Do not enumerate all fields.

### Task 1: Derive and retain opaque config binding

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_config.py`
- Modify: `tests/test_prime_p1_authority_receipt.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`

**Interfaces:**

- Produces: private `PrimeP1OperatorConfig._operator_config_binding_hmac_sha256: str`, a 64-character lowercase digest produced only by verified config admission.
- Consumes: verified exact config mapping and raw receipt HMAC key transiently inside `load_operator_config`; `_new_authority_receipt_issuer` remains the key-custody transfer point.

- [ ] **Step 1: Write RED tests.**

  In `TestPrimeP1AuthorityReceiptCustody`, load two valid independently opened config FDs with the same fixed receipt key and assert equal private binding digests; change exactly `ASTERION_PRIME_P1_MODEL_ID` in one accepted config and assert the binding digest changes. Assert it matches lowercase SHA-256 form, the raw receipt key is absent from `_values`, and repr/raised invalid-load exception/context/cause do not contain either secret sentinel.

- [ ] **Step 2: Run RED.**

  Run: `uv run python -m unittest -v tests.test_prime_p1_authority_receipt`

  Expected: FAIL because the config has no binding digest field.

- [ ] **Step 3: Add minimal canonical derivation.**

  After `_parse_verified_bytes`, remove the exact receipt-key entry into a local string, canonicalize the remaining mapping with `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, and `allow_nan=False`, then calculate the domain-prefixed HMAC using the transient key bytes. Create the opaque issuer from the same key and construct config with `MappingProxyType(values)`, issuer, and only the lowercase digest. Normalize every failure through `PrimeP1OperatorConfigError` with `from None` outside an active exception context.

- [ ] **Step 4: Refresh lock and run GREEN.**

  Recompute exactly the `authority_config.py` digest entry in the packaged authority artifact lock. Run: `uv run python -m unittest -v tests.test_prime_p1_authority_receipt tests.test_prime_p1_authority_artifact_lock && uv run ruff check src/asterion/applications/prime_agent/operator/authority_config.py tests/test_prime_p1_authority_receipt.py && uv run pyright src/asterion/applications/prime_agent/operator/authority_config.py tests/test_prime_p1_authority_receipt.py && git diff --check`

  Expected: PASS. Commit: `feat: bind Prime P1 receipts to admitted operator config`.

## Self-review

- No interface accepts arbitrary bytes for signing or HMAC.
- The derivation includes `DEEPSEEK_API_KEY` and all other accepted config fields but excludes only the receipt key to avoid self-reference.
- A test demonstrates one accepted field changes the digest and all secret channels stay redacted.
