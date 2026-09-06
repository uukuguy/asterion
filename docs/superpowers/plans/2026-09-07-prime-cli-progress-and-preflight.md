# Prime CLI Progress and Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Prime P1-P7 development Make command self-preparing, purpose-labelled, safely progressive, and reproducible after an Orb restart, with P2 as the first real command proof.

**Architecture:** Add a Python-only framework progress reporter injected through `HostServiceFactoryContext`, then add an application-owned preparation service whose authority comes from a packaged exact lock and whose cache receipt lives under ignored `.asterion-private/prime-development/`. Make recipes execute preparation and the selected application in one Orb command, while a separate aggregate command prepares and preflights all seven applications without executing application workloads.

**Tech Stack:** Python 3.12, `unittest`, argparse, dataclasses/protocols, asyncio context managers, Make, OrbStack, Node 22.23.2, TypeScript Prime Gateway, Docker.

## Global Constraints

- Preserve the four closed contracts: `asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, and `asterion.application-assembly/v1`.
- Framework modules remain domain-neutral and must not import Prime or DCI application code.
- Progress values contain only enumerated component/state plus optional bounded `current/total`; never render prompts, answers, credentials, paths, provider payloads, raw output, or exception text.
- Progress writes to `stderr`; the immutable final application JSON remains the only Asterion payload on `stdout`.
- Reporter failures never affect application execution, failure semantics, cancellation, or cleanup.
- Preparation and execution use the same `PRIME_ORB_MACHINE`, user, working tree, Linux architecture, and Docker daemon.
- Node is exactly `22.23.2`. Official archive SHA-256 values are `d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307` for Linux x64 and `fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8` for Linux arm64. Extracted `bin/node` SHA-256 values are `3517c2df0b2f8cd7f422b4b8450ef81c6889f08eb03e281d6de9079b15e6a327` and `1a638b0fe2b68da0489276aca95526c5122fc61ba54d6a2d0d00c1c92ab7b876`, respectively.
- Cache evidence lives only under ignored `.asterion-private/prime-development/`; it is never authority and has no public path override.
- Reuse requires content rehashing against a packaged code-owned lock and the current execution context. Path existence, version output, mtime, or receipt content alone never permits reuse.
- Staging and receipt publication use sibling temporary paths plus atomic rename; incomplete staged content is never reused.
- Preparation may download exact artifacts, build the locked Gateway, prepare exact Prime source, and inspect/build pinned images. It never reads `.env`, provider credentials, or model configuration.
- The development seccomp profile is canonicalized from Moby `profiles` tag `seccomp/v0.2.3`, commit `836ae4d37ef2ec995c77c99fc55f5b5f3af3a897`: upstream raw SHA-256 `536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74`, canonical SHA-256 `9da637d2ab0a204fcbd91bd88f1be9e004a3acab61c571a9f5b8870e588a17d2`.
- Development seccomp/image locks remain separate from production `Promoted*` catalogs; the promoted catalogs remain empty and fail closed.
- Verification is limited to focused normal-path and boundary assertions plus one real P2 command and zero-residue inspection.

---

### Task 1: Framework-safe host progress contract and CLI rendering

**Files:**
- Create: `src/asterion/services/progress.py`
- Modify: `src/asterion/services/__init__.py`
- Modify: `src/asterion/services/registry.py`
- Modify: `src/asterion/cli.py`
- Test: `tests/test_host_progress.py`
- Test: `tests/test_host_service_registry.py`
- Test: `tests/test_asterion_cli.py`

**Interfaces:**
- Produces: `HostProgressEvent(component: str, state: str, current: int | None = None, total: int | None = None)`.
- Produces: `HostProgressReporter.emit(event: HostProgressEvent) -> None`, `NOOP_HOST_PROGRESS_REPORTER`, and `TextHostProgressReporter(stream: TextIO)`.
- Produces: `HostServiceFactoryContext.progress` with `repr=False, compare=False, hash=False`.
- Changes: `HostServiceFactoryRegistry.open(..., progress: HostProgressReporter = NOOP_HOST_PROGRESS_REPORTER)`.
- Changes: `asterion run --progress` constructs the text reporter and passes it to the registry.

- [ ] **Step 1: Add failing progress value and renderer tests**

Create `tests/test_host_progress.py` with table-driven tests that accept all nine component names, all three states, and valid bounded counters; reject subclassed strings, unknown values, partial counters, zero, and totals above 64. Assert frozen mutation failure, fixed rendering such as `[host] model 1/2: started\n`, and a hostile stream that raises after one write without escaping `emit`.

- [ ] **Step 2: Run the focused test and confirm the missing module failure**

Run: `uv run python -m unittest -v tests.test_host_progress`
Expected: FAIL because `asterion.services.progress` does not exist.

- [ ] **Step 3: Implement the closed Python-only progress value**

Implement `progress.py` with exact tuples:

```python
HOST_PROGRESS_COMPONENTS = (
    "cleanup", "gateway", "image", "model", "preflight",
    "source", "tool", "validation", "worker",
)
HOST_PROGRESS_STATES = ("failed", "started", "succeeded")

