# Local Package Catalog

## Explicit local roots

The catalog turns operator-selected directories into a deterministic set of
validated `dci.package/v1` manifests. Roots are explicit configuration owned by
the local caller; they are not accepted from an agent request, model response,
package manifest, or provider payload.

Discovery follows these rules:

- **Direct JSON children only.** It does not recurse and ignores non-JSON files.
- Roots and results are canonicalized and sorted, so argument and filesystem
  enumeration order do not change the catalog.
- Every JSON document must be an object conforming to the canonical package
  validator.
- Duplicate canonical roots and duplicate `package_id@version` identities are
  rejected rather than resolved by hidden precedence.

## Exact package_id@version selection

Selection requires exact `PackageRef` values. There is no highest-version rule,
range syntax, prerelease policy, dependency solver, lockfile, or implicit
upgrade. Requested refs are deduplicated, validated against the catalog, sorted,
and returned as deep-fresh manifest mappings.

```python
from pathlib import Path

from dci.framework.package_catalog import PackageRef, discover_packages
from dci.framework.packages import compose_packages

catalog = discover_packages(
    [
        Path("src/asterion/capabilities/dci_research/manifests"),
        Path("src/asterion/capabilities/controlled_code/manifests"),
    ]
)
refs = (
    PackageRef("policy.local-corpus", "1.0.0"),
    PackageRef("dci.research", "1.0.0"),
    PackageRef("dci.evaluation", "1.0.0"),
    PackageRef("protocol.observability", "1.0.0"),
)
manifests = catalog.select(refs)
composition = compose_packages(
    manifests,
    host_capabilities={"filesystem.read", "shell"},
    host_events={
        "artifact.created",
        "run.completed",
        "run.started",
        "tool.result",
    },
    host_artifacts={"text/plain"},
)
print(composition.package_ids)
```

Discovery and selection do not replace composition. The catalog establishes
local source and exact identity; the composer checks capability, policy, event,
artifact, and cycle relationships.

## Filesystem and execution boundary

Symlinks are rejected for both roots and manifest files before canonicalization
can hide them. Missing roots, file roots, duplicate roots, unreadable or malformed
documents, non-object JSON, protocol-invalid manifests, and duplicate identities
fail the whole discovery operation.

Public errors identify the structural class and may name a local path or exact
identity, but do not echo document contents. Underlying local exceptions remain
chained for debugging.

**No network registry or installation** is part of this surface. It does not
download, publish, cache, import modules, load entry points, run hooks, watch
directories, or mutate catalog roots. It also does not execute packages,
workflows, commands, runtimes, or the Rust sidecar.

Canonical source paths are local operator evidence only. They do not enter
manifests, Agent Runtime Protocol values, prompts, normalized runtime events, or
provider requests.

## Language boundary

Python owns discovery because Python already owns local orchestration and the
reference composer. TypeScript does not implement a parallel catalog in AF-080;
it continues validating all checked-in manifests through the canonical shared
schema.

## Verification

Run these checks from the standalone repository root:

```bash
uv run python -m unittest -v tests.test_package_execution
make test-typescript
```
