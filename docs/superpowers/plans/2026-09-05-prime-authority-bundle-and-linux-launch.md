# Prime Authority Bundle and Linux Launch Implementation Plan

> **For agentic workers:** Use the existing delegated Terra implementation lane with independent Sol review. Preserve concurrent edits and exact source locks.

**Goal:** Deliver the trusted Linux execution boundary needed by Prime P1, then reuse it for the remaining six scenarios.

**Architecture:** The operator-owned manager also serves as trusted supervisor and launches authority and application processes under distinct identities in one Linux guest. Authority code runs from an exact immutable CPython bundle; executable, code bundle and launch policy have separate identities. A parsed record never grants execution authority.

**Tech Stack:** Python orchestration and unittest; Linux Unix sockets, peer credentials and process/FD ownership; existing Prime runtime and Docker worker; current public Asterion contracts.

## Development verification scope — user correction, 2026-09-06

The user explicitly prioritizes development over release qualification. Keep
normal-flow tests and focused boundary-control assertions; do not block the
next functional slice on exhaustive fault matrices, native signal-action test
helpers, repeated full promotion runs or production certification. Fix already
demonstrated ownership/redaction defects with narrow regression assertions,
then connect the actual authority IPC and Prime execution path. The detailed
qualification lists below remain later release-reference material wherever
they exceed this development scope. This correction changes verification
intensity, not the runtime/protocol boundaries or the meaning of scenario PASS.

## Global constraints

- Preserve `asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1` and `asterion.application-assembly/v1`.
- Preserve exact legacy authority receipt/IPC parsing. A Python interpreter digest cannot populate the legacy standalone-authority-ELF catalog.
- No provider configuration, executable commands or launch paths enter portable capability/application manifests. Operator release inventories are private deployment inputs.
- Prime and Native remain parallel runtimes. P1-A qualification does not close P1-B multi-turn/compaction semantics.
- Deterministic backend tests prove process boundaries only. Real scenario closure needs finite model execution, trusted oracle, cancellation and cleanup evidence.
- No global harness activation, full ARC benchmark, publication or deployment into an unrelated service.

## Task 1: establish the actual Linux baseline

**Files:** `src/asterion/applications/prime_agent/operator/authority_docker_socket.py`, its exact entry in `resources/authority-artifact-lock.json`, `tests/test_prime_p1_authority_docker_socket.py`.

**Consumes:** existing `_new_daemon_client()` and trusted stdlib socket constants.
**Produces:** working Linux atomic close-on-exec/nonblocking Unix client creation without relaxing external-value validation.

- [x] Reproduce current Linux failure using the existing socket test.
- [x] Accept stdlib `SocketKind` integer constants while preserving zero/missing-flag rejection.
- [x] Add a regression using actual enum-valued constants and refresh only the changed source hash.
- [x] Run all 16 P1 modules on macOS and in an isolated installed Linux environment. Execute the Linux socket/SCM_RIGHTS/memfd tests rather than counting skips as evidence.

## Task 2: exact immutable bundle admission and launch contract

**Create:** `src/asterion/applications/prime_agent/operator/authority_bundle.py`, `tests/test_prime_authority_bundle.py`.

**Consumes:** an operator-selected root, one exact trusted release inventory and platform identity.
**Produces:** an opaque admitted bundle with separate interpreter, complete bundle and launch-profile digests; explicit close and pre-spawn revalidation. No self-registration or authority receipt issuance.

The release inventory enumerates every regular file as a sorted unique relative path, byte length, mode and SHA-256. Reject absolute/traversing/noncanonical paths, symlinks at every component, extra/missing files, duplicate identities, non-root ownership and group/world writes. Root is trusted; the application must be unable to write the bundle. The selected interpreter is a fixed code-owned relative entry and must match its exact Linux ELF target. Never infer compatibility from the current machine.

Canonical bundle hashing binds the exact inventory format/version, target and entries with domain-separated canonical bytes. The launch profile is code-owned and separately hashed; it defines isolated Python startup, cleared environment, fixed bootstrap entry and explicit inherited descriptor roles. The complete import closure includes stdlib, native extensions and dependencies, with explicitly declared system libraries in the operator TCB. No ambient cwd, user-site, editable install or PYTHONPATH import selection is permitted.

