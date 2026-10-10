import { normalizeFunctionParameters } from "./tool-schema.js";
import { MemoryContextController, memoryRecord, parseMemoryEnvelope } from "./context-memory.js";
import { nativeContextArchive, createContextCheckpoint, contextArchiveOperation } from "./context-archive.js";
import { ContextViewTelemetry, type ContextViewNumbers } from "./context-metrics.js";
import { admitToolStateView, projectToolStateViewContext } from "./tool-state-view.js";
import { type IpythonBridge, type MethodTool, type AppToolResult, unavailable } from "./tool-bridge.js";
import type { ExtensionApi, PrimeToolModule, PrimeToolModuleDependencies } from "./ipython-extension.js";
import {
  Array as TypeArray,
  Integer as TypeInteger,
  Null as TypeNull,
  Number as TypeNumber,
  Object as TypeObject,
  String as TypeString,
  Union as TypeUnion,
  Optional as TypeOptional,
  Boolean as TypeBoolean,
  Literal as TypeLiteral,
  type Static,
} from "typebox";

const EMPTY_PARAMETERS = TypeObject({}, { additionalProperties: false });
const LEVEL_PARAMETERS = TypeObject(
  {
    level: TypeOptional(TypeUnion([
      TypeInteger({ minimum: 0 }),
      TypeNull(),
    ])),
  },
  { additionalProperties: false },
);
const HISTORY_PARAMETERS = TypeObject(
  {
    start: TypeNumber({ minimum: 0 }),
    limit: TypeNumber({ minimum: 1 }),
  },
  { additionalProperties: false },
);
const FRAME_PARAMETERS = TypeObject(
  { sequence: TypeNumber({ minimum: 0 }) },
  { additionalProperties: false },
);
const HYPOTHESIS_PARAMETERS = TypeObject(
  {
    layer: TypeString({ minLength: 1 }),
    key: TypeString({ minLength: 1 }),
    value: TypeObject(
      {
        mechanism: TypeObject({}, { additionalProperties: true }),
        probe: TypeObject({}, { additionalProperties: true }),
        dependencies: TypeArray(TypeString()),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
const PROMOTION_PARAMETERS = TypeObject(
  {
    key: TypeString({ minLength: 1 }),
    evidence_kind: TypeString({ minLength: 1 }),
  },
  { additionalProperties: false },
);
const COGNITION_PARAMETERS = TypeObject(
  {
    op: TypeString({ minLength: 1 }),
    proposal: TypeOptional(TypeObject({}, { additionalProperties: true })),
    experiment: TypeOptional(TypeObject({}, { additionalProperties: true })),
    analysis: TypeOptional(TypeObject({}, { additionalProperties: true })),
    reason: TypeOptional(TypeString({ minLength: 1 })),
  },
  { additionalProperties: false },
);

interface AppToolSpec {
  name: string;
  method: string;
  description: string;
  parameters: unknown;
  inputKey?: string;
}

const P7_LEGACY_TOOL_SPECS: readonly AppToolSpec[] = Object.freeze([
  {
    name: "p7_decision",
    method: "decision",
    description: "Before a significant action plan, record a concise public goal, observation basis, and expected feedback. Each field is nonempty and at most 600 characters. Returns the decision ID at the current observation; never grants execution authority. Do not include private reasoning, credentials, paths, or raw context.",
    parameters: TypeObject({
      goal: TypeString({ minLength: 1, maxLength: 600 }),
      basis: TypeString({ minLength: 1, maxLength: 600 }),
      expected: TypeString({ minLength: 1, maxLength: 600 }),
    }, { additionalProperties: false }),
  },
  {
    name: "p7_act_checked",
    method: "act_checked",
    description:
      "Dispatch a checked batch of actions. `plan` is a list of {action, expect} dicts. "
      + "The broker stops at the first prediction mismatch / no-effect / unavailable action. "
      + "Read feedback and learning_hint in the result: changed_cell_count and changed_cells describe observed frame effects. A frame change does not prove objective progress; only an increased levels_completed or authoritative terminal state does. Use the effects to form the next falsifiable probe. "
      + "If the result has stop_reason 'invalid-checked-plan', do not submit another batch: "
      + "inspect the settled observation once, then use a one-item probe or RESET with one valid expect object.",
    parameters: TypeObject(
      {
        plan: TypeArray(
          TypeObject({ action: TypeObject({}), expect: TypeObject({}) }),
        ),
      },
      { additionalProperties: false },
    ),
  },
  {
    name: "p7_action_effects",
    method: "action_effects",
    description: "Read bounded per-action effect summaries learned in this run.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_cognition",
    method: "cognition",
    description: "Read advisory type cognition and exact-game experience.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_cognition_update",
    method: "cognition_update",
    description:
      "Propose or analyze semantic game-cognition hypotheses. Use {op, proposal|experiment|analysis|reason}; this updates the persisted language ledger only and never dispatches an action or grants execution authority.",
    parameters: COGNITION_PARAMETERS,
  },
  {
    name: "p7_counterfactual_search",
    method: "counterfactual_search",
    description: "Compare candidate mechanics and subgoal progress without dispatching actions.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_frame_at",
    method: "frame_at",
    description: "Read the settled frame at history sequence `sequence`.",
    parameters: FRAME_PARAMETERS,
  },
  {
    name: "p7_game_mechanics",
    method: "game_mechanics",
    description: "Read persistent game-wide mechanisms; this is advisory memory only.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_history",
    method: "history",
    description: "Read a page of session history records starting at index `start` with up to `limit` records.",
    parameters: HISTORY_PARAMETERS,
  },
  {
    name: "p7_last_outcome_summary",
    method: "last_outcome_summary",
    description: "Read bounded per-action outcome counts for one level or the whole run.",
    parameters: LEVEL_PARAMETERS,
    inputKey: "level",
  },
  {
    name: "p7_mechanism_candidates",
    method: "mechanism_candidates",
    description: "Read mechanism candidates and their evidence lifecycle.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_mechanics_prior",
    method: "mechanics_prior",
    description: "Read bounded mechanics evidence inferred from prior actions. This is evidence for reasoning, not a route or action prescription.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_model_search",
    method: "model_search",
    description: "Search a verified same-game mechanism without dispatching actions.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_observation_state",
    method: "observation_state",
    description: "Read the unified immutable observation with optional game metadata.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_observe",
    method: "observe",
    description: "Read the current observation: available_actions, settled frame or animation frames, levels_completed, state, win_levels, tried_summary, learning_hint, and remaining action budget. A changed_cell_count in action feedback does not prove objective progress while levels_completed is unchanged. Use feedback and the settled frame to form the next falsifiable probe. Call this after a level boundary or when an action result omitted the board you need.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_planning_background",
    method: "planning_background",
    description:
      "Read the refreshable planning background combining semantic cognition, WorldMap, the current frame identity, and simulator status. It never dispatches actions or grants execution authority.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_playbook",
    method: "playbook",
    description: "Read the bounded same-game Playbook projection.",
    parameters: LEVEL_PARAMETERS,
    inputKey: "level",
  },
  {
    name: "p7_probe_plan",
    method: "probe_plan",
    description: "Read one safe probe suggestion without dispatching it.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_promote_hypothesis",
    method: "promote_hypothesis",
    description: "Promote a visual candidate only after broker-verified action evidence.",
    parameters: PROMOTION_PARAMETERS,
  },
  {
    name: "p7_record_hypothesis",
    method: "record_hypothesis",
    description: "Submit one bounded hypothesis with an application-owned probe.",
    parameters: HYPOTHESIS_PARAMETERS,
  },
  {
    name: "p7_retrodiction_status",
    method: "retrodiction_status",
    description: "Read scalar transition-model verification status.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_simulator_status",
    method: "simulator_status",
    description: "Read simulator coverage and certificate status.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_status",
    method: "status",
    description: "Read the current action budget and terminal status.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_tried_actions",
    method: "tried_actions",
    description: "Enumerate every dispatched action and its bounded count for one level or the whole run.",
    parameters: LEVEL_PARAMETERS,
    inputKey: "level",
  },
  {
    name: "p7_world_model",
    method: "world_model",
    description: "Read the bounded same-game confirmed model projection.",
    parameters: EMPTY_PARAMETERS,
  },
]);

const PUBLIC_TEXT = TypeString({ maxLength: 600 });
const EXPORT_ID = TypeString({ pattern: "^sha256:[0-9a-f]{64}$" });
const ID = TypeString({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}$" });
const TASK_PARAMETERS = TypeObject({
  goal: PUBLIC_TEXT, obstacles: TypeArray(PUBLIC_TEXT, { maxItems: 32 }), question: PUBLIC_TEXT,
  next_operation: TypeUnion([TypeLiteral("analyze"), TypeLiteral("model"), TypeLiteral("validate"), TypeLiteral("search"), TypeLiteral("probe"), TypeLiteral("execute")]),
  public_basis: PUBLIC_TEXT,
}, { additionalProperties: false });
const ACTION_LABEL_NAME = TypeUnion([
  TypeLiteral("ACTION1"), TypeLiteral("ACTION2"), TypeLiteral("ACTION3"), TypeLiteral("ACTION4"),
  TypeLiteral("ACTION5"), TypeLiteral("ACTION6"), TypeLiteral("ACTION7"), TypeLiteral("RESET"),
]);
const ACTION_LABEL_PARAMETERS = TypeUnion([
  TypeObject({
    action: ACTION_LABEL_NAME, label: TypeString({ minLength: 1, maxLength: 24, pattern: "\\S" }),
    purpose: TypeString({ minLength: 1, maxLength: 600, pattern: "\\S" }),
    confidence: TypeUnion([TypeLiteral("certain"), TypeLiteral("hypothesis")]),
    evidence_sequences: TypeArray(TypeInteger({ minimum: 0, maximum: 1000000000 }),
      { minItems: 1, maxItems: 32, uniqueItems: true }),
  }, { additionalProperties: false }),
  TypeObject({
    action: ACTION_LABEL_NAME, label: TypeNull(), purpose: PUBLIC_TEXT,
    confidence: TypeUnion([TypeLiteral("unknown"), TypeLiteral("conflict")]),
    evidence_sequences: TypeArray(TypeInteger({ minimum: 0, maximum: 1000000000 }),
      { maxItems: 32, uniqueItems: true }),
  }, { additionalProperties: false }),
]);
const WORLDMAP_PARAMETERS = TypeObject({
  description_zh: TypeString({ minLength: 1, maxLength: 8000 }),
  state_summary: PUBLIC_TEXT, rules: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  unknowns: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  competing_hypotheses: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  action_labels: TypeOptional(TypeArray(ACTION_LABEL_PARAMETERS, { maxItems: 8, uniqueItems: true,
    description: "Your current-level judgments from actual observations: write directly displayed short labels and purposes; use certain/hypothesis or null labels for unknown/conflict. Sort unique action IDs and each evidence list; evidence must reference this run at or before the current observation sequence. No UI semantic inference occurs." })),
}, { additionalProperties: false });
const CORRECTION_PARAMETERS = TypeObject({
  changed: TypeArray(PUBLIC_TEXT, { maxItems: 32 }), retained: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  counterexample_sequence: TypeOptional(TypeInteger({ minimum: 0 })),
}, { additionalProperties: false });

export const P7_WORKSPACE_PARAMETERS = TypeUnion([
  TypeObject({ op: TypeLiteral("read"), revision: TypeOptional(EXPORT_ID) }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("publish"), base_revision: EXPORT_ID, draft_export_id: EXPORT_ID }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("checkpoint"), revision: EXPORT_ID, state_export_id: TypeOptional(EXPORT_ID),
    frontier_export_id: TypeOptional(EXPORT_ID), analyzed_through: TypeInteger({ minimum: 0 }) }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("focus"), task: TASK_PARAMETERS }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral('revise'), base_revision: EXPORT_ID, worldmap: WORLDMAP_PARAMETERS,
    task: TASK_PARAMETERS, evidence_sequences: TypeArray(TypeInteger({ minimum: 0 }), { minItems: 1, maxItems: 128, uniqueItems: true }),
    correction: CORRECTION_PARAMETERS }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("notes"), base_revision: EXPORT_ID,
    observation_ref: TypeObject({run_id: ID,attempt_id: ID,level: TypeInteger({minimum:1}),
      sequence: TypeInteger({minimum:0}),observation_sha256: EXPORT_ID}, {additionalProperties:false}),
    text: TypeString({minLength:1,maxLength:16384}) }, {additionalProperties:false}),
  TypeObject({op: TypeLiteral("notes_read"),revision: TypeOptional(EXPORT_ID)}, {additionalProperties:false}),
  TypeObject({op: TypeLiteral("notes_history"),start: TypeOptional(TypeInteger({minimum:0})),
    limit: TypeOptional(TypeInteger({minimum:1,maximum:32}))}, {additionalProperties:false}),
  TypeObject({op:TypeLiteral('context_archive_list'),start:TypeOptional(TypeInteger({minimum:0})),limit:TypeOptional(TypeInteger({minimum:1,maximum:32}))},{additionalProperties:false}),
  TypeObject({op:TypeLiteral('context_archive_read'),ref:TypeObject({session_id:TypeString({minLength:1,maxLength:256}),entry_id:TypeString({minLength:1,maxLength:256})},{additionalProperties:false}),
    start:TypeOptional(TypeInteger({minimum:0})),limit:TypeOptional(TypeInteger({minimum:1,maximum:16384}))},{additionalProperties:false}),
]);
const ACTION_PARAMETERS = TypeUnion([
  TypeObject({ name: TypeUnion([TypeLiteral("RESET"), TypeLiteral("ACTION1"), TypeLiteral("ACTION2"), TypeLiteral("ACTION3"), TypeLiteral("ACTION4"), TypeLiteral("ACTION5"), TypeLiteral("ACTION7")]),
    data: TypeObject({}, { additionalProperties: false }) }, { additionalProperties: false }),
  TypeObject({ name: TypeLiteral("ACTION6"), data: TypeObject({ x: TypeInteger({ minimum: 0, maximum: 63 }),
    y: TypeInteger({ minimum: 0, maximum: 63 }) }, { additionalProperties: false }) }, { additionalProperties: false }),
]);
export const P7_EXECUTE_PLAN_PARAMETERS = TypeObject({
  plan_id: ID,
  start: TypeObject({ run_id: ID, attempt_id: ID, level: TypeInteger({ minimum: 1 }),
    sequence: TypeInteger({ minimum: 0 }), observation_sha256: EXPORT_ID }, { additionalProperties: false }),
  workspace_revision: TypeOptional(EXPORT_ID), goal: TypeOptional(PUBLIC_TEXT),
  purpose: TypeOptional(TypeUnion([TypeLiteral("advance"), TypeLiteral("probe")])),
  assumptions: TypeOptional(TypeArray(PUBLIC_TEXT, { maxItems: 32 })),
  stop_on_mismatch: TypeOptional(TypeBoolean()),
  stop_on_view_change: TypeOptional(TypeBoolean()),
  steps: TypeArray(TypeObject({ action: ACTION_PARAMETERS,
    observe_after: TypeOptional(TypeBoolean()),
    before: TypeOptional(TypeObject({ cells: TypeArray(TypeObject({
      x: TypeInteger({ minimum: 0, maximum: 63 }), y: TypeInteger({ minimum: 0, maximum: 63 }),
      value: TypeInteger({ minimum: 0, maximum: 255 }),
    }, { additionalProperties: false }), { minItems: 1, maxItems: 128 }) }, { additionalProperties: false })),
    expect: TypeOptional(TypeObject({
    cells: TypeOptional(TypeArray(TypeObject({ x: TypeInteger({ minimum: 0, maximum: 63 }),
      y: TypeInteger({ minimum: 0, maximum: 63 }), value: TypeInteger({ minimum: 0, maximum: 255 }) },
      { additionalProperties: false }), { minItems: 1, maxItems: 128 })),
    frame_sha256: TypeOptional(EXPORT_ID),
    state: TypeOptional(TypeUnion([TypeLiteral("NOT_FINISHED"), TypeLiteral("WIN"), TypeLiteral("GAME_OVER")])),
    levels_completed: TypeOptional(TypeInteger({ minimum: 0 })),
  }, { additionalProperties: false })) }, { additionalProperties: false }), { minItems: 1, maxItems: 20 }),
}, { additionalProperties: false });
const P7_FRAME_DELIVERY_DESCRIPTION = " Boards may use the lossless palette-row-dictionary/v1 encoding: row_ids selects rows and each row character selects its literal numeric pixel through symbols and palette; shape preserves the singleton frame layer if present. Numeric frames with frame_delivery.encoding=raw are already decoded. For optional research in IPython, use import p7_research as r. Read the current exact raw 2D settled board with r.frame(), or a historical board with r.frame(sequence). r.render(), r.geometry(), and r.diff(before_sequence) provide read-only observation helpers; r.patches(windows,sequence) returns exact local pixels, and r.view_change(before_sequence,after_sequence) compares bounded literal pixel translation candidates with historical sequence/hash references. These candidates do not identify game objects, world coordinates, camera truth or safety. Choose whichever investigation is useful. settled_frame_sha256 identifies the pixel grid, separately from observation_sha256.";
const P7_TOOL_SPECS: readonly AppToolSpec[] = Object.freeze([
  { name: "p7_workspace", method: "workspace", parameters: P7_WORKSPACE_PARAMETERS,
    description: "Optionally use op notes with the exact current base_revision and observation_ref to replace your freeform research NOTES (at most 16 KiB UTF-8). Select useful observations, hypotheses, counterexamples, questions and plans yourself; no required headings, WorldMap, task or action labels. Notes are an external memory aid, not an action prerequisite. Accepted autonomous NOTES establish the primary working-memory epoch: summarized older completed interactions leave the working view but remain readable; recent correction evidence, unknown effects and user constraints stay protected. This does not certify the notes or authorize actions. Use context_archive_list (start, limit 1–32) for this selected native session's opaque message refs, and context_archive_read (ref, start, limit 1–16384 characters) for paged original actor-visible text, calls and errors. Archive reads do not execute saved programs or actions. If projection or archive admission is unavailable, full history stays visible and primary retirement is not established. Read accepted notes with notes_read (optional revision), or page newest-first accepted notes_history (optional start, limit 1–32). Optional revise/publish retains prior program/report evidence and never certifies new prose. Also read current/historical revisions, focus a task, publish an IPython draft or checkpoint source/JSON exports. Publishing never dispatches actions. Write success returns an acknowledgement with current refs and controls; op read returns the complete selected workspace and current board." + P7_FRAME_DELIVERY_DESCRIPTION },
  { name: "p7_execute_plan", method: "execute_plan", parameters: P7_EXECUTE_PLAN_PARAMETERS,
    description: "Submit a short ordered plan with plan_id, start equal to the current observation_ref, and 1–20 action steps. Notes, WorldMap and program models are optional research aids. workspace_revision, goal, purpose, assumptions and each step's expect prediction may be omitted; a supplied workspace_revision must match the current workspace. Optional step.before={cells:[{x,y,value}]} checks 1–128 distinct literal pixels on the actual settled screen immediately before that step. x is the current screen column and y the row; map your model coordinates to the current screen yourself and recheck after view changes. The entire plan syntax validates before dispatch. A before mismatch returns precondition_feedback with the observed reference and differences, stops the current step and suffix without executing or charging them, and preserves the executed prefix. A matched before is not a post-action prediction or a safety guarantee. Predictions can test key cells, a complete frame, state or progress; an omitted prediction is not a confirmed match. stop_on_mismatch defaults to true; explicitly false allows continuing known post-action prediction misses but never bypasses before. The unique Broker executes sequentially; unknown effects, pause, RESET, game-over, level changes, budget and cancellation stop the suffix. stop_on_view_change defaults to true: after a known committed step, a bounded pixel-translation candidate can return control before executing the suffix. This is not confirmed camera movement or a safety judgment. Set stop_on_view_change=false for a plan whose view changes your model already covers; this cannot bypass hard stops or preconditions. Optional step.observe_after=true requests an observation checkpoint even when the soft view policy is disabled. With a remaining suffix these boundaries return stop_reason observation-boundary, explanatory evidence, the actual current observation and unexecuted steps. No suffix is automatically resumed; decide whether to continue, adjust or investigate, then submit a new plan_id and current start. Returns actual feedback and unexecuted steps. Reuse an identical plan_id only to retrieve its recorded result; never replay an uncertain action." + P7_FRAME_DELIVERY_DESCRIPTION },
]);