@dataclass(frozen=True, slots=True)
class HostProgressEvent:
    component: str
    state: str
    current: int | None = None
    total: int | None = None
```

Validate exact built-in types in `__post_init__`. Implement no-op, text, and failure-contained reporters. The contained reporter copies fields into a new framework-owned event, disables itself after any reporter exception, rejects post-failure non-cleanup work, and treats cleanup failure as terminal. Rendering must select labels from a code-owned mapping and never call arbitrary `str` or `repr`.

- [ ] **Step 4: Inject the reporter without changing existing context behavior**

Add `progress: HostProgressReporter = field(default=NOOP_HOST_PROGRESS_REPORTER, repr=False, compare=False, hash=False)` to `HostServiceFactoryContext`. In `HostServiceFactoryRegistry.open`, create one contained reporter per open call and inject it into every selected factory context. Add registry tests for default no-op compatibility, exact reporter identity isolation, hostile reporter containment, and unchanged context repr/equality/hash.

- [ ] **Step 5: Wire `asterion run --progress`**

Add the parser flag, pass `stderr` into `_run`, construct `TextHostProgressReporter(stderr)` only when requested, and pass it to `HostServiceFactoryRegistry.open`. Extend `tests/test_asterion_cli.py` to prove progress is on stderr, final JSON is unchanged on stdout, and sentinel data from reporter/host exceptions is absent.

- [ ] **Step 6: Verify and commit Task 1**

Run: `uv run python -m unittest -v tests.test_host_progress tests.test_host_service_registry tests.test_asterion_cli`
Expected: PASS.

Commit only Task 1 files with: `feat(services): add safe host progress reporting`.

---

### Task 2: Exact Prime development preparation and private receipt

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/resources/prime-development-preparation-lock.json`
- Create: `src/asterion/applications/prime_agent/operator/resources/prime-development-seccomp.json`
- Create: `src/asterion/applications/prime_agent/operator/resources/prime-development-seccomp-lock.json`
- Create: `src/asterion/applications/prime_agent/operator/resources/moby-profiles-LICENSE.txt`
- Create: `src/asterion/applications/prime_agent/operator/development_preparation.py`
- Create: `tools/prepare_prime_development.py`
- Create: `tools/generate_prime_development_lock.py`
- Modify: `pyproject.toml`
- Test: `tests/test_prime_development_preparation.py`

**Interfaces:**
- Produces: `PrimeDevelopmentPreparationError` with one fixed public message.
- Produces: `PrimeDevelopmentPaths(root: Path, node: Path, seccomp: Path, gateway_root: Path, source_root: Path)`.
- Produces: `prepare_prime_development(repo_root: Path, scenarios: tuple[str, ...], *, emit: Callable[[str, str], None] | None = None) -> Mapping[str, PrimeDevelopmentPaths]`.
- Produces CLI: `python tools/prepare_prime_development.py --scenario p2`; repeatable `--scenario` supports P1-P7 and `--all`.
- Consumes the existing exact source validator from `src/asterion/applications/prime_agent/source_lock.py`, existing P7 locks, Prime Gateway resource locks, and the existing development image identities currently enforced by P1-P7 CLI hosts.
- Keeps `PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG` and `PRIME_IPYTHON_IMAGE_INPUT_CATALOG` unchanged and empty.

- [ ] **Step 1: Add failing preparation tests**

Cover canonical cache derivation, x64/arm64 Node lock selection, archive and executable digest mismatch, packaged seccomp raw/canonical/provenance validation, wrong architecture, Gateway input/output aggregate mismatch, source lock mismatch, selected-image mismatch, receipt-only rejection, receipt context mismatch, interrupted staging, idempotent reuse after full rehash, stale `/tmp` independence, unchanged empty production resolvers, and proof that `dotenv_values`/credential access is never invoked.

Use temporary directories and injected download/subprocess/platform functions; do not perform real downloads or Docker operations in unit tests.

- [ ] **Step 2: Confirm the new module is absent**

Run: `uv run python -m unittest -v tests.test_prime_development_preparation`
Expected: FAIL because `development_preparation` does not exist.

