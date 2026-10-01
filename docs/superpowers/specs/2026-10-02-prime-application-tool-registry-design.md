# Prime application tool registry design

## Goal

Promote application-level tool registration to a Prime-level module contract. The
Prime runtime must consume an application-supplied, immutable tool registry
through its existing preflighted launch seam. P7 remains the owner of ARC tool
implementations and semantics; the Prime layer owns only the registration
protocol, canonical names, validation, and module capability gate.

This change also closes the currently observed drift between the Python P7
allowlist, the TypeScript extension source, and the checked-in bundled
extension resource.

## Boundaries

The generic Prime registry is domain-neutral. It contains no ARC prompts,
credentials, commands, game state, or P7 implementation imports. A registry
entry identifies a tool by its canonical name and module capability; execution
continues through the existing Pi method-call bridge.

P7 owns the concrete registry and the implementation behind each method. The
P7 broker, operator, IPython facade, and live worker remain responsible for
method semantics and redaction. P1–P6 continue to receive the default Prime
registry containing only `ipython`.

## Architecture

### Generic Prime contract

Add a small immutable registry module under `src/asterion/agents/prime/`.
`PrimeApplicationToolRegistry` validates a module identifier, an internal
capability identifier, and a tuple of non-empty canonical tool names. Names
must be unique and in the repository's canonical sorted order. The registry
exposes only read-only metadata and `allowed_tool_names`; it cannot register,
discover, or execute implementations.

The registry's module capability is an exact runtime gate, not a manifest
authority. The public `prime.tool.ipython` runtime capability remains unchanged.
The P7 launch seam carries the concrete registry and the P7 runtime accepts it
only when the application, version, module id, and capability id all match the
P7 contract. A Prime application with no P7 registry therefore cannot expose a
P7 tool by configuration alone.

### P7 concrete registry

Add a P7-owned registry module containing the canonical P7 tool names and the
P7 module capability id. Move the current `P7_APPLICATION_TOOL_NAMES` source
from `p7/live.py` to this module and retain a compatibility re-export from
`live.py` while callers migrate. The P7 prompt registry remains responsible for
rich prompt descriptions, but its registered names must be checked against the
concrete registry so prompt-only additions cannot silently become executable
tools.

`PrimeLaunch` carries the immutable registry supplied by the P7 operator. The
P7 operator creates it during preflight; the runtime validates it before
constructing `AsterionPrimeSession` and passes its names to the existing
execution kernel. No runtime code scans source files or discovers tools.

### Runtime dependency direction

Move the P7-specific runtime binding implementation and P7 launch material into
the P7 application package, leaving the Prime root binding as a thin dispatcher
that lazily selects P1–P7 bindings. The dispatcher and generic session import
the Prime registry protocol only. This removes the current Prime-root import
of `p7.live` and keeps P7 semantics behind the selected application boundary.

### TypeScript and bundled resource

Make the TypeScript extension's registered tool names equal to the P7 concrete
registry's canonical set. `toolNames()` and `createAppLevelTools()` must derive
the same sorted set, including the experience and hypothesis tools already
implemented by the Python bridge. Add a package resource sync/check command so
`src/asterion/applications/prime/resources/ipython-extension.mjs` is produced
from the tested TypeScript source rather than being an independently edited
copy. The check fails on source/resource drift and on tool-name drift.

The cross-language check compares the Python registry, TypeScript
`toolNames()`, registered tool names, and the bundled resource. It does not
move P7 implementation code into the generic Prime package.

## Data flow and failure behavior

1. P7 operator preflight constructs the concrete registry and places it in the
   immutable `PrimeLaunch` value alongside the already-pinned extension lease.
2. P7 runtime binding verifies exact application identity, registry module and
   capability, extension identity, and launch fingerprint before starting Pi.
3. The session receives only the registry's immutable name tuple. Unknown tool
   calls remain rejected by the existing Prime execution kernel.
4. Missing, mutable, duplicated, unsorted, cross-module, or P7-injected-into-
   non-P7 registries fail closed with the existing runtime configuration error.
5. Registry validation errors never expose prompts, credentials, command lines,
   private paths, or bridge payloads.

## Tests and verification

Write failing tests before implementation for:

- registry immutability, canonical ordering, duplicate/name validation, and
  exact module capability checks;
- P7 preflight/runtime acceptance and rejection of a wrong or missing registry;
- non-P7 Prime sessions retaining `ipython` only;
- P7 prompt registrations matching the executable registry;
- Python, TypeScript source, registered tool names, and bundled resource having
  one exact canonical set;
- resource sync/check detecting a stale bundle;
- existing live bridge dispatch and P7 solve/gameplay behavior remaining intact.

Run the focused Python and TypeScript tests first, then the repository checks
appropriate to the changed surfaces (`make test`, `make lint`, `make docs-check`,
`make check`, and `make promotion-check` when the packaged resource changes).
The final verification report must name the passing commands and identify any
external-limited or not-rerun boundary explicitly.

## Independent review gate

After implementation and verification, request an independent code review of
the changed source, tests, packaging/resource sync, and dependency direction.
Resolve all material findings, rerun the affected checks, and only then report
completion. The review must specifically inspect fail-closed behavior, P7
capability isolation, cross-language registry drift, and preservation of the
existing bridge dispatch contract.

## Non-goals

- No generic Prime module may import P7 code or contain ARC-specific semantics.
- No registry discovery, source scanning, ranges, registries, or symlink
  traversal are introduced.
- No new provider/model/cost/deadline controls are exposed to users.
- No unrelated refactor of the repeated P1–P6 runtime session implementations
  is included in this change.
