# Hermetic Promotion npm Cache Design

## Goal

Make the npm portions of `make promotion-check` deterministic and offline when
an operator provides one declared, pre-populated npm content cache.  Preserve
the existing closed subprocess boundary: no proxy, credentials, user npm
configuration, host HOME, or ambient npm cache enters promotion.

## Decision

`tools/check_promotion.py` will accept one explicit `--npm-cache PATH` option.
The Make target will pass `ASTERION_PROMOTION_NPM_CACHE` only as that argument;
it will not export npm configuration into child processes.

The option is an operator-owned tool resource, not packaged evidence and not a
manifest field.  Its root must be an absolute, existing, non-symlink directory
that resolves successfully before any promotion command starts.  A missing,
relative, malformed, or symlink root fails closed with a redacted promotion
error.

The canonical cache root is threaded as an explicit `Path` into each npm
execution environment:

- the isolated external Prime source checkout;
- the isolated operational Prime checkout; and
- npm commands in the copied-project promotion runner.

Those environments retain their private temporary directory and empty
user/global npm configs, while adding only:

```text
NPM_CONFIG_CACHE=<canonical declared cache path>
NPM_CONFIG_OFFLINE=true
NPM_CONFIG_REGISTRY=https://registry.npmjs.org/
```

They do not inherit `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, tokens,
`NPM_CONFIG_*` settings, `HOME`, or `.npmrc`.  Every `npm ci` runs with
`--offline --ignore-scripts --no-audit --no-fund`; no online or
`--prefer-offline` fallback exists.  Existing lockfiles remain the dependency
authority; their npm integrity values constrain requested archive bytes.

## Boundary and Limit

This makes the sealed npm phase offline **given a populated declared cache**.
It does not claim that a cacheless cold machine can perform promotion.  CI must
restore or otherwise provision the same explicit cache resource before invoking
promotion.  The cache remains operator-owned mutable tooling, so it is not
treated as immutable evidence; promotion still creates clean checkouts and
verifies the existing source, operational, and package locks.

The project-wide non-npm steps are not broadened by this design.  In particular
this work does not run a model, Docker worker, network benchmark, or ARC task.

## Tests

Tests must prove that invalid cache paths reject before command execution; that
all relevant child environments contain only the canonical cache/offline/fixed
registry additions and redact hostile proxy/token variables; that each npm
install command is explicit offline/no-scripts; and that cache misses do not
retry online.  Existing standalone-repository and Makefile assertions will be
updated to reflect the declared-cache contract.
