from __future__ import annotations
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator import (
    development_preparation as subject,
)


def _tar_member(
    name: str,
    data: bytes = b"",
    member_type: bytes = tarfile.REGTYPE,
    linkname: str = "",
) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.type = member_type
    member.mode = 0o644
    member.size = len(data) if member_type == tarfile.REGTYPE else 0
    member.linkname = linkname
    return member, data


def _write_node_archive(
    path: Path, members: list[tuple[tarfile.TarInfo, bytes]]
) -> None:
    with tarfile.open(path, "w:xz") as archive:
        for member, data in members:
            archive.addfile(member, io.BytesIO(data) if member.isreg() else None)


class TestPrimeDevelopmentPreparation(unittest.TestCase):
    def test_public_error_is_fixed(self) -> None:
        self.assertEqual(
            str(subject.PrimeDevelopmentPreparationError("private")),
            "Prime development preparation is unavailable",
        )

    def test_rejects_invalid_scenarios_without_io(self) -> None:
        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject.prepare_prime_development(Path.cwd(), ("p8",))

    def test_solving_is_a_separate_selector_without_changing_p7_lock(self) -> None:
        self.assertIn("p7-solving", subject._SCENARIOS)
        self.assertIn("p7", subject._SCENARIOS)
        self.assertEqual(
            subject._lock()["p7"]["resource_sha256"],
            "sha256:210d4f6423e6d577b239fa441b90b91c79c06fe983d6be3019ff119a99d39ebd",
        )

    def test_packaged_seccomp_has_locked_canonical_digest(self) -> None:
        lock = subject._seccomp_lock()
        self.assertEqual(
            sha256(subject._bytes("prime-development-seccomp.json")).hexdigest(),
            lock["canonical_sha256"],
        )

    def test_development_seccomp_lock_is_separate_and_complete(self) -> None:
        lock = subject._seccomp_lock()
        self.assertEqual(lock["format"], "asterion.prime-development-seccomp-lock/v1")
        self.assertEqual(lock["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertEqual(
            set(lock["images"]), {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
        )

    def test_preparation_lock_binds_seccomp_lock_bytes_for_each_architecture(self) -> None:
        lock = subject._lock()
        digest = sha256(subject._bytes("prime-development-seccomp-lock.json")).hexdigest()
        self.assertEqual(
            lock["seccomp"]["lock_sha256_by_arch"],
            {"amd64": digest, "arm64": digest},
        )

    def test_preparation_rejects_tampered_seccomp_lock_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_tampered_seccomp_lock(name: str) -> bytes:
            if name == "prime-development-seccomp-lock.json":
                return original_bytes(name) + b" "
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_tampered_seccomp_lock):
            repo = Path(temp)
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    repo,
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((repo / ".asterion-private").exists())

    def test_preparation_rejects_changed_seccomp_provenance_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_changed_provenance(name: str) -> bytes:
            if name == "prime-development-seccomp-lock.json":
                value = json.loads(original_bytes(name))
                value["tag"] = "seccomp/v0.2.4"
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_changed_provenance):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    Path(temp),
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(temp) / ".asterion-private").exists())

    def test_preparation_rejects_missing_seccomp_arch_binding_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_missing_arch_binding(name: str) -> bytes:
            if name == "prime-development-preparation-lock.json":
                value = json.loads(original_bytes(name))
                del value["seccomp"]["lock_sha256_by_arch"]["arm64"]
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_missing_arch_binding):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    Path(temp),
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(temp) / ".asterion-private").exists())

    def test_preparation_rejects_mismatched_seccomp_lock_digest_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_wrong_digest(name: str) -> bytes:
            if name == "prime-development-preparation-lock.json":
                value = json.loads(original_bytes(name))
                value["seccomp"]["lock_sha256_by_arch"]["amd64"] = "0" * 64
                value["seccomp"]["lock_sha256_by_arch"]["arm64"] = "0" * 64
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_wrong_digest):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    Path(temp),
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(temp) / ".asterion-private").exists())

    def test_resolver_rejects_receipt_without_materialized_content(self) -> None:
        with TemporaryDirectory() as temp:
            repo = Path(temp)
            root = subject._root(repo)
            (root / "receipt.json").write_text(
                json.dumps({"context": {}, "scenarios": ["p1"], "identities": {}}),
                encoding="utf-8",
            )
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.resolve_prepared_prime_development(repo, "p1")

    def test_resolver_rejects_symlinked_receipt(self) -> None:
        with TemporaryDirectory() as temp:
            repo = Path(temp)
            root = subject._root(repo)
            target = repo / "receipt-target.json"
            target.write_text("{}", encoding="utf-8")
            (root / "receipt.json").symlink_to(target)
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.resolve_prepared_prime_development(repo, "p1")

    def test_resolver_rehashes_stable_resources_before_docker_bound_identities(self) -> None:
        calls: list[str] = []
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            root = repo / ".asterion-private" / "prime-development"
            root.mkdir(parents=True)
            receipt = {"scenarios": ["p2"]}
            (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            lock = {"node": {"amd64": {"archive_sha256": "a" * 64}}}
            with (
                patch.object(subject, "_lock", return_value=lock),
                patch.object(subject, "_arch", return_value="amd64"),
                patch.object(subject, "_validated_seccomp_lock", return_value={}),
                patch.object(subject, "_root", return_value=root),
                patch.object(subject, "_resource_identities", side_effect=lambda *_args, **_kwargs: calls.append("resources") or {}),
                patch.object(subject, "_context", side_effect=lambda *_args, **_kwargs: calls.append("docker-context") or {}),
                patch.object(subject, "_image_identities", side_effect=lambda *_args, **_kwargs: calls.append("docker-image") or {}),
                patch.object(subject, "_receipt", return_value=receipt),
            ):
                subject.resolve_prepared_prime_development(repo, "p2")
        self.assertEqual(calls, ["resources", "docker-context", "docker-image"])

    def test_node_downloader_has_a_finite_timeout(self) -> None:
        calls: list[object] = []

        class Response:
            def read(self, _size: int) -> bytes:
                return b""

        def downloader(*_args: object, **kwargs: object) -> Response:
            calls.append(kwargs["timeout"])
            return Response()

        with TemporaryDirectory() as temp:
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject._node(
                    Path(temp),
                    {
                        "url": "https://example.invalid/node.tar.xz",
                        "archive_sha256": "0" * 64,
                        "node_sha256": "0" * 64,
                    },
                    downloader=downloader,
                    runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=b""),
                )
        self.assertEqual(calls, [10])

    def test_command_output_is_bounded(self) -> None:
        calls: list[object] = []

        def runner(*_args: object, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs["timeout"])
            return SimpleNamespace(stdout=b"x" * 4097)

        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject._run(["/usr/bin/true"], runner=runner)
        self.assertEqual(calls, [120])

    def test_real_command_exceeding_output_cap_is_rejected_while_streaming(self) -> None:
        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject._run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('x' * 4097); sys.stderr.flush()",
                ],
                runner=subprocess.run,
            )

    def test_node_download_uses_one_deadline_across_incremental_reads(self) -> None:
        read_sizes: list[int] = []
        time_calls: list[object] = []
        downloader_timeouts: list[object] = []

        class Response:
            def read(self, size: int) -> bytes:
                read_sizes.append(size)
                return b"x"

            def close(self) -> None:
                return None

        def downloader(*_args: object, **kwargs: object) -> Response:
            downloader_timeouts.append(kwargs["timeout"])
            return Response()

        def monotonic() -> float:
            time_calls.append(None)
            return (0.0, 0.0, 0.0, 121.0)[len(time_calls) - 1]

        with TemporaryDirectory() as temp, patch.object(subject, "_DOWNLOAD_CHUNK", 1), patch.object(
            subject.time, "monotonic", monotonic
        ):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject._node(
                    Path(temp),
                    {
                        "url": "https://example.invalid/node.tar.xz",
                        "archive_sha256": "0" * 64,
                        "node_sha256": "0" * 64,
                    },
                    downloader=downloader,
                    runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=b""),
                )
        self.assertEqual(read_sizes, [1])
        self.assertEqual(len(time_calls), 4)
        self.assertEqual(downloader_timeouts, [10])

    def test_node_download_rejects_eof_after_global_deadline(self) -> None:
        read_sizes: list[int] = []
        timeout_updates: list[float] = []
        time_calls: list[object] = []

        class Response:
            def settimeout(self, value: float) -> None:
                timeout_updates.append(value)

            def read(self, size: int) -> bytes:
                read_sizes.append(size)
                return b""

            def close(self) -> None:
                return None

        def monotonic() -> float:
            time_calls.append(None)
            return (0.0, 0.0, 0.0, 121.0)[len(time_calls) - 1]

        with TemporaryDirectory() as temp, patch.object(subject.time, "monotonic", monotonic):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject._node(
                    Path(temp),
                    {
                        "url": "https://example.invalid/node.tar.xz",
                        "archive_sha256": "0" * 64,
                        "node_sha256": "0" * 64,
                    },
                    downloader=lambda *_args, **_kwargs: Response(),
                    runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=b""),
                )
        self.assertEqual(read_sizes, [1024 * 1024])
        self.assertEqual(timeout_updates, [10])
        self.assertEqual(len(time_calls), 4)

    def test_node_publication_retains_existing_versioned_tree(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "node.tar.xz"
            archive.write_bytes(b"untrusted archive bytes")
            node = root / ("node-" + subject._digest(archive)[:16]) / "bin" / "node"
            node.parent.mkdir(parents=True)
            node.write_bytes(b"last verified node")
            self.assertEqual(subject._publish_node(root, archive), node)
            self.assertEqual(node.read_bytes(), b"last verified node")

    def test_node_extraction_accepts_locked_archive_layout_without_materializing_links(self) -> None:
        expected = "node-v22.23.2-linux-arm64/bin/node"
        payload = b"locked node executable"
        members = [
            _tar_member(
                f"node-v22.23.2-linux-arm64/share/doc/link-{index}",
                member_type=tarfile.SYMTYPE,
                linkname="README.md",
            )
            for index in range(4097)
        ]
        members.append(_tar_member(expected, payload))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "node.tar.xz"
            stage = root / "stage"
            stage.mkdir()
            _write_node_archive(archive, members)
            self.assertEqual(
                subject._extract_node(
                    archive, stage, expected, sha256(payload).hexdigest()
                ),
                stage,
            )
            node = stage / "bin/node"
            self.assertEqual(node.read_bytes(), payload)
            self.assertEqual(node.stat().st_mode & 0o777, 0o555)
            self.assertFalse((stage / "node-v22.23.2-linux-arm64").exists())

    def test_node_extraction_rejects_unsafe_or_nonmatching_members(self) -> None:
        expected = "node-v22.23.2-linux-arm64/bin/node"
        payload = b"locked node executable"
        cases = {
            "target symlink": [
                _tar_member(
                    expected, member_type=tarfile.SYMTYPE, linkname="elsewhere"
                )
            ],
            "target hardlink": [
                _tar_member(
                    expected, member_type=tarfile.LNKTYPE, linkname="elsewhere"
                )
            ],
            "target device": [_tar_member(expected, member_type=tarfile.CHRTYPE)],
            "duplicate target": [
                _tar_member(expected, payload),
                _tar_member(expected, payload),
            ],
            "missing target": [_tar_member("node-v22.23.2-linux-arm64/README.md")],
            "wrong target name": [
                _tar_member("node-v22.23.2-linux-arm64/bin/not-node", payload)
            ],
            "traversal": [
                _tar_member("../escape"),
                _tar_member(expected, payload),
            ],
        }
        for name, members in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "node.tar.xz"
                stage = root / "stage"
                stage.mkdir()
                _write_node_archive(archive, members)
                with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                    subject._extract_node(
                        archive, stage, expected, sha256(payload).hexdigest()
                    )
                self.assertFalse((stage / "bin/node").exists())

    def test_node_extraction_rejects_a_target_with_the_wrong_digest(self) -> None:
        expected = "node-v22.23.2-linux-arm64/bin/node"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "node.tar.xz"
            stage = root / "stage"
            stage.mkdir()
            _write_node_archive(archive, [_tar_member(expected, b"unexpected node")])
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject._extract_node(archive, stage, expected, "0" * 64)

    def test_paths_are_private_and_canonical(self) -> None:
        with TemporaryDirectory() as temp:
            root = subject._root(Path(temp))
            self.assertEqual(
                root, Path(temp).resolve() / ".asterion-private" / "prime-development"
            )

    def test_production_catalogs_remain_empty(self) -> None:
        from asterion.applications.prime_agent.operator.image_input_lock import (
            PRIME_IPYTHON_IMAGE_INPUT_CATALOG,
        )
        from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
            PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG,
        )

        self.assertEqual(PRIME_IPYTHON_IMAGE_INPUT_CATALOG.locks, ())
        self.assertEqual(PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG.locks, ())

    def test_gateway_rebuilds_only_when_outputs_do_not_match_locked_inventory(self) -> None:
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gateway = repo / "packages/typescript/prime-gateway"
            (gateway / "src").mkdir(parents=True)
            (gateway / "src/input.ts").write_text("export {};\n")
            lock = {
                "inputs": ["src/input.ts"],
                "inputs_sha256": subject._aggregate(gateway, ["src/input.ts"]),
                "outputs": ["dist/src/output.js"],
                "outputs_sha256": "0" * 64,
            }
            calls: list[list[str]] = []
            def runner(argv: list[str], **_: object) -> object:
                calls.append(argv)
                (gateway / "dist/src").mkdir(parents=True)
                (gateway / "dist/src/output.js").write_text("built\n")
                lock["outputs_sha256"] = subject._aggregate(gateway, ["dist/src/output.js"])
                return SimpleNamespace(stdout=b"", stderr=b"")
            subject._prepare_gateway(repo, lock, runner=runner)
            self.assertEqual(calls, [["npm", "--prefix", "packages/typescript/prime-gateway", "run", "build"]])

    def test_gateway_rejects_untrusted_inputs_without_building(self) -> None:
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            gateway = repo / "packages/typescript/prime-gateway"
            (gateway / "src").mkdir(parents=True)
            (gateway / "src/input.ts").write_text("changed\n")
            lock = {"inputs": ["src/input.ts"], "inputs_sha256": "0" * 64, "outputs": [], "outputs_sha256": subject._aggregate(gateway, [])}
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject._prepare_gateway(repo, lock, runner=lambda *_args, **_kwargs: self.fail("must not build"))

    def test_selected_image_is_inspected_then_built_and_reinspected(self) -> None:
        record = subject._locked_image_record("p1")
        calls: list[list[str]] = []
        responses = [SimpleNamespace(stdout=b"", stderr=b""), SimpleNamespace(stdout=b"", stderr=b""), SimpleNamespace(stdout=(record["digest"] + "\n").encode(), stderr=b"")]
        def runner(argv: list[str], **_: object) -> object:
            calls.append(argv)
            return responses.pop(0)
        subject._prepare_image(Path.cwd(), "p1", record, "linux/amd64", runner=runner)
        self.assertEqual(calls[0], ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "image", "inspect", "--format", "{{.Id}}", record["tag"]])
        self.assertIn("build", calls[1])
        self.assertEqual(calls[2], calls[0])

    def test_selected_image_is_not_built_when_inspection_matches(self) -> None:
        record = subject._locked_image_record("p1")
        calls: list[list[str]] = []
        subject._prepare_image(Path.cwd(), "p1", record, "linux/amd64", runner=lambda argv, **_: calls.append(argv) or SimpleNamespace(stdout=(record["digest"] + "\n").encode(), stderr=b""))
        self.assertEqual(len(calls), 1)

    def test_selected_image_rejects_wrong_digest_after_build(self) -> None:
        record = subject._locked_image_record("p1")
        responses = [SimpleNamespace(stdout=b"", stderr=b""), SimpleNamespace(stdout=b"", stderr=b""), SimpleNamespace(stdout=b"sha256:" + b"0" * 64 + b"\n", stderr=b"")]
        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject._prepare_image(Path.cwd(), "p1", record, "linux/amd64", runner=lambda *_args, **_kwargs: responses.pop(0))

    def test_image_lock_mutations_are_rejected_before_runner_or_cache_mutation(self) -> None:
        for field, value in (
            ("tag", "other:1"),
            ("digest", "sha256:" + "0" * 64),
            ("dockerfile", "p2_development_image/Dockerfile"),
            ("context", "elsewhere"),
            ("platforms", ["linux/amd64", "linux/arm64", "linux/ppc64le"]),
        ):
            with self.subTest(field=field):
                record = subject._locked_image_record("p1")
                record[field] = value
                with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                    subject._prepare_image(
                        Path.cwd(), "p1", record, "linux/amd64",
                        runner=lambda *_args, **_kwargs: self.fail("must not invoke runner"),
                    )

    def test_p7_resources_are_validated_only_for_p7(self) -> None:
        seen: list[Path] = []
        with patch.object(subject, "verify_p7_development_resources", side_effect=lambda root: seen.append(root) or SimpleNamespace(resource_sha256="sha256:" + "a" * 64)), patch.object(subject, "verify_p7_development_runtime", return_value=SimpleNamespace(runtime_sha256="sha256:" + "b" * 64)):
            self.assertEqual(subject._p7_identities(Path("/repo"), {"external_root": "external-prime/arc-agi-3", "resource_sha256": "sha256:" + "a" * 64, "runtime_wheels": {"arc_agi": subject.P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256, "arcengine": subject.P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256}}), {"p7_resource_sha256": "sha256:" + "a" * 64, "p7_runtime_sha256": "sha256:" + "b" * 64})
        self.assertEqual(seen, [Path("/external-prime/arc-agi-3/environment_files/ls20/9607627b")])

    def test_p7_validator_exception_is_redacted_as_preparation_error(self) -> None:
        record = {"external_root": "external-prime/arc-agi-3", "resource_sha256": "sha256:" + "a" * 64, "runtime_wheels": {"arc_agi": subject.P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256, "arcengine": subject.P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256}}
        with patch.object(subject, "verify_p7_development_resources", side_effect=RuntimeError("private path")):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError) as raised:
                subject._p7_identities(Path("/repo"), record)
        self.assertEqual(str(raised.exception), "Prime development preparation is unavailable")

    def test_p7_runtime_cache_is_repaired_before_one_retry(self) -> None:
        from asterion.applications.prime_agent.operator.p7_runtime_repair import verify_p7_runtime_after_cache_repair
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for package in ("arc_agi", "arcengine"):
                cache = root / "venv/lib/python3.11/site-packages" / package / "__pycache__"
                cache.mkdir(parents=True)
                (cache / "module.pyc").write_bytes(b"cache")
            calls = 0
            def verify(_root):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise ValueError("pycache")
                return "verified"
            self.assertEqual(verify_p7_runtime_after_cache_repair(root, verify), "verified")
            self.assertEqual(calls, 2)

    def test_resolver_failure_emits_source_failed_and_removes_receipt(self) -> None:
        events: list[tuple[str, str]] = []
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            with patch.object(subject, "_prepare_gateway"), patch.object(subject, "_prepare_image"), patch.object(subject, "_node", return_value=repo / "node"), patch.object(subject, "_identities", return_value={}), patch.object(subject, "_context", return_value={}), patch.object(subject, "resolve_prepared_prime_development", side_effect=RuntimeError("private resolver detail")):
                with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                    subject.prepare_prime_development(
                        repo, ("p1",), emit=lambda component, state: events.append((component, state))
                    )
            self.assertFalse((repo / ".asterion-private/prime-development/receipt.json").exists())
        self.assertEqual(events, [("gateway", "started"), ("gateway", "succeeded"), ("image", "started"), ("image", "succeeded"), ("source", "started"), ("source", "failed")])
