# Prime P7 GPT-6-Sol Solving Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or execute the tasks inline.

**Goal:** Run native P7 with `openai-codex/gpt-6-sol` through the existing Pi installation while preserving historical DeepSeek prefixes and evidence.

**Architecture:** P7 will use an operator-owned Pi agent directory supplied explicitly to the Orb guest. Its argv selects the exact provider/model and high reasoning, disables automatic extension discovery, and loads only the packaged IPython extension. Trace identities for new runs change to Codex; saved-prefix readers accept the two known historical/current identities and retain all existing replay checks.

**Tech Stack:** Python, Pi 0.87.1 RPC, Orb, unittest, Makefile, immutable private traces.

## Global Constraints

- DCI remains unchanged and continues to resolve its own provider/model.
- Historical DeepSeek traces and official receipts are immutable.
- User-facing commands expose no model, credential, cost, or deadline knobs.
- No model call occurs during provider-free tests, preflight, or RPC `get_state` validation.
- New runs require `openai-codex/gpt-6-sol`; seed, prompts, prefix actions, and action caps remain unchanged.

---

### Task 1: Model and identity contract

**Files:**
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `src/asterion/applications/prime/p7/live.py`
- Modify: `src/asterion/applications/prime/runtime_binding.py`
- Modify: `src/asterion/applications/prime/p7/private_trace.py`
- Modify: `src/asterion/applications/prime/p7/gameplay_trace.py`
- Test: `tests/test_prime_p7_native_provider.py`, `tests/test_prime_p7_live_command.py`

**Interfaces:**
- `resolve_pi_provider(environment, model)` accepts the exact Codex provider/model and validates the operator Pi agent directory.
- `resolve_p7_runtime` and `p7_runtime_options` publish `openai-codex` / `gpt-6-sol`.
- Active trace identity constants use `gpt-6-sol`; historical prefix loading remains independent of the active constant.

- [ ] Add failing assertions that runtime selection rejects DeepSeek and accepts Codex, and that the launch argv contains `--provider openai-codex`, `--model gpt-6-sol`, and `--thinking high`.
- [ ] Run focused provider/live command tests and confirm failure against the old DeepSeek contract.
- [ ] Implement the smallest constant and validation changes; remove the DeepSeek API-key requirement and require the supplied Pi agent directory instead.
- [ ] Re-run focused tests; update only assertions that describe the intentional new identity.
- [ ] Commit `feat: bind native p7 to codex gpt-6-sol`.

### Task 2: Pi agent directory and guest propagation

**Files:**
- Modify: `Makefile`
- Modify: `tools/run_prime_p7_guest.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Test: `tests/test_prime_p7_live_command.py`, `tests/test_prime_p7_native_provider.py`

**Interfaces:**
- `ASTERION_PRIME_PI_AGENT_DIR` is an operator-owned path passed to the guest and becomes `PI_CODING_AGENT_DIR` for Pi.
- P7 no longer writes `settings.json` into the operator's global profile.
- P7 argv includes `--no-extensions`, `--no-skills`, `--no-prompt-templates`, `--no-themes`, `--no-context-files`, and `--thinking high`; the packaged extension lease remains explicit.

- [ ] Add failing tests for missing agent directory, non-directory/symlink rejection, and exact Pi isolation flags.
- [ ] Run focused tests and confirm failure.
- [ ] Add the Makefile default for the mounted canonical profile, propagate the variable through the guest allowlist, validate it read-only, and stop writing global settings.
- [ ] Run focused tests plus a zero-prompt host and Orb guest RPC `get_state`; expect provider `openai-codex`, model `gpt-6-sol`, thinking `high`.
- [ ] Commit `feat: use operator codex profile for p7 pi`.

### Task 3: Historical prefix identity allowlist

**Files:**
- Modify: `src/asterion/applications/prime/p7/solutions.py`
- Test: `tests/test_prime_p7_solutions.py`

**Interfaces:**
- Saved-prefix loading accepts only exact historical DeepSeek and current Codex identity maps; it rejects unknown, mixed, or malformed identities.
- Prefix replay records new transitions under the current Codex identity without modifying source traces.

- [ ] Add failing fixtures for historical DeepSeek acceptance, unknown identity rejection, and mixed identity rejection.
- [ ] Run the solutions tests and confirm failure.
- [ ] Implement identity extraction/allowlist at `_load_one` after trace verification, leaving seals, replay hashes, game/seed, and action checks unchanged.
- [ ] Run solutions and official replay tests.
- [ ] Commit `fix: preserve verified p7 prefixes across model migration`.

### Task 4: Bounded smoke and first solve attempts

**Files:**
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`
- Create: private run receipts under `.asterion-private/` only

- [ ] Run provider-free focused tests and `make docs-check`.
- [ ] Run one bounded Codex RPC tool smoke with no-op IPython and verify usage, terminal event, and cleanup.
- [ ] Run offline retries in order: FT09 L5, M0R0 L4, TR87 L3; each has 30-minute and 5-minute no-action bounds.
- [ ] Verify each run's seal, replay, cleanup, and prefix promotion before the next attempt.
- [ ] If at least one pass, continue AR25 L5, KA59 L3, TU93 L5; otherwise stop paid attempts and compare trace diagnostics.
- [ ] Submit one official card only after accumulating verified new prefixes; record the score and limits in RESUME/JOURNAL.
