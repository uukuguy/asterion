from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from asterion.capabilities.dci.implementation.runtime.pi_rpc import PiRpcClient


_PRIVATE_FD_VARIABLE = "ASTERION_DCI_PATHLIGHT_PRIVATE_FD"
_PRIVATE_CONTRACT_VARIABLE = "ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT"
_FIXED_ERROR = "Pi RPC get_entries shape is invalid"


def _client(root: Path, **overrides: object) -> PiRpcClient:
    package = root / "pi" / "packages" / "coding-agent"
    (package / "dist").mkdir(parents=True, exist_ok=True)
    (package / "dist" / "cli.js").write_text("", encoding="utf-8")
    agent = root / "agent"
    agent.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "package_dir": package,
        "cwd": root,
        "agent_dir": agent,
        "provider": "openai-codex",
        "model": "gpt-test",
        "tools": "read",
        "show_tools": False,
        "system_prompt_file": None,
        "append_system_prompt_file": None,
        "extra_args": (),
        "literal_extra_args": (),
        "keep_session": False,
        "node_max_old_space_size_mb": None,
    }
    values.update(overrides)
    return PiRpcClient(**values)  # type: ignore[arg-type]


def _provider_entry(*, entry_id: str = "provider-entry-1", request_index: int = 1) -> dict[str, object]:
    return {
        "id": entry_id,
        "parentId": None,
        "timestamp": "2026-08-03T12:00:00.000Z",
        "type": "custom",
        "customType": "dci-provider-request-observation",
        "data": {
            "schema": "dci.provider-request-observation/v1",
            "request_index": request_index,
            "capture_status": "captured",
            "payload_sha256": "a" * 64,
            "payload_bytes": 27,
            "shape_sha256": "b" * 64,
            "field_count": 2,
            "leaf_count": 1,
            "text_characters": 5,
            "segments": [
                {
                    "segment_index": 0,
                    "role": "user",
                    "structure_kind": "message",
                    "content_sha256": "c" * 64,
                    "content_length": 5,
                    "source_call_sha256": None,
                    "missing_evidence": False,
                    "segment_sha256": "d" * 64,
                }
            ],
            "missing_evidence": [],
            "summary_sha256": "e" * 64,
        },
    }


def _context_entry() -> dict[str, object]:
    state = {
        "accumulatedOriginalToolCharacters": 0,
        "truncatedResults": 0,
        "compactionCount": 0,
        "preservedTurns": None,
        "compactionPending": False,
        "summaryAttempts": 0,
        "summarySuccesses": 0,
        "consecutiveSummaryFailures": 0,
        "summarySuppressed": False,
    }
    return {
        "id": "context-entry-1",
        "parentId": "provider-entry-1",
        "timestamp": "2026-08-03T12:00:00.000Z",
        "type": "custom",
        "customType": "dci-context-state",
        "data": {
            "schema": "dci.context-state/v2",
            "profile": "level3",
            "contractVersion": "dci.context-profile/v1",
            "state": state,
        },
    }


def _response(entries: list[object], *, leaf_id: str | None = None) -> dict[str, object]:
    resolved_leaf = leaf_id
    if leaf_id is None and entries and isinstance(entries[-1], dict):
        candidate = entries[-1].get("id")
        resolved_leaf = candidate if isinstance(candidate, str) else None
    return {
        "type": "response",
        "id": "py-1",
        "command": "get_entries",
        "success": True,
        "data": {"entries": entries, "leafId": resolved_leaf},
    }


