import { Type } from "typebox";

const STATE_KEY = "__ASTERION_ECOSYSTEM_EXTENSION_STATE__";

type ExtensionState = {
	events: string[];
	commandStates: Array<{ args: string }>;
};

function state(): ExtensionState {
	const globalValue = globalThis as typeof globalThis & {
		[STATE_KEY]?: ExtensionState;
	};
	globalValue[STATE_KEY] ??= { commandStates: [], events: [] };
	return globalValue[STATE_KEY];
}

export default function exactEcosystemExtension(pi: any): void {
	const extensionState = state();
	extensionState.events.push("start");

	pi.on("session_start", () => {
		extensionState.events.push("session");
	});

	pi.on("session_shutdown", () => {
		extensionState.events.push("shutdown");
	});

	pi.registerCommand("ecosystem-state", {
		description: "Persist deterministic ecosystem command state.",
		handler: async (args: string) => {
			extensionState.events.push("command");
			extensionState.commandStates.push({ args });
			pi.appendEntry("ecosystem-state", { args });
		},
	});

	pi.registerTool({
		name: "ecosystem_echo",
		label: "Ecosystem echo",
		description: "Echo deterministic ecosystem text locally.",
		parameters: Type.Object({ message: Type.String() }),
		execute: async (_toolCallId: string, params: { message: string }) => {
			extensionState.events.push("tool");
			return {
				content: [{ type: "text", text: `echo:${params.message}` }],
				details: { length: params.message.length },
			};
		},
	});

	pi.registerProvider("ecosystem-local", {
		baseUrl: "http://127.0.0.1/unused",
		apiKey: "ECOSYSTEM_PROVIDER_KEY_SHOULD_NOT_BE_READ",
		api: "openai-completions",
		models: [
			{
				id: "model-1",
				name: "Ecosystem Local Model",
				reasoning: false,
				input: ["text"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				contextWindow: 4096,
				maxTokens: 128,
			},
		],
	});
}
