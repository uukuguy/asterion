# Prime Seven-Scenario Execution Closure Delta

> Status: implementation direction accepted by the user’s 2026-09-05 instruction
> to continue along the evaluated mainline; Astra owns exact contract decisions
> with independent Sol review. Deployment and production evidence remain separate.
> This document does not enable execution, change existing receipt validators,
> populate promoted catalogs, or authorize operator deployment/full benchmarks.

## Objective

Close the seven existing Prime end-to-end scenarios, retaining their IPython,
RLM and Continual Harness semantics. Prime and Native remain parallel runtimes.
Use the implementation already present; correct the execution-contract gaps
that currently prevent real evidence. Do not expand the work into Native parity
or broad framework restructuring.

Canonical worklist: `docs/status/PRIME-TYPICAL-APPLICATIONS.md`.

## Why this delta is required

The existing P1 production redesign correctly rejects authority inside an
adversarial application interpreter. Its current deployment/identity wording
nevertheless has three incompatible assumptions:

1. The local operator uses macOS, but the trusted supervisor's reciprocal peer
   checks require Linux `SOCK_SEQPACKET` and `SO_PEERCRED` in the same kernel.
2. A service-manager-owned `Accept=yes` listener does not identify its later
   accepted child as the client-side socket's original peer PID.
3. The implementation is Python. `/proc/self/exe` identifies its interpreter;
   an interpreter digest alone does not identify authority source/dependencies.

Separately, the current one-request/one-cell P1 workload cannot prove the
original P1 multiple-turn and post-compaction continuity requirements.

## Decision 1: one Linux execution boundary

Run the trusted manager, trusted verification supervisor, untrusted application
child and authority in the same operator-owned Linux guest. The first tested
deployment target may be explicit linux/arm64 on the available local substrate;
portable manifests and release selection retain explicit target identities and
must not infer a default architecture from this development machine.

The macOS command can initiate the installed Linux command, but it is not the
security supervisor described below. A future cross-VM transport is separate
scope. Docker's reported OS/architecture is readiness information, not proof of
the guest identity separation or its installed authority resources.

The manager starts the authority under its dedicated OS identity before the
supervisor connects. The authority creates/binds/listens on the one-shot private
Unix socket itself. The manager retains exact process identity; the supervisor
connects once and verifies the authority UID/PID, while the authority verifies
the supervisor UID/PID. Do not transfer a service-manager-created listening
socket and then expect its original peer credentials to become the child PID.

The manager owns process creation, identity assignment, private configuration
opening, key generation and descriptor transfer. Children cannot supply their
own authoritative expected PID/UID. Exact inherited descriptors cross the
necessary exec explicitly; the entry point immediately sets CLOEXEC before
provider imports or helper launches. No key/config descriptor reaches the
application child. Unknown inherited descriptors close before application work.

The socket serves exactly one client/run, one absolute deadline and one
terminal outcome. The manager reaps the authority and application child on
every outcome and removes only its own socket/workspace artifacts.

## Decision 2: immutable Python authority bundle

Prefer an explicitly enumerated, root-owned CPython runtime bundle over a new
single-file packaging tool or another language's authority implementation.
The bundle contains the interpreter, stdlib, native extensions, required
application/framework modules and third-party dependencies. Its imported code
closure is verified before use and unavailable to application writes. This
preserves Python ownership of orchestration.

The bundle must be installed under a no-symlink, non-application-writable root.
Its release manifest enumerates exact resource identities and immutable file
digests. A selected bundle is not assembled from cwd, user site-packages,
PYTHONPATH, editable installs, or an adjacent source checkout. Cleared
environment and isolated Python startup flags prevent ambient import selection.
System kernel and explicitly declared system libraries remain part of the
operator TCB; this is not a claim to hash the entire OS or resist root compromise.

Maintain distinct identities:

- `interpreter_executable_sha256`: actual selected/executed CPython ELF;
- `authority_bundle_sha256`: the canonical complete code/runtime release;
- `launch_profile_sha256`: the exact launch flags and allowed environment schema,
  containing no private values;
- existing source/application/workload/image/seccomp/receipt/config bindings.

The old `authority_executable_sha256` field must not be reinterpreted as Python
source identity. Introduce an explicitly versioned receipt contract with the
new identities and a discriminator that old readers reject. Old unavailable
receipts remain readable only under their original version and never promote.

