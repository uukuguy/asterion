import { registerPrime, type ExtensionApi } from "./ipython-extension.js";
import { p7ResearchModule } from "./p7-tools.js";
export * from "./ipython-extension.js";
export * from "./p7-tools.js";
export { toolNames } from "./p7-tools.js";
export function register(pi: ExtensionApi, dependencies?: unknown): void {
  registerPrime(pi, dependencies, p7ResearchModule);
}
export default register;
