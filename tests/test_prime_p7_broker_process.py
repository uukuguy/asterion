from __future__ import annotations

import socket
import tempfile
import threading
import unittest
import os
from pathlib import Path
from unittest.mock import patch


class TestP7BrokerProcess(unittest.TestCase):
    def test_service_retries_ready_when_control_socket_exists_before_listening(self) -> None:
        from asterion.applications.prime_agent.operator.p7_broker_service import P7BrokerService

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src"
            resource = root / "normal-env/ls20/9607627b"
            source.mkdir(parents=True)
            resource.mkdir(parents=True)
            private = root / "private"
            requests: list[dict[str, object]] = []
            commands: list[tuple[object, ...]] = []
            listener: socket.socket | None = None
            server: threading.Thread | None = None

            class Process:
                def poll(self) -> None:
                    return None

            def launch(command: tuple[object, ...], **_: object) -> Process:
                nonlocal listener, server
                commands.append(command)
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                listener.bind(str(private / "control.sock"))
                os.chmod(private / "control.sock", 0o600)

                def serve() -> None:
                    assert listener is not None
                    threading.Event().wait(.05)
                    listener.listen(2)
                    connection, _ = listener.accept()
                    with connection:
                        import json
                        request = json.loads(connection.makefile("rb").readline())
                        requests.append(request)
                        connection.sendall(b'{"ok":true,"result":{"ready":true}}\n')

                server = threading.Thread(target=serve)
                server.start()
                return Process()

            service = P7BrokerService(
                interpreter=Path("/bin/sh"),
                asterion_src=source,
                resource_root=resource,
                private_dir=private,
            )
            with patch("asterion.applications.prime_agent.operator.p7_broker_service.subprocess.Popen", side_effect=launch):
                client = service.start()
            self.assertTrue(client)
            self.assertEqual([request["sequence"] for request in requests], [1])
            self.assertEqual(commands[0][1:3], ("-I", "-X"))
            self.assertEqual(commands[0][3], f"pycache_prefix={private / 'pycache'}")
            assert server is not None
            server.join(2)
            assert listener is not None
            listener.close()

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
