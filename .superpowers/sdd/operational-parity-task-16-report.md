# Operational Parity Task 16 Report

## Scope

Task 16 closes H-036 for exactly six Prime Gateway operational interface rows:

- `operation.auth`
- `operation.model-selection`
- `operation.settings-keybindings`
- `operation.telemetry-usage`
- `operation.doctor`
- `operation.controlled-update-restart`

It does not create H-037 and does not claim live OAuth, live model selection,
live telemetry delivery, real update/restart effects, Asterion-native behavior,
or full system parity.

## RED and implementation

The initial focused command was:

```bash
uv run python -m unittest -v \
  tests.test_prime_climb \
  tests.test_prime_parity_ledger \
  tests.test_check_prime_parity
```

It exited `1`: `tools/climb/cycle.sh H-036` had no six-receipt closure gate
and returned `2`.

Task 16 then added:

- H-036 climb tests for the exact cycle row and command sequence, dirty-tree
  rejection, no H-037 successor, and no native-parity claim;
- the six provider-free receipt targets, exact six-feature checker,
  `make check`, `make promotion-check`, and `git diff --check` to the H-036
  cycle gate; and
- the accepted transition to `check.operational-parity-closure`, ending at
  `future-work-queue`.

## Closure-audit compatibility hardening

Fresh detached closure audits exposed three portability defects that the prepared
canonical environment had not exercised:

1. The isolated-HOME verification test computed its expected expanded path
   outside the same cleared environment that ran the subject. The expectation
   now executes inside that environment.
2. `asterion.client.acp` imported `collections.abc.Buffer`, which is
   unavailable on Python 3.10 and 3.11. Runtime code now accepts `bytes`;
   test-only override annotations retain `Buffer` behind `TYPE_CHECKING` so
   Pyright still checks `BytesIO.write` correctly.
