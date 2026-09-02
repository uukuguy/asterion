# Prime Platform-Neutral Release Recipe Design

**Status:** Approved direction — 2026-09-03

## Purpose

Replace the synthetic, single-architecture Prime IPython image-input lock with
an honest release pipeline that is platform-neutral by default.  A release
recipe describes the source and build closure independently of a runtime
target.  Exact target artifacts are separate, finite records and never imply
fallback, host inference, or cross-architecture equivalence.

This is P1 infrastructure for `prime.ipython-coding/v1`, not an end-to-end
PASS.  It preserves the seven-product Prime program and does not redefine
Prime as a Docker product.

## Decisions

1. The default release recipe contains no `os`, `architecture`, or variant.
   A caller must explicitly choose a complete target descriptor when creating
   a target proposal, assembling an image, or exercising a runtime.
2. The initial candidate policy contains exactly `linux/arm64` and
   `linux/amd64`, both with explicitly absent variants.  This policy is not a
   promoted catalog and does not claim either target is supported.
3. `linux/arm64` is the first engineering candidate because the current
   Darwin-arm64/OrbStack host can expose arm64 closure and compatibility
   failures without instruction-set emulation.  Any result from that host is
   still `External-limited/desktop-vm`; it cannot establish supported-native
   or `bounded-sandboxed` evidence.
4. A target becomes supported only after an independently reviewed,
   non-emulated native-Linux replay on the same exact descriptor.  The first
   formally supported target follows the first available approved native
   Linux runner; the product architecture is not preselected by this order.
5. A multi-platform distributable is a later OCI index which binds each exact
   target to its input-lock digest, OCI child-manifest digest, and OCI config
   digest.  It never turns one platform image into a generic image.

## Recipe and Target Model

`ReleaseRecipe/v1` is code-owned and binds:

- the exact pinned Prime source triple: commit, source-tree SHA-256, and
  package-lock SHA-256;
- Python 3.11, exact base distribution and libc family;
- exact Node version and the source package-lock build recipe;
- an exact Python dependency closure, including a locally built
  `prime-agent-runtime` 0.1.0 wheel from pinned source;
- fixture and frontend recipe revisions; and
- the metadata parsers and claim-binding revision used for acquisition.

It excludes OCI target descriptors, URL locators, credentials, host paths,
operator configuration, mutable state, and execution authority.

`CandidateTargetPolicy/v1` is a separate, sorted code-owned set of exact
descriptors.  Proposal generation and release staging may admit only a target
in this policy plus the exact recipe identity.  They must not consult the
promoted image-input catalog.

`PromotedImageInputCatalog/v1` contains only independently reviewed real
locks.  It may be empty.  Runtime/verification resolution requires an exact
requested descriptor and fails closed with `missing-promoted-target` when no
matching lock is present.  The existing size-one CPython-3.12/x86_64 record
is a synthetic test fixture, not a promoted authority.

## Artifact Closure

Every target proposal binds real size and SHA-256 values for a complete
artifact graph.  Metadata records and fetched objects are distinct: a
code-owned parser revision must prove that captured metadata declares the
captured object's exact digest and size.  Metadata and object bytes are never
required to have the same digest or size.

The following are target-specific and must be independently acquired and
locked for each target:

- base OCI child manifest, config, and layers;
- Node archive;
- canonical Linux `node_modules` archive, including platform optional
  dependencies;
- all ABI/glibc-specific Python binary wheels; and
- assembled image child-manifest and config identities.

Pinned source, fixtures, pure-Python wheels, and a frontend build output may
be shared only when independently reproduced and byte-equal; they are still
listed in each target lock.  SDists, version ranges, tags, base image indexes
in place of child manifests, host-native package installation, and networked
startup installation are rejected.

The assembled runtime has root-owned read-only
`/opt/prime-kernel/bin/python`, identifies it with
`PRIME_AGENT_KERNEL_PYTHON`, contains Python 3.11 and the complete locked
closure, and contains no `uv`-based or other startup dependency installation.
Offline assembly uses `--network=none --pull=never`.

## Evidence Ladder

| Stage | Permitted host | Result | It does not prove |
|---|---|---|---|
| Proposal | Any host | `untrusted` proposal | artifact verification or release authority |
| Full artifact verification | Any host | exact input bytes | platform execution or isolation |
| Compatibility exercise | matching desktop VM or native Linux | target/substrate-bound functional result | supported-native unless the substrate is approved native Linux |
| Supported-native replay | matching approved native Linux, non-emulated | target-native functional receipt | `bounded-sandboxed` |
| Bounded scenario | approved native Linux plus worker attestation, cleanup, broker, fixed IPython scenario | `bounded-sandboxed PASS` when every existing gate passes | support for another platform |

All public proposal output is URL-redacted; it may expose only a deterministic
locator digest.  Proposal data is not parseable as an image input lock or a
verified artifact proof.

## Required Failure Behavior

- Missing target, unknown target, duplicate policy target, variant mismatch,
  host-derived target, range, engine fallback, and emulation substitution
  fail closed.
- Target proposal/staging rejects a source triple or recipe identity other
  than the pinned one.
- A promoted lock parser accepts only exact code-owned promoted records;
  candidate policy membership never promotes a record.
- Any missing, extra, symlinked, wrong-sized, or wrong-hash artifact causes
  full-set verification failure.
- Desktop-VM and emulated results remain `External-limited` even when Prime
  functionally starts.

## Delivery Order

1. Add recipe, candidate-policy, metadata/object claim, and empty-catalog
   contracts; migrate the synthetic record into test-only fixtures.
2. Generate a real arm64 proposal with the exact recipe; capture and inspect
   a complete artifact closure without granting promotion authority.
3. Assemble it offline and perform a target-bound desktop-VM arm64
   compatibility exercise, explicitly external-limited.
4. Repeat on an approved native Linux arm64 runner, review it, and promote
   only if the full native receipt is valid.
5. Reproduce the same recipe for native Linux amd64 and promote it only after
   its independent replay/review.
6. Add a closed OCI index contract after both targets have promoted locks.
7. Use a promoted target in the existing worker, broker, cleanup, persistent
   IPython, RLM, and continual-harness scenario work; only the complete
   evidence chain may satisfy `prime.ipython-coding/v1`.

## Acceptance Criteria

- The recipe has no platform field; every target-sensitive operation requires
  one exact descriptor.
- Arm64 and amd64 proposals cannot exchange target-specific artifacts, and no
  policy/catalog/runtime path falls back between them.
- Every real proposal has non-placeholder bytes, exact source/recipe identity,
  and metadata-to-object claims, yet is still untrusted.
- A promoted root passes the full no-follow artifact verifier and a synthetic
  fixture cannot be promoted.
- The kernel environment is Python 3.11, offline at startup, and completes
  the pinned upstream ready imports/harness API checks.
- All evidence includes target, input-lock digest, output image identity,
  substrate, and emulation state; only the complete approved-native worker
  chain may claim `bounded-sandboxed PASS`.
