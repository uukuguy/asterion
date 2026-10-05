import type { Static, TSchema } from "typebox";

import {
  IPYTHON_PARAMETERS,
  P7_WORKSPACE_PARAMETERS,
  P7_EXECUTE_PLAN_PARAMETERS,
  createIpythonTool,
  register,
  type IpythonBridge,
  type IpythonToolResult,
} from "../src/ipython-extension.js";

declare const bridge: IpythonBridge;

interface AgentToolResult<TDetails> {
  content: Array<
    | { type: "text"; text: string }
    | { type: "image"; data: string; mimeType: string }
  >;
  details: TDetails;
  terminate?: boolean;
}

interface ToolDefinition<TParams extends TSchema, TDetails> {
  name: string;
  label: string;
  description: string;
  parameters: TParams;
  executionMode?: "sequential" | "parallel";
  execute(
    toolCallId: string,
    params: Static<TParams>,
    signal: AbortSignal | undefined,
    onUpdate: ((result: AgentToolResult<TDetails>) => void) | undefined,
    context: unknown,
  ): Promise<AgentToolResult<TDetails>>;
}

interface ExtensionAPI {
  registerTool<TParams extends TSchema, TDetails>(
    tool: ToolDefinition<TParams, TDetails>,
  ): void;
}

const registeredTool: ToolDefinition<
  typeof IPYTHON_PARAMETERS,
  Record<string, never>
> = createIpythonTool(bridge);
const registeredResult: AgentToolResult<Record<string, never>> =
  {} as IpythonToolResult;
const extensionFactory: (pi: ExtensionAPI) => void = register;
const workspaceRead: Static<typeof P7_WORKSPACE_PARAMETERS> = { op: "read" };
const workspaceFocus: Static<typeof P7_WORKSPACE_PARAMETERS> = {
  op: "focus", task: { goal: "移动", obstacles: [], question: "移动规律？",
    next_operation: "probe", public_basis: "真实观察" },
};
const semanticRevision: Static<typeof P7_WORKSPACE_PARAMETERS> = {
  op: 'revise', base_revision: 'sha256:' + 'b'.repeat(64),
  worldmap: { description_zh: '当前游戏工作模型，目标未知。', state_summary: '当前起点',
    rules: [], unknowns: ['移动方向'], competing_hypotheses: [] },
  task: { goal: '辨识控制', obstacles: [], question: '哪个对象移动？', next_operation: 'probe', public_basis: '当前画面' },
  evidence_sequences: [0], correction: { changed: ['记录初始观察'], retained: [] },
};
const shortPlan: Static<typeof P7_EXECUTE_PLAN_PARAMETERS> = {
  plan_id: "plan-1", start: { run_id: "run-1", attempt_id: "attempt-1", level: 1,
    sequence: 0, observation_sha256: "sha256:" + "a".repeat(64) },
  workspace_revision: "sha256:" + "b".repeat(64), goal: "移动", purpose: "probe", assumptions: [],
  steps: [{ action: { name: "ACTION1", data: {} }, expect: { cells: [{x: 0, y: 0, value: 1}] } }],
};

void registeredTool;
void registeredResult;
void extensionFactory;
void workspaceRead;
void workspaceFocus;
void semanticRevision;
void shortPlan;
