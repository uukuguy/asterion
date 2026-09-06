from __future__ import annotations

import socket
import tempfile
import threading
import unittest
import os
from pathlib import Path


class TestP7BrokerProcess(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("ASTERION_P7_REAL_BROKER_TEST") == "1", "operator opt-in")
    def test_external_process_completes_and_replays_four_actions(self) -> None:
        from asterion.applications.prime_agent.operator.p7_broker_service import P7BrokerService

        root = Path("/tmp/arc-agi-probe.zAWnDU")
        service = P7BrokerService(
            interpreter=root / "venv/bin/python",
            asterion_src=Path(__file__).resolve().parents[1] / "src",
            resource_root=root / "normal-env/ls20/9607627b",
        )
        try:
            namespace: dict[str, object] = {}
            exec(service.start(), namespace)
            namespace["observe"]()
            for _ in range(4):
                namespace["act"](1)
            self.assertEqual(namespace["status"]()["terminal_reason"], "action-limit")
            self.assertEqual(service.replay()["action_count"], 4)
        finally:
            service.close()

    def test_generated_model_client_uses_only_authenticated_framed_surface(self) -> None:
        from asterion.applications.prime_agent.operator.p7_broker_process import (
            p7_model_client_module_bytes,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(path))
            listener.listen(1)
            seen: list[dict[str, object]] = []

            def serve() -> None:
                connection, _ = listener.accept()
                with connection:
                    request = connection.makefile("rb").readline()
                    import json
                    seen.append(json.loads(request))
                    connection.sendall(b'{"ok":true,"result":{"terminal":true}}\n')

            thread = threading.Thread(target=serve)
            thread.start()
            namespace: dict[str, object] = {}
            exec(p7_model_client_module_bytes(str(path), "t"), namespace)
            self.assertEqual(namespace["status"](), {"terminal": True})
            thread.join(2)
            listener.close()
            self.assertEqual(seen, [{"data": {}, "method": "status", "sequence": 1, "token": "t"}])

    def test_rejects_noncanonical_resource_root(self) -> None:
        from asterion.applications.prime_agent.operator.p7_broker_process import (
            P7BrokerProcessError,
            p7_arcade_environment_root,
        )

        with self.assertRaises(P7BrokerProcessError):
            p7_arcade_environment_root(Path("relative"))
