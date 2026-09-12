# Prime P1 Docker Executable Resource Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Admit the configured Docker executable as an opaque authority-only resource that can be revalidated immediately before a future direct-argv spawn.

**Architecture:** Add a narrow descriptor-based module under the Prime authority boundary. It validates a canonical absolute path with descriptor-relative no-symlink traversal, root ownership, regular executable type, and no group/world write bits; it retains a private identity snapshot and never exposes path or FD. It is not wired into Docker transport or authority ready yet.

**Tech Stack:** Python 3, os.open, os.fstat, stat, threading, unittest, Ruff.

## Global Constraints

- Consume only PrimeP1OperatorConfig._values["ASTERION_PRIME_P1_DOCKER_EXECUTABLE"]; no environment, cwd, host discovery, or application input.
- Accept only absolute canonical paths with no empty, dot, parent, or symlink components.
- The final object is root-owned, regular, executable, and not group/world writable; errors and reprs stay public-safe and redacted.
- Retain private immutable device/inode/mode/uid/gid/size/mtime-ns plus bounded SHA-256; revalidate all immediately before a future spawn.
- Exact type/private token construction and exact-once FD lifecycle are mandatory. No Docker command/connect/process spawn/model/network/readiness/basic change.

---

### Task 1: Admit and revalidate the Docker executable descriptor

**Files:**

- Create: src/asterion/applications/prime_agent/operator/authority_docker_executable.py
- Create: tests/test_prime_p1_authority_docker_executable.py

**Interfaces:**

- Produces admit_docker_executable(config: object) -> AdmittedPrimeP1DockerExecutable.
- AdmittedPrimeP1DockerExecutable.revalidate_for_spawn() -> None raises a fixed public-safe resource error after close or identity/content change.
- close() -> None releases its descriptor exactly once.

- [ ] **Step 1: Write failing tests**

```python
def test_admits_root_owned_non_writable_regular_executable_and_revalidates(self) -> None:
    resource = admit_docker_executable(_config(path=str(self.executable)))
    resource.revalidate_for_spawn()
    self.assertEqual(repr(resource), "AdmittedPrimeP1DockerExecutable(redacted)")

def test_rejects_relative_symlink_parent_symlink_writable_or_non_root_paths(self) -> None:
    for value in (self.relative, self.final_symlink, self.parent_symlink_child, self.writable, self.non_root):
        with self.subTest(value=value):
            with self.assertRaises(PrimeP1DockerExecutableError):
                admit_docker_executable(_config(path=str(value)))

def test_revalidation_rejects_mutated_fd_contents_and_closed_resource(self) -> None:
    resource = admit_docker_executable(_config(path=str(self.executable)))
    self._mutate_open_file()
    with self.assertRaises(PrimeP1DockerExecutableError):
        resource.revalidate_for_spawn()
    resource.close()
    with self.assertRaises(PrimeP1DockerExecutableError):
        resource.revalidate_for_spawn()
```

Use fstat seams only for root ownership on non-root hosts. Test every metadata field independently; assert sensitive sentinels are absent from error/cause/context/repr and an FD opened before rejection is closed once.

- [ ] **Step 2: Verify RED**

Run: uv run python -m unittest -v tests.test_prime_p1_authority_docker_executable

Expected: import error because the module does not exist.

- [ ] **Step 3: Implement descriptor admission and revalidation**

Open components from / with O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC; final with O_RDONLY|O_NOFOLLOW|O_CLOEXEC. Validate exact metadata, calculate bounded digest through retained FD, store private snapshot. Revalidation must fstat, recompute digest from offset zero, compare exactly, and fail after close. Clear FD inside lock before close.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v tests.test_prime_p1_authority_docker_executable
uv run ruff check src/asterion/applications/prime_agent/operator/authority_docker_executable.py tests/test_prime_p1_authority_docker_executable.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/authority_docker_executable.py tests/test_prime_p1_authority_docker_executable.py
git commit -m "Admit Prime P1 Docker executable resource"
```

## Self-Review

- One production resource boundary only: no daemon trust, Docker launch, authority readiness, or model call.
- Config value and identity remain private. No placeholders remain.

---

### Task 2: Bind the admitted Docker executable into production ownership

**Files:**

- Modify: src/asterion/applications/prime_agent/operator/authority_resources.py
- Modify: tests/test_prime_p1_authority_resources.py

**Interfaces:**

- Consumes `admit_static_authority_resources(config)`, `admit_evidence_root(config)`, and `admit_docker_executable(config)`.
- `AdmittedProductionAuthorityResources` now owns exact static, evidence-root, and Docker-executable children. It still exposes only `close()`.

- [ ] **Step 1: Write failing tests**

```python
def test_production_aggregate_requires_exact_docker_executable(self) -> None:
    with patch.object(module, "admit_docker_executable", return_value=_docker()) as docker:
        resource = admit_production_authority_resources(_config())
    docker.assert_called_once()
    resource.close()

def test_docker_failure_closes_evidence_then_static_once(self) -> None:
    # Make Docker admission fail after exact static/evidence admission and assert
    # reverse-order, exact-once cleanup plus normalized aggregate error.
```

Also cover direct constructor rejection of a Docker lookalike/subclass and constructor failure: no caller-owned child becomes consumed on direct rejection; acquired exact children close Docker, evidence, static in reverse order on factory failure.

- [ ] **Step 2: Verify RED**

Run: uv run python -m unittest -v tests.test_prime_p1_authority_resources

Expected: missing Docker aggregate dependency/constructor parameter.

- [ ] **Step 3: Implement exact three-child ownership**

Import `AdmittedPrimeP1DockerExecutable` and `admit_docker_executable`. Require all three children by exact type before aggregate state assignment. Admit in static, evidence, Docker order. On any factory exception, close only successfully acquired exact children in reverse Docker, evidence, static order; suppress close exceptions but never accept partial state. Aggregate `close()` atomically detaches all three before closing in the same reverse order.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v tests.test_prime_p1_authority_docker_executable tests.test_prime_p1_authority_evidence tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_process
uv run ruff check src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_resources.py
git diff --check
```

Authority process must still end unavailable and no Docker runner/command can be reached.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_resources.py
git commit -m "Bind Prime P1 Docker executable resource"
```

## Execution Handoff

Execute Task 1 with a fresh Terra worker, then an independent Sol security review before binding this resource into the production aggregate.