- [x] Freeze concrete types/signatures and wire migration: `docs/superpowers/specs/2026-09-05-prime-authority-bundle-contract.md`.
- [x] Implement the frozen module and descriptor-tree helper; Sol approved admission/revalidation after security regressions. Actual process consumer follows in Task 3.
- [x] Verify deterministic identity, mutation and inventory rejection, ownership/symlink checks, closed-state rejection and redaction with sentinel values. Tests cover source/mac and actual root-owned Linux boundaries.
- [ ] Produce a real installed bundle and prove its bootstrap loads only the selected import roots.

## Task 3: manager, supervisor and authority process path

**Development implementation:** `operator/authority_linux_launch.py`, `operator/authority_linux_policy.py`, then `operator/authority_qualification.py`, `operator/authority_qualification_entry.py` and their focused tests. The manager owns the trusted supervisor role; no additional supervisor process is required.
**Integrate:** `authority_process.py`, existing admission/configuration and exact runtime proxy.

**Consumes:** admitted bundle, exact operator identities, finite scenario profile, authority-only configuration and key descriptors.
**Produces:** one authenticated ready/execute/terminal path, final public-safe status rendered by the supervisor, and complete child reaping.

The manager launches authority before connection; authority binds/listens itself. Expected UID/PID values come from the manager, not the application. The supervisor validates reciprocal peer identity and one-run frame sequencing. Required descriptors survive their intended exec only, immediately regain CLOEXEC and never reach the application. The application runs provider → assembly → runner → Prime runtime with an exact proxy. It cannot supply signing keys, choose an executable or render the final trusted result.

- [ ] Run deterministic-backend success/failure/cancellation under actual distinct Linux UIDs, without persistent account changes.
- [ ] Exercise forged application output, wrong peer, FD leakage, replay, timeout and child crash; require one terminal and cleanup before return.
- [ ] Wire preflight to actual side-effect-free readiness and preserve acceptance as installed contract verification.
- [ ] Connect killable model transport and the existing worker/oracle chain only after the process boundary passes independent review.

### First concrete consumer: Linux child launch

Implement the private process primitive in `operator/authority_linux_launch.py`
with `tests/test_prime_authority_linux_launch.py`. It consumes the admitted
bundle and manager-owned configuration, key, runtime-directory and
launch-instance descriptors. This is one component of Task 3, not a second
runner or a claim that the supervisor/IPC/application path is complete.

The callable is `launch_authority_child(bundle, *, config_fd, session_key_fd,
runtime_directory_fd, launch_instance_fd) -> AuthorityLinuxChild`. The child
owner exposes `wait(*, deadline=None)`, `cancel()` and `close()`, plus a private
`_process_identity()` returning the manager's exact `(pid, uid)`. Wait returns
only `exited`, `failed`, `cancelled` or `timed-out`; `exited` means exit code zero,
never an authority receipt or scenario PASS. A supplied absolute monotonic
deadline may only shorten the internal profile deadline. The owner has a sealed
constructor, redacted repr and rejects copying/pickling. Concurrent wait and
cleanup must never reap or signal the same numeric PID after ownership ends.

The manager is a dedicated single-threaded Linux root process. Reject other
platforms, non-root callers and existing additional threads before forking.
Input descriptors transfer on entry, become CLOEXEC immediately, and close on
every rejection. Configuration, key and launch-instance inputs must be regular
sealed memfds (WRITE/GROW/SHRINK/SEAL), with bounded sizes and a 32-byte key;
the runtime directory must have the profile's authority UID/GID and mode 0700.
The primitive validates deployment resources, not scenario authorization.

In the child, duplicate every source descriptor above the fixed descriptor
range before remapping to 3–9, so arbitrary input FD numbering cannot overwrite
another source. Preserve the interpreter only as a CLOEXEC fd-exec input.
Redirect 0–2 to `/dev/null`, close all other descriptors, establish a new session,
apply the exact resource limits and no-new-privileges policy, clear supplementary
groups and permanently set all real/effective/saved UID/GID values. Apply the
profile umask, descriptor-selected cwd, exact argv and empty environment.
No path-exec fallback, shell, caller callback or arbitrary program is accepted.

The immutable bootstrap first uses frozen `os`/`sys` to restore CLOEXEC on 3–9,
before importing ordinary modules. It must reject an ambient interpreter prefix
or module origin. Real startup qualification uses the actual admitted CPython
candidate and a separately identified qualification bootstrap; it never issues
a production receipt. Complete loaded-library mapping admission and the
authenticated authority-owned listener remain mandatory subsequent Task 3 work.