- [ ] **Step 3: Add the code-owned preparation lock**

Commit the canonical Moby profile bytes, its upstream Apache-2.0 license, and a separate `asterion.prime-development-seccomp-lock/v1` containing upstream tag/commit/raw SHA-256, canonical SHA-256, supported Linux architectures, and applicable development image digests. This lock is development compatibility identity only; it never calls or populates a `Promoted*` resolver.

The canonical preparation lock must include format `asterion.prime-development-preparation-lock/v1`, Linux `amd64` and `arm64` Node records with the exact URLs and hashes in Global Constraints, the development seccomp lock digest per architecture, the sorted Gateway locked-input file list and aggregate digest, the sorted Gateway output file list and aggregate digest, the exact Prime source commit/tree/package-lock identities validated through existing `source_lock.py`, these existing development image bindings: P1/P4 `asterion-p1b-development:20260906` → `sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657`; P2 `asterion-p2-development:20260906` → `sha256:7d97b51a21bfffe6caa574063294f72205c60b05d8650fab8c70fdf661921c33`; P3/P5/P6/P7 `asterion-p3-development:20260906` → `sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243`; and the P7 resource/runtime lock identities.

`tools/generate_prime_development_lock.py` computes canonical sorted aggregates and refuses missing, symlinked, non-regular, duplicate, or out-of-root inputs. Generation is maintainer tooling; runtime preparation only reads and validates the packaged lock.

- [ ] **Step 4: Implement preparation with atomic cache publication**

Use `importlib.resources` to load the packaged lock. Derive `repo_root/.asterion-private/prime-development`; reject symlinked roots and files. Bind the receipt to `PRIME_ORB_MACHINE`, effective uid, resolved worktree identity, `linux/<arch>`, and Docker daemon identity. The official Node archive contains npm/npx/corepack symlink members that are not runtime inputs. After validating the complete archive digest, scan all member names only for absolute paths, `..`, and duplicates; stream-read exactly one `node-v22.23.2-linux-{arch}/bin/node` member and require it to be a bounded regular non-link. Write only that member with `O_EXCL|O_NOFOLLOW`, verify its locked SHA-256, set mode `0555`, fsync, and atomically publish its versioned directory. Never call `extract`/`extractall` or materialize any other archive member. For each selected scenario:

1. rehash every referenced cached artifact;
2. download the exact Node archive only when the cache is invalid, cap bytes/time, verify archive SHA-256 before extraction, verify `bin/node` SHA-256 and `--version == v22.23.2`;
3. rehash the packaged development-only seccomp profile, validate provenance/platform/image binding, and materialize those exact canonical bytes without consulting production resolvers;
4. rebuild Gateway using `npm --prefix packages/typescript/prime-gateway run build` only after locked inputs mismatch, then verify every output and aggregate;
5. invoke existing exact source preparation/validation without reading `.env`;
6. inspect the selected image and build from its reviewed Dockerfile only when absent/mismatched, then require its exact digest;
7. prepare the locked offline environment only for P7;
8. write canonical receipt bytes to a sibling staged file, fsync, and publish with `os.replace`.

All subprocesses use direct argv, cleared/allowlisted env, finite timeout, and capped captured output. Emit only fixed component/state pairs. Immediately before Docker create, consumers rehash the packaged profile, recheck platform and selected image digest, and seal the verified bytes into a memfd. Do not claim the resource is the lost historical `/tmp` profile, promoted, production-ready, or an OS sandbox.

- [ ] **Step 5: Add the operator CLI and package inclusion**

The tool parses only `--scenario {p1,...,p7}`, repeatable, or `--all`; it derives the repo root and cache path internally. It prints fixed `[prepare] component: state` lines to stderr and a public one-row-per-scenario result to stdout without paths. Include the lock resource in the wheel through the existing Prime operator resource include pattern in `pyproject.toml`.

- [ ] **Step 6: Verify and commit Task 2**

Run: `uv run python -m unittest -v tests.test_prime_development_preparation tests.test_prime_source_lock tests.test_prime_image_input_lock tests.test_prime_p1_seccomp_policy_lock`
Expected: PASS.

Commit only Task 2 files with: `feat(prime): add reproducible development preparation`.

---