export function toolNames(): string[] {
  return ["ipython", ...P7_TOOL_SPECS.map((spec) => spec.name)].sort();
}

function makeMethodTool(
  bridge: IpythonBridge,
  name: string,
  description: string,
  inputType: unknown,
  method: string,
  inputKey?: string,
): MethodTool {
  return {
    name,
    label: name,
    description,
    parameters: normalizeFunctionParameters(inputType),
    executionMode: "sequential" as const,
    execute: async (
      id: string,
      input: unknown,
      signal?: AbortSignal,
      _onUpdate?: unknown,
      context?: unknown,
    ): Promise<AppToolResult> => {
      const params = inputKey
        ? (input as Record<string, unknown> | null | undefined)?.[inputKey] ?? null
        : input;
      if(method==='workspace' && ['context_archive_list','context_archive_read'].includes(String(memoryRecord(params)?.op))) {
        const archive=nativeContextArchive(context);
        const result=contextArchiveOperation(archive,params);
        const latest=archive?.entries.map(entry=>memoryRecord(entry.message)).reverse().find(message=>{
          const details=memoryRecord(message?.details);return typeof details?.environment_result_unknown==='boolean' && typeof details.processing_blocked==='boolean';
        });
        const details=memoryRecord(latest?.details);
        if(details) Object.assign(result,{environment_result_unknown:details.environment_result_unknown,processing_blocked:details.processing_blocked});
        if(result.status==='rejected') result.context_interaction={version:'asterion.prime-context-interaction/v1',effect:'settled',feedback:'negative'};
        return {content:[{type:'text',text:JSON.stringify(Object.fromEntries(Object.entries(result).filter(([key])=>key!=='context_interaction')))}],details:result};
      }
      let result:unknown;
      try {result=await bridge.callMethod(id,method,params,signal);}
      catch(error) {
        const known=memoryRecord(error)?.context_effect==='settled';
        return {content:[{type:'text',text:known && error instanceof Error?error.message:unavailable().message}],isError:true,
          details:{context_interaction:{version:'asterion.prime-context-interaction/v1',effect:known?'settled':'unknown',feedback:'negative'}}};
      }
      let record = memoryRecord(result);
      let visibleResult = result;
      let details = result;
      let interaction:unknown;
      if(record && Object.hasOwn(record,'context_interaction')) {
        const {context_interaction,...publicResult}=record;
        const marker=memoryRecord(context_interaction);
        if(marker && Object.keys(marker).sort().join(',')==='effect,feedback,version' && marker.version==='asterion.prime-context-interaction/v1'
          && ['unknown','settled'].includes(String(marker.effect)) && ['negative','ordinary'].includes(String(marker.feedback))) interaction=marker;
        record=publicResult;visibleResult=publicResult;details=publicResult;
      }
      // A private application proposal is not model content. Bind its admitted
      // form only after constructing the exact visible text below.
      let stateProposal: unknown;
      if (record && Object.hasOwn(record,"tool_state_view")) {
        const {tool_state_view: privateProposal,...publicResult} = record;
        stateProposal = privateProposal;
        record = publicResult;
        visibleResult = publicResult;
        details = publicResult;
      }
      if (record && Object.hasOwn(record,"context_memory")) {
        const {context_memory: privateEnvelope, ...publicResult} = record;
        visibleResult = publicResult;
        const envelope = parseMemoryEnvelope(privateEnvelope);
        const accepted = method === "workspace" && memoryRecord(input)?.op === "notes"
          && record.status === "noted" && record.notes_revision === envelope?.revision;
        const trusted = envelope && (!envelope.commit || accepted)
          && !["rejected","cancelled","lost","processing-blocked"].includes(String(record.status));
        // The actual native successful toolResult establishes the checkpoint.
        // Merely completing this callback does not establish a model cut.
        details = trusted ? {...publicResult,context_memory:envelope,
          ...(envelope.commit ? {context_memory_anchor:id} : {})} : publicResult;
        if(trusted && envelope.version==='asterion.prime-context-memory/v3' && envelope.commit) {
          const receipt=createContextCheckpoint(nativeContextArchive(context),id,envelope.revision!);
          if(receipt) details={...memoryRecord(details),context_checkpoint:receipt};
        }
      }
      if(interaction) details={...memoryRecord(details),context_interaction:interaction};
      let text: string;
      try {
        const serialized = JSON.stringify(visibleResult);
        if (
          visibleResult !== null
          && typeof visibleResult === "object"
          && !Array.isArray(visibleResult)
          && typeof (visibleResult as Record<string, unknown>).cognition_narrative_zh === "string"
        ) {
          const structured = { ...(visibleResult as Record<string, unknown>) };
          const narrative = structured.cognition_narrative_zh as string;
          delete structured.cognition_narrative_zh;
          text = narrative + "\n\n结构化证据（程序校验用）：\n" + JSON.stringify(structured);
        } else {
          text = serialized === undefined ? String(visibleResult) : serialized;
        }
      } catch {
        text = String(visibleResult);
      }
      if (method === "execute_plan" && record?.status === "recorded"
        && record.environment_result_unknown !== true && record.processing_blocked !== true
        && !Object.hasOwn(record,"uncertain_step")
        && !["unknown","environment-result-unknown","processing-failed"].includes(String(record.stop_reason))) {
        const view = admitToolStateView(stateProposal,text,id,name);
        if (view) details = {...memoryRecord(details),tool_state_view:view};
      }
      return {
        content: [{ type: "text", text }],
        details,
      };
    },
  };
}

