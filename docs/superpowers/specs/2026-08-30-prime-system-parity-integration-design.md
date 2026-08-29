# Prime System-Parity Integration Design

## Objective

Asterion's program objective is full Prime functional parity through two named
gates against pinned Prime commit
`a18809e00ea30638584d87b3afea7285a9d7296c`:

1. Prime Gateway reaches `Verified-system-parity` for every mandatory public
   scenario.
2. An interchangeable Asterion-native kernel later reaches
   `Verified-native-parity` against the same closed ledger.

This design closes the first gate by integrating two complementary, already
verified evidence lines. It does not implement or claim native parity.

## Current Evidence Split

The canonical ledger contains 63 feature rows: 61 mandatory rows and two
approved non-functional exclusions.

| Candidate | Mandatory PASS | Blocking | Excluded | Exact missing scope |
|---|---:|---:|---:|---|
| Local `main` at `262b2fd` | 40 | 21 | 2 | session compaction/branch summaries, RLM, and long-running operations |
| Archived ecosystem line at `67d2fc3` | 46 | 15 | 2 | client interfaces and six operational surfaces |
| Mixed root snapshot at diagnostic commit `6b6aa8b` | 46 | 15 | 2 | the same H-035/H-036 client and operation rows |

The sets of 21 and 15 blocking rows do not overlap. The mixed root snapshot is
therefore not disposable worktree dirt: it is the uncommitted integration
candidate that preserves the earlier 21 PASS rows while incorporating the
newer ecosystem implementation.

Commit `1396ab5` is the provenance boundary for the missing earlier state. Its
provider-free checker produces 36 PASS and lacks only the later ten ecosystem
and fifteen interface/operation rows. The current mixed root snapshot produces
46 PASS because it combines that prior state with the newer ecosystem closure.

## Chosen Approach

Create one integration commit from the meaningful mixed-root contents, then
merge local `main` into it. A merge-tree preflight shows that Git resolves the
majority automatically and leaves ten content conflicts. Resolve those ten by
contract and evidence ownership, not by selecting one side wholesale.

Rejected approaches:

- Reimplementing the 21 rows on `main` would discard a verified 92-file
  provenance boundary and repeat authorized bounded work.
- Merging all 178 commits from `feature/prime-ecosystem-parity` would combine
  duplicate ecosystem/client implementations and obsolete H-044/H-045
  alternative history across 337 differing files.
- Cleaning branches and worktrees before integration would destroy the only
  complete working-tree representation of the complementary evidence.

## Integration Graph

```text
f1316bb
├── 1396ab5 prior authorized state ── 21 additional mandatory PASS rows
│   └── mixed root candidate ──────── newer ecosystem 10/10
└── h024/new line ── H-035 ── H-036 ── local main@262b2fd
                                             │
mixed root candidate ───── three-way merge ──┘
                         ↓
              Phase 2 integration candidate
              61 PASS / 0 BLOCKED / 2 excluded
```

The archived branch after `1396ab5` is evidence history, not a merge input.
Only its still-valid design findings may be retained separately after the
integration gate passes.

## Snapshot Boundary

The integration snapshot includes:

- all 73 tracked modifications currently present in the primary worktree;
- the thirteen meaningful untracked long-running source, test, plan, fixture,
  and experiment files;
- the append-only historical state needed to validate H-001 through H-034.

It excludes:

- the literal repository-local `$(getconf DARWIN_USER_TEMP_DIR)/` Node compile
  cache tree;
- `.task13-promotion-bin/`;
- generated virtual environments, build products, credentials, external Prime
  state, and private evidence;
- the abandoned Git-only cleanup plan superseded by this design.

Before merge, the snapshot must reproduce the diagnostic tree
`bbe76e2c2e2ad2a87afb81a918bf276106342381` for the meaningful file set.

## Conflict Ownership

The merge preflight identifies ten conflict files.

### Runtime integration

- `packages/typescript/prime-gateway/src/main.ts`: preserve the long-running
  commands and lifecycle fences from the mixed candidate and the client and
  operational dispatch added on `main`. There remains one Gateway entry point.
- `packages/typescript/prime-gateway/test/main.test.mjs`: retain tests for all
  three surfaces; deduplicate only assertions with identical inputs and
  semantics.
- `src/asterion/control/providers/prime/client.py`: preserve one selected Prime
  client with long-running, client-interface, ecosystem, and operation
  translation. It must not authorize, retry, or choose a runtime.