### Task 3: P2 first executable vertical slice

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/p2_cli_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p2_development_host.py`
- Modify: `Makefile`
- Test: `tests/test_prime_p2_cli_host.py`
- Test: `tests/test_prime_p2_development_host.py`
- Create: `tests/test_prime_make_presets.py`

**Interfaces:**
- Consumes: `HostServiceFactoryContext.progress` and `prepare_prime_development(..., scenarios=("p2",))`.
- Consumes canonical `PrimeDevelopmentPaths`; P2 host derives those paths and validates the preparation receipt before resource opening.
- Produces: P2 coarse sequence `preflight → image → source → worker → model 1/2..2/2 → tool 1/1 → validation → cleanup`.
- Produces: `make prime-p2-run` purpose line, same-Orb preparation, and `asterion run --progress`.

- [ ] **Step 1: Add failing P2 path, progress, Make, and argv tests**

Assert P2 rejects absent/tampered receipt before Node, Docker, source, or credential access; accepts canonical prepared paths without any `/tmp` dependency; emits only the required safe sequence; emits cleanup after representative failure; preserves the exact Docker argv:

```text
/usr/bin/docker --host unix:///var/run/docker.sock image inspect
  --format {{.Id}} asterion-p2-development:20260906
```

Add a Makefile text test proving P2 contains `--extra prime`, `--progress`, exact selector/runtime/input, a static purpose line, and one Orb shell that runs preparation before Asterion.

- [ ] **Step 2: Confirm focused failures**

Run: `uv run python -m unittest -v tests.test_prime_p2_cli_host tests.test_prime_p2_development_host tests.test_prime_make_presets`
Expected: FAIL on missing progress/preparation integration.

- [ ] **Step 3: Replace P2 ephemeral resources and emit lifecycle progress**

Remove `_NODE` and `_SECCOMP`. Resolve canonical paths through the verified preparation receipt in `_preflight`. Emit `started/succeeded/failed` around preflight and internal stages, with repeated counters exactly as specified. Guarantee cleanup emission after transport/gateway cleanup settles and never expose caught exception values.

- [ ] **Step 4: Make P2 self-prepare and describe itself**

Make the recipe print:

```text
[prime-p2] Programmatic long context: use the fixed corpus, execute one cell, and validate the answer
```

to stderr, then execute preparation and `asterion run --progress` sequentially within the same `orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" ...` shell. Preserve the generated or supplied `PRIME_RUN_ID`.

- [ ] **Step 5: Run focused tests and real P2**

Run the Task 3 unit command; expected PASS.

Then run: `PRIME_RUN_ID=prime-p2-20260907-fixed make prime-p2-run`
Expected: purpose and safe progress on stderr, one final P2 JSON result on stdout, exit 0.

Inspect P2 containers, gateway processes, sockets, and workspaces; expected zero residue.

- [ ] **Step 6: Commit Task 3**

Commit only Task 3 files with: `feat(prime): make P2 command self-preparing`.

---

### Task 4: Extend safe progress and stable resources across P1 and P3-P7

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/p1_cli_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p1b_development_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p3_cli_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p4_cli_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p5_cli_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p6_cli_host.py`
- Modify: `src/asterion/applications/prime_agent/operator/p7_cli_host.py`
- Modify lifecycle hosts under `src/asterion/applications/prime_agent/operator/p{3,4,5,6,7}_development_host.py` only where progress must surround internal work.
- Modify: `Makefile`
- Test: existing focused P1/P3-P7 CLI-host and development-host test modules.
- Test: `tests/test_prime_make_presets.py`

**Interfaces:**
- Consumes: Task 1 progress reporter and Task 2 canonical preparation paths.
- Produces: scenario-specific sequences from the approved design and static descriptions for all remaining Make recipes.

- [ ] **Step 1: Add failing table-driven host and Make assertions**

For each scenario assert its canonical prepared resources replace all `/tmp/asterion-node22` and `/tmp/asterion-p1-development-seccomp.json` assumptions, its exact purpose text is present, and its coarse success/failure/cleanup sequence matches the spec. Use `subTest` matrices and one representative failure boundary per scenario.

- [ ] **Step 2: Confirm focused failures**

Run:

```bash
uv run python -m unittest -v \
  tests.test_prime_p1_cli_host tests.test_prime_p1_development_host \
  tests.test_prime_p3_cli_host tests.test_prime_p3_development_host \
  tests.test_prime_p4_cli_host tests.test_prime_p4_development_host \
  tests.test_prime_p5_cli_host tests.test_prime_p5_development_host \
  tests.test_prime_p6_cli_host tests.test_prime_p6_development_host \
  tests.test_prime_p7_cli_host tests.test_prime_p7_development_host \
  tests.test_prime_make_presets
