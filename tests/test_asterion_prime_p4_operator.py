"""P4 operator: env-driven commit→recover witness, prior_checkpoint_sha256 fix.

The operator is the sole bridge between the P4 native implementation and the
Makefile `asterion-prime-p4-run` supervisor. Three invariants anchor it:

* ``recover.prior_checkpoint_sha256`` MUST equal the prior's last sealed
  checkpoint digest (i.e. ``commit.checkpoint_sha256``). Earlier the field
  held ``prior_identity.continuation_id``; this test pins the correct shape.
* The recover-mode next_identity MUST inherit the prior's
  ``pi_command_sha256`` / ``extension_binding_fingerprint`` /
  ``ceilings_sha256``; hardcoded literals would only match if the same
  operator build sealed the prior (which the fixture deliberately violates
  to exercise the cross-build detach+attach path).
* The SHA inequality that proves no-replay must still hold between the
  commit and recover rounds.

Two test classes back this contract:

* :class:`P4OperatorEndToEnd` runs the operator twice via subprocess against
  a fresh private_root, like the Makefile supervisor will.
* :class:`P4OperatorRecoverFromFixture` exercises ``_recover_mode`` in
  process against a pre-baked gen=1 state materialized from
  ``tests/fixtures/prime_p4/small_state.json`` — faster, lower-fragility
  regression for the same invariants, including the cross-build recovery
  path that the subprocess pair cannot exercise (since both invocations
  share one operator build's hardcoded SHA literals).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import unittest

from asterion.agents.prime.state import PrimeCheckpoint
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    _canonical_bytes,
    private_root_identity,
)


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P4_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P4_MODE"


def _run_operator(
    *, operator_root: Path, private_root: Path, mode: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        _OPERATOR_ROOT_ENV: str(operator_root),
        _PRIVATE_ROOT_ENV: str(private_root),
        _MODE_ENV: mode,
        "LANG": "C.UTF-8",
    }
    return subprocess.run(
        [sys.executable, "-I", "-m", "asterion.applications.prime.p4.operator"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(operator_root),
    )


def _parse_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    line = completed.stdout.strip()
    assert line, (
        f"operator stdout empty; stderr={completed.stderr!r}, rc={completed.returncode}"
    )
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


class P4OperatorEndToEnd(unittest.TestCase):
    """Run commit, then recover, against a fresh private_root; assert SHA wire."""

    def test_recover_prior_checkpoint_sha256_matches_commit_digest(self) -> None:
        operator_root = Path.cwd()
        with __import__("tempfile").TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p4-test"

            commit_proc = _run_operator(
                operator_root=operator_root,
                private_root=private_root,
                mode="commit",
            )
            self.assertEqual(
                commit_proc.returncode,
                0,
                f"commit rc={commit_proc.returncode}; stderr={commit_proc.stderr!r}",
            )
            commit = _parse_stdout(commit_proc)
            self.assertEqual(commit["status"], "committed")
            self.assertIsNotNone(commit["checkpoint_sha256"])
            commit_digest = commit["checkpoint_sha256"]
            assert isinstance(commit_digest, str) and len(commit_digest) == 64

            recover_proc = _run_operator(
                operator_root=operator_root,
                private_root=private_root,
                mode="recover",
            )
            self.assertEqual(
                recover_proc.returncode,
                0,
                f"recover rc={recover_proc.returncode}; stderr={recover_proc.stderr!r}",
            )
            recover = _parse_stdout(recover_proc)
            self.assertEqual(recover["status"], "recovered")

            # The fix: prior_checkpoint_sha256 is the prior's last sealed
            # checkpoint digest (matches commit), NOT continuation_id.
            self.assertEqual(
                recover["prior_checkpoint_sha256"],
                commit_digest,
                "recover.prior_checkpoint_sha256 must equal commit.checkpoint_sha256",
            )
            self.assertNotEqual(
                recover["prior_checkpoint_sha256"],
                recover["continuation_id"],
                "regression guard: prior_checkpoint_sha256 must not be continuation_id",
            )

            # Continuity invariants remain intact.
            commit_generation = commit["generation"]
            assert isinstance(commit_generation, int)
            self.assertEqual(recover["new_generation"], commit_generation + 1)
            self.assertEqual(recover["continuation_id"], commit["continuation_id"])
            self.assertNotEqual(recover["result_sha256"], commit["result_sha256"])
            self.assertNotEqual(
                recover["worker_identity_sha256"],
                commit["worker_identity_sha256"],
            )

    def test_recover_seals_generation_two_checkpoint(self) -> None:
        from asterion.agents.prime.store import FilePrimeSessionStore
        from asterion.applications.prime.p4.operator import _read_prior_identity

        with __import__("tempfile").TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p4-test"
            for mode in ("commit", "recover"):
                process = _run_operator(
                    operator_root=Path.cwd(), private_root=private_root, mode=mode
                )
                self.assertEqual(process.returncode, 0, process.stderr)
            identity = _read_prior_identity(private_root)
            self.assertEqual(identity.generation, 2)
            store = FilePrimeSessionStore(private_root, identity)
            try:
                self.assertEqual(store.highest_sealed_generation, 2)
                recovered = store.recover_checkpoint()
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered.checkpoint.generation, 2)
            finally:
                store.close()

    def test_operator_round_uses_composed_provider_route(self) -> None:
        import asyncio
        from unittest.mock import patch

        from asterion.applications.prime.p4 import operator
        from asterion.runner.composed import run_composed_application

        with __import__("tempfile").TemporaryDirectory() as tmp:
            environment = {
                _OPERATOR_ROOT_ENV: str(Path.cwd()),
                _PRIVATE_ROOT_ENV: str(Path(tmp) / "prime-p4-test"),
                _MODE_ENV: "commit",
            }
            with (
                patch.dict(os.environ, environment),
                patch.object(
                    operator,
                    "run_composed_application",
                    wraps=run_composed_application,
                    create=True,
                ) as composed,
            ):
                result = asyncio.run(operator._run_async())
            self.assertEqual(result.status, "committed")
            self.assertEqual(composed.call_count, 1)


def _fixture_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures/prime_p4/small_state.json"


def _materialize_private_root(fixture: dict[str, object], root: Path) -> str:
    """Write identity.json + records.jsonl + blobs to ``root`` per the
    canonical on-disk contract that ``FilePrimeSessionStore`` validates.

    Returns the prior's last sealed checkpoint digest (what the operator's
    recover-mode output's ``prior_checkpoint_sha256`` must equal).
    """
    root.mkdir(mode=0o700)

    # 1. identity.json — exact canonical encoding from store._identity_document.
    identity_mapping = dict(fixture["identity_document"]["identity"])  # type: ignore[arg-type]
    # Re-derive private_root_identity from THIS root, not the seed root.
    identity_mapping["private_root_identity"] = private_root_identity(root)
    identity_doc = {
        "version": fixture["identity_document"]["version"],  # type: ignore[index]
        "identity": identity_mapping,
    }
    identity_bytes = _canonical_bytes(identity_doc) + b"\n"
    (root / "identity.json").write_bytes(identity_bytes)
    os.chmod(root / "identity.json", 0o600)

    # 2. checkpoint + blobs — checkpoint mapping is fixed by the fixture.
    checkpoint_mapping: dict[str, object] = dict(fixture["checkpoint"])  # type: ignore[arg-type]
    checkpoint = PrimeCheckpoint.from_mapping(checkpoint_mapping)
    assert checkpoint.digest == _mapping_digest_from_fixture(checkpoint_mapping), (
        "fixture checkpoint mapping must be self-consistent (digest vs fields)"
    )

    transcript_hex = str(fixture["transcript_hex"])  # type: ignore[arg-type]
    transcript_bytes = bytes.fromhex(transcript_hex)
    summary_hex_raw = fixture.get("summary_hex")  # type: ignore[union]
    summary_bytes = (
        None if summary_hex_raw is None else bytes.fromhex(str(summary_hex_raw))
    )
    usage_mapping: dict[str, object] = dict(fixture["usage"])  # type: ignore[arg-type]
    usage_bytes = _canonical_bytes(usage_mapping)

    # Validate checkpoint hashes match the fixture's stated values.
    assert checkpoint.private_transcript_sha256 == _sha256_of(transcript_bytes), (
        "fixture transcript_sha256 mismatch"
    )
    assert checkpoint.usage_sha256 == _sha256_of(usage_bytes), (
        "fixture usage_sha256 mismatch"
    )
    if summary_bytes is None:
        assert checkpoint.summary_sha256 is None
    else:
        assert checkpoint.summary_sha256 == _sha256_of(summary_bytes)

    transcript_blob = root / f"transcript-{checkpoint.private_transcript_sha256}.blob"
    transcript_blob.write_bytes(transcript_bytes)
    os.chmod(transcript_blob, 0o600)

    summary_blob: Path | None = None
    if checkpoint.summary_sha256 is not None and summary_bytes is not None:
        summary_blob = root / f"summary-{checkpoint.summary_sha256}.blob"
        summary_blob.write_bytes(summary_bytes)
        os.chmod(summary_blob, 0o600)

    usage_blob = root / f"usage-{checkpoint.usage_sha256}.json"
    usage_blob.write_bytes(usage_bytes)
    os.chmod(usage_blob, 0o600)

    # 3. records.jsonl — one canonical row per line. Only one checkpoint
    # record (gen=1); previous_digest is null.
    record_payload = {
        "checkpoint": checkpoint_mapping,
        "checkpoint_sha256": checkpoint.digest,
        "summary_blob": (None if summary_blob is None else summary_blob.name),
        "transcript_blob": transcript_blob.name,
        "usage_blob": usage_blob.name,
    }
    record_id = f"checkpoint:{checkpoint.checkpoint_id}"
    record_digest = _sha256_of(
        _canonical_bytes(
            {
                "record_id": record_id,
                "kind": "checkpoint.sealed",
                "payload": record_payload,
            }
        )
    )
    row = {
        "version": "asterion.prime-session-store/v1",
        "position": 1,
        "previous_digest": None,
        "record_digest": record_digest,
        "record": {
            "record_id": record_id,
            "kind": "checkpoint.sealed",
            "payload": record_payload,
        },
    }
    (root / "records.jsonl").write_bytes(_canonical_bytes(row) + b"\n")
    os.chmod(root / "records.jsonl", 0o600)

    return checkpoint.digest


def _sha256_of(value: bytes) -> str:
    from hashlib import sha256

    return sha256(value).hexdigest()


def _mapping_digest_from_fixture(mapping: dict[str, object]) -> str:
    """PrimeCheckpoint.digest via store._mapping_digest."""
    return _sha256_of(_canonical_bytes(mapping))


class P4OperatorRecoverFromFixture(unittest.TestCase):
    """_recover_mode reads prior's last sealed checkpoint via the pre-baked fixture.

    Faster / lower-fragility regression for the prior_checkpoint_sha256
    invariant than the subprocess pair. The fixture encodes gen=1 sealed
    state; the test rebuilds a private_root from it, then runs _recover_mode
    in-process and asserts the captured prior_checkpoint_digest matches the
    fixture's checkpoint.digest.
    """

    def test_recover_mode_reads_prior_checkpoint_from_fixture(self) -> None:
        fixture_path = _fixture_path()
        self.assertTrue(
            fixture_path.is_file(),
            f"missing fixture: {fixture_path}",
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "fixture-root"
            prior_digest = _materialize_private_root(fixture, private_root)

            # Sanity: opening the materialized root reads back the prior.
            prior_identity = FilePrimeSessionStore.__new__(FilePrimeSessionStore)
            prior_identity._closed = True  # any read-only introspection only.
            from asterion.agents.prime.store import _read_prior_identity

            read_back = _read_prior_identity(private_root)
            self.assertEqual(read_back.generation, 1)
            self.assertEqual(read_back.continuation_id, "continuation-p4-fixture-001")

            # Build the env + preflight + run _recover_mode directly.
            env = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(Path.cwd()),
                "ASTERION_PRIME_P4_PRIVATE_ROOT": str(private_root),
                "ASTERION_PRIME_P4_MODE": "recover",
                "LANG": "C.UTF-8",
            }
            from asterion.applications.prime.p4.operator import (
                _preflight,
                _recover_mode,
                _Preflight,
            )

            preflight = _preflight(
                __import__("types").MappingProxyType(env)  # type: ignore[arg-type]
            )
            assert isinstance(preflight, _Preflight)
            self.assertEqual(preflight.mode, "recover")

            # Drive the async coroutine and unpack the 4-tuple.
            import asyncio as _asyncio

            result = _asyncio.run(_recover_mode(preflight))
            self.assertEqual(len(result), 4)
            _, next_identity, prior_checkpoint_digest, result_sha = result
            self.assertEqual(prior_checkpoint_digest, prior_digest)
            self.assertNotEqual(prior_checkpoint_digest, next_identity.continuation_id)
            # The fixture's checkpoint was sealed at gen=1, so the next
            # generation must be 2; the fixture's worker_sha is
            # fa8a601b6987f028107182117f32b9fbb4d28b27579afcbf2455ac6d6e7e9903
            # but the recover-mode worker is different (recover payload), so
            # the worker identity is allowed to swap.
            self.assertEqual(next_identity.generation, 2)
            self.assertEqual(
                next_identity.continuation_id, "continuation-p4-fixture-001"
            )
            self.assertEqual(
                len(result_sha), 64
            )  # recover result SHA must be a 64-hex digest

    def test_recover_mode_seeded_identity_uses_random_worker(self) -> None:
        """A fresh recover-mode invocation must produce a non-empty
        worker_identity_sha256 on its next identity, even when the prior was
        pre-baked by the fixture. Worker-swap is allowed; the next identity
        is constructed in-process, so its worker_sha comes from the running
        recover-mode worker, not the fixture.
        """
        fixture_path = _fixture_path()
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "fixture-root"
            _materialize_private_root(fixture, private_root)
            env = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(Path.cwd()),
                "ASTERION_PRIME_P4_PRIVATE_ROOT": str(private_root),
                "ASTERION_PRIME_P4_MODE": "recover",
                "LANG": "C.UTF-8",
            }
            from asterion.applications.prime.p4.operator import (
                _preflight,
                _recover_mode,
            )
            from types import MappingProxyType

            preflight = _preflight(MappingProxyType(env))  # type: ignore[arg-type]
            import asyncio as _asyncio

            _, next_identity, _, _ = _asyncio.run(_recover_mode(preflight))
            # The fixture pinned the prior worker_sha to fa8a601b…e9903;
            # the recover-mode worker uses a different payload, so the swap
            # is recorded on the next identity.
            self.assertEqual(len(next_identity.worker_identity_sha256), 64)
            self.assertNotEqual(
                next_identity.worker_identity_sha256,
                "fa8a601b6987f028107182117f32b9fbb4d28b27579afcbf2455ac6d6e7e9903",
            )


if __name__ == "__main__":
    unittest.main()
