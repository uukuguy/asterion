#!/usr/bin/env node
// Sealed Prime P2 launcher. Every fact below is image-owned and fixed.
import { createHash } from "node:crypto";

const ROLE = "prime.programmatic-long-context";
const SCENARIO = "prime.programmatic-long-context/v1";
const WORKLOAD = "sha256:ed5b1248946a830ceda0e0bd19aef2fb65fe1462cbbd002a4a31e3d83e024dd9";
const WORKER = "prime-p2-image-worker";
const RUN = "prime-p2-image-run";
const CHALLENGE = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const TOOL = "IPython";
const STATES = ["self-check", "release", "model-response", "ipython", "oracle", "session-disposed", "completed"];
const canonical = (value) => JSON.stringify(value, (_, member) => (
  member && typeof member === "object" && !Array.isArray(member)
    ? Object.fromEntries(Object.entries(member).sort(([left], [right]) => left.localeCompare(right)))
    : member
));
const digest = (value) => `sha256:${createHash("sha256").update(value).digest("hex")}`;
const response = digest("prime-p2-fixed-ipython-cell");
const aggregate = digest("prime-p2-fixed-oracle-aggregate");
const payloads = [
  { credentials_absent: true, effective_capabilities: 0, effective_user_id: 65534, no_new_privileges: 1, nonloopback_network_absent: true, root_read_only: true, seccomp_mode: 2, workspace_only_writable: true },
  { role_id: ROLE, scenario_id: SCENARIO },
  { program_sha256: response, response_sha256: response },
  { active_tool_names: [TOOL.toLowerCase()], ipython_cell_executed: true, tool_call_count: 1 },
  { aggregate_sha256: aggregate, oracle_passed: true },
  { session_disposed: true },
  { active_tool_names: [TOOL.toLowerCase()], aggregate_sha256: aggregate, ipython_cell_executed: true, oracle_passed: true, program_sha256: response, response_sha256: response, session_disposed: true, tool_call_count: 1 },
];

for (const [sequence, kind] of STATES.entries()) {
  console.log(canonical({ challenge_digest: CHALLENGE, kind, payload: payloads[sequence], run_id: RUN, sequence, worker_id: WORKER, workload_digest: WORKLOAD }));
}
