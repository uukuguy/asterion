# Prime IPython Workload-Result Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make the sole prime.ipython-coding/v1 Docker worker issue a receipt only from a fixed, code-owned IPython workload's canonical result.

**Architecture:** A small registry admits one exact workload digest. The fixed Node launcher executes its image-owned fixture after the release barrier and emits one bounded canonical completion frame. The Docker adapter validates that frame, binds it to its lease, then derives the execution receipt digest from private normalized result bytes.

**Tech Stack:** Python 3.11 dataclasses/unittest, Node ESM built-ins, Docker CLI adapter, SHA-256.

## Global Constraints

- Docker remains exact role prime.ipython-coding; no generic command, mount, source text, or environment surface.
- Accept exactly one code-owned SHA-256 workload digest; reject all other digests before container creation.
- Completion is one canonical JSON line no larger than 1024 bytes. It contains normalized fixture facts/digests, never raw source, output, prompt, credential, path, or transcript.
- Recheck canonical serialization, result SHA-256, and lease workload identity before receipt issuance.
- P2–P7 remain External-limited; P5/P6 do not consume this P1 path.
- All checks remain provider-free: do not start Docker, a model, network activity, or a benchmark.

---

### Task 1: Admit one code-owned workload and type the private completion

**Files:**
- Create: src/asterion/applications/prime_agent/operator/ipython_workload.py
- Modify: src/asterion/applications/prime_agent/operator/docker_worker.py
- Modify: tests/test_prime_docker_worker.py

**Interfaces:**
- Produces PRIME_IPYTHON_CODING_WORKLOAD_DIGEST: Final[str],
  is_prime_ipython_coding_workload(value: object) -> bool, and
  DockerWorkerCompletion(workload_digest: str, result_bytes: bytes).
- Changes DockerLauncherChannel.completed_result() to return DockerWorkerCompletion.

- [ ] **Step 1: Write the failing admission and immutability tests**

~~~python
def test_admits_only_the_fixed_workload(self) -> None:
    self.service.request_for(_request(
        workload_digest=PRIME_IPYTHON_CODING_WORKLOAD_DIGEST
    ))
    with self.assertRaises(RestrictedWorkerError):
        self.service.request_for(_request(workload_digest="sha256:" + "f" * 64))

def test_completion_is_private_and_immutable(self) -> None:
    completion = DockerWorkerCompletion(
        PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, b'{"fixture":"passed"}'
    )
    self.assertEqual(repr(completion), "DockerWorkerCompletion(redacted)")
    with self.assertRaises(FrozenInstanceError):
        completion.result_bytes = b"changed"  # type: ignore[misc]
~~~

- [ ] **Step 2: Run the failing test**

Run: uv run python -m unittest -v tests.test_prime_docker_worker

Expected: FAIL because the registry and completion type do not exist.

- [ ] **Step 3: Add the closed registry and completion**

~~~python
# ipython_workload.py
PRIME_IPYTHON_CODING_WORKLOAD_DIGEST: Final = "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"

def is_prime_ipython_coding_workload(value: object) -> bool:
    return value == PRIME_IPYTHON_CODING_WORKLOAD_DIGEST

# docker_worker.py
@dataclass(frozen=True, repr=False)
class DockerWorkerCompletion:
    workload_digest: str
    result_bytes: bytes

    def __post_init__(self) -> None:
        if (not is_prime_ipython_coding_workload(self.workload_digest)
                or type(self.result_bytes) is not bytes or not self.result_bytes):
            raise RestrictedWorkerError("restricted worker value is invalid")

    def __repr__(self) -> str:
        return "DockerWorkerCompletion(redacted)"
~~~

In DockerRestrictedWorkerService.request_for(), require
is_prime_ipython_coding_workload(request.workload_digest). The literal is the
SHA-256 of UTF-8 normalized result bytes
{"fixture":"passed","oracle":"passed","tool":"ipython"}; Task 3 locks
that identical literal in the launcher.

- [ ] **Step 4: Bind receipt derivation to completion bytes**

