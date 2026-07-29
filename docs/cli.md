# Asterion CLI

## Benchmark

`asterion benchmark` creates generic benchmark plans from installed application
and capability metadata. Execution remains behind an embedding host's explicit
authorization, implementation, executor, and evidence boundaries. The command
accepts exact public selectors and bounded limits only; product-specific datasets,
corpora, launchers, prompts, providers, and budget amounts are not command-line
authority.

Plan an immutable, body-free benchmark plan from an ordinary installation:

```bash
asterion benchmark plan --application ID@VERSION --suite ID@VERSION
```

Run a benchmark only after explicit external authorization:

```bash
asterion benchmark run \
  --application ID@VERSION \
  --suite ID@VERSION \
  --capability-source-lock PATH \
  --evidence-root PATH \
  --execute
```

Resume a benchmark run only after explicit external authorization:

```bash
asterion benchmark resume \
  --application ID@VERSION \
  --suite ID@VERSION \
  --run-id ID \
  --capability-source-lock PATH \
  --evidence-root PATH \
  --execute
```

Common options:

- `--case-limit N` sets a positive bounded case count. When omitted, the selected
  suite default is used by the host plan.
- `--capability-source-lock PATH` selects the exact capability package source
  lock required for execution.
- `--evidence-root PATH` selects the private evidence root required for execution
  and resume.

`plan` prints the plan, does not create evidence, and does not load capability
implementation providers. The plain installed CLI intentionally has no execution
authority. An embedding host may supply that authority and the exact
implementations; then `run` and `resume` print the public result after evidence is
closed. Both commands reject before implementation loading unless `--execute`,
`--capability-source-lock`, and `--evidence-root` are present.

## DCI application adapter

`asterion-dci benchmark` is a product adapter over the same generic host API.
It fixes the application selector to `dci.complete-application@1.0.0` and the
default suite to `dci.all@1.0.0`; it does not contain a task loop, composer,
source scanner, process runner, or evidence writer.

Installed DCI suite identities are:

- `dci.github@1.0.0`: 12 exact GitHub-reference tasks.
- `dci.paper-main@1.0.0`: 13 exact paper-main tasks.
- `dci.all@1.0.0`: 15 tasks, including both distinct Bamboogle variants.

Use `asterion-dci benchmark plan --case-limit 1` for the DCI-default public
plan. `run` and `resume` retain the generic `--execute`, source-lock, private
evidence, cancellation, and compatibility rules. Dataset/corpus roots,
credentials, provider environment, and optional amount are private
application/operator inputs and never enter package manifests, plans, or
public evidence.
