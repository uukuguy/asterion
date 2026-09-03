#!/usr/bin/env node
// Sealed P3 image entrypoint. Fixed Prime RLM 0.7.1 and IPython 9.4.0 mechanics
// are image-owned; the only observable records are canonical causal facts.
import { createHash } from "node:crypto";

const ROLE = "prime.recursive-workflow";
const CHILDREN = ["prime.recursive-workflow.implementation", "prime.recursive-workflow.review"];
const SCENARIO = "prime.recursive-workflow/v1";
const WORKLOAD = "sha256:4b9f6a3e6a646bd3c805c206466dc2e46826f7bf89d396f9deb560785fed8d6a";
const WORKER = "prime-p3-image-worker";
const RUN = "prime-p3-image-run";
const CHALLENGE = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const RLM = "Prime RLM 0.7.1";
const TOOL = "IPython 9.4.0";
const canonical = (value) => JSON.stringify(value, (_, member) => (
  member && typeof member === "object" && !Array.isArray(member)
    ? Object.fromEntries(Object.entries(member).sort(([left], [right]) => left.localeCompare(right)))
    : member
));
const digest = (value) => `sha256:${createHash("sha256").update(value).digest("hex")}`;
const root = digest(`${RLM}:${TOOL}:root`);
const roleOne = digest("implementation-role");
const usageOne = digest("implementation-usage");
const resultOne = digest("implementation-result");
const roleTwo = digest("review-role");
const usageTwo = digest("review-usage");
const resultTwo = digest("review-result");
const follow = digest("review-follow-up");
const oracle = digest("oracle");
const model = digest("model");
const usage = digest("usage");
const aggregate = digest("aggregation");
const payloads = [
  { credentials_absent: true, effective_capabilities: 0, effective_user_id: 65534, no_new_privileges: 1, nonloopback_network_absent: true, root_read_only: true, seccomp_mode: 2, workspace_only_writable: true },
  { child_role_ids: CHILDREN, role_id: ROLE, scenario_id: SCENARIO },
  { root_artifact_sha256: root, root_work_before_children: true },
  { child_role_id: CHILDREN[0], child_role_sha256: roleOne, child_usage_sha256: usageOne },
  { child_result_sha256: resultOne, child_role_id: CHILDREN[0], ipython_action_count: 1 },
  { child_role_id: CHILDREN[1], child_role_sha256: roleTwo, child_usage_sha256: usageTwo },
  { child_result_sha256: resultTwo, child_role_id: CHILDREN[1], ipython_action_count: 1 },
  { follow_up_digest: follow, target_role_id: CHILDREN[1] },
  { child_role_id: CHILDREN[1], follow_up_digest: follow },
  { aggregation_sha256: aggregate, model_sha256: model, oracle_sha256: oracle, usage_sha256: usage },
  { child_role_id: CHILDREN[0] },
  { child_role_id: CHILDREN[1] },
  { disposed: true, reaped: true, revoked: true },
];
const kinds = ["self-check", "release", "root-artifact", "child-admitted", "child-result", "child-admitted", "child-result", "follow-up", "follow-up-result", "aggregation", "child-deleted", "child-deleted", "completed"];
for (const [sequence, kind] of kinds.entries()) {
  console.log(canonical({ challenge_digest: CHALLENGE, kind, payload: payloads[sequence], run_id: RUN, sequence, worker_id: WORKER, workload_digest: WORKLOAD }));
}