class DciPiRpcObservationTests(unittest.TestCase):
    def test_context_extension_precedes_observation_extension_and_private_values_stay_off_argv(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            context_path = root / "context.ts"
            observation_path = root / "SENTINEL-observation.ts"
            client = _client(
                root,
                extension_path=context_path,
                context_profile="level3",
                context_contract="dci.context-profile/v1",
                observation_extension_path=observation_path,
                observation_fd=37,
                observation_contract="SENTINEL-private-contract/v1",
            )
            command = client._build_command(node_bin="/usr/bin/node")

        extension_positions = [
            index for index, value in enumerate(command) if value == "--extension"
        ]
        self.assertEqual(len(extension_positions), 2)
        self.assertEqual(command[extension_positions[0] + 1], str(context_path))
        self.assertEqual(command[extension_positions[1] + 1], str(observation_path))
        self.assertNotIn("37", command)
        self.assertNotIn("SENTINEL-private-contract/v1", command)
        self.assertNotIn(_PRIVATE_FD_VARIABLE, command)
        self.assertNotIn(_PRIVATE_CONTRACT_VARIABLE, command)

    def test_start_passes_sorted_unique_union_of_resource_and_observation_fds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            client = _client(
                root,
                inherited_fds=(9, 5, 9, 37),
                observation_extension_path=root / "observation.ts",
                observation_fd=37,
                observation_contract="dci.pathlight-provider-request-capture/v1",
            )
            process = MagicMock()
            with (
                patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.resolve_node_bin",
                    return_value="/usr/bin/node",
                ),
                patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.subprocess.Popen",
                    return_value=process,
                ) as popen,
                patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.threading.Thread"
                ),
                patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True),
            ):
                client.start()

        self.assertEqual(popen.call_args.kwargs["pass_fds"], (5, 9, 37))
        self.assertEqual(
            popen.call_args.kwargs["env"][_PRIVATE_FD_VARIABLE], "37"
        )
        self.assertEqual(
            popen.call_args.kwargs["env"][_PRIVATE_CONTRACT_VARIABLE],
            "dci.pathlight-provider-request-capture/v1",
        )

    def test_partial_or_invalid_observation_configuration_fails_before_node_or_process(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            valid = {
                "observation_extension_path": root / "SENTINEL-observation.ts",
                "observation_fd": 37,
                "observation_contract": "SENTINEL-private-contract/v1",
            }
            cases = (
                {"observation_extension_path": valid["observation_extension_path"]},
                {"observation_fd": valid["observation_fd"]},
                {"observation_contract": valid["observation_contract"]},
                {**valid, "observation_extension_path": Path("relative.ts")},
                {**valid, "observation_fd": True},
                {**valid, "observation_fd": -1},
                {**valid, "observation_contract": ""},
            )
            for values in cases:
                with self.subTest(values=tuple(values)), patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.resolve_node_bin"
                ) as resolve_node, patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.subprocess.Popen"
                ) as popen, self.assertRaises(ValueError) as raised:
                    client = _client(root, **values)
                    client.start()
                self.assertNotIn("SENTINEL", str(raised.exception))
                resolve_node.assert_not_called()
                popen.assert_not_called()

    def test_provider_projection_is_closed_body_free_and_separate_from_context_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            provider = _provider_entry()
            context = _context_entry()
            response = _response([provider, context])
            with patch.object(client, "_send") as send, patch.object(
                client, "_read_json_line", return_value=response
            ):
                observed = client.get_provider_request_entries()

            self.assertEqual(observed, (provider,))
            self.assertEqual(
                send.call_args.args[0], {"id": "py-1", "type": "get_entries"}
            )
            rendered = repr(observed)
            self.assertNotIn("SENTINEL", rendered)
            observed_data = observed[0]["data"]
            for forbidden in ("payload_json", "api_key", "path", "provider", "model", "config"):
                self.assertNotIn(forbidden, observed_data)

            second_response = copy.deepcopy(response)
            second_response["id"] = "py-2"
            with patch.object(client, "_send"), patch.object(
                client, "_read_json_line", return_value=second_response
            ):
                context_only = client.get_entries()
            self.assertEqual(context_only, (context,))

    def test_provider_projection_rejects_body_fields_duplicates_and_malformed_shapes(
        self,
    ) -> None:
        base = _provider_entry()
        cases: list[tuple[str, list[object], str | None]] = []
        for forbidden in ("payload_json", "api_key", "path", "provider", "model", "config"):
            entry = copy.deepcopy(base)
            entry["data"][forbidden] = f"SENTINEL-{forbidden}"  # type: ignore[index]
            cases.append((forbidden, [entry], None))
        duplicate_id = copy.deepcopy(base)
        duplicate_request = _provider_entry(entry_id="provider-entry-2")
        duplicate_id["parentId"] = "provider-entry-1"
        duplicate_request["parentId"] = "provider-entry-1"
        cases.extend(
            (
                ("duplicate-id", [base, duplicate_id], None),
                ("duplicate-request", [base, duplicate_request], None),
            )
        )
        mutations: tuple[tuple[str, tuple[str, ...], object], ...] = (
            ("schema", ("data", "schema"), "SENTINEL-schema"),
            ("capture-status", ("data", "capture_status"), "missing"),
            ("bool-count", ("data", "field_count"), True),
            ("negative-count", ("data", "leaf_count"), -1),
            ("segments-type", ("data", "segments"), {}),
            ("segment-missing-drift", ("data", "missing_evidence"), ["context-segment"]),
            ("segment-index", ("data", "segments", "0", "segment_index"), 1),
            ("segment-role", ("data", "segments", "0", "role"), "SENTINEL-role"),
            ("segment-length", ("data", "segments", "0", "content_length"), True),
        )
        for name, path, value in mutations:
            entry = copy.deepcopy(base)
            target: object = entry
            for part in path[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]  # type: ignore[index]
            target[path[-1]] = value  # type: ignore[index]
            cases.append((name, [entry], None))
        foreign = copy.deepcopy(base)
        foreign["customType"] = "SENTINEL-foreign-custom-type"
        cases.append(("foreign-custom", [foreign], None))
        cases.append(("cursor-drift", [base], "SENTINEL-drifted-leaf"))

        with tempfile.TemporaryDirectory() as directory:
            for name, entries, leaf_id in cases:
                with self.subTest(name=name):
                    client = _client(Path(directory).resolve())
                    response = _response(entries, leaf_id=leaf_id)
                    with patch.object(client, "_send"), patch.object(
                        client, "_read_json_line", return_value=response
                    ), self.assertRaises(RuntimeError) as raised:
                        client.get_provider_request_entries()
                    self.assertEqual(str(raised.exception), _FIXED_ERROR)
                    self.assertIsNone(raised.exception.__cause__)
                    self.assertIsNone(raised.exception.__context__)
                    self.assertNotIn("SENTINEL", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
