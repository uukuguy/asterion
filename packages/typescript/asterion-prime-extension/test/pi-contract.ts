import type { Static, TSchema } from "typebox";

import {
  IPYTHON_PARAMETERS,
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

void registeredTool;
void registeredResult;
void extensionFactory;
