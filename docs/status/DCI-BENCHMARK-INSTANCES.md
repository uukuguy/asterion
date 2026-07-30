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
| `dci.qa.bamboogle.github-sample50@1.0.0` | `qa.bamboogle.github-sample50` | implemented | External-limited | 50 | provision Pi checkout/CLI, operator environment, and basic resources |
| `dci.qa.bamboogle.paper-full125@1.0.0` | `qa.bamboogle.paper-full125` | planned | Not rerun | — | separate paper-full authorization design |
| `dci.qa.hotpotqa@1.0.0` | `qa.hotpotqa` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.musique@1.0.0` | `qa.musique` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.nq@1.0.0` | `qa.nq` | planned | Not rerun | — | lock finite range and implement |
| `dci.qa.triviaqa@1.0.0` | `qa.triviaqa` | planned | Not rerun | — | lock finite range and implement |

## Verification evidence

`Verified-local` for `dci.local-fixture@1.0.0` is established by:

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark_installed
```

That test builds the wheel, installs it into an isolated environment, invokes
the installed `asterion-dci` entry point, executes all 15 fixture tasks, and
resumes the exact run without repeated work. It performs zero Agent and zero
Judge operations and uses no external benchmark data.

The Bamboogle implementation has provider-free and fake-dependency test
coverage. On 2026-07-30, the exact 50-case plan succeeded without execution:

```bash
uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output FRESH_LOCK
uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases \
  --capability-source-lock FRESH_LOCK
```

The public plan selected the exact Bamboogle suite/task with `case_limit: 50`.
Planning created no execution evidence and performed zero Agent or Judge
operations.

`uv run asterion-dci preflight` then reported these body-free categories:
Agent authentication, Agent selection, Judge, and Node passed; the Pi checkout,
built Pi CLI, operator environment, and basic resources were unavailable.
Verification is therefore `External-limited`. Selected execution cases were
zero, provider operations were zero, and external data/network were not used.
The following authorized commands were deliberately not run:

```bash
uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock FRESH_LOCK \
  --evidence-root FRESH_EVIDENCE \
  --execute
uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --run-id RETURNED_RUN_ID \
  --case-limit 1 \
  --capability-source-lock FRESH_LOCK \
  --evidence-root FRESH_EVIDENCE \
  --execute
```

The 50-case benchmark was not executed.
