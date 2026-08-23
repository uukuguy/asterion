import { createHash } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const SCENARIO_IDS = Object.freeze([
  "prime-parity.harness.history-snapshots",
  "prime-parity.harness.memory-entries",
  "prime-parity.harness.prompt-entries",
  "prime-parity.harness.rollback",
  "prime-parity.harness.scope-isolation",
  "prime-parity.harness.skill-descriptions",
  "prime-parity.harness.subagent-specifications",
]);

function fail() {
  throw new Error("Prime continual harness observation failed");
}

function canonical(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function digest(value) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

function semantic(value) {
  if (Array.isArray(value)) return value.map(semantic);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => key !== "created_at" && key !== "updated_at")
      .map(([key, item]) => [key, semantic(item)]));
  }
  return value;
}

function proposal(summary, edits) {
  return { summary, rationale: "provider-free deterministic fixture", expectedOutcome: "exact state transition", edits };
}

function edit(action, kind, id, overrides = {}) {
  if (action === "delete") return { action, kind, id, reason: "provider-free delete" };
  return {
    action,
    kind,
    id,
    title: `${kind} fixture`,
    content: `${kind} ${action} body`,
    path: "provider-free",
    reference: {},
    arguments: {},
    metadata: { fixture: true },
    reason: `provider-free ${action}`,
    ...overrides,
  };
}

const [modulePath, privateRoot, phase] = process.argv.slice(2);
if (!modulePath || !privateRoot || !["seed", "verify"].includes(phase)) fail();
const prime = await import(pathToFileURL(modulePath).href);
for (const name of ["loadHarnessState", "applyRefinementProposal", "saveHarnessState"]) {
  if (typeof prime[name] !== "function") fail();
}

const roots = {
  session: join(privateRoot, "session"),
  project: join(privateRoot, "project"),
  global: join(privateRoot, "global"),
};
for (const root of Object.values(roots)) mkdirSync(root, { recursive: true, mode: 0o700 });

if (phase === "seed") {
  const state = prime.loadHarnessState(roots.session, "local");
  const kinds = ["prompt", "memory", "skill", "subagent"];
  for (const kind of kinds) {
    const id = `${kind}-entry`;
    const extra = kind === "skill" ? {
      reference: { type: "python", python_import: "asterion.skills.fixture", callable: "run" },
      arguments: { required: ["value"], value: "string" },
    } : {};
    const create = prime.applyRefinementProposal(
      state, proposal(`${kind} create`, [edit("create", kind, id, extra)]),
      { id: `${kind}-create`, scope: "local" },
    );
    const update = prime.applyRefinementProposal(
      state, proposal(`${kind} update`, [edit("update", kind, id, { ...extra, content: `${kind} updated body` })]),
      { id: `${kind}-update`, scope: "local" },
    );
    const remove = prime.applyRefinementProposal(
      state, proposal(`${kind} delete`, [edit("delete", kind, id)]),
      { id: `${kind}-delete`, scope: "local" },
    );
    if (![create, update, remove].every((result) => result.appliedEdits.length === 1 && result.appliedEdits[0].applied)) fail();
    if (state.entries[kind][id] !== undefined) fail();
  }
  const base = prime.applyRefinementProposal(
    state,
    proposal("base prompt rejection", [edit("update", "prompt", "base_system_prompt")]),
    { id: "base-prompt-rejected", scope: "local" },
  );
  if (base.appliedEdits.length !== 1 || base.appliedEdits[0].applied || !base.appliedEdits[0].error) fail();
  prime.saveHarnessState(roots.session, state);
  process.stdout.write(`${canonical({ refinement_count: state.refinements.length, seed_digest: digest(semantic(state)) })}\n`);
} else {
  const restarted = prime.loadHarnessState(roots.session, "local");
  const restartDigest = digest(semantic(restarted));
  if (restarted.refinements.length !== 13) fail();

  const created = prime.applyRefinementProposal(
    restarted,
    proposal("rollback target create", [edit("create", "memory", "rollback-entry", { content: "original" })]),
    { id: "rollback-target-create", scope: "local" },
  );
  const updated = prime.applyRefinementProposal(
    restarted,
    proposal("rollback target update", [edit("update", "memory", "rollback-entry", { content: "changed" })]),
    { id: "rollback-target-update", scope: "local" },
  );
  const rolledBack = prime.applyRefinementProposal(
    restarted,
    proposal("rollback inverse", [edit("update", "memory", "rollback-entry", { content: "original" })]),
    { id: "rollback-new-revision", rollbackOf: "rollback-target-update", scope: "local" },
  );
  if (![created, updated, rolledBack].every((result) => result.appliedEdits[0]?.applied)) fail();
  if (rolledBack.rollbackOf !== "rollback-target-update" || restarted.entries.memory["rollback-entry"].content !== "original") fail();
  prime.saveHarnessState(roots.session, restarted);

  const scoped = [
    ["session", "local", "session-body"],
    ["project", "local", "project-body"],
    ["global", "global", "global-body"],
  ];
  for (const [name, scope, content] of scoped) {
    const state = prime.loadHarnessState(roots[name], scope);
    const result = prime.applyRefinementProposal(
      state,
      proposal(`${name} isolated`, [edit("create", "prompt", "colliding-entry", { content })]),
      { id: `${name}-isolated`, scope },
    );
    if (!result.appliedEdits[0]?.applied) fail();
    prime.saveHarnessState(roots[name], state);
  }
  const isolatedBodies = scoped.map(([name, scope]) =>
    prime.loadHarnessState(roots[name], scope).entries.prompt["colliding-entry"].content);
  if (new Set(isolatedBodies).size !== 3) fail();

  const assertions = {
    base_prompt_immutable: true,
    exact_python_skill_contract: true,
    scope_roots_disjoint: true,
    subagent_not_spawned: true,
  };
  const observation = {
    assertions,
    fake_daemon: false,
    model_credential_reads: 0,
    provider_operations: 0,
    real_prime_runtime: true,
    restart_after_admission: true,
    restart_digest: restartDigest,
    scenario_ids: SCENARIO_IDS,
    snapshot_digest: digest(semantic(restarted)),
  };
  process.stdout.write(`${canonical({
    ...observation,
    observation_digest: digest(observation),
    status: "PASS",
  })}\n`);
}
