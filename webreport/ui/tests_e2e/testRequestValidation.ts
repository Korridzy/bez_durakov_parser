import type { Request } from "@playwright/test";

interface TestValidationIssue {
  readonly type: string;
  readonly loc: readonly (string | number)[];
  readonly msg: string;
  readonly input: unknown;
  readonly ctx?: Readonly<Record<string, unknown>>;
}

export class TestRequestValidationError extends Error {
  constructor(readonly detail: readonly TestValidationIssue[]) {
    super("Request validation failed");
    this.name = "TestRequestValidationError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Mirror the body models in chat_routes, not semantic route validation. */
export function testRequestBody(request: Request): Record<string, unknown> {
  const path = new URL(request.url()).pathname;
  const create = request.method() === "POST" && path === "/api/chats";
  const rename = request.method() === "PATCH" && /^\/api\/chats\/[^/]+$/.test(path);
  const send = request.method() === "POST" && /^\/api\/chats\/[^/]+\/messages$/.test(path);
  const cancel = request.method() === "POST" && /^\/api\/chats\/[^/]+\/cancel$/.test(path);
  // Saved/Update endpoints have no body model; FastAPI ignores their request body.
  if (!create && !rename && !send && !cancel) return {};
  const raw = request.postData();
  let parsed: unknown = null;
  try {
    if (raw !== null && raw !== "") parsed = JSON.parse(raw);
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    const offset = /position (\d+)/.exec(error.message)?.[1];
    const position = offset === undefined ? (raw ?? "").length : Number(offset);
    const context = error.message.includes("property name")
      ? "Expecting property name enclosed in double quotes"
      : error.message.includes("after JSON") ? "Extra data"
      : error.message.includes("Expected ','") ? "Expecting ',' delimiter"
      : "Expecting value";
    throw new TestRequestValidationError([{
      type: "json_invalid", loc: ["body", [...(raw ?? "").slice(0, position)].length],
      msg: "JSON decode error", input: {}, ctx: { error: context },
    }]);
  }
  if (parsed === null) {
    throw new TestRequestValidationError([{
      type: "missing", loc: ["body"], msg: "Field required", input: null,
    }]);
  }
  if (!record(parsed)) {
    throw new TestRequestValidationError([{
      type: "model_attributes_type", loc: ["body"],
      msg: "Input should be a valid dictionary or object to extract fields from", input: parsed,
    }]);
  }
  const fields = send ? ["request_id", "message"] : cancel ? ["request_id"] : ["title"];
  const issues: TestValidationIssue[] = [];
  for (const field of fields) {
    if (!Object.hasOwn(parsed, field)) {
      if (!create) issues.push({
        type: "missing", loc: ["body", field], msg: "Field required", input: parsed,
      });
    } else if (!(create && parsed[field] === null) && typeof parsed[field] !== "string") {
      issues.push({
        type: "string_type", loc: ["body", field],
        msg: "Input should be a valid string", input: parsed[field],
      });
    }
  }
  if (issues.length > 0) throw new TestRequestValidationError(issues);
  return parsed;
}

export function testQueryLimit(input: string | null): number {
  const raw = input ?? "50";
  const value = Number(raw);
  let issue: TestValidationIssue | undefined;
  if (!/^[+-]?\d+(?:\.0+)?$/.test(raw.trim()) || !Number.isInteger(value)) {
    issue = {
      type: "int_parsing", loc: ["query", "limit"],
      msg: "Input should be a valid integer, unable to parse string as an integer", input: raw,
    };
  } else if (value < 1) {
    issue = {
      type: "greater_than_equal", loc: ["query", "limit"],
      msg: "Input should be greater than or equal to 1", input: raw, ctx: { ge: 1 },
    };
  } else if (value > 100) {
    issue = {
      type: "less_than_equal", loc: ["query", "limit"],
      msg: "Input should be less than or equal to 100", input: raw, ctx: { le: 100 },
    };
  }
  if (issue !== undefined) throw new TestRequestValidationError([issue]);
  return value;
}
