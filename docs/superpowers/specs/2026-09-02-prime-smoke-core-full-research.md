# Prime Smoke Core / Full Research and Smoke Core Design

## Status

Research and proposed design.  No implementation is authorized by this document
alone.

## Decision

Use two distinct validation products:

- **Smoke Core** is one bounded, real, deterministic-oracle task proving the
  end-to-end Prime control path.
- **Smoke Full** is a repeatable validation suite for typical Prime
  applications and long-running quality; it is not a larger one-off smoke.

Add an aggregate `prime-core-acceptance` only after Smoke Core exists.  It
combines current-HEAD provider-free proof with one current-HEAD bounded Core
receipt.  It must never reuse an old receipt as current evidence.

## Why the current README RLM smoke is insufficient

`make prime-readme-rlm-smoke` has proved a real, bounded RLM lifecycle:
model-driven root execution, one child lifecycle, child messaging, cleanup,
budget accounting, and post-completion detach/attach.  Its current PASS rule
is only completed terminal, child started, message delivered, child deleted,
and in-budget use.  See `tools/prime_native_rlm_experiment.py`.

It does not prove an application effect with an oracle, in-flight reconnect,
two-child collaboration, current observation completeness, checkpoint/restart,
Continual Harness, or typical task quality.  The scenario intentionally turns
off application, checkpoint, cancellation, and budget probes in
`tools/run_prime_readme_smoke.py`.

The Prime parity ledger establishes broad provider-free protocol coverage and
historical bounded evidence, but those receipts cannot substitute for a
current-HEAD real task receipt.

## Prime capabilities worth reproducing

| Priority | Capability | Smoke Core position |
|---|---|---|
| P0 | Programmatic RLM: persistent program environment, generated program, recursive children, result collection | Required |
| P0 | Multi-agent coordination: independent children, direct messaging, root aggregation | Required |
| P0 | Long-task continuity: running detach/attach, cursor replay, continuation | Required |
| P1 | Session/context: persistence, compaction, branches, fork/clone, attachments, usage | Separate bounded suite |
| P1 | Continual Harness: evidence-backed refine, isolation, snapshots, rollback | Separate bounded suite, then Full |
| P1 | Ecosystem: skills, MCP, extensions, packages, tools | Separate bounded suite, then Full |
| P2 | CLI/RPC/ACP/SDK and operational interfaces | Provider-free plus integration suites |
| P2 | Long benchmarks and quality trends | Full only |

## Smoke Core design

### Commands

```make
prime-smoke-core:
	uv run python -m tools.run_prime_core_smoke

test.prime-smoke-core.provider-free:
	uv run python -m unittest -v tests.test_prime_core_smoke
	npm --prefix packages/typescript/prime-gateway test -- test/core-smoke.test.mjs

prime-core-acceptance:
	make test.prime-smoke-core.provider-free
	make prime-smoke-core
```

The real command reads operator-owned `.env` integration settings and applies
an internal finite preset.  It is excluded from `make test`, `make check`, and
promotion defaults.  The existing README RLM command remains a compatibility
probe until Core has stable evidence.

### Scenario `prime-core-smoke/v1`

1. Preflight exact Prime lock, gateway artifact, daemon handshake, model
   selector digest, and fixed authority.
2. Create a unique root session and admit one real model turn.
3. Require the model to produce and admit a programmatic RLM call.
4. Run two isolated children with distinct fixed objectives; require both to
   start, finish, and delete.  First version may serialize them only if the
   pinned runtime cannot safely prove overlap; the receipt records that fact.
5. Require a causally bound parent/child or child/child direct message.
6. Execute one closed `application.invoke` in a mode-0700 temporary fixture;
   a deterministic oracle validates its body-free result summary.  It must not
   change the user worktree.
7. Detach while a child is non-terminal; reattach and prove exact cursor
   replay and continued work.
8. Require one terminal, complete cleanup of children/owned processes/socket,
   and public-output redaction.

### PASS contract

The receipt format is `asterion.prime-core-smoke-receipt/v1`.  It binds
scenario version, Asterion revision, Prime source digest, gateway artifact
digest, configuration digest, and verifier digest.  It exposes no prompts,
answers, raw tool values, model/provider values, credentials, or private paths.

PASS requires all of the following:

- completed unique terminal; exact contiguous control event sequence;
- real root model selected and generated RLM program admitted;
- application succeeded and its deterministic oracle passed;
- both target children started, completed, and deleted;
- direct-message delivery and causal identity chain are complete;
- detach occurred while active, reattach succeeded, replay is contiguous, and
  work continued after attach;
