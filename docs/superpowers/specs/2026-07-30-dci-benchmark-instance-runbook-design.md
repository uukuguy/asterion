# DCI Benchmark Instance Runbook Design

## Goal

Make `docs/status/DCI-BENCHMARK-INSTANCES.md` the authoritative inventory and
operator entry point for every immutable DCI benchmark instance. Whenever an
instance becomes executable, its inventory status and complete operating
instructions must change together.

## Language and terminology

The instance inventory and all explanatory runbook prose are written in
Chinese. Immutable identifiers, CLI commands, environment-variable names, JSON
fields, file names, and literal status values remain unchanged so commands are
safe to copy and public contracts stay exact.

The document distinguishes three different outcomes:

- `dci.local-fixture@1.0.0` is a provider-free framework closure fixture. It
  does not produce an original DCI benchmark score.
- A bounded one-case Bamboogle run verifies the real Agent/Judge capability
  path, but it is not the complete fifty-case benchmark.
- A complete `dci.qa.bamboogle.github-sample50@1.0.0` run selects all fifty
  cases and publishes the aggregate result from `summary.json`. It still does
  not reproduce `dci.qa.bamboogle.paper-full125@1.0.0`, which remains planned.

## Status and documentation invariant

Each instance remains one row in the inventory.

- `planned` instances describe their missing implementation gate and expose no
  runnable command.
- `implemented` instances must have a matching runbook section in the same
  document.
- Verification state remains independent from implementation state. A runnable
  instance may still be `Not rerun` or `External-limited`.
- Historical evidence identifies what was verified, but historical run IDs
  must not appear in copyable execution commands.

A change that promotes an instance to `implemented` is incomplete unless it
also adds or updates the matching runbook and verifies its provider-free
commands.

## Per-instance runbook

Every implemented instance runbook explains:

1. what the instance measures and why it exists;
2. its application, suite, task, default range, and finite maximum when known;
3. whether it accesses models, networks, external datasets, or corpora;
4. required operator-owned resources, credentials, and expected cost class;
5. preflight and readiness checks;
6. absolute lock and evidence paths rooted at `"$PWD"`;
7. source locking and provider-free planning;
8. explicitly authorized execution;
9. extraction of the new run ID from the run result;
10. exact resume using the same instance, range, lock, and evidence root;
11. expected public result and private evidence location;
12. the exact verified boundary and what remains unverified.

The initial runbooks cover:

- `dci.local-fixture@1.0.0`, a provider-free installed closure over all fifteen
  task bindings;
- `dci.qa.bamboogle.github-sample50@1.0.0`, the first real bounded Agent/Judge
  benchmark, defaulting to one case with a finite fifty-case catalog.

## Command safety

Commands assume execution from the repository root and use quoted absolute
paths. They create a new evidence root for a new run. The run result is saved
to an operator-owned file and its `run_id` is extracted with `jq`; resume never
uses a published historical ID.

The Bamboogle runbook separates provider-free lock/plan commands from the
cost-bearing run command. It states that `--execute` grants only the selected
finite run and that prior configuration, readiness, locks, or evidence do not
grant execution authority.

The runbook provides separate copyable workflows for a one-case capability
check and the complete fifty-case GitHub sample evaluation. The complete
workflow uses `--all-cases` consistently for plan, run, and resume, states its
finite maximum of fifty Agent and fifty Judge operations, and shows how to read
aggregate counts and accuracy from the private `summary.json`. Documentation
verification must not execute this cost-bearing workflow.

The troubleshooting section explains:

- relative lock or evidence paths are rejected;
- a run ID can only resume against its original evidence root;
- inherited process environment values override `.env`;
- planned instances cannot be selected for execution.

## Verification

Documentation verification includes:

- `uv run python tools/check_docs.py`;
- `uv run asterion-dci benchmark instances --json`;
- local-fixture lock and plan using fresh absolute temporary paths;
- Bamboogle lock and one-case plan using fresh absolute temporary paths;
- a scan ensuring copyable resume examples contain no fixed historical run ID;
- repository tests that enforce the implemented-instance/runbook invariant.

No Agent, Judge, network, or external dataset operation is needed to verify the
documentation change. Real execution remains separately authorized.