The pure admitted-executable aggregate implemented and reviewed in this task
remains a no-execution identity primitive. It does not, by itself, prove this
bundle or authorize launch. Its empty standalone-ELF catalog must not be filled
with an interpreter digest under the old meaning. The new bundle admission is
a separate versioned extension with tests and a reviewed migration.

## Decision 3: separate spine qualification from complete P1 semantics

P1-A qualifies the actual authority/process/Docker/model/oracle/cleanup spine
using the existing fixed one-request coding workload. Its public result states
that exact qualification scope; it cannot close original
`prime.ipython-coding/v1` or cause a full-P1 basic PASS.

P1-B is the complete P1 semantic scenario. Its new exact workload/request/receipt
contract must bind all of:

- multiple finite model turns using IPython as the only built-in action;
- initial failing and final passing independent oracle plus model-caused edit;
- explicit compaction between turns without replacing the kernel/session;
- post-compaction cwd, import, function, namespace and workspace-file witnesses;
- exact source/package/assembly/runtime and admitted worker identities;
- aggregate model usage, cancellation/deadline, cleanup and public-safe evidence.

Do not silently raise the existing closed request limit or mutate a 1.0.0
workload in place. The P1-B implementation plan fixes one bounded preset and
declares its new contract identities before execution; users are not asked to
choose provider/model/cost/deadline knobs. Full benchmarks remain separate.

## Shared spine for P2–P7

Reuse the trusted host execution, exact runtime proxy, cancellation/cleanup and
receipt verification boundaries. Keep each scenario's workload/oracle/finite
limits exact. Reuse existing P2/P3 launchers and P4–P7 worker/reducer modules,
adding only the missing host/launcher connections and public application routes.

Sharing does not mean accepting a caller-supplied executable, arbitrary program,
unrecognized scenario ID or mutable scope. Each admitted scenario is selected
from a code-owned exact set and supplies its own versioned request/oracle.

P6 begins in local/project scope. Global activation requires its explicit
approval. P7 begins with a finite public-subset game scenario; its full-suite
reproduction is a distinct separately authorized deliverable.

## Public verification boundary

The trusted supervisor selects the exact approved verification profile before
loading provider code. It then starts the separate application child with a
fixed request/cancel proxy. The child follows provider → assembly → runner →
Prime runtime, but it never receives a receipt signing key or raw authority
socket and cannot control final rendering/exit status.

Authority receipt verification and application result digest agreement happen
in the supervisor. Worker output, application stdout, in-process fakes and
provider-defined VerificationResult values cannot independently produce a
production PASS. The production runtime factory accepts only the exact proxy
required by the selected scenario; the current blanket rejection of host
services is replaced only after this boundary has real-process tests.

Preflight inspects installation/readiness without starting the workload or
contacting a model. Acceptance validates installed contracts. Basic invokes the
fixed admitted real scenario. These levels remain distinct.

## Implementation and evidence gates

1. Completed: pure P1 aggregate with 42 passing focused tests and independent
   Sol approval; no-execution behavior remains intact.
2. Freeze the versioned bundle/launch/receipt contracts and align the config key
   list with authority_config.py, including socket owner/group/mode/server fields.
3. Deliver a real-process deterministic-backend test under separate Linux
   identities: peer/FD custody, hostile app forgery, cancellation, one terminal,
   cleanup and redaction. This is provider-free boundary evidence only.
4. Build and verify the complete authority bundle, exact worker image and
   seccomp resources. Prepare a reviewable deployment plan before operator
   identity/config/service changes. Existing backend configuration is consumed
   only through explicit operator provisioning; its presence is not authority.
5. Implement killable model transport, existing Docker mechanics and exact
   terminal issuance; connect the trusted public supervisor and runtime proxy.
6. Run finite P1-A, then P1-B; close P1 only with P1-B's complete semantic evidence.
7. Extend the same spine through P2/P3, P4/P5, P6 and P7 bounded functional gates.

Terra owns explicit implementation slices. Luna checks evidence/inventory.
Astra owns cross-scenario semantics and launch/bundle contracts. Sol reviews
material trust-boundary changes and their integrated evidence independently.

## Independent review outcome

Sol confirmed the all-Linux, authority-owned listener topology and recommended
the immutable CPython bundle with separately versioned identities. It also
confirmed the P1-A/P1-B mismatch and the absent supervisor/model-helper/runtime
connections. This review validates the proposal's direction; it does not certify
unimplemented code or imply operator deployment has occurred.
