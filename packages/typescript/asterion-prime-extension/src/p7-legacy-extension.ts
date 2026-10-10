import { registerPrime, type ExtensionApi } from "./ipython-extension.js";
import { p7LegacyModule } from "./p7-tools.js";
export * from "./ipython-extension.js";
export * from "./p7-tools.js";
export function toolNames(): string[] {
  return [...p7LegacyModule.registry.tool_names];
}
export function register(pi: ExtensionApi, dependencies?: unknown): void {
  registerPrime(pi, dependencies, p7LegacyModule);
}
export default register;
