# Prime P1 Production Evidence Resource Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit an authority-owned evidence root as an opaque, closeable Prime P1 production resource, without enabling authority readiness or execution.

**Architecture:** Keep path handling inside the Prime authority boundary. A new `authority_evidence.py` opens the configured directory by descriptor, rejects unsafe ownership and modes, and retains an opaque directory FD. `authority_resources.py` later combines it with the static image/seccomp resource set; authority remains unavailable until every production resource exists.

**Tech Stack:** Python 3, `os.open`, `stat`, `threading`, `unittest`, Ruff.

## Global Constraints

- Changes remain under `src/asterion/applications/prime_agent/operator/`; framework code stays neutral.
- Consume only `PrimeP1OperatorConfig`; never read `.env`, process environment, cwd, CLI values, or application resources.
- Evidence root is an absolute canonical authority-owned `0700` directory with no symlink in any path component. Every malformed value fails closed.
- Errors/reprs expose no paths, FD numbers, credentials, receipt keys, prompts, or provider payloads.
- Child ownership transfers only after aggregate construction. Failures and repeated/concurrent close release each child exactly once.
- This slice makes neither `basic` nor authority ready runnable, and performs no Docker, network, model, or provider work.

---

### Task 1: Admit and retain an authority-owned evidence root

**Files:**

- Create: `src/asterion/applications/prime_agent/operator/authority_evidence.py`
- Create: `tests/test_prime_p1_authority_evidence.py`

**Interfaces:**

- Consumes: `PrimeP1OperatorConfig._values["ASTERION_PRIME_P1_EVIDENCE_ROOT"]`.
- Produces: `admit_evidence_root(config: object) -> AdmittedPrimeP1EvidenceRoot` and `PrimeP1EvidenceResourceError`.
- `AdmittedPrimeP1EvidenceRoot.close() -> None` owns/closes one directory descriptor exactly once and has no public path/FD accessor.

- [ ] **Step 1: Write the failing tests**

```python
def test_admits_exact_owner_mode_directory_without_public_path(self) -> None:
    resource = admit_evidence_root(_config(evidence_root=str(self.root)))
    self.assertEqual(repr(resource), "AdmittedPrimeP1EvidenceRoot(redacted)")
    with self.assertRaises(TypeError):
        resource.__reduce__()
    resource.close()

def test_rejects_relative_symlink_wrong_mode_or_wrong_owner(self) -> None:
    for root in ("relative", str(self.symlink), str(self.symlink_parent_child), str(self.world_readable), str(self.other_owned)):
        with self.subTest(root=root):
            with self.assertRaises(PrimeP1EvidenceResourceError):
                admit_evidence_root(_config(evidence_root=root))

def test_close_is_exactly_once_when_called_concurrently(self) -> None:
    # Patch module os.close with a counter, call close from two threads, assert one close.
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_evidence`

Expected: import failure because `authority_evidence` does not exist.

- [ ] **Step 3: Implement the descriptor-only admission boundary**

```python
fd = _open_absolute_directory_without_symlinks(path)
info = os.fstat(fd)
if not stat.S_ISDIR(info.st_mode):
    raise ValueError
if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise ValueError
result = AdmittedPrimeP1EvidenceRoot(fd, _token=_EVIDENCE_TOKEN)
fd = None
```

Validate absolute path before opening. Normalize all failures to the one public-safe error. Clear the retained FD under a lock before calling `os.close`. Do not retain the pathname or add evidence-file creation yet.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v tests.test_prime_p1_authority_evidence
uv run ruff check src/asterion/applications/prime_agent/operator/authority_evidence.py tests/test_prime_p1_authority_evidence.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/authority_evidence.py tests/test_prime_p1_authority_evidence.py
git commit -m "Admit Prime P1 authority evidence root"
```

### Task 2: Bind evidence ownership into the production aggregate

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_resources.py`
- Modify: `tests/test_prime_p1_authority_resources.py`

**Interfaces:**

- Consumes: `admit_static_authority_resources(config)` and `admit_evidence_root(config)`.
- Produces: `admit_production_authority_resources(config: object) -> AdmittedProductionAuthorityResources`.
- `AdmittedProductionAuthorityResources.close() -> None` closes both children exactly once and exposes no child/FD/digest/execution API.
- Construction accepts only exact `AdmittedStaticAuthorityResources` and exact `AdmittedPrimeP1EvidenceRoot` children plus the module-private token; subclasses and lookalikes are rejected before ownership transfer.

- [ ] **Step 1: Write failing aggregate tests**

```python
def test_production_resources_require_static_and_evidence(self) -> None:
    with patch.object(module, "admit_static_authority_resources", return_value=_static()) as static:
        with patch.object(module, "admit_evidence_root", return_value=_evidence()) as evidence:
            resources = admit_production_authority_resources(_config())
    static.assert_called_once()
    evidence.assert_called_once()
    self.assertEqual(repr(resources), "AdmittedProductionAuthorityResources(redacted)")
    resources.close()

def test_evidence_failure_closes_static_once(self) -> None:
    static = _counting_static()
    with patch.object(module, "admit_static_authority_resources", return_value=static):
        with patch.object(module, "admit_evidence_root", side_effect=PrimeP1EvidenceResourceError):
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_production_authority_resources(_config())
    self.assertEqual(static.close_calls, 1)

def test_rejects_lookalike_children_and_closes_acquired_exact_children(self) -> None:
    # Patch either factory to return a lookalike/subclass and assert normalized
    # rejection; assert every already-acquired exact child closes once in reverse order.
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_resources`

Expected: missing aggregate symbol.

- [ ] **Step 3: Implement aggregate-only ownership transfer**

```python
static = admit_static_authority_resources(config)
evidence = admit_evidence_root(config)
if type(static) is not AdmittedStaticAuthorityResources:
    raise ValueError
if type(evidence) is not AdmittedPrimeP1EvidenceRoot:
    raise ValueError
result = AdmittedProductionAuthorityResources(static, evidence, _token=_PRODUCTION_TOKEN)
static = evidence = None
return result
```

On any exception, close acquired children in reverse acquisition order, suppressing close exceptions, then raise `PrimeP1AuthorityResourceError`. Do not replace `_run_ready_execute_exchange`'s unavailable result.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v tests.test_prime_p1_authority_evidence tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_process
uv run ruff check src/asterion/applications/prime_agent/operator/authority_evidence.py src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_evidence.py tests/test_prime_p1_authority_resources.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/authority_evidence.py src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_evidence.py tests/test_prime_p1_authority_resources.py
git commit -m "Bind Prime P1 production evidence resources"
```

## Self-Review

- This covers the production design's authority-owned evidence-root admission and aggregate ownership; Docker executable/socket, packaged-resource locks, evidence persistence, and readiness remain separate later slices.
- Empty promoted image catalogs still fail before external operations.
- No placeholders or unbounded product surface were introduced.

## Execution Handoff

Execute Task 1 with a fresh Terra worker, independently review it, then execute Task 2 with a fresh Terra worker and independent security review. Do not pause between clean task gates.
