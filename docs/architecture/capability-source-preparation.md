# Capability Source Preparation

Capability-package sources use one host-owned lifecycle between metadata
discovery and provider loading. The lifecycle applies equally to built-in,
explicit local-directory, and installed-distribution adapters without adding a
method to the public `CapabilityPackageSource` protocol.

## Public operations

`prepare_capability_source(package_ref, sources, lock)` returns one frozen,
process-local `PreparedCapabilityPackage` handle containing:

- the selected digest-bearing `CapabilityPackageCandidate`;
- the validated `PortableCapabilityPayload`; and
- opaque references to the selected source adapter and its original discovered
  candidate, used only by the paired load operation.

The opaque references are excluded from representation and equality. The
prepared handle is not a wire value and must not be serialized or persisted.

`load_prepared_capability_source(prepared)` reopens and revalidates the selected
source using its original discovered candidate, compares the current payload
with the prepared digest, and then loads exactly that provider using the same
original candidate. It returns an `InstalledCapabilityPackage` only when
package ref, source ID, source kind, and payload digest still match the prepared
candidate.

Both operations expose a single redacted preparation error. Adapter-specific
exceptions, private locators, entry-point values, and filesystem paths do not
cross this boundary.

## Selection sequence

```text
validate the exact package request and the complete optional lock
  -> validate the declared source adapters
  -> call discover_metadata on every declared adapter
  -> validate and snapshot candidate values
  -> retain the requested exact package ref
  -> if a lock entry exists, narrow by its exact source ID
  -> reject zero or multiple identity matches
  -> open and validate only the selected payload
  -> create one digest-bearing candidate
  -> apply the existing exact digest lock resolver
  -> return the prepared immutable value
  -> reopen the original candidate and revalidate payload identity and digest
  -> load only the selected provider
  -> verify the installed package identity
```

When no lock entry exists, the requested package must have exactly one
metadata candidate before the host calls `open_payload`. A lock may
disambiguate sources by exact source ID; its payload digest is checked after
the selected payload is opened. Duplicate candidates with the same identity
remain ambiguous.

## Boundary invariants

- Discovery and preparation never call `load_provider`, entry-point `load`, or
  a provider factory.
- After discovery, a lock causes the host to call `open_payload` only for its
  exact source identity. Other candidates remain discovery results.
- Provider loading accepts a prepared value and passes only the privately held
  original candidate back to its selected adapter.
- Payload drift observed by the load-time reopen is rejected before the host
  calls `load_provider`. Drift in the non-atomic interval after that check is
  subject only to the adapter's existing validation and the final installed
  package identity check.
- Candidate metadata remains a safe immutable projection; opaque source state
  is excluded from representation and equality.
- Existing source adapters and external implementations retain the four-method
  `CapabilityPackageSource` protocol unchanged.
- The operation adds no scanning, version ranges, registry lookup, precedence,
  symlink traversal, or execution authority.

The v1 source contract does not identify or lock provider implementation bytes,
and source validation plus provider loading are not atomic. Provider code,
entry-point, or factory drift is outside this lifecycle's detection boundary;
the provider loader remains part of the trusted source adapter. The final check
binds only the declared package ref, source ID, source kind, and payload digest.
An implementation-byte lock or atomic validate-and-load operation would require
a separately designed contract.

The method-call boundary above does not claim that discovery avoids reading
payload resources. Existing local-directory and installed-distribution adapters
validate and hash payloads inside `discover_metadata`; built-in discovery reads
only its descriptor. All three remain compatible because none imports or calls
a provider during discovery. Physically separating metadata discovery from
payload reads would require a new source-adapter contract.

This is a Python host API over the existing closed v1 source/package values. It
does not change a manifest or wire protocol and therefore does not introduce a
new protocol version.
