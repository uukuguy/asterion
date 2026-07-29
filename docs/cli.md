# Asterion CLI

## Benchmark

`asterion benchmark` coordinates generic benchmark planning and execution through
an injected host boundary. The generic command accepts exact public selectors and
bounded limits only; product-specific datasets, corpora, launchers, prompts,
providers, and budget amounts are not command-line authority.

Plan a deterministic, body-free benchmark plan:

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

`plan` prints the deterministic plan, does not create evidence, and does not
load benchmark implementations. `run` and `resume` print the public run result
after the host records evidence; both reject before host loading unless
`--execute`, `--capability-source-lock`, and `--evidence-root` are present.
