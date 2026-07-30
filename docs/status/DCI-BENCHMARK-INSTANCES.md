# DCI Benchmark Instances

This is the implementation and verification backlog for every immutable DCI
benchmark instance exposed by `asterion-dci benchmark instances --json`.
Implementation and verification are independent: code existence never implies
that an external benchmark was rerun.

Verification is closed to `Not rerun`, `Verified-local`, `External-limited`,
`Verified-bounded`, and `Verified-full`.

| Instance | Task | Implementation | Verification | Full count | Next gate |
|---|---|---|---|---:|---|
| `dci.bcplus.level3@1.0.0` | `bcplus.level3` | planned | Not rerun | — | lock finite range and implement |
| `dci.bcplus.main@1.0.0` | `bcplus.main` | planned | Not rerun | — | lock finite range and implement |
| `dci.beir.arguana@1.0.0` | `beir.arguana` | planned | Not rerun | — | lock finite range and implement |
| `dci.beir.scifact@1.0.0` | `beir.scifact` | planned | Not rerun | — | lock finite range and implement |
| `dci.bright.biology@1.0.0` | `bright.biology` | planned | Not rerun | — | lock finite range and implement |
| `dci.bright.earth-science@1.0.0` | `bright.earth-science` | planned | Not rerun | — | lock finite range and implement |
| `dci.bright.economics@1.0.0` | `bright.economics` | planned | Not rerun | — | lock finite range and implement |
| `dci.bright.robotics@1.0.0` | `bright.robotics` | planned | Not rerun | — | lock finite range and implement |
| `dci.local-fixture@1.0.0` | 15-task fixture | implemented | Verified-local | 1/task | maintain installed-wheel closure |
| `dci.qa.2wikimultihopqa@1.0.0` | `qa.2wikimultihopqa` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.bamboogle.github-sample50@1.0.0` | `qa.bamboogle.github-sample50` | implemented | Verified-bounded | 50 | extend only under an explicit finite case limit |
| `dci.qa.bamboogle.paper-full125@1.0.0` | `qa.bamboogle.paper-full125` | planned | Not rerun | — | separate paper-full authorization design |
| `dci.qa.hotpotqa@1.0.0` | `qa.hotpotqa` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.musique@1.0.0` | `qa.musique` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.nq@1.0.0` | `qa.nq` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.triviaqa@1.0.0` | `qa.triviaqa` | planned | Not rerun | — | lock finite range and implement |

## How to use this document

Only instances marked `implemented` are executable. Each implemented row must
have a matching runbook below. A `planned` row is a real catalog identity, but
its implementation and operating contract are incomplete; do not attempt to
run it.

Run all commands from the Asterion repository root. Each runbook creates
absolute lock and evidence paths beneath `"$PWD/outputs/manual"`. A new run
creates a new evidence root and returns a new run ID. Resume must use that ID
with the same instance, case range, source lock, and evidence root.

Lock and plan are metadata-only and perform zero Agent and Judge operations. A
command containing `--execute` grants only that explicitly selected finite run.
For a real instance it may access the models, network, dataset, and corpus named
by the runbook.

## Runbook: `dci.local-fixture@1.0.0`

### Purpose and boundary

This provider-free fixture proves that the installed DCI capability package,
generic Asterion benchmark planner/runner, all fifteen task bindings, private
evidence, and compatible resume form one executable loop. It does not measure a
research model and does not access an Agent, Judge, network, external dataset,
or external corpus.

- Application: `dci.local-benchmark-application@1.0.0`
- Suite: `dci.all@1.0.0`
- Tasks: all fifteen DCI task bindings
- Range: one fixture case per task
- Cost class: provider-free
- Expected result: fifteen completed tasks and zero provider operations

### Lock, plan, run, and resume

The timestamp gives each new run a distinct operator-owned directory. All paths
passed to Asterion are absolute.

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-local-fixture-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.local-fixture@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.local-fixture@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

