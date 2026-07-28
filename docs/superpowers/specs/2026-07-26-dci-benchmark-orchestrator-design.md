# DCI Benchmark Orchestrator Design

> **Superseded by Plan 4 Task 5:** Retired global DCI launcher/orchestrator references in this historical document are replaced by the generic benchmark host and package-owned benchmark bindings.

> Approved direction: provide one operator-run entry point that walks the
> Asterion DCI benchmark inventory sequentially, with bounded defaults, clear
> progress logs, and no monetary fields unless a future design adds them.

## Context

Asterion already exposes the individual DCI benchmark profiles and the
standalone launchers derived from the fixed upstream DCI-Agent-Lite revision.
It also records the paper's main-result dataset inventory, including the two
BEIR datasets and the paper's complete 125-row Bamboogle selection. Running
these one by one currently requires the operator to discover commands, keep
output roots separate, and track progress manually.

The operator has already downloaded all datasets and corpora and configured
their locations in the repository `.env`. This feature therefore coordinates
existing benchmark capability; it does not provision resources or attempt a
strict paper reproduction.

## Goals

- Add `scripts/run_dci_benchmarks.sh` as the stable operator entry point.
- Cover the fixed upstream GitHub launcher suite, the paper main-result
  benchmark inventory, or their union.
- Default to a one-query, single-concurrency preview and require an explicit
  `--execute` before provider-backed work.
- Run executable tasks sequentially and stop on the first failure.
- Give every task a distinct private output directory and log.
- Emit timestamped, useful progress without exposing data, credentials,
  provider payloads, or private absolute paths.
- Resume compatible task outputs when the same run directory is reused.
- Make unavailable or method-incomplete inventory entries visible as `SKIP`
  with a stable reason instead of presenting them as completed.

## Non-goals

- No paper-score, published-score, or full paper reproduction claim.
- No use of `asterion-dci paper reproduce`.
- No dataset or corpus download, conversion, repair, or source scanning.
- No implicit provider execution from `.env`, cached results, or prior
  evidence.
- No USD budget, price, or monetary amount prompt or flag.
- No cross-task parallelism, retry policy, scheduler, or service startup.
- No changes to benchmark, package, assembly, or runtime wire contracts.

## Selected structure

The public entry point remains a shell script:

```bash
scripts/run_dci_benchmarks.sh [OPTIONS]
```

The shell entry point delegates argument validation, dotenv loading, task
planning, subprocess execution, and logging to a small Python coordinator under
`tools/`. Python is used because it owns orchestration in Asterion and can load
dotenv syntax without evaluating `.env` as shell code. The coordinator only
invokes existing repository launchers or the existing `asterion-dci benchmark`
CLI; it does not become a second benchmark runner.

## Command contract

Supported options are:

```text
--suite github|paper-main|all
--limit POSITIVE_INTEGER
--max-concurrency POSITIVE_INTEGER
--output-root PATH
--env-file PATH
--execute
--help
```

Defaults are:

```text
--suite all
--limit 1
--max-concurrency 1
--env-file <repository>/.env
plan-only (no --execute)
```

`--output-root` defaults to a new run directory below the output root resolved
from `.env`; if no configured output root is available, it uses the existing
repository-local Asterion output area. The public summary prints an opaque run
label and relative artifact names, not the resolved absolute root.

There are deliberately no monetary options. The coordinator prints a startup
warning that the direct benchmark command has no USD ledger and that
`--limit`, per-benchmark concurrency, and sequential task execution are the
operator's bounds.

Plan-only mode validates arguments and builds the exact ordered task list. It
prints what would run or skip, performs no Agent or Judge operation, and
creates no task output directories. `--execute` is the only switch that starts
provider-backed benchmark subprocesses.

## Suite definitions

`github` represents the 12 launchers preserved from
`DCI-Agent/DCI-Agent-Lite@271f37e71f053bf0c99c05ce6d2fb53b841d922e`:

- BrowseComp-Plus main and level-3 launcher variants;
- BRIGHT biology, earth science, economics, and robotics;
- 2WikiMultihopQA, Bamboogle sample-50, HotpotQA, MuSiQue, NQ, and TriviaQA.

`paper-main` represents the 13 Asterion paper benchmark dataset identities:

- BEIR ArguAna and SciFact;
- the four BRIGHT datasets;
- BrowseComp-Plus main;
- the six QA datasets, using the complete 125-row paper selection for
  Bamboogle.

This suite is benchmark-oriented. Paper-unreported IR duplicate handling is
identified as the Asterion benchmark metric and is never described as a
reported paper method. Inventory entries that do not have an executable
benchmark binding, including method-incomplete ablations, produce `SKIP`
records with their packaged reason.

`all` is the deterministic union of both suites by benchmark task identity.
Exact duplicates run once. Selection variants remain distinct, so GitHub
Bamboogle sample-50 and paper-main Bamboogle-125 are separate tasks. The
resulting executable plan has 15 task variants when all current bindings are
available.

The task inventory is explicit and repository-owned. The coordinator does not
scan source trees, infer launchers, or silently add future profiles.

## Environment and resource handling

The coordinator loads the selected dotenv file with the project's existing
dotenv support. It passes the resulting environment to child processes while
preserving explicit process-environment overrides. It never sources or
evaluates `.env` as shell code.

