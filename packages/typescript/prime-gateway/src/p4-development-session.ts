import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPrimeArtifactLock, verifyPrimeArtifact } from "./artifact-lock.js";
export class PrimeP4DevelopmentError extends Error { readonly stage: string | undefined; constructor(stage?: string) { super("Prime P4 development daemon is unavailable"); this.stage = stage; } }
export async function runPrimeP4DevelopmentSmoke(primeSourceRoot: string): Promise<Readonly<{ activeSessionId: string; cursor: Readonly<{ generation: string; sequence: number }> }>> {
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p4-"));
  let stage: string | undefined;
  try { const lock = await loadPrimeArtifactLock(new URL("../../resources/prime-artifact-lock.json", import.meta.url)); if (lock.package_name !== "@earendil-works/pi-coding-agent" || lock.package_version !== "0.7.1") throw new Error(); await verifyPrimeArtifact(primeSourceRoot, lock); const socket = join(workspace, `${randomUUID()}.sock`); const main = fileURLToPath(new URL("./p4-development-main.js", import.meta.url)); const child = spawn(process.execPath, [main, primeSourceRoot, workspace, socket], { stdio: ["ignore", "pipe", "ignore", "pipe"], env: {} }); child.stdio[3]?.on("data", (v: Buffer) => { const candidate = v.toString("utf8").trim().split("\n").at(-1); if (candidate && /^[a-z-]+(?::error)?$/.test(candidate)) stage = candidate; }); const output = await new Promise<string>((resolve, reject) => { let body = ""; const timer = setTimeout(() => reject(new Error()), 15_000); child.stdout?.on("data", (v: Buffer) => body += v.toString("utf8")); child.once("exit", (code) => { clearTimeout(timer); code === 143 ? resolve(body) : reject(new Error()); }); child.once("error", reject); }); const value = JSON.parse(output) as { activeSessionId?: unknown; cursor?: { generation?: unknown; sequence?: unknown } }; if (typeof value.activeSessionId !== "string" || typeof value.cursor?.generation !== "string" || !Number.isSafeInteger(value.cursor.sequence)) throw new Error(); const sequence = value.cursor.sequence as number; return Object.freeze({ activeSessionId: value.activeSessionId, cursor: Object.freeze({ generation: value.cursor.generation, sequence }) }); } catch { throw new PrimeP4DevelopmentError(stage); } finally { await rm(workspace, { recursive: true, force: true }); }
}