Return only an opaque child owner with bounded wait/cancel/close operations.
Use a monotonic deadline no later than the selected profile limit; kill the
owned process group on cancellation/deadline and reap the direct child on every
outcome. Keep an exited leader unreaped until group cleanup, preventing PID reuse
from targeting another process group. Child output and exception text are never
public output. Tests must cover successful real fd-exec after UID drop,
descriptor collisions/leaks, invalid inputs, failed exec, cancellation,
deadline and idempotent cleanup. Mocked syscall tests alone cannot close this
boundary.

### Independent review corrections for the consumer

- The sealed launch instance contains only pre-fork facts: run/session and
  expected supervisor identity. Authority obtains its own PID from `getpid()`;
  the supervisor compares it with the manager's fork result. The bundle
  contract's reference to dynamic PID fields does not require an unknowable
  pre-fork authority PID. The v1 launch contract is not reused.
- Use a CLOEXEC child-status pipe with a fixed failure byte and finite
  handshake deadline. Return the child owner only after exec closes the pipe,
  so immediate cancellation cannot precede creation of the child's process
  group. EOF is exec-handshake evidence only, not authenticated readiness.
  Reject any failure marker or already-observed abnormal child termination,
  including a signal before exec; always clean up on handshake failure.
- Observe exit with `waitid(..., WNOWAIT)` before group cleanup and direct-child
  `waitpid`. Serialize lifecycle ownership; no later call may signal a reused
  PID after reaping. Enforce the launch-time profile deadline even for `wait()`
  with no argument.
- Before fork, check `/proc/self/task` contains exactly the current TID;
  `threading.active_count()` alone misses native threads. Load needed modules
  before this final check and do not invoke callbacks between it and fork.
- Reject duplicate numeric descriptors and dev/inode aliases among the three
  sealed inputs and four bundle descriptors. Stage all sources, interpreter and
  status pipe with `F_DUPFD_CLOEXEC` above 9; preserve an exact descriptor
  whitelist. Use `fchdir(5)` and reset readable input offsets.
- The runtime directory is deployment-unique, empty and stable at launch with
  exact authority owner/group and 0700 mode. The deployment manager must reserve
  distinct authority/application identities; a numeric UID alone does not prove
  absence of other same-UID processes.
- Child setup includes parent-death signal and parent-race check, reset signal
  mask/ignored dispositions, `RLIMIT_CORE=0`, and explicit bounding/ambient/
  effective/permitted/inheritable capability clearing. Set all GID/UID slots,
  then no-new-privileges and verify the resulting IDs/groups/capabilities and
  policy before exec. Re-arm parent-death signal after credential changes,
  which may clear it, and check the expected parent again.
  Set and verify `PR_SET_DUMPABLE=0` after credential changes as well.
- Concrete consumer limits are 1–65,536 bytes each for configuration and launch
  instance, exactly 32 bytes for the key, and at least 32 open files in the
  selected profile. Reject unsupported lower descriptor ceilings before fork.

### Manager wait-status ownership decision (Astra, 2026-09-06)

The manager is a dedicated, trusted CPython main-interpreter/main-thread process
and the sole consumer of each owned child's wait status. Before the first
authority fork, within the blocked-signal region, unconditionally call
`signal.signal(SIGCHLD, SIG_DFL)`, then prepare the child identity-policy signal
snapshot and perform the final thread check. Keep this SIGCHLD action for the
entire manager/child-owner lifetime; never restore an inherited reaping handler
after launch or error cleanup. Restore the parent's signal mask separately.
No other `wait*` consumer, signal handler, at-fork callback or native component
may reap an owned child. This is a manager TCB obligation, not something a
one-time Python thread check can prove forever.

