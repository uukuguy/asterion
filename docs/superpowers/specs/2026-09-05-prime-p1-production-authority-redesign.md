# Prime P1 Production Authority Redesign

## Decision

Commit `15160b7` must not be connected to production execution as written. Its
module seals, private constructors, exact-type checks, and one-shot flags all
live in the same Python interpreter as import-capable application code. They
prevent accidental misuse, but they are not an authorization boundary:
application code can import, replace, or call the producer path and can replace
the consumer that interprets an in-process trace. The current
`asyncio.to_thread(urllib.request...)` provider call also cannot prove transport
quiescence after cancellation, and charging the fixed cost ceiling does not
prove actual provider cost.

Production P1 therefore uses a separate, one-request authority process. A
trusted CLI supervisor owns the user-visible result; the selected provider,
assembly, runner, and runtime execute in a separate application child. The
authority alone owns Docker access, model credentials, the completion oracle,
receipt authentication, and the private evidence root. The application child
receives only a proxy for requesting the one fixed P1 action. It never receives
the authority socket, receipt channel, configuration descriptor, authentication
key, Docker service, provider transport, or an object that can upgrade a result
to production PASS.

```text
trusted `asterion verify` supervisor (does not import provider code)
        |
        | bounded relay: execute/cancel + safe result digest
        v
application child: provider -> assembly -> runner -> prime.agent runtime

trusted supervisor == authenticated Unix IPC ==> one-shot P1 authority
                                                    |-- Docker daemon
                                                    |-- killable model helper
                                                    `-- private evidence root