- recursion policy, root/child/application usage attribution, budget, and
  cleanup all pass;
- client observation health is `healthy` with zero gaps;
- public privacy checks pass.

Unknown, absent, degraded, External-limited, or false fields always fail.

### Observation-health prerequisite

The current control-flow isolation of a failed optional client observation is
useful, but permanent silent disabling is not acceptable for Core.  The Prime
Gateway private observation plane needs durable health:

```text
healthy -- gap/invalid supported payload --> degraded
healthy -- durable commit uncertainty ----> resync-required
degraded/resync-required -- full snapshot and suffix replay --> healthy
```

The private IPC health snapshot must retain only fixed status, reason code,
native generation, observed-through sequence, first missing sequence, and
resync flag.  Legitimate other-session traffic is ignored.  A gap must remain
visible across restart; only complete reconciliation restores `healthy`.
Canonical control events may continue, but Core fails whenever observation
health is not healthy.

### Sol specialist review: Prime cursor semantics

Two authorized Core attempts provided the decisive wire evidence: a root
subscription advanced from `134` to `136`, and independently from `140` to
`141`, without a transport failure.  Prime assigns `meta.sequence` before its
capability, filter, and reconstruction decisions, so it is a session cursor,
not a contiguous per-client delivery sequence.  A numeric jump is therefore
not evidence of replay loss.

The private observation projection consequently has these closed rules:

- For the active root session and one cursor generation, a larger cursor is
  accepted; an equal cursor is an idempotent replay duplicate; a smaller cursor
  fails closed.
- Foreign-session and unscoped daemon frames are ignored before cursor
  processing and cannot advance root observation progress.
- Durable observation progress is strictly increasing, while public
  `source_sequence` remains exactly contiguous.
- Generation changes, attach `replay.status=unavailable`, transport failure,
  and uncertain durable commits remain the only causes for degraded or
  resync-required health.  A cursor jump alone never degrades health.

The cursor-generation identity must be retained when the transport exposes it;
the current version preserves the independently durable root observation
cursor rather than deriving it from the canonical event cursor.

### Planned implementation surfaces

- `tools/run_prime_core_smoke.py`: bounded entrypoint, safe heartbeat and
  terminal output, complete receipt verification.
- `tools/prime_native_rlm_experiment.py`: Core result/assertion model, two
  children, application oracle, active detach/attach.
- Prime gateway `client-observation.ts`, `durable-store.ts`, `gateway.ts`, and
  `main.ts`: durable observation health and private IPC contract.
- Python Prime process/client adapters: parse a closed health snapshot.
- `tests/test_prime_core_smoke.py` and `test/core-smoke.test.mjs`: truth table,
  privacy, failure, recovery, and zero-provider-operation matrices.
- `Makefile`: the three named commands and help text.

No change is proposed to `asterion.agent-control/v1`; observation health stays
a private Prime Gateway transport contract.

### Implementation order

1. Define receipt/verifier truth table and evidence-freshness tests.
2. Implement durable observation health, gaps, resync, and restart tests.
3. Include existing RLM model/program/recursion assertions in PASS.
4. Add two-child orchestration and closed application oracle.
5. Add in-flight detach/attach, replay, and continuation proof.
6. Add command, safe logging, cleanup, and full provider-free suite.
7. Run one authorized bounded Core and register its current-HEAD evidence.

## Smoke Full research boundary

Smoke Full should be named `prime-full-validation` during research.  It is a
versioned suite, not an expanded single fixture.  It validates typical isolated
applications:

1. Small repository code fix with tests as oracle.
2. Offline corpus research synthesis with a facts/citations verifier.
3. Multi-child analysis and root aggregation.
4. Long-running heartbeat, detach, process restart, and checkpoint recovery.
5. Continual Harness refine, second-task improvement, scope isolation, and
   snapshot rollback.
6. Packaged skill plus controlled MCP task.
7. Compaction followed by continuation under preserved constraints.

Full PASS is statistical: fixed repeated runs per scenario, recorded success
rate and quality thresholds, no privacy/security/orphan/evidence failures,
bounded cost and p95 latency, and exactly-once recovery.  It remains
milestone/nightly work rather than normal CI until fixtures, repeat count, and
quality thresholds are stable.

## Evidence boundaries

- Provider-free tests prove contracts and fault behavior; they do not prove a
  model task.
- One bounded Core receipt proves its exact scenario on its exact revisions;
  it is not Full quality proof.
- Full evidence proves only its pinned task set and thresholds; it is not a
  full paper benchmark.
- Existing historical receipts remain historical and must not be promoted to
  current-HEAD PASS without an exact fresh run.