3. The generic promotion runner inherited outer Python and uv project bindings.
   A detached `PYTHONPATH` therefore made the isolated promotion copy import
   the outer source tree. The runner now removes Python home/path/startup/user
   bindings plus `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, and `UV_NO_SYNC`
   before executing copied-project commands.

The second defect had a direct RED witness: an installed Python 3.11 wheel
failed while importing `asterion.client.acp`. The corrected wheel imports and
the Python 3.11 ACP test module passes.

## Attempt accounting

Only the accepted canonical run wrote repository climb state. All confirmation
state was redirected to private temporary directories outside the repository.

| Attempt group | Boundary | Result | Repository `runs.csv` write |
|---|---|---|---|
| Early detached A4-A7 | Disposable worktrees | Invalid preparation: missing prepared material, inherited HOME, temp symlink ancestry, or npm layout drift | No |
| Detached A8 | Clean disposable tree | Reached 2,211 tests; isolated-HOME expectation and offline missing build dependency failed | No |
| Detached A9 | Clean disposable tree | Reached 2,211 tests; installed Python 3.11 wheel exposed the ACP `Buffer` import defect | No |
| Detached A10-A12 | Disposable worktrees | Setup preflight failure or externally interrupted before a complete gate | No |
| Detached A13 and B4 | Clean disposable trees | `/var` worktree alias violated the no-symlink capability template boundary; B4 completed 2,211 tests with exactly two related failures and A13 was stopped after the common cause was proven | No |
| Detached C3 and D3 | Clean disposable trees | Real worktree paths passed the capability preflight, but using the resolved temp path as `TMPDIR` changed the locked npm dependency-tree identity; rejected at the first receipt gate | No |
| Detached E | Separately rebuilt clean tree | Reached 2,211 tests; one uv/Python 3.11 temporary-directory cleanup race occurred while E and F ran concurrently | No |
| Detached F | Separately rebuilt clean tree | Main 2,211 tests passed; promotion copied-project tests proved outer Python/uv project bindings were inherited | No |
| Detached G and H | Separately rebuilt clean trees, executed serially | Final confirmations; both passed every terminal gate | No |

Short-lived orchestration/preflight-only attempts never entered the H-036
cycle and are not counted as closure runs.

The final environment preserves both closed boundaries:

- Asterion, Prime, `PYTHONPATH`, HOME, and XDG paths use resolved, non-symlink
  paths;
- `TMPDIR` retains the operating system's canonical spelling required by the
  locked npm dependency-tree digest;
- credentials, tokens, cloud keys, and proxy variables are empty;
- Prime has no remote; npm uses the locked offline cache; uv may read its
  dependency cache but is not forced offline; and
- each confirmation independently runs Prime `npm ci`, all required builds,
  runtime derivation, and both Asterion TypeScript builds.

## Canonical closure accounting

The repository contains exactly one accepted row:

```text
36,H-036,passed,check.operational-parity-closure
```

The generated state is:

```json
{"last_hypothesis":"H-036","last_outcome":"passed","next_action":"future-work-queue"}
```

The exact selected-feature checker output is:

```json
{"application_operations":0,"blocking_feature_count":0,"blocking_feature_ids":[],"claim":"feature-parity","passed_feature_count":6,"provider_operations":0,"reason_codes":[],"selected_feature_count":6,"selected_feature_ids":["operation.auth","operation.controlled-update-restart","operation.doctor","operation.model-selection","operation.settings-keybindings","operation.telemetry-usage"],"selection_kind":"features","status":"PASS"}
```

The canonical promotion result is:

```text
promotion full PASS commands=28 provider_operations=0 full_dataset=no
```

## Independent clean confirmations

Both final confirmations use detached Asterion commit
`c32074726cd535d8fb466e52780c03036fd1583b`, pinned Prime commit
`a18809e00ea30638584d87b3afea7285a9d7296c`, Node `v22.23.2`, and npm
`11.4.1`. Their logs and generated state remain outside the repository.

| Confirmation | Exact checker | Full suite | Promotion | External state | Tree state |
|---|---|---|---|---|---|
| G | 6 selected, 6 passed, 0 blocking, 0 provider/application operations | 2,211 tests in 1,060.231s, OK, one skip | PASS: 28 commands, 0 provider operations, `full_dataset=no` | 37 lines; one exact H-036 row; `future-work-queue` | Asterion and Prime clean; Prime has no remote |
| H | 6 selected, 6 passed, 0 blocking, 0 provider/application operations | 2,211 tests in 1,028.770s, OK, one skip | PASS: 28 commands, 0 provider operations, `full_dataset=no` | 37 lines; one exact H-036 row; `future-work-queue` | Asterion and Prime clean; Prime has no remote |

Both promotion runs also executed their copied-project test suites from a venv
inside the promotion copy, proving that the outer project environment was not
reused. The repository `runs.csv` remained 37 lines with exactly one H-036 row.

## Receipt identities

| Feature | Evidence identity |
|---|---|
| `operation.auth` | `evidence.operation.b1ad7223aab563156d8991d97e8b216b33ce131fefdc5a4bbc976b2a867031e8` |
| `operation.model-selection` | `evidence.operation.d607c48b96afe83a2fc1346020dbf914ac40138c6ff04105a7daf06d8c85f92a` |
| `operation.settings-keybindings` | `evidence.operation.14ec3308d4c777eb349be8f8a79710301d8db0264f2013ad06fe0cbb9e83fe2e` |
| `operation.telemetry-usage` | `evidence.operation.84a78d29b2fc30cec854b81e32d95072a308d6eae98d7d7288c19b882a48f731` |
| `operation.doctor` | `evidence.operation.e51e972608257ddd54c7fb1835e08f4da361078d2c145c0f31bb04a5f9f79e02` |
| `operation.controlled-update-restart` | `evidence.operation.8d973b07690020955820347d724f1a609a808a01ca734fac9f30f56ca4837071` |

Every selected receipt reports zero for the prohibited public effect vector:
credential reads, network requests, provider operations, retained processes,
stdout writes, and unauthorized uploads.

## Claims and nonclaims

- `interfaces.operations`: PASS at exactly 15/15 Prime Gateway rows after
  H-035 plus H-036.
- `Verified-system-parity`: BLOCKED. The exact checker reports 40 passed, 21
  blocking, two excluded, and zero provider/application operations.
- `Verified-native-parity`: Missing.
- `full_dataset`: `no`.
- H-037: not approved and not created.
