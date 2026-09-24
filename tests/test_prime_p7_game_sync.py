from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.sync_prime_p7_games import SyncError, main, sync_games


class _Response:
    def __init__(self, *, payload: object | None = None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class TestPrimeP7GameSync(unittest.TestCase):
    def test_syncs_exact_catalog_metadata_and_class_sources_with_get_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "arc-agi-3"
            ids = tuple(f"g{i:03d}-{i:08x}" for i in range(25))
            calls: list[tuple[str, dict[str, str], float]] = []

            def get(url: str, *, headers: dict[str, str], timeout: float) -> _Response:
                calls.append((url, headers, timeout))
                if url.endswith("/api/games"):
                    return _Response(payload=[{"game_id": game_id} for game_id in reversed(ids)])
                game_id = url.split("/api/games/", 1)[1].removesuffix("/source")
                short = game_id.split("-", 1)[0]
                class_name = short[0].upper() + short[1:]
                if url.endswith("/source"):
                    return _Response(content=f"class {class_name}:\n    pass\n".encode())
                return _Response(
                    payload={
                        "game_id": game_id,
                        "title": game_id,
                        "tags": ["keyboard"],
                        "class_name": class_name,
                    }
                )

            synced = sync_games(root, api_key="private-key", base_url="https://arc.example", get=get)

            self.assertEqual(synced, ids)
            self.assertEqual(len(calls), 51)
            self.assertTrue(all(headers == {"X-API-Key": "private-key", "Accept": "application/json"}
                                for _, headers, _ in calls))
            self.assertTrue(all(timeout == 10.0 for _, _, timeout in calls))
            for game_id in ids:
                short, version = game_id.split("-", 1)
                destination = root / "environment_files" / short / version
                self.assertEqual(json.loads((destination / "metadata.json").read_text())["game_id"], game_id)
                self.assertIn(f"class {short[0].upper() + short[1:]}:",
                              (destination / f"{short}.py").read_text())

    def test_rejects_symlinked_destination_before_network_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "arc-agi-3"
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / "environment_files").parent.mkdir(parents=True)
            (root / "environment_files").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(SyncError, "symlink"):
                sync_games(root, api_key="private-key", get=lambda *_args, **_kwargs: self.fail("network called"))
            self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_existing_different_game_without_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "arc-agi-3"
            destination = root / "environment_files" / "ls20" / "9607627b"
            destination.mkdir(parents=True)
            source = destination / "ls20.py"
            source.write_text("old private source", encoding="utf-8")

            def get(url: str, **_kwargs: object) -> _Response:
                if url.endswith("/api/games"):
                    return _Response(payload=[{"game_id": "ls20-9607627b"}])
                if url.endswith("/source"):
                    return _Response(content=b"class Ls20:\n    pass\n")
                return _Response(payload={"game_id": "ls20-9607627b", "title": "LS20", "tags": [], "class_name": "Ls20"})

            with self.assertRaisesRegex(SyncError, "existing"):
                sync_games(root, api_key="private-key", get=get)
            self.assertEqual(source.read_text(encoding="utf-8"), "old private source")

    def test_cli_reads_operator_key_without_printing_it_or_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "arc-agi-3"
            env_file = Path(directory) / ".env"
            env_file.write_text("ARC_API_KEY=private-key\n", encoding="utf-8")
            output = io.StringIO()
            with patch("tools.sync_prime_p7_games.sync_games", return_value=("ls20-9607627b",)) as sync:
                with patch("sys.stdout", output):
                    result = main(["--arc-root", str(root), "--env-file", str(env_file)])
            self.assertEqual(result, 0)
            self.assertEqual(sync.call_args.kwargs["api_key"], "private-key")
            self.assertIn("ls20-9607627b", output.getvalue())
            self.assertNotIn("private-key", output.getvalue())
            self.assertNotIn(str(root), output.getvalue())


if __name__ == "__main__":
    unittest.main()