~~~python
completion = await state.channel.completed_result(control=control)
if (type(completion) is not DockerWorkerCompletion
        or completion.workload_digest != lease.workload_digest
        or len(completion.result_bytes) > request.max_output_bytes):
    raise RestrictedWorkerError("restricted worker value is invalid")
execution = RestrictedWorkerExecutionReceipt(
    lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
    lease.workload_digest,
    "sha256:" + sha256(completion.result_bytes).hexdigest(), "completed",
)
~~~

Keep completion bytes local; do not add them to public receipts, state, errors,
or repr output.

- [ ] **Step 5: Run and commit**

Run: uv run python -m unittest -v tests.test_prime_docker_worker

Expected: PASS; substituted workload completion and a frame digest cannot
become a receipt.

~~~bash
git add src/asterion/applications/prime_agent/operator/ipython_workload.py src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
git commit -m "feat(prime): bind fixed IPython workload"
~~~

### Task 2: Parse exactly one canonical workload-result frame

**Files:**
- Modify: src/asterion/applications/prime_agent/operator/docker_cli.py
- Modify: tests/test_prime_docker_cli.py

**Interfaces:**
- Consumes the bounded attach stream and DockerWorkerCompletion.
- Produces _parse_completed_result_line(raw: bytes) -> DockerWorkerCompletion.

- [ ] **Step 1: Replace fixed terminal tests with a real completion frame**

~~~python
result = b'{"fixture":"passed","oracle":"passed","tool":"ipython"}'
digest = "sha256:" + hashlib.sha256(result).hexdigest()
frame = json.dumps({
    "result": json.loads(result),
    "result_digest": digest,
    "terminal": "completed",
    "workload_digest": PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
}, separators=(",", ":"), sort_keys=True).encode() + b"\n"

completion = await channel.completed_result(control=self._control())
self.assertEqual(completion.result_bytes, result)
for invalid in (
    frame.replace(digest.encode(), b"sha256:" + b"0" * 64),
    frame.replace(b'"completed"', b'"failed"'),
    frame[:-1] + b" \n",
    frame + b"extra\n",
):
    with self.subTest(invalid=invalid), self.assertRaises(RestrictedWorkerError):
        DockerCliEngineTransport._parse_completed_result_line(invalid)
~~~

- [ ] **Step 2: Run the failing test**

Run: uv run python -m unittest -v tests.test_prime_docker_cli

Expected: FAIL because only the old terminal marker is accepted.

- [ ] **Step 3: Implement strict parsing**

~~~python
value = DockerCliEngineTransport._json(body)
if type(value) is not dict or set(value) != {
    "workload_digest", "result", "result_digest", "terminal"
} or value["terminal"] != "completed" or type(value["result"]) is not dict:
    raise RestrictedWorkerError("restricted worker value is invalid")
result_bytes = json.dumps(
    value["result"], separators=(",", ":"), sort_keys=True
).encode()
if (json.dumps(value, separators=(",", ":"), sort_keys=True).encode() != body
        or value["result_digest"] != "sha256:" + sha256(result_bytes).hexdigest()):
    raise RestrictedWorkerError("restricted worker value is invalid")
return DockerWorkerCompletion(value["workload_digest"], result_bytes)
~~~

Retain existing one-line and byte-cap checks. Reject an unknown workload through
the completion constructor; all errors remain redacted.

- [ ] **Step 4: Run and commit**

Run: uv run python -m unittest -v tests.test_prime_docker_cli

Expected: PASS; only one canonical P1 result frame parses.

~~~bash
git add src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py
git commit -m "feat(prime): parse canonical IPython result"
~~~

### Task 3: Execute the image-owned fixture and emit its normalized result

**Files:**
- Modify: src/asterion/applications/prime_agent/operator/image/launcher.mjs
- Modify: tests/test_prime_ipython_launcher_protocol.py

**Interfaces:**
- Consumes one canonical release frame with release true and fixed workload digest.
- Produces one canonical completion frame used in Task 2.

- [ ] **Step 1: Add failing static protocol assertions**

~~~python
self.assertIn(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, launcher)
self.assertIn('createHash("sha256")', launcher)
self.assertIn('"result_digest"', launcher)
self.assertNotIn('{"terminal":"completed"}', launcher)
for forbidden in ("process.env", "socket", "provider", "transcript", "child_process"):
    self.assertNotIn(forbidden, launcher.lower())
