import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { Buffer } from "node:buffer";
import ts from "../../asterion-runtime/node_modules/typescript/lib/typescript.js";

const sourceUrl = new URL("../src/dci-context-extension.ts", import.meta.url);

export async function loadExtension() {
  assert.equal(
    existsSync(sourceUrl),
    true,
    "src/dci-context-extension.ts is not implemented",
  );
  const source = readFileSync(sourceUrl, "utf8");
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      verbatimModuleSyntax: true,
    },
    reportDiagnostics: true,
  });
  assert.deepEqual(result.diagnostics ?? [], []);
  const encoded = Buffer.from(result.outputText).toString("base64");
  return import(`data:text/javascript;base64,${encoded}#${Date.now()}`);
}

export class FakePi {
  constructor(flags = {}) {
    this.flags = new Map(Object.entries(flags));
    this.flagDefinitions = new Map();
    this.handlers = new Map();
    this.entries = [];
  }

  registerFlag(name, options) {
    this.flagDefinitions.set(name, options);
  }

  getFlag(name) {
    return this.flags.get(name);
  }

  on(name, handler) {
    this.handlers.set(name, handler);
  }

  appendEntry(customType, data) {
    this.entries.push({ customType, data });
  }
}

export function context(entries = []) {
  return {
    sessionManager: { getEntries: () => entries },
    compactCalls: [],
    compact(options) {
      this.compactCalls.push(options);
    },
  };
}

export function textMessage(role, text, extra = {}) {
  return { role, content: [{ type: "text", text }], ...extra };
}
