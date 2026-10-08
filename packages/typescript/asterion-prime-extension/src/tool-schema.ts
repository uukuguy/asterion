/** Normalize function schemas at the Prime tool boundary, without narrowing inputs. */
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiresObject(schema: unknown, depth = 0): boolean {
  if (!record(schema) || depth > 32) return false;
  if (schema.type === "object") return true;
  if (schema.type !== undefined) return false;
  for (const key of ["anyOf", "oneOf"] as const) {
    const branches = schema[key];
    if (Array.isArray(branches) && branches.length > 0
        && branches.every(branch => requiresObject(branch, depth + 1))) return true;
  }
  const intersection = schema.allOf;
  return Array.isArray(intersection)
    && intersection.some(branch => requiresObject(branch, depth + 1));
}

export function normalizeFunctionParameters(schema: unknown): Record<string, unknown> {
  if (!record(schema) || !requiresObject(schema)) {
    throw new Error("Prime function parameters must accept only objects");
  }
  // A tagged object union already rejects non-objects. Making that root type
  // explicit preserves its branches while satisfying function API validators.
  return { ...schema, type: "object" };
}
