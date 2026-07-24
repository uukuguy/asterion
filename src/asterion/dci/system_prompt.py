"""Render Pi's dynamically generated prompt inside the Asterion DCI boundary."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from asterion.dci.config import DciPaths
from asterion.dci.pi_rpc import _node_env, resolve_node_bin


_NODE_SCRIPT = """
const { buildSystemPrompt } = await import(process.argv[1]);
const { createAllToolDefinitions } = await import(process.argv[2]);
const cwd = process.argv[3];
const tools = JSON.parse(process.argv[4]);
const appendText = process.argv[5] || "";
const definitions = createAllToolDefinitions(cwd);
const toolSnippets = {};
const promptGuidelines = [];
for (const toolName of tools) {
  const definition = definitions[toolName];
  if (!definition) throw new Error(`Unknown built-in tool: ${toolName}`);
  if (definition.promptSnippet) toolSnippets[toolName] = definition.promptSnippet;
  if (Array.isArray(definition.promptGuidelines)) promptGuidelines.push(...definition.promptGuidelines);
}
process.stdout.write(buildSystemPrompt({
  cwd, selectedTools: tools, toolSnippets, promptGuidelines,
  appendSystemPrompt: appendText || undefined,
}));
"""


def render_pi_system_prompt(
    paths: DciPaths,
    cwd: Path,
    tools: str | None,
    append_system_prompt_file: Path | None,
) -> str:
    """Ask the built Pi modules for a prompt using literal Node argv."""

    package_dir = paths.pi.package_dir
    prompt_module = package_dir / "dist" / "core" / "system-prompt.js"
    tools_module = package_dir / "dist" / "core" / "tools" / "index.js"
    if not prompt_module.is_file() or not tools_module.is_file():
        raise RuntimeError("Pi system prompt modules are unavailable")
    selected_tools = [
        part.strip()
        for part in (tools or "read,bash,edit,write").split(",")
        if part.strip()
    ]
    append_text = ""
    if append_system_prompt_file is not None:
        append_text = Path(append_system_prompt_file).read_text(encoding="utf-8")
    node_bin = resolve_node_bin(os.environ)
    completed = subprocess.run(
        [
            node_bin,
            "--input-type=module",
            "-e",
            _NODE_SCRIPT,
            prompt_module.resolve().as_uri(),
            tools_module.resolve().as_uri(),
            str(Path(cwd).resolve()),
            json.dumps(selected_tools),
            append_text,
        ],
        text=True,
        capture_output=True,
        env=_node_env({}, node_bin),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Pi system prompt rendering failed")
    return completed.stdout