authority terminal receipt ======================> trusted supervisor stdout
```

A production PASS exists only when the supervisor receives and validates the
authority's terminal frame and the application child's safe result projection
has the receipt digest named by that frame. No `IpythonHostTrace`, capability
object, provider result, fixture, or application-child stdout can independently
mint or display production PASS.

## Threat and trust boundary

The design resists application code that can import and monkeypatch any module
available in its interpreter, inspect its Python object graph, open ordinary
user-readable files, forge worker frames, and control its stdout/stderr. It also
resists replay, extra IPC clients, inherited-FD discovery, symlink/path
replacement, provider stalls, cancellation-resistant threads, and fabricated
Docker/model result objects.

The TCB is the generic verification supervisor, the separately installed
authority executable and its locked dependencies, the authority OS account,
the kernel/service manager, the Docker daemon, and the fixed host oracle. Root,
kernel, Docker-daemon, authority-account, or trusted-supervisor compromise is
out of scope and must not be described as sandbox resistance.

Production PASS requires the authority to run under a dedicated OS identity
whose configuration, receipt key, and evidence root are unreadable and
unwritable by the application identity. Mode `0600` alone is not a boundary
between two processes running as the same uid. A same-uid development launch
may exercise the protocol but is permanently classified `UNAVAILABLE` for
production evidence. The authority account's Docker access is privileged and
must never be inherited by the application child or model helper.

## One-shot process and authenticated IPC

The production deployment is a socket-activated, one-connection process (for
example, a systemd `Accept=yes` service). It accepts one request, emits exactly
one terminal frame, closes all descriptors, and exits. It never becomes a
general daemon, provider proxy, Docker command service, or reusable lease
issuer.

The socket is an absolute, operator-installed Unix `SOCK_SEQPACKET` socket below
a root/authority-owned, non-writable directory. The supervisor validates the
path without following symlinks, connects once, then verifies Linux
`SO_PEERCRED`: exact authority uid, supervisor uid, and the service-manager
reported child pid. The authority performs the reciprocal peer check. The
application child never inherits this socket. Service-manager activation and
the peer credentials authenticate the live endpoints; a fresh 256-bit session
nonce binds the frames and prevents cross-run replay. Production is Linux-only
and fails closed if `SOCK_SEQPACKET`, `SO_PEERCRED`, safe descriptor passing, or
the dedicated identities are unavailable.

Every frame is strict UTF-8 canonical JSON in one packet, at most 8192 bytes,
with exact keys:

```json
{
  "protocol": "asterion.prime-p1-authority-ipc/v1",
  "session_id": "<64 lowercase hex>",
  "sequence": 0,
  "kind": "execute",
  "payload": {},
  "frame_hmac_sha256": "<64 lowercase hex>"
}
```

`session_id` is the lowercase hexadecimal encoding of exactly 32 independently
CSPRNG-generated bytes. The session key is a random 32-byte value delivered by the service manager to
the supervisor and authority through distinct anonymous, close-on-exec
descriptors. It is never placed in argv, environment, a filesystem socket,
application-child memory, or evidence. The HMAC covers the canonical frame
without `frame_hmac_sha256`, prefixed by the byte string
`asterion.prime-p1-authority-ipc/v1\0`. Keys and inherited descriptors are
closed immediately after derivation/handshake.

The closed state machine is:

1. Authority -> supervisor: `ready`, sequence 0, payload containing only the
   fixed request-contract SHA-256 and authority resource-set SHA-256.
2. Supervisor -> authority: `execute`, sequence 0, payload containing exactly
   `run_id`, `request_contract_sha256`, and `application_request_sha256`.
3. Supervisor -> authority: optional `cancel`, sequence 1, with empty payload.
   No other second client frame is valid.
4. Authority -> supervisor: `terminal`, sequence 1, containing the exact receipt
   below. It is the only terminal frame. EOF, timeout, duplicate/out-of-order
   sequence, unknown/extra fields, noncanonical bytes, bad HMAC, peer change, or
   a second execute request is a redacted non-PASS.

The request contract fixes the provider/application/version, assembly/package/
implementation/runtime identities, workload and oracle locks, `ipython` as the
sole model tool, all byte/token/cost/deadline limits, and one provider request.
It contains no prompt, credential, path, model choice, budget choice, Docker
command, or executable path. Thus stealing request-side access can at most
request or cancel the fixed bounded operation; it cannot manufacture success or
widen authority.

The application's host-service proxy sends its fixed request to the trusted
supervisor over a separate bounded child pipe. The supervisor creates the
authority `execute` frame itself. It returns only `{status, receipt_sha256,
result_projection_sha256}` to the child. Child stdout/stderr is captured under a
cap and is never relayed as verification output.

## Operator configuration

The authority receives the already-open configuration descriptor, not a path.
The service manager opens the fixed external configuration; neither the
repository `.env`, cwd, process environment, CLI flags, nor host-service options
are consulted. The configuration has this exact key set:

```text
ASTERION_PRIME_P1_DOCKER_EXECUTABLE
ASTERION_PRIME_P1_DOCKER_SOCKET
ASTERION_PRIME_P1_SECCOMP_PROFILE
ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST
ASTERION_PRIME_P1_MODEL_ID
ASTERION_PRIME_P1_EVIDENCE_ROOT
ASTERION_PRIME_P1_RECEIPT_KEY_ID
ASTERION_PRIME_P1_RECEIPT_HMAC_KEY
DEEPSEEK_API_KEY
```

The file must be a single-link regular file owned by the authority uid, exact
mode `0600`, 1..65536 bytes, below a no-symlink directory chain not writable by
the application uid. Open uses descriptor-relative component traversal with
`O_NOFOLLOW|O_CLOEXEC` (and `O_DIRECTORY` for ancestors); `lstat` plus a later
path open is insufficient. `fstat` identity is checked before and after the
bounded read. The authority rejects duplicate, missing, extra, empty, NUL,
control-character, non-UTF-8, or multiline entries.

If `python-dotenv` remains the parser, it is called only on the verified in-memory
text with `interpolate=False`; duplicate and exact-key checks occur before its
mapping is accepted. No environment merge or fallback is allowed. Interpolation
syntax remains literal and never resolves process values. Errors and reprs use
one fixed public-safe category and never expose values or paths.

`ASTERION_PRIME_P1_RECEIPT_HMAC_KEY` is exactly 64 lowercase hexadecimal
characters and is retained only in authority memory. The model remains from the
closed code allowlist, and the HTTPS endpoint and fixed prompt are code-owned.
The receipt key authenticates private evidence; later audit is performed by a
fresh read-only authority invocation, never by giving the key to application
code.

## Production resource admission and revalidation

Static readiness performs no Docker or network operation and cannot mint an
execution receipt. Before execution, the authority verifies:

- its installed executable/module lock and distribution version against the
  packaged authority lock; every file is regular, owner/root-owned, not
  group/world writable, no-follow opened, bounded, and digest exact;
- Docker executable absolute canonical path, root-owned ancestry, regular
  executable identity, no group/world write bits, bounded SHA-256, and unchanged
  `(st_dev, st_ino, st_mode, st_uid, st_gid, st_size, st_mtime_ns)` immediately
  before every direct-argv spawn;
- Docker socket absolute canonical path, socket type, configured owner/group and
  mode policy, unchanged pathname identity before and after connect, and exact
  server API/version projection;
- seccomp profile no-follow regular identity, size cap, SHA-256, and the closed
  deny-by-default canonical schema already required by P1;
- image reference is exactly a local config digest `sha256:<64 hex>`,
  `--pull=never` is used, daemon inspection returns that exact image ID and an
  empty repo-digest tuple, and the fixed entry point/environment/user/network/
  mount/capability/security projection matches;
- evidence root is an existing authority-owned exact-mode `0700` directory with
  no symlink ancestry; receipt files are direct children created with
  `O_NOFOLLOW|O_CREAT|O_EXCL|O_CLOEXEC`, mode `0600`, then file and directory
  fsynced;
- assembly, package manifest, implementation binding, source lock, build-input
  lock, launcher, workload, starter, and oracle bytes match their exact packaged
  digests before Docker admission.

All opened resources remain strongly referenced. Identity and digest checks are
repeated at their last safe point of use. A changed path, inode, bytes, daemon
projection, package resource, or configuration produces `resource-changed` and
no provider request. Application-supplied resource identities are ignored.

## Killable model transport and cancellation

The authority must not use `asyncio.to_thread`, an executor thread, or any
blocking HTTP call in its own process. Each permitted provider request runs in a
fresh model-transport helper process in a new process group with cleared
environment, fixed direct argv, fixed cwd, stdin/stdout/stderr pipes, and only a
single credential/request descriptor. The helper may perform the blocking HTTPS
call; its entire process group is disposable.

The authority owns one absolute monotonic deadline across broker admission,
connect, response read, worker delivery, and cleanup. It concurrently drains
stdout and stderr under one 65536-byte cap. On caller cancellation, deadline,
cap breach, malformed response, worker failure, or authority shutdown it closes
the request descriptor, sends `SIGTERM` to the helper process group, waits at
most 2 seconds, sends `SIGKILL`, and reaps the group leader. Success is
ineligible until EOF is observed, the helper is reaped with the expected exit
status, no tracked descendant remains, the broker is revoked, and the Docker
container is force-removed with daemon absence verified. Cancellation is
latched and propagated only after this finite cleanup; uncertainty is always
non-PASS.

Provider token counts are provider-reported and explicitly labelled as such.
Because the current response does not prove billed currency cost, P1 records
`cost_basis="reserved-ceiling"` and charges the full authorized ceiling. It must
not label that value actual cost. Missing/malformed/over-limit token usage is a
failure.

## Exact terminal receipt and evidence

The terminal payload is exact-key canonical JSON. `status` is one of `PASS`,
`FAIL`, `CANCELLED`, or `UNAVAILABLE`; only PASS contains all positive booleans
below. Failure reason is one enum value and carries no exception text.

```text
format = "asterion.prime-p1-authority-receipt/v1"
status
reason_code
run_id
session_id
request_contract_sha256
application_request_sha256

