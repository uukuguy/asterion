from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_H036 = {
    "hypothesis": "H-036",
    "outcome": "passed",
    "command_id": "check.operational-parity-closure",
}
EXPECTED_H037 = {
    "hypothesis": "H-037",
    "outcome": "passed",
    "command_id": "prime-system-parity-operation-host-callback",
}


def _seed_h035_state(state_dir: Path) -> None:
    state_dir.mkdir()
    canonical_rows = (ROOT / "docs" / "status" / "climb" / "runs.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    h035_rows = [
        row
        for row in canonical_rows
        if row.startswith("cycle,") or int(row.split(",", 1)[0]) <= 35
    ]
    (state_dir / "runs.csv").write_text("\n".join(h035_rows) + "\n", encoding="utf-8")


def _seed_h036_state(state_dir: Path) -> None:
    state_dir.mkdir()
    canonical_rows = (ROOT / "docs" / "status" / "climb" / "runs.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    h036_rows = [
        row
        for row in canonical_rows
        if row.startswith("cycle,") or int(row.split(",", 1)[0]) <= 36
    ]
    (state_dir / "runs.csv").write_text("\n".join(h036_rows) + "\n", encoding="utf-8")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


def _fake_h036_path(bin_dir: Path, log_path: Path, *, dirty: bool = False) -> str:
    dirty_status = "printf ' M docs/status/JOURNAL.md\\n'" if dirty else ":"
    _write_executable(
        bin_dir / "make",
        "#!/bin/sh\n"
        "printf 'make %s\\n' \"$*\" >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "exit 0\n",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/bin/sh\n"
        "printf 'uv %s\\n' \"$*\" >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "exit 0\n",
    )
    _write_executable(
        bin_dir / "git",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"status\" ]; then\n"
        f"  {dirty_status}\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"diff\" ] && [ \"$2\" = \"--check\" ]; then\n"
        "  printf 'git diff --check\\n' >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
    )
    _write_executable(
        bin_dir / "node",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-v\" ]; then\n"
        "  printf 'v22.23.2\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )
    return str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _run_h036_cycle(state_dir: Path, path: str, log_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "tools" / "climb" / "cycle.sh"), "H-036"],
        cwd=ROOT,
        env={
            **os.environ,
            "ASTERION_CLIMB_STATE_DIR": str(state_dir),
            "ASTERION_TEST_COMMAND_LOG": str(log_path),
            "PATH": path,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _fake_h037_path(
    bin_dir: Path,
    log_path: Path,
    *,
    status: tuple[str, ...] = (),
) -> str:
    del log_path
    _write_executable(
        bin_dir / "npm",
        "#!/bin/sh\n"
        "printf 'npm %s\\n' \"$*\" >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "exit 0\n",
    )
    _write_executable(
        bin_dir / "make",
        "#!/bin/sh\n"
        "printf 'make %s\\n' \"$*\" >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "exit 0\n",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/bin/sh\n"
        "printf 'uv %s\\n' \"$*\" >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "exit 0\n",
    )
    rendered_status = "".join(
        f"  printf '%s\\n' {shlex.quote(line)}\n" for line in status
    ) or "  :\n"
    _write_executable(
        bin_dir / "git",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"status\" ]; then\n"
        f"{rendered_status}"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"diff\" ] && [ \"$2\" = \"--check\" ]; then\n"
        "  printf 'git diff --check\\n' >> \"$ASTERION_TEST_COMMAND_LOG\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
    )
    _write_executable(
        bin_dir / "node",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-v\" ]; then\n"
        "  printf 'v22.23.2\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )
    return str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _run_h037_cycle(
    state_dir: Path, path: str, log_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "tools" / "climb" / "cycle.sh"), "H-037"],
        cwd=ROOT,
        env={
            **os.environ,
            "ASTERION_CLIMB_STATE_DIR": str(state_dir),
            "ASTERION_TEST_COMMAND_LOG": str(log_path),
            "PATH": path,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _latest_cycle_result(state_dir: Path) -> dict[str, str]:
    rows = (state_dir / "runs.csv").read_text(encoding="utf-8").splitlines()
    _, hypothesis, outcome, command_id = rows[-1].split(",")
    return {
        "hypothesis": hypothesis,
        "outcome": outcome,
        "command_id": command_id,
    }


def _new_hypothesis_ids(state_dir: Path) -> tuple[str, ...]:
    rendered = (state_dir / "research-tree.md").read_text(encoding="utf-8")
    ids = tuple(
        token.rstrip(":")
        for token in rendered.replace("—", " ").split()
        if token.startswith("H-")
    )
    return tuple(hypothesis_id for hypothesis_id in ids if hypothesis_id > "H-036")


def _passed_ledger_claims() -> tuple[str, ...]:
    claims: list[str] = []
    table_started = False
    for line in (ROOT / "docs" / "status" / "PRIME-PARITY-LEDGER.md").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.startswith("| Phase claim |"):
            table_started = True
            continue
        if table_started and not line.startswith("|"):
            break
        if not table_started or line.startswith("|---"):
            continue
        columns = [column.strip(" `") for column in line.strip("|").split("|")]
        if len(columns) >= 2 and columns[1].startswith("PASS"):
            claims.append(columns[0])
    return tuple(claims)


class TestPrimeClimb(unittest.TestCase):
    def test_h001_cycle_records_safe_provider_free_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            completed = subprocess.run(
                [str(ROOT / "tools" / "climb" / "cycle.sh"), "H-001"],
                cwd=ROOT,
                env={**os.environ, "ASTERION_CLIMB_STATE_DIR": str(state_dir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rendered = completed.stdout + completed.stderr
            self.assertNotIn("PRIVATE", rendered)
            self.assertNotIn("SECRET", rendered)
            state = json.loads((state_dir / "session-state.json").read_text())
            self.assertEqual(
                state,
                {
                    "last_hypothesis": "H-001",
                    "last_outcome": "passed",
                    "next_action": "H-002",
                },
            )
            rows = (state_dir / "runs.csv").read_text().splitlines()
            self.assertEqual(
                rows,
                [
                    "cycle,hypothesis_id,outcome,command_id",
                    "1,H-001,passed,test.prime-rlm.provider-free",
                ],
            )

    def test_h035_closure_records_exact_transition_and_contiguous_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            state_dir.mkdir()
            (state_dir / "runs.csv").write_text(
                "\n".join(
                    (ROOT / "docs" / "status" / "climb" / "runs.csv")
                    .read_text()
                    .splitlines()[:35]
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "tools" / "climb" / "regen-tree.py"),
                    "H-035",
                    "passed",
                    "H-036",
                    "check.client-interfaces-closure",
                ],
                cwd=ROOT,
                env={**os.environ, "ASTERION_CLIMB_STATE_DIR": str(state_dir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads((state_dir / "session-state.json").read_text()),
                {
                    "last_hypothesis": "H-035",
                    "last_outcome": "passed",
                    "next_action": "H-036",
                },
            )
            rows = (state_dir / "runs.csv").read_text().splitlines()
            self.assertEqual(
                rows[-1],
                "35,H-035,passed,check.client-interfaces-closure",
            )
            self.assertEqual(
                [int(row.split(",", 1)[0]) for row in rows[1:]],
                list(range(1, 36)),
            )
            self.assertIn(
                "- H-035: passed — client interface closure gates",
                (state_dir / "research-tree.md").read_text(),
            )
            self.assertIn(
                "- Next: H-036 — operational surface inventory",
                (state_dir / "research-tree.md").read_text(),
            )

    def test_h035_transition_rejects_noncanonical_existing_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            state_dir.mkdir()
            (state_dir / "runs.csv").write_text(
                "cycle,hypothesis_id,outcome,command_id\n"
                "34,H-034,passed,check.ecosystem-capabilities-closure\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "tools" / "climb" / "regen-tree.py"),
                    "H-035",
                    "passed",
                    "H-036",
                    "check.client-interfaces-closure",
                ],
                cwd=ROOT,
                env={**os.environ, "ASTERION_CLIMB_STATE_DIR": str(state_dir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)

    def test_h036_closure_remains_unique_with_h037_successor(self) -> None:
        hypotheses = (ROOT / "docs" / "status" / "climb" / "hypotheses.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "- id: H-035\n"
            "  description: client interface closure inventory identifies exact shared-stream evidence packages\n"
            "  parent_paradigm: interface-clients\n"
            "  ranking: 0.7\n"
            "  status: passed\n",
            hypotheses,
        )
        self.assertIn(
            "- id: H-036\n"
            "  description: operational surface inventory identifies six host-owned authority packages\n"
            "  parent_paradigm: interface-operations\n"
            "  ranking: 0.7\n"
            "  status: passed\n",
            hypotheses,
        )
        rows = (ROOT / "docs" / "status" / "climb" / "runs.csv").read_text(
            encoding="utf-8"
        ).splitlines()
        run_rows = [row.split(",") for row in rows[1:]]
        self.assertEqual(
            [int(columns[0]) for columns in run_rows],
            list(range(1, 38)),
        )
        self.assertEqual(
            [columns[1] for columns in run_rows],
            [f"H-{cycle:03d}" for cycle in range(1, 38)],
        )
        self.assertEqual(
            rows[-3:],
            [
                "35,H-035,passed,check.client-interfaces-closure",
                "36,H-036,passed,check.operational-parity-closure",
                "37,H-037,passed,prime-system-parity-operation-host-callback",
            ],
        )
        self.assertEqual(
            json.loads(
                (ROOT / "docs" / "status" / "climb" / "session-state.json").read_text(
                    encoding="utf-8"
                )
            ),
            {
                "last_hypothesis": "H-037",
                "last_outcome": "passed",
                "next_action": "phase-3-native-kernel-design",
            },
        )
        research_tree = (ROOT / "docs" / "status" / "climb" / "research-tree.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("- H-036: passed — operational surface closure gates", research_tree)
        self.assertIn("- H-037: passed — Prime system parity production callback", research_tree)
        self.assertIn("- Next: Phase 3 — Asterion-native kernel design", research_tree)
        self.assertNotIn("- Future: separately approved hypothesis required", research_tree)
        for excluded_hypothesis_id in ("H-044", "H-045"):
            self.assertNotIn(excluded_hypothesis_id, hypotheses)
            self.assertNotIn(excluded_hypothesis_id, "\n".join(rows))
            self.assertNotIn(excluded_hypothesis_id, research_tree)

    def test_h036_requires_all_six_receipts_and_does_not_invent_successor_or_native_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_dir = workspace / "climb"
            command_log = workspace / "commands.log"
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            _seed_h035_state(state_dir)

            completed = _run_h036_cycle(
                state_dir,
                _fake_h036_path(bin_dir, command_log),
                command_log,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(_latest_cycle_result(state_dir), EXPECTED_H036)
            self.assertEqual(_new_hypothesis_ids(state_dir), ())
            self.assertEqual(
                json.loads((state_dir / "session-state.json").read_text()),
                {
                    "last_hypothesis": "H-036",
                    "last_outcome": "passed",
                    "next_action": "future-work-queue",
                },
            )
            self.assertIn(
                "- H-036: passed — operational surface closure gates",
                (state_dir / "research-tree.md").read_text(encoding="utf-8"),
            )
            self.assertNotIn("Verified-native-parity", _passed_ledger_claims())
            self.assertEqual(
                command_log.read_text(encoding="utf-8").splitlines(),
                [
                    "make test.prime-operational-auth.provider-free",
                    "make test.prime-operational-model-selection.provider-free",
                    "make test.prime-operational-settings-keybindings.provider-free",
                    "make test.prime-operational-telemetry-usage.provider-free",
                    "make test.prime-operational-doctor.provider-free",
                    "make test.prime-operational-controlled-update-restart.provider-free",
                    "uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway",
                    "make check",
                    "make promotion-check",
                    "git diff --check",
                ],
            )

    def test_h036_rejects_dirty_input_before_receipts_or_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_dir = workspace / "climb"
            command_log = workspace / "commands.log"
            bin_dir = workspace / "bin"
            bin_dir.mkdir()
            _seed_h035_state(state_dir)

            completed = _run_h036_cycle(
                state_dir,
                _fake_h036_path(bin_dir, command_log, dirty=True),
                command_log,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(command_log.exists())
            rows = (state_dir / "runs.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(rows[-1], "35,H-035,passed,check.client-interfaces-closure")

    def test_h037_canonical_closure_occurs_once_and_routes_to_phase3(self) -> None:
        hypotheses = (ROOT / "docs" / "status" / "climb" / "hypotheses.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "- id: H-037\n"
            "  description: Prime system parity production path closes through the operator-owned operation callback\n"
            "  parent_paradigm: system-parity\n"
            "  ranking: 0.9\n"
            "  status: passed\n",
            hypotheses,
        )
        rows = (ROOT / "docs" / "status" / "climb" / "runs.csv").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(
            rows[-1],
            "37,H-037,passed,prime-system-parity-operation-host-callback",
        )
        self.assertEqual(
            [int(row.split(",", 1)[0]) for row in rows[1:]],
            list(range(1, 38)),
        )
        self.assertEqual(sum(",H-037," in row for row in rows), 1)
        self.assertEqual(
            json.loads(
                (ROOT / "docs" / "status" / "climb" / "session-state.json").read_text(
                    encoding="utf-8"
                )
            ),
            {
                "last_hypothesis": "H-037",
                "last_outcome": "passed",
                "next_action": "phase-3-native-kernel-design",
            },
        )
        research_tree = (ROOT / "docs" / "status" / "climb" / "research-tree.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            research_tree.count(
                "- H-037: passed — Prime system parity production callback"
            ),
            1,
        )
        self.assertIn("- Next: Phase 3 — Asterion-native kernel design", research_tree)
        self.assertNotIn("- Future: separately approved hypothesis required", research_tree)

    def test_h037_gate_is_exact_and_allows_only_audited_artifact_roots(self) -> None:
        allowed_statuses = (
            (),
            ('?? "$(getconf DARWIN_USER_TEMP_DIR)/"',),
            ("?? .task13-promotion-bin/",),
            (
                '?? "$(getconf DARWIN_USER_TEMP_DIR)/"',
                "?? .task13-promotion-bin/",
            ),
        )
        for status in allowed_statuses:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                state_dir = workspace / "climb"
                command_log = workspace / "commands.log"
                bin_dir = workspace / "bin"
                bin_dir.mkdir()
                _seed_h036_state(state_dir)

                completed = _run_h037_cycle(
                    state_dir,
                    _fake_h037_path(bin_dir, command_log, status=status),
                    command_log,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(_latest_cycle_result(state_dir), EXPECTED_H037)
                self.assertEqual(
                    json.loads((state_dir / "session-state.json").read_text()),
                    {
                        "last_hypothesis": "H-037",
                        "last_outcome": "passed",
                        "next_action": "phase-3-native-kernel-design",
                    },
                )
                self.assertEqual(
                    command_log.read_text(encoding="utf-8").splitlines(),
                    [
                        "npm --prefix packages/typescript/prime-gateway run build",
                        "uv run python -m unittest -v tests.test_prime_operation_real_process",
                        "uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway",
                        "make check",
                        "make promotion-check",
                        "git diff --check",
                    ],
                )

    def test_h037_rejects_every_other_dirty_path_before_commands_or_state(self) -> None:
        for status in (
            (" M docs/status/JOURNAL.md",),
            ("?? unexpected-artifact/",),
            (
                '?? "$(getconf DARWIN_USER_TEMP_DIR)/"',
                "?? unexpected-artifact/",
            ),
        ):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                state_dir = workspace / "climb"
                command_log = workspace / "commands.log"
                bin_dir = workspace / "bin"
                bin_dir.mkdir()
                _seed_h036_state(state_dir)

                completed = _run_h037_cycle(
                    state_dir,
                    _fake_h037_path(bin_dir, command_log, status=status),
                    command_log,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertFalse(command_log.exists())
                rows = (state_dir / "runs.csv").read_text(encoding="utf-8").splitlines()
                self.assertEqual(
                    rows[-1],
                    "36,H-036,passed,check.operational-parity-closure",
                )


if __name__ == "__main__":
    unittest.main()