- `tests/test_control_host.py` and `tests/test_prime_control_factory.py`: retain
  host preflight and exact provider construction coverage from both sides.

### Ledger and verification

- `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`: form the closed union
  by stable feature and scenario ID. A row may be PASS only when its existing
  evidence identity validates exactly; arrays remain sorted and unique.
- `tests/test_check_prime_parity.py` and `tests/test_prime_parity_ledger.py`:
  require the combined 61/0/2 result and preserve all negative tests for forged,
  missing, external-limited, and non-canonical evidence.

### Durable state

- `tests/test_prime_climb.py`: the canonical history is H-001 through H-036,
  each exactly once. Do not import the alternative branch's H-044/H-045 cycle
  sequence.
- `docs/status/JOURNAL.md`: form an append-only chronological union. Never edit
  or delete an existing historical line; append corrections for conflicting
  statements.

Conflict resolution must not fork composers, runners, provider registries, or
public protocol versions.

## Evidence and Cost Rules

- Reuse existing bounded receipts only when their pinned source, scenario,
  identity, digest, and counter contracts still validate after integration.
- Provider-free verification may revalidate stored evidence but may not access
  credentials, perform model work, contact a provider, or invoke an
  application.
- Any required live or paid rerun is a new authority boundary and requires a
  separate finite budget approval.
- Public results remain body-free and must not reveal prompts, answers,
  credentials, provider payloads, private paths, raw output, or opaque state.
- `executor.controlled` remains policy enforcement rather than an OS sandbox.

## Verification Flow

Run gates from narrowest to broadest:

1. Conflict-file unit tests and schema validation.
2. Exact checks for the 21 earlier rows, ten ecosystem rows, nine client rows,
   and six operational rows.
3. Every stable parity domain: session/context, RLM, long-running, continual
   harness, ecosystem, and interfaces/operations.
4. The system claim checker, requiring exactly:

   ```text
   passed_feature_count=61
   blocking_feature_count=0
   excluded_feature_count=2
   provider_operations=0
   application_operations=0
   status=PASS
   ```

5. `make check`, `make promotion-check`, `make docs-check`, distribution checks,
   and `git diff --check`.
6. Independent review of architecture direction, evidence truthfulness,
   privacy/redaction, deterministic composition, and duplicate implementations.

No merge result is promoted to `main` unless every gate passes. A failure leaves
the integration branch, original branch refs, and all source worktrees intact.

## Project-State Transition

After the system gate passes:

- record `Verified-system-parity: PASS` with the named command and exact pinned
  boundary;
- update `CURRENT-STATE.md` to canonical branch `main` and Phase 2 closed;
- rewrite the live recovery baton to point to Phase 3 design, without claiming
  native implementation;
- append the integration and verification results to `JOURNAL.md`;
- keep the two exclusions unchanged unless a separately reviewed ledger change
  reclassifies them.

The Phase 3 native-kernel design begins only after this transition is committed.

## Git and Worktree Closure

Git cleanup follows functional promotion rather than preceding it:

1. Create and verify a Git bundle containing local `main`, the archived
   ecosystem line, the pre-integration snapshot, and any detached head or dirty
   verification state not already reachable.
2. Promote the verified integration commit to local `main`.
3. Switch the primary workspace to `main` and verify it is clean.
4. Remove the ancestor H-024 branch, archived ecosystem branch, temporary
   integration/recovery branches, and registered detached worktrees only after
   bundle verification.
5. Run `git worktree prune` and require one registered primary worktree.
6. Leave `origin/main` unchanged until push is separately authorized.

The bundle is recovery evidence, not an active development line. The normal
steady state is one canonical branch and one primary worktree; future isolated
worktrees must be closed immediately after their verified result returns to
`main`.

## Completion Definition

This integration is complete only when all of the following are true:

- the exact system checker reports 61 PASS, zero blocking, two exclusions, and
  zero provider/application operations;
- all repository, promotion, distribution, and review gates pass;
- `main` contains the integration and truthful Phase 2 state;
- the primary worktree is clean and is the only registered worktree;
- removed refs and unique historical states are recoverable from a verified
  bundle;
- no native parity claim is made.

The overall program remains incomplete until the later native provider reaches
`Verified-native-parity` against the same mandatory ledger.