export function createAppLevelTools(bridge: IpythonBridge): MethodTool[] {
  return [...P7_TOOL_SPECS]
    .sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0)
    .map((spec) =>
    makeMethodTool(
      bridge,
      spec.name,
      spec.description,
      spec.parameters,
      spec.method,
      spec.inputKey,
    )
  );
}

export function createLegacyAppLevelTools(bridge: IpythonBridge): MethodTool[] {
  return [...P7_LEGACY_TOOL_SPECS].sort((a, b) => a.name.localeCompare(b.name)).map((spec) =>
    makeMethodTool(bridge, spec.name, spec.description, spec.parameters, spec.method, spec.inputKey));
}

/** Recover only extension-validated metadata from actual successful native results. */
export function recoverP7MemoryContext(controller: MemoryContextController, entries: readonly unknown[]): void {
  for (const raw of entries) {
    const entry = memoryRecord(raw);
    if (entry?.type !== "message") continue;
    const message = memoryRecord(entry.message);
    if (message?.role !== "toolResult" || message.isError !== false
      || !["p7_workspace","p7_execute_plan"].includes(String(message.toolName))
      || typeof message.toolCallId !== "string") continue;
    const details = memoryRecord(message.details);
    const envelope = parseMemoryEnvelope(details?.context_memory);
    if (!envelope || !details) continue;
    if (envelope.commit && (message.toolName !== "p7_workspace" || details.status !== "noted"
      || details.notes_revision !== envelope.revision || details.context_memory_anchor !== message.toolCallId)) continue;
    // Unknown application effects remain model-visible, but cannot promise a
    // stable state boundary merely because the native transport settled.
    const stableSource = details.environment_result_unknown !== true && details.processing_blocked !== true
      && !Object.hasOwn(details,"uncertain_step")
      && !["unknown","environment-result-unknown","processing-failed"].includes(String(details.stop_reason))
      && !["unknown","uncertain","rejected","cancelled","lost","processing-blocked"].includes(String(details.status));
    controller.accept(message.toolCallId,envelope,stableSource,details.context_checkpoint);
  }
}