```

Expected: FAIL on remaining ephemeral paths and missing progress/descriptions.

- [ ] **Step 3: Integrate hosts without duplicating orchestration**

Use a small application-owned helper for canonical preparation path lookup and progress emission if duplication appears in three or more hosts. Keep each host's existing validation, authorization, bounded callback counts, cancellation, and cleanup behavior. Do not move runtime orchestration into the preparation service.

- [ ] **Step 4: Update remaining Make recipes**

Each recipe prints its exact approved static description, runs only its selected scenario preparation, then invokes the exact existing application selector with `--extra prime --progress --input fixed-small-verification` inside one Orb execution context.

- [ ] **Step 5: Verify and commit Task 4**

Run the focused command from Step 2; expected PASS. Run `rg -n '/tmp/asterion-node22|/tmp/asterion-p1-development-seccomp' src/asterion/applications/prime_agent/operator/*cli_host.py`; expected no matches.

Commit only Task 4 files with: `feat(prime): add progress to all development presets`.

---

### Task 5: Seven-application provider-free preparation and host preflight

**Files:**
- Create: `tools/preflight_prime_apps.py`
- Modify: `Makefile`
- Test: `tests/test_prime_apps_preflight.py`
- Test: `tests/test_prime_make_presets.py`

**Interfaces:**
- Consumes: installed `prime-agent` provider selection, Task 2 `prepare_prime_development(..., scenarios=("p1", ..., "p7"))`, and Task 1 text reporter.
- Produces: `make prime-apps-preflight` with exactly seven public PASS/FAIL rows and a nonzero exit if any row fails.

- [ ] **Step 1: Add failing aggregate tests**

Inject fake provider entry points, preparation, and host registry. Assert all seven scenarios are prepared first in the same context; preparation failure creates that row's FAIL and skips its context; later rows still execute; every opened context closes; no runtime factory, model callback, tool, worker workload, or application container runs; secrets and private paths never appear.

- [ ] **Step 2: Confirm the tool is absent**

Run: `uv run python -m unittest -v tests.test_prime_apps_preflight tests.test_prime_make_presets`
Expected: FAIL because the aggregate tool/target is absent.

- [ ] **Step 3: Implement aggregate preflight**

Resolve the exact installed provider/applications and assemblies, map each application to its host capability, prepare P1-P7, then open and close each host-service context with empty public options. Render fixed rows in P1-P7 order:

```text
prime-p1 PASS
prime-p2 PASS
...
prime-p7 PASS
```

On failure replace only `PASS` with `FAIL`; keep evaluating. Credential presence may be read by application preflight, but values cannot be rendered, transmitted, persisted, or used. P7 may perform its bounded isolated local-interpreter readiness probe.

- [ ] **Step 4: Add the Make target and verify**

Add `prime-apps-preflight` using the same Orb/user/worktree context and `uv run --extra prime --isolated`.

Run: `uv run python -m unittest -v tests.test_prime_apps_preflight tests.test_prime_make_presets`; expected PASS.

Run: `make prime-apps-preflight`; expected seven PASS rows and exit 0.

- [ ] **Step 5: Commit Task 5**

Commit only Task 5 files with: `feat(prime): add seven-app host preflight`.

---

### Task 6: Focused integration closure and durable status

**Files:**
- Modify only if findings require fixes: Task 1-5 implementation files.
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

**Interfaces:**
- Produces completion evidence for the approved development boundary.

- [ ] **Step 1: Run the bounded framework and Prime checks once**

Run:

```bash
uv run python -m unittest -v \
  tests.test_host_progress tests.test_host_service_registry tests.test_asterion_cli \
  tests.test_prime_development_preparation tests.test_prime_make_presets \
  tests.test_prime_apps_preflight tests.test_prime_p2_cli_host \
  tests.test_prime_p2_development_host
make test.framework-provider-free
make docs-check
git diff --check
```

Expected: PASS. Do not run full `make check` or `promotion-check`.

- [ ] **Step 2: Re-run the one formal executable proof only if implementation changed after Task 3**

Run: `PRIME_RUN_ID=prime-p2-20260907-fixed make prime-p2-run`
Expected: exit 0, visible fixed progress, final JSON, zero P2 residue.

- [ ] **Step 3: Final material-change review**

Generate one review package from `739e207b` to HEAD. Ask a Sol specialist to review dependency direction, progress/redaction containment, preparation authority, same-context execution, application host cleanup, and whether the real P2 evidence supports the claimed boundary. Fix blocker/major findings; record minor findings only when they do not affect the development acceptance criteria.

- [ ] **Step 4: Record the verified state**

Append concise journal entries for each durable commit and the exact P2/aggregate verification results. Rewrite the live-session checkpoint so it identifies P1-P7 commands as restart-safe only if `prime-apps-preflight` and the real P2 proof passed.

- [ ] **Step 5: Commit status closure**

Commit only status files with: `docs(status): record Prime command closure`.