~~~

Also assert the release parser compares its workload digest with the fixed
literal before executing the fixture.

- [ ] **Step 2: Run the failing static test**

Run: uv run python -m unittest -v tests.test_prime_ipython_launcher_protocol

Expected: FAIL because the launcher emits a fixed unbound completion marker.

- [ ] **Step 3: Replace the marker with fixture execution and canonical emission**

~~~javascript
const workloadDigest = "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022";
const result = { fixture: "passed", oracle: "passed", tool: "ipython" };
const resultBytes = Buffer.from(JSON.stringify(result));
const completion = {
  result,
  result_digest: "sha256:" + createHash("sha256").update(resultBytes).digest("hex"),
  terminal: "completed",
  workload_digest: workloadDigest,
};
process.stdout.write(JSON.stringify(completion) + "\n");
~~~

Import only Node createHash and use the image’s existing code-owned
fixture/oracle invocation mechanism before the snippet. A failed fixture exits
through the redacted invalid-worker path without serializing output. Require
one canonical release line with exactly release and workload_digest, where
release is true and digest exactly matches workloadDigest.

- [ ] **Step 4: Run static/syntax checks and commit**

Run: uv run python -m unittest -v tests.test_prime_ipython_launcher_protocol && node --check src/asterion/applications/prime_agent/operator/image/launcher.mjs

Expected: PASS; this command does not start the launcher or Docker.

~~~bash
git add src/asterion/applications/prime_agent/operator/image/launcher.mjs tests/test_prime_ipython_launcher_protocol.py
git commit -m "feat(prime): emit fixed IPython workload result"
~~~

### Task 4: Verify the closed P1 protocol and checkpoint its boundary

**Files:**
- Modify: docs/status/JOURNAL.md
- Modify: docs/status/RESUME-NEXT-SESSION.md
- Test: tests/test_prime_docker_worker.py, tests/test_prime_docker_cli.py,
  tests/test_prime_ipython_launcher_protocol.py, tests/test_prime_worker_gate.py,
  tests/test_prime_coding_fixture_receipt.py

**Interfaces:**
- Consumes the completed fixed-workload implementation.
- Produces provider-free test verification only, never a Docker/model/network PASS claim.

- [ ] **Step 1: Run the exact provider-free verification set**

Run: uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_docker_cli tests.test_prime_ipython_launcher_protocol tests.test_prime_worker_gate tests.test_prime_coding_fixture_receipt && uv run ruff check src/asterion/applications/prime_agent/operator tests/test_prime_docker_worker.py tests/test_prime_docker_cli.py tests/test_prime_ipython_launcher_protocol.py && uv run pyright src/asterion/applications/prime_agent/operator && node --check src/asterion/applications/prime_agent/operator/image/launcher.mjs && git diff --check

Expected: all named checks PASS. Do not run make test, Docker, a model,
network operation, or benchmark.

- [ ] **Step 2: Record exact non-overclaiming state**

~~~markdown
- P1 fixed workload-result protocol is provider-free test-verified.
- Docker/model/network execution was not run and is not a PASS claim.
- P2–P7 remain External-limited; P5/P6 gained no bounded evidence.
~~~

- [ ] **Step 3: Commit**

~~~bash
git add docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md
git commit -m "docs(prime): record P1 protocol verification"
~~~

## Plan Self-Review

**Spec coverage:** Task 1 makes workload admission and receipt derivation exact;
Task 2 validates canonical, bounded private result frames; Task 3 executes only
the image-owned fixture after the release barrier; Task 4 records
provider-free-only evidence. The plan adds no generic executor and leaves
P2–P7 outside the P1 path.

**Completeness scan:** No unresolved value remains. The fixed digest is
SHA-256 of the UTF-8 normalized result bytes named in Task 1; Task 3 locks the
Python and launcher literals together.

**Type consistency:** DockerWorkerCompletion is defined in Task 1, returned by
Task 2, and consumed by Task 1 receipt issuance. The registry digest is
defined in Task 1 and used by Tasks 2–3.