interface MemoryExtensionApi {
  on(event: "context", handler: (event: unknown, context: unknown) => unknown): unknown;
}

const MEMORY_DIAGNOSTIC_LIMIT = 4 * 1024;
const MEMORY_DIAGNOSTIC_SUPPRESSED = '[prime-context-memory] {"status":"diagnostics-suppressed"}';
const MEMORY_DIAGNOSTIC_SUPPRESSED_BYTES = Buffer.byteLength(MEMORY_DIAGNOSTIC_SUPPRESSED+"\n","utf8");
// All registered hooks in this module instance share the process log budget.
let memoryDiagnosticBytes = 0;
let memoryDiagnosticsSuppressed = false;

function emitMemoryDiagnostic(line: string): void {
  if (memoryDiagnosticsSuppressed) return;
  const bytes = Buffer.byteLength(line+"\n","utf8");
  if (memoryDiagnosticBytes+bytes+MEMORY_DIAGNOSTIC_SUPPRESSED_BYTES>MEMORY_DIAGNOSTIC_LIMIT) {
    memoryDiagnosticsSuppressed = true;
    memoryDiagnosticBytes += MEMORY_DIAGNOSTIC_SUPPRESSED_BYTES;
    console.error(MEMORY_DIAGNOSTIC_SUPPRESSED);
    return;
  }
  memoryDiagnosticBytes += bytes;
  console.error(line);
}

