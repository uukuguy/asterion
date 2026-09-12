# Prime P1 Static Resource Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject a Prime P1 configuration unless its selected image input lock's sole OCI config artifact has exactly the configured image config digest.

**Architecture:** `authority_resources.py` remains the authority-only image admission boundary. After resolving the explicitly selected promoted image lock, it derives the OCI config identity from the lock's already validated artifact set and compares it in constant time with the descriptor-only configuration. This makes the existing seccomp policy's config-digest check refer to the same exact image target without adding Docker, host discovery, model work, or catalog promotion.

**Tech Stack:** Python 3, `unittest`, `hmac.compare_digest`, existing immutable `ImageInputLock` and `ImageArtifact` contracts.

## Global Constraints

- Framework code remains domain-neutral; changes stay under the Prime application authority boundary.
- Explicit configured OCI platform is authoritative; do not inspect the host or add platform fallback.
- Empty promoted catalogs remain fail-closed; no release, Docker, network, model, receipt, ready, or execute work.
- All external-facing failures normalize to `PrimeP1AuthorityResourceError` and disclose neither secrets nor paths.
- Use TDD and commit only the implementation and test files for this task.

---

### Task 1: Bind image admission to its OCI config artifact

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_resources.py`
- Modify: `tests/test_prime_p1_authority_resources.py`

**Interfaces:**

- Consumes: `PrimeP1OperatorConfig._values["ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST"]` and a resolved `ImageInputLock.artifacts` tuple.
- Produces: unchanged `admit_static_image_resource(config: object) -> ImageInputLock`, now returning only a lock whose sole `oci-config` artifact has digest `config_digest.removeprefix("sha256:")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rejects_resolved_image_lock_with_wrong_oci_config_digest(self) -> None:
    config = self._config()
    wrong = replace(_image_lock(), artifacts=_artifacts(config_sha256="f" * 64))
    with patch.object(module, "resolve_promoted_image_input_lock", return_value=wrong):
        with self.assertRaises(PrimeP1AuthorityResourceError):
            admit_static_image_resource(config)

def test_rejects_image_lock_without_exactly_one_oci_config_artifact(self) -> None:
    config = self._config()
    malformed = replace(_image_lock(), artifacts=_artifacts_without_one_oci_config())
    with patch.object(module, "resolve_promoted_image_input_lock", return_value=malformed):
        with self.assertRaises(PrimeP1AuthorityResourceError):
            admit_static_image_resource(config)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_resources`

Expected: the patched resolver currently permits a structurally valid wrong-digest image lock.

- [ ] **Step 3: Write the minimal implementation**

```python
resource = resolve_promoted_image_input_lock(platform)
config_artifacts = tuple(item for item in resource.artifacts if item.kind == "oci-config")
if len(config_artifacts) != 1:
    raise ValueError
expected = values["ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST"]
if not hmac.compare_digest(expected, "sha256:" + config_artifacts[0].sha256):
    raise ValueError
```

Keep this inside the existing exception-normalizing admission block. Do not accept uppercase, bare digests, multiple config artifacts, arbitrary artifact paths, or a caller-supplied lock.

- [ ] **Step 4: Run focused verification**

Run:

```bash
uv run python -m unittest -v tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_seccomp tests.test_prime_p1_authority_process
uv run ruff check src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_resources.py
git diff --check
```

Expected: all selected tests pass; no lint or whitespace output.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_resources.py
git commit -m "Bind Prime P1 image config resource"
```

## Self-Review

- Spec coverage: Task 1 validates the previously missing image-lock side of the common configured image-config digest; `authority_seccomp.py` already validates the seccomp-lock side.
- No Docker, model, profile delivery, promotion, or public protocol expansion is included.
- `admit_static_image_resource` signature is unchanged, so `authority_process.py` continues to call it before seccomp admission.
- Placeholder scan: none.

## Execution Handoff

Execute Task 1 with a fresh worker, then independently review the commit before considering the later resource-set digest and sealed Docker delivery work.
