import { readFile } from "node:fs/promises";

const FORBIDDEN_OPERATION_KEYS = new Set([
  "api_key", "authorization", "body", "credential", "destination", "path",
  "prompt", "refresh_token", "text", "token",
]);
const schema = JSON.parse(await readFile(new URL("./prime-settings-keybindings-request.schema.json", import.meta.url), "utf8"));

function resolve(fragment) {
  if (typeof fragment.$ref !== "string" || !fragment.$ref.startsWith("#/$defs/")) return fragment;
  const resolved = schema.$defs?.[fragment.$ref.slice("#/$defs/".length)];
  if (resolved === undefined) throw new Error("settings schema invalid");
  return resolved;
}
function valid(fragment, value) {
  const rule = resolve(fragment);
  if (Array.isArray(rule.oneOf)) return rule.oneOf.filter((branch) => valid(branch, value)).length === 1;
  if (rule.type === "object") {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
    const object = value;
    if (rule.additionalProperties === false && Object.keys(object).some((key) => !Object.hasOwn(rule.properties ?? {}, key))) return false;
    if (Array.isArray(rule.required) && rule.required.some((key) => !Object.hasOwn(object, key))) return false;
    return Object.entries(rule.properties ?? {}).every(([key, child]) => !Object.hasOwn(object, key) || valid(child, object[key]));
  }
  if (rule.type === "string" && typeof value !== "string") return false;
  if (rule.type === "boolean" && typeof value !== "boolean") return false;
  if (Object.hasOwn(rule, "const") && value !== rule.const) return false;
  if (Array.isArray(rule.enum) && !rule.enum.includes(value)) return false;
  return typeof rule.pattern !== "string" || (typeof value === "string" && new RegExp(rule.pattern, "u").test(value));
}

function freeze(value) {
  if (value !== null && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

/** Copied closed Asterion settings request admission: schema plus forbidden keys. */
export function validateSettingsKeybindingsRequest(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("settings request invalid");
  for (const key of Object.keys(value)) if (FORBIDDEN_OPERATION_KEYS.has(key)) throw new Error("settings request forbidden key");
  if (!valid(schema, value)) throw new Error("settings request invalid");
  return freeze(structuredClone(value));
}