authority:
  authority_version
  authority_executable_sha256
  operator_config_binding_hmac_sha256
  production_resource_set_sha256
  receipt_key_id

identity:
  provider_id = "prime-agent"
  application_id = "prime.ipython-coding"
  application_version = "1.0.0"
  assembly_ref = "prime.ipython-coding@1.0.0"
  assembly_sha256
  package_ref = "prime-agent@1.0.0"
  package_manifest_sha256
  implementation_ref = "prime.ipython-coding@1.0.0"
  runtime_id = "prime.agent"
  prime_sdk_ref = "prime-agent@0.7.1"
  source_sha256
  build_input_sha256
  image_config_digest
  workload_sha256
  starter_sha256
  oracle_sha256
  seccomp_sha256

model_accounting:
  request_count = 1
  input_bytes
  output_bytes
  provider_reported_input_tokens
  provider_reported_output_tokens
  charged_cost_microunits
  cost_basis = "reserved-ceiling"
  max_requests = 1
  max_input_bytes
  max_output_bytes
  max_input_tokens
  max_output_tokens
  max_cost_microunits
  deadline_milliseconds
  request_sha256
  response_sha256
  broker_receipt_sha256
  transport_reaped = true

worker_evidence:
  worker_count = 1
  container_id_sha256
  model_tool_calls = 1
  ipython_tool_calls = 1
  sent_cell_sha256
  initial_workspace_sha256
  post_workspace_sha256
  initial_oracle_passed = false
  final_oracle_passed = true
  mutation_after_model_response = true
  broker_quiesced = true
  container_removed = true
  daemon_absence_verified = true