The public result must report `status: completed`. Private run state is under
`"$DCI_EVIDENCE_ROOT/runs/$DCI_RUN_ID"`; task outputs are under
`"$DCI_EVIDENCE_ROOT/outputs/$DCI_RUN_ID"`. Resume returns the completed result
without repeating task execution.

### Verified boundary

`Verified-local` is established by:

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark_installed
```

That test builds and installs the wheel in isolation, executes all fifteen
fixture tasks through the installed `asterion-dci` entry point, and resumes the
exact run without repeated work.

## Runbook: `dci.qa.bamboogle.github-sample50@1.0.0`

### Purpose and boundary

Bamboogle is the first real DCI benchmark instance. It evaluates a research
Agent on one exact QA task against the GitHub sample of fifty cases, then sends
the answer to an independent Judge. Asterion binds the portable DCI package to
operator-owned resources only after preflight and explicit execution
authorization.

- Application: `dci.complete-application@1.0.0`
- Suite: `dci.qa.bamboogle.github-sample50@1.0.0`
- Task: `qa.bamboogle.github-sample50`
- Default range: one case
- Finite catalog: fifty cases
- Agent: Pi using the configured research model and DCI prompt contract
- Judge: independently configured Judge model
- External dependencies: Pi checkout, Agent authentication, Judge credential,
  Bamboogle dataset, corpus, and network access
- Cost class: one bounded Agent operation plus one bounded Judge operation per
  selected case

The commands below deliberately select one case. Do not substitute
`--all-cases` in the run command without a separate explicit finite-budget
authorization.

### Preflight

Populate `.env` from the operator template and configure the external resource
paths and credentials. Preflight checks readiness only; it performs no Agent or
Judge operation and does not grant execution authority.

```bash
uv run asterion-dci preflight --env-file "$PWD/.env"
```

Every category must report `PASS` before execution. Process environment values
take precedence over `.env`; if authentication unexpectedly fails, inspect
inherited variables such as `DEEPSEEK_API_KEY`.

### Lock and bounded plan

These commands create an exact package lock and a one-case public plan without
accessing the model, Judge, dataset body, or corpus body.

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bamboogle-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK"
```

The plan must identify the exact application, suite, task, package digest, and
`case_limit: 1`. To inspect the finite catalog without executing it, replace
`--case-limit 1` in the plan command with `--all-cases`; the resulting public
plan has `case_limit: 50`.

### Authorized one-case run and exact resume

The run command performs one real Agent operation and one real Judge operation.
It writes private evidence beneath the selected absolute evidence root. `tee`
retains the public result so the exact new run ID can be extracted rather than
copied from historical evidence.

```bash
uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

The public run result must report one completed task with `case_count: 1`.
Private run state is under `"$DCI_EVIDENCE_ROOT/runs/$DCI_RUN_ID"` and native
task evidence is under `"$DCI_EVIDENCE_ROOT/outputs/$DCI_RUN_ID"`. Resume must
use the same run ID, evidence root, lock, instance, and case limit; a completed
resume reuses evidence instead of repeating Agent or Judge work.

### Verified boundary

On 2026-07-30, main-workspace run
`run-48217ad3214649dea9ff7e06c23d1625` completed one Agent operation, one Judge
operation, and one correct result. Exact resume completed in zero seconds and
added no evidence. Provider-free tests also cover the fifty-case plan and fake
Agent/Judge end-to-end behavior.

This establishes `Verified-bounded`. It does not establish a fifty-case score,
the 125-case paper result, or paper-score reproduction.

## Troubleshooting

- `benchmark source lock is invalid`: pass a quoted absolute path such as
  `"$PWD/outputs/manual/.../source-lock.json"`, not a bare relative
  `FRESH_LOCK`.
- Resume cannot find or match a run: use the run ID and evidence root produced
  by the same `run` command. A historical run ID cannot resume inside a new
  empty evidence root.
- Provider authentication unexpectedly fails: inspect inherited process
  variables because they override values loaded from `.env`.
- A planned instance is rejected: its catalog identity exists, but its
  implementation is not executable yet. Implement and promote it together with
  its runbook before attempting lock, plan, or run.