/** Pi owns prompt/tools; this hook changes only its cloned conversation view. */
export function registerP7MemoryContext(pi: unknown, telemetry?: (numbers: ContextViewNumbers) => void): boolean {
  const api = memoryRecord(pi);
  if (!api || typeof api.on !== "function") return false;
  let lastOutcome: string | undefined;
  const metrics = telemetry ? new ContextViewTelemetry() : undefined;
  const observe = (messages: readonly unknown[]): void => {
    try {if (metrics && telemetry) telemetry(metrics.observe(messages));} catch {}
  };
  (pi as MemoryExtensionApi).on("context", (rawEvent,rawContext) => {
    const event = memoryRecord(rawEvent);
    if (event?.type !== "context" || !Array.isArray(event.messages)) return undefined;
    try {
      // Rebuild from the selected branch on each request: navigation/reload must
      // not inherit a checkpoint belonging to another branch.
      const controller = new MemoryContextController();
      const context = memoryRecord(rawContext);
      const manager = memoryRecord(context?.sessionManager);
      let entries: unknown = event.messages.map(message => ({type:"message",message}));
      if (manager && typeof manager.getBranch === "function") entries = manager.getBranch();
      if (!Array.isArray(entries)) {observe(event.messages); return {messages:event.messages};}
      recoverP7MemoryContext(controller,entries);
      const branchMessages = entries.flatMap(raw => {
        const entry = memoryRecord(raw);
        return entry?.type === "message" ? [entry.message] : [];
      });
      const stateView = controller.primaryMode ? {messages:event.messages,outcome:{replaced_results:0,replaced_bytes:0}}
        : projectToolStateViewContext(event.messages,branchMessages);
      const projected = controller.project(stateView.messages,nativeContextArchive(rawContext));
      const safeOutcome = JSON.stringify({...projected.outcome,state_view:stateView.outcome});
      if ((projected.outcome.status !== "inactive" || stateView.outcome.replaced_results > 0) && safeOutcome !== lastOutcome) {
        emitMemoryDiagnostic("[prime-context-memory] " + safeOutcome);
        lastOutcome = safeOutcome;
      }
      observe(projected.messages);
      return {messages:projected.messages};
    } catch {
      // Pi catches extension exceptions, so an exception is not a request fence.
      // A projection failure explicitly preserves every original message.
      emitMemoryDiagnostic('[prime-context-memory] {"status":"projection-unavailable"}');
      observe(event.messages);
      return {messages:event.messages};
    }
  });
  return true;
}


const registryIdentity = {module_id: "prime.p7.application-tools", capability_id: "prime.tool.p7"};
export const p7ResearchModule: PrimeToolModule = Object.freeze({
  registry: Object.freeze({...registryIdentity, tool_names: Object.freeze(toolNames())}),
  createTools: createAppLevelTools,
  registerContextHooks(pi: ExtensionApi, dependencies: unknown) {
    const metrics = (dependencies as PrimeToolModuleDependencies).contextMetrics;
    if (!registerP7MemoryContext(pi, metrics)) metrics?.close();
  },
});
export const p7LegacyModule: PrimeToolModule = Object.freeze({
  registry: Object.freeze({...registryIdentity,
    tool_names: Object.freeze(["ipython", ...P7_LEGACY_TOOL_SPECS.map(spec => spec.name)].sort())}),
  createTools: createLegacyAppLevelTools,
  registerContextHooks: p7ResearchModule.registerContextHooks!,
});
