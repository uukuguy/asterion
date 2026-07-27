# Local Package Catalog

## Explicit local roots

The catalog turns operator-selected directories into a deterministic set of
validated `asterion.capability/v1` manifests. Roots are explicit configuration owned by
the local caller; they are not accepted from an agent request, model response,
package manifest, or provider payload.

Discovery follows these rules:

- **Direct JSON children only.** It does not recurse and ignores non-JSON files.
- Roots and results are canonicalized and sorted, so argument and filesystem
  enumeration order do not change the catalog.
- Every JSON document must be an object conforming to the canonical package
  validator.
- Duplicate canonical roots and duplicate `capability_id@version` identities are
  rejected rather than resolved by hidden precedence.

## Exact capability_id@version selection

Selection requires exact `CapabilityRef` values. There is no highest-version rule,
range syntax, prerelease policy, dependency solver, lockfile, or implicit
upgrade. Requested refs are deduplicated, validated against the catalog, sorted,
and returned as deep-fresh manifest mappings.

```python
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef, discover_capabilities
from asterion.capabilities.composition import compose_capabilities

catalog = discover_capabilities(
    [
        Path("src/asterion/capabilities/dci_research/manifests"),
        Path("src/asterion/capabilities/controlled_code/manifests"),
    ]
)
refs = (
    CapabilityRef("policy.local-corpus", "1.0.0"),
    CapabilityRef("dci.research", "1.0.0"),
    CapabilityRef("dci.evaluation", "1.0.0"),
    CapabilityRef("protocol.observability", "1.0.0"),
)
manifests = catalog.select(refs)
composition = compose_capabilities(
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
print(composition.capability_ids)
```

Discovery and selection do not replace composition. The catalog establishes
local source and exact identity; the composer checks capability, policy, event,
artifact, and cycle relationships.

## Filesystem and execution boundary

Callers provide physical root paths: no component may be a symbolic link, and
discovery does not call `resolve()` to turn an alias into an accepted root.
Absolute roots are walked from a pinned `/` descriptor; relative roots are
walked from a pinned current-directory descriptor. Every component is opened
relative to the preceding descriptor with `O_DIRECTORY | O_NOFOLLOW`. A `..`
component is rejected. Empty paths and `.` select the pinned starting
directory, while normalized empty and `.` components are ignored.

All descriptors are registered for cleanup immediately after each successful
open and remain pinned until discovery finishes or unwinds for any exception,
including interrupts. Direct child names are enumerated relative to the final
root descriptor, each JSON child is opened relative to the same descriptor
with no-follow semantics, its regular file identity is validated with `fstat`,
and its body is read only from the pinned descriptor. Source provenance is
constructed from the final pinned root path and enumerated child name;
discovery never re-resolves the child pathname after opening it.

Platforms without descriptor-relative open/list/stat, no-follow directory and
file opens, or pinned-descriptor path provenance fail closed rather than using
an unsafe path-based fallback. Missing roots, file roots, duplicate roots,
unreadable or malformed documents, non-object JSON, protocol-invalid manifests,
and duplicate identities fail the whole discovery operation.

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
uv run python -m unittest -v tests.test_capability_execution
make test-typescript
```
