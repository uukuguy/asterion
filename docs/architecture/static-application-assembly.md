# Static Application Assembly

## Static planning, not execution

`dci.assembly/v1` binds one runtime identity, exact `package_id@version`
references, and explicit host edges into an immutable `AssemblyPlan`. Resolution
validates those identities and asks the existing package composer to prove the
declared graph. It does not start a runtime, invoke a tool, execute a workflow,
launch the Rust sidecar, or mutate any input manifest.

## Reachability classes

Packaged, bound, composed, executable, and verified are distinct states:

| State | Meaning |
| --- | --- |
| Packaged | The assembly JSON exists in the source tree or wheel. |
| Bound | An installed provider exposes the exact application binding. |
| Composed | The exact package catalog and composer prove every declared graph edge. |
| Executable | The selected runtime factory exists and every executable package has one exact implementation binding. |
| Verified | A named command passed inside the documented boundary. |

The checked-in `src/asterion/applications/dci_agent_lite/assemblies/dci-local-research.json` and
`src/asterion/applications/controlled_code/assemblies/controlled-code-validation.json` files are portable application
descriptions. Their package refs are sorted, unique, and exact: assembly does
not select a highest version, solve ranges, install packages, or access a
registry.

The shipped `dci-agent-lite` provider binds two exact application identities
and four DCI assemblies in total: `dci.research-capability` and
`dci.complete-application`, each with Pi and Claude Code variants. The
standalone `dci-local-research.json` inventory file remains packaged only and
is not provider-reachable.

## Runtime capabilities and host-service capabilities

Runtime capabilities are declared by the selected Agent Runtime Protocol
manifest. The assembly's `runtime_id` must match that manifest exactly. This
keeps equivalent Pi and Claude Code capability mappings interchangeable while
retaining an auditable runtime identity.

Host-service capabilities are supplied by application infrastructure rather
than the selected agent runtime. For DCI, `corpus.local-root` is the operator
owned directory authority for research assemblies, and
`evaluation.answer-judge` is the operator-owned Judge authority for complete
assemblies. For example, `executor.controlled` is an explicit host capability
in the controlled-code assembly; it is not advertised as a native Pi or Claude
Code capability. The resolver combines these two sets only for static
composition and preserves their ownership in the source manifests.
The research assemblies declare only `corpus.local-root`. The complete
assemblies add `evaluation.answer-judge`. `corpus.local-root` pins the owned
directory descriptor before process start; it is working-directory authority,
not command authorization or an OS sandbox.

The application host selects the runtime binding, opens all declared services
in one lifetime scope, then constructs the runtime with the immutable,
redacted service mapping. Missing, ambiguous, or invalid service authority
fails before package or runtime work.

Complete DCI evidence also binds a 65-resource product implementation digest.
That digest covers the exact DCI product modules, selected manifests and
assemblies, and their packaged resources. Generic framework/runtime source is
an external contract boundary represented separately by exact package/runtime
identities; it is not silently folded into the DCI product digest.

## Failure and security boundary

Resolution must fail closed on an invalid assembly or runtime manifest, a runtime
identity mismatch, an unknown exact package ref, or any missing composition
edge. Public errors describe the structural failure without echoing manifest
content. Assembly manifests cannot carry prompts, credentials, provider/model
configuration, transports, executable paths, commands, mutable state, or
adapter-private objects.

## Language ownership

Python owns resolution because it owns catalog discovery and the reference
composer. TypeScript validates the same canonical assembly schema and exports
the public manifest type, but deliberately contains no second resolver,
catalog, or composer. Rust remains the controlled execution service and does
not participate in static application planning.

## Verification

Run these checks from the standalone repository root:

```bash
uv run python -m unittest -v tests.test_application_selection
uv run asterion verify --provider dci-agent-lite --level acceptance
make check
make promotion-check
```