The following configured surfaces may be consumed by existing DCI commands:

- resource, corpus, output, Pi, and runtime working roots;
- Agent runtime/provider/model configuration;
- Judge configuration;
- provider credential variables.

Only variable presence and redacted readiness status may appear in logs.
Values, credentials, absolute private paths, and resolved provider
configuration must not be printed or persisted in the coordinator's public
summary.

Before execution, the coordinator performs the existing provider-free
benchmark resource check against the loaded environment. A failed check stops
before the first Agent or Judge operation. It never invokes resource setup or a
download path.

## Task execution

For each executable task, the coordinator:

1. Allocates a deterministic, filesystem-safe task name below the selected run
   root.
2. Creates the task directory with private permissions.
3. Builds the existing launcher or `asterion-dci benchmark` command with the
   exact dataset variant.
4. Appends `--limit`, `--max-concurrency`, `--resume-policy compatible`, and the
   task-specific output root.
5. Runs the task synchronously with the dotenv-derived child environment.
6. Streams redacted child output to the terminal and a private task log.
7. Records the exit status and elapsed time.

The coordinator does not inspect dataset bodies, prompts, answers, retrieved
documents, or benchmark result bodies. Existing benchmark code retains
responsibility for selection, execution, evaluation, artifact validation, and
resume compatibility.

Reusing an explicit `--output-root` reuses the same deterministic child roots
with `--resume compatible`. A new default run receives a new opaque run label.
An incompatible existing batch fails closed through the benchmark runner.

## Logging and summary

Every task transition uses one timestamped line with:

```text
[N/TOTAL] TASK_ID START
[N/TOTAL] TASK_ID DONE elapsed=...
[N/TOTAL] TASK_ID FAILED exit=... elapsed=...
[N/TOTAL] TASK_ID SKIP reason=...
```

The plan begins with suite, task count, limit, concurrency, mode, dotenv
filename, and the no-USD-ledger warning. It does not echo the full command when
that command would contain a private path.

Each task has `runner.log` in its private task directory. The run root has a
body-free `summary.json` containing only task identities, selection variant,
status, exit code, elapsed time, relative artifact/log names, and the
coordinator options. It excludes command lines, environment values, data
bodies, private absolute paths, provider payloads, prompts, answers, and raw
benchmark output.

On the first executable-task failure, no later executable task starts. The
summary is finalized with the failure and remaining tasks marked `NOT_RUN`.
`SKIP` is non-fatal because it represents a known inventory limitation, not an
execution result.

## Failure behavior

The coordinator fails before provider work for:

- an unknown option or suite;
- a missing, non-file, or unreadable dotenv file;
- zero, negative, boolean-like, or non-integer limits/concurrency;
- an unsafe, replaced, or non-private output target;
- a missing repository launcher or unknown packaged task binding;
- a failed provider-free benchmark resource check.

During execution, an interrupt is forwarded to the active child. The
coordinator records the interrupted task as failed, marks later tasks
`NOT_RUN`, finalizes the body-free summary when safe, and exits nonzero.

Public coordinator errors remain stable and body-free. Detailed child output
is confined to the terminal stream and private task log and relies on the
existing benchmark redaction boundary.

## Compatibility

- Existing individual launchers remain valid and authoritative for their
  profiles.
- Existing `.env` variable names and configuration precedence remain
  unchanged.
- Existing benchmark selection, resume, metric, Judge, and artifact behavior
  remain unchanged.
- The new coordinator adds no provider authority to `list`, `describe`,
  `acceptance`, `preflight`, tests, or checks.
- The result is Asterion benchmark evidence. Even when its dataset inventory
  overlaps the paper, it is not automatically paper reproduction evidence.

## Verification

Implementation follows test-driven development and remains provider-free.
Tests use temporary directories, fixture dotenv files containing sentinel
secrets, and fake child commands.

Tests cover:

- default plan-only mode selects the 15-task `all` union, uses limit one and
  concurrency one, starts no child benchmark, and creates no task output;
- `github` and `paper-main` have stable ordered membership and de-duplicate
  exact overlaps;
- Bamboogle sample-50 and Bamboogle-125 remain distinct tasks;
- `--execute` performs the resource check before the first fake benchmark;
- task commands receive the requested limit, concurrency, compatible resume,
  exact variant, and distinct output roots;
- tasks run sequentially and stop at the first failure;
- reusing an explicit run root uses the same child roots;
- known unavailable or method-incomplete entries log `SKIP`, never `DONE`;
- progress lines include sequence, status, and elapsed time;
- the final summary uses only relative artifact names and body-free metadata;
- missing resources, invalid arguments, unsafe output targets, and interrupts
  fail closed;
- sentinel credentials, dotenv values, dataset bodies, prompts, answers,
  provider payloads, and private absolute paths do not appear in public output
  or `summary.json`;
- the real provider-free resource check, focused unit tests, `make check`, and
  `make promotion-check` pass with zero Agent and Judge operations.

No provider-backed benchmark is run during implementation or verification. The
operator invokes `scripts/run_dci_benchmarks.sh --execute` after reviewing the
implementation and choosing the desired suite and limit.