causal_evidence:
  event_count
  first_sequence = 1
  last_sequence = event_count
  event_chain_sha256
  result_projection_sha256

evidence_id = "prime-p1-<receipt_sha256>"
receipt_sha256
receipt_hmac_sha256
```

`receipt_sha256` hashes the domain prefix plus the entire receipt excluding
`evidence_id`, `receipt_sha256`, and `receipt_hmac_sha256`.
`receipt_hmac_sha256` authenticates the domain-prefixed receipt including
`receipt_sha256` with the operator receipt key. `evidence_id` is then derived
from `receipt_sha256`; circular or self-selected identifiers are rejected.

The private evidence file contains this receipt and only normalized identities,
counts, booleans, digests, and reason enums. It contains no prompt, answer,
credential, provider/model name, HTTP payload, source/cell/output text, raw
container ID, executable/socket/config/evidence path, environment value, or
exception. The public CLI projection is limited to product ID, level, status,
reason code, evidence ID, receipt SHA-256, provider-operation count, token/byte/
charged-cost counts, and `full_dataset_ran=false`; it omits both HMACs and all
private identities.

## Integration sequence

1. Add provider-neutral trusted-supervisor support in
   `src/asterion/applications/product.py` and `src/asterion/cli.py`. A
   provider-backed verifier may declare a separate authority binding; the
   supervisor must fork the application execution child before loading its
   entry point and must own final rendering and exit status.
2. Add strict shared frame/receipt parsing in
   `src/asterion/applications/prime_agent/operator/authority_protocol.py` with
   valid/invalid canonical fixtures and cross-process tests. Parsing grants no
   authority and exposes no receipt constructor usable for PASS.
3. Add the separately launched implementation in
   `src/asterion/applications/prime_agent/operator/authority_process.py` and the
   killable helper in `model_transport_process.py`. Package them as distinct
   console entry points and install the operator service definition separately;
   do not load either as `asterion.host_services` in the application child.
4. Replace `production_host.py` with an IPC proxy that has only one fixed
   `execute(run_id, signal)` operation. Remove
   `PrimeP1ProductionHostCapability`, `PrimeP1ProductionRunAuthority`, and
   `_consume_production_authority`; their nominal seals must not remain as an
   alternate production path.
5. Wire `ipython_host_issuer.py` to the proxy. Keep
   `ipython_host_orchestrator.py`, Docker worker, broker, and AST supervisor
   inside the authority process; the application child sees only the safe
   projection and receipt digest. Existing provider-free traces remain
   `provider-free` and can never satisfy the new receipt parser.
6. Add the Prime product verifier and fixed `basic` preset in `provider.py`.
   `preflight` validates static installation/readiness without connecting;
   `acceptance` remains provider-free; `basic` invokes exactly one authority
   run with internal finite controls and no model/provider/cost/deadline knobs.
7. Delete the separate production `model.bounded-session` entry point for this
   assembly after the authority owns model admission. Retain the generic service
   protocol for nonproduction tests and other applications; do not grant two
   independent model-authority paths to P1.

Implementation proceeds in that order with failing tests first. Required
adversarial coverage includes imported constructor/monkeypatch forgery,
application-child fake PASS/stdout, socket replacement, wrong peers, stolen or
replayed request frames, malformed/extra/out-of-order frames, config
interpolation and duplicate keys, every resource replacement race, Docker
inspect mismatch, provider stall and cancellation suppression, helper
TERM/KILL/reap, receipt/HMAC tampering, evidence overwrite, cleanup uncertainty,
and sentinel redaction. No unit, acceptance, preflight, `make test`, or
`make check` command may contact Docker or a provider. The first real `basic`
run remains separately operator-authorized and is reported as PASS only if the
named private receipt validates through the authority boundary.

## Acceptance gate

The redesign is complete only when a test places hostile import-capable code in
the application child, lets it import and monkeypatch all former P1 host modules,
forge every old in-process type, and print a fake PASS, while the trusted
supervisor still returns non-PASS without a valid authority terminal frame. A
second test must complete one deterministic fake-backend authority run across
real processes and prove that only the authority-owned receipt can pass. Native
Docker qualification and a real model call remain separately authorized gates;
neither is implied by provider-free process tests.