The currently inspected and Linux-qualified manager is CPython 3.13.7.
Its `signal.signal()` invokes the native `PyOS_setsig()` implementation, which
uses the target's compiled `sigaction` layout and replaces action flags,
clearing `SA_NOCLDWAIT`. `getsignal()` alone sees Python's cache and is
insufficient to detect native action changes. Do not infer qualification for
arbitrary Python implementations from the wheel's general Python requirement.
See the [CPython signal implementation](https://github.com/python/cpython/blob/v3.13.7/Modules/signalmodule.c)
and [native action setter](https://github.com/python/cpython/blob/v3.13.7/Python/pylifecycle.c).

All cleanup paths share wait-status ownership. On `ECHILD`, permanently mark
ownership lost and never signal the saved numeric PID/group again; return the
fixed safe error. Probe with `waitid(...WNOWAIT...)` before the first numeric
signal as defense in depth, while retaining the sole-reaper requirement.
Mask-restoration failures must neither skip FD/child cleanup nor expose raw
exceptions, and must not return a live owner as success.

Qualify Python ignored/reaping SIGCHLD actions and native `SIG_DFL|SA_NOCLDWAIT`
using an architecture-compiled, test-only C helper. Production uses CPython's
native implementation, not handwritten ctypes signal-action structures.
Verify repeated WNOWAIT observations before final reap, non-restoration of
dangerous actions on every outcome, no signaling after ECHILD, actual timeout,
concurrent lifecycle cleanup, and restoration-failure redaction/cleanup.

### Active development slice: real qualification IPC (Astra, 2026-09-06)

The trusted manager may also be the supervisor: both roles are in the operator
TCB. Authority remains a separate UID; the later untrusted application uses a
different UID. The manager owns connection, authenticated result verification,
cancellation, final safe rendering and reaping. Authority creates its own
`SOCK_SEQPACKET` listener after privilege drop, binds `authority.sock` in the
FD5 runtime directory, and accepts one connection. Both sides check exact
`SO_PEERCRED` PID/UID before sending protocol data.

FD6 contains canonical JSON with exactly: `format` equal to
`asterion.prime-p1-authority-launch-instance/v2`, `purpose=qualification`,
`run_id`, `session_id`, `supervisor_pid`, `supervisor_uid`, `runtime_identity`
(the three full I/B/P field names), `request_contract_sha256`,
`resource_set_sha256`, `application_request_sha256`, and
`workload_id=bounded-ipc-qualification-v1`. All identities are manager-owned;
there is no authority PID or configurable command/path in this instance.

Use the separate `asterion.prime-p1-authority-qualification-ipc/v2` protocol and
the same bytes plus NUL as the HMAC domain. FD4 supplies exactly 32 session-key
bytes, not a production receipt key. Reuse the existing canonical/HMAC/strict
validation algorithms without changing v1 constants or receipt semantics.
Authority emits ready sequence 0 and terminal sequence 1; manager sends execute
sequence 0 and optionally cancel sequence 1. Frames bind run/session, I/B/P and
the exact request/resource/application identities. Authority checks I/B/P
against FD8 release data; manager checks them against its admitted identity.

The immutable bootstrap restores CLOEXEC on 3–9 and validates prefix/import
roots. After exec, reset/verify dumpable and parent-death policy before reading
secret descriptors. The self-contained qualification entry performs only fixed
finite deterministic work and checks cancellation/deadline. A terminal reports
qualification `completed`, `failed` or `cancelled`; it is never a production
PASS, receipt or evidence ID. Manager returns completed only after an authentic
terminal and child reaping. EOF, timeout or forced kill cannot create a terminal.

First implement a real normal exchange, then cancellation/reaping and key
peer/identity/HMAC rejection assertions. Do not require release catalogs,
complete mapping certification or another full promotion run before developing
this unpromoted path. The next integration point is the workload function after
execute validation: connect the existing P1 worker/model/oracle there and reuse
the same manager connection and cleanup path.

## Task 4: semantic scenario qualification and reuse

**Integrate:** P1 workload/request/receipt profiles and existing P2/P3 launchers; P4–P7 missing host/launcher routes follow the canonical seven-scenario worklist.

- [ ] Prove P1-A finite real coding execution without calling it full P1 PASS.
- [ ] Deliver exact P1-B versioned multi-turn and compaction scenario; verify namespace/import/function/cwd/files persist in the same kernel and final oracle passes after model-caused edits.
- [ ] Reuse the same admitted host boundary for P2/P3, then P4/P5, P6 local/project scope and P7 finite public subset.
- [ ] Require installed public application paths, causal worker evidence, aggregate finite accounting, cancellation and cleanup for each of seven scenario completions.

## Verification and delivery

Use unittest success/failure/subTest matrices for each actual boundary. Before integrating packaged files or entry points, run full promotion with private complete failure logs; never infer current PASS from historical gates or residual temporary directories. Update the canonical worklist with exact named commands, platform and scope. Review and commit bounded source changes independently of pre-existing uncommitted documents.
