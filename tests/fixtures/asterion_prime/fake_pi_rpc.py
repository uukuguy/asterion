"""Provider-free Pi JSONL double used only by the installed P7 smoke test.

It loads the pinned Asterion extension and invokes its public ``ipython`` tool.
The accompanying test supplies the deterministic game and worker edges; this is
not solver evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _emit(value: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _run_extension(loader: str, node: str) -> None:
    extension_fd = os.environ["ASTERION_PRIME_IPYTHON_FD"]
    source_fd = os.environ["ASTERION_PI_EXTENSION_SOURCE_FD"]
    script = """
let tool;
const loader = await import(process.argv[1]);
await loader.default({registerTool(value) { tool = value; }});
if (!tool || tool.name !== 'ipython') process.exit(2);
const result = await tool.execute('fixture-call-1', {code: 'fixture.solve()'});
if (!Array.isArray(result.content) || result.content[0]?.text !== 'completed') process.exit(3);
"""
    completed = subprocess.run(
        (node, "--input-type=module", "--eval", script, loader),
        check=False,
        close_fds=True,
        env=dict(os.environ),
        pass_fds=(int(extension_fd), int(source_fd)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        sys.stderr.write(completed.stderr.decode("utf-8", "replace"))
        raise RuntimeError("fixture extension failed")


def main() -> int:
    arguments = sys.argv[1:]
    try:
        loader = arguments[arguments.index("--extension") + 1]
    except (ValueError, IndexError):
        return 2
    if not arguments or not Path(loader).is_file() or not Path(arguments[0]).is_file():
        return 2
    node = arguments[0]
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("type") == "prompt":
            _emit({"id": request["id"], "success": True, "type": "response"})
            _emit({"type": "agent_start"})
            _emit({"type": "turn_start"})
            _emit(
                {
                    "toolCallId": "fixture-call-1",
                    "toolName": "ipython",
                    "type": "tool_execution_start",
                    "args": {"code": "fixture.solve()"},
                }
            )
            _run_extension(loader, node)
            _emit(
                {
                    "toolCallId": "fixture-call-1",
                    "isError": False,
                    "result": {"content": [{"text": "completed", "type": "text"}]},
                    "type": "tool_execution_end",
                }
            )
            _emit({"type": "turn_end"})
            # The native prime contract made agent_end the round terminal;
            # agent_settled is no longer a recognized type on this path.
            _emit({"type": "agent_end"})
            return 0
        if request.get("type") == "abort":
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
