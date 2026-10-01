/** Exact responses captured from the real chat router and RunRegistry validators. */
export interface TestValidationCase {
  readonly name: string;
  readonly method: string;
  readonly path: string;
  readonly body: string | null;
  readonly expected: Readonly<Record<string, unknown>>;
}

const messages = "/api/chats/:id/messages";
const stringIssue = (field: string, input: unknown) => ({
  type: "string_type", loc: ["body", field], msg: "Input should be a valid string", input,
});
const missingIssue = (field: string) => ({
  type: "missing", loc: ["body", field], msg: "Field required", input: {},
});
const semantic = (message: string) => ({ error: { code: "invalid_request", message } });

export const testValidationCases: readonly TestValidationCase[] = [
  { name: "broken-json", method: "POST", path: messages, body: "{broken",
    expected: { detail: [{
      type: "json_invalid", loc: ["body", 1], msg: "JSON decode error", input: {},
      ctx: { error: "Expecting property name enclosed in double quotes" },
    }] } },
  { name: "wrong-message-types", method: "POST", path: messages,
    body: '{"request_id":42,"message":[]}',
    expected: { detail: [stringIssue("request_id", 42), stringIssue("message", [])] } },
  { name: "missing-message-fields", method: "POST", path: messages, body: "{}",
    expected: { detail: [missingIssue("request_id"), missingIssue("message")] } },
  { name: "array-body", method: "POST", path: messages, body: "[]",
    expected: { detail: [{
      type: "model_attributes_type", loc: ["body"],
      msg: "Input should be a valid dictionary or object to extract fields from", input: [],
    }] } },
  { name: "null-body", method: "POST", path: messages, body: "null",
    expected: { detail: [{ type: "missing", loc: ["body"], msg: "Field required", input: null }] } },
  { name: "title-type", method: "POST", path: "/api/chats", body: '{"title":42}',
    expected: { detail: [stringIssue("title", 42)] } },
  { name: "rename-missing-title", method: "PATCH", path: "/api/chats/:id", body: "{}",
    expected: { detail: [missingIssue("title")] } },
  { name: "cancel-type", method: "POST", path: "/api/chats/:id/cancel",
    body: '{"request_id":42}', expected: { detail: [stringIssue("request_id", 42)] } },
  { name: "limit-type", method: "GET", path: "/api/chats?limit=abc", body: null,
    expected: { detail: [{
      type: "int_parsing", loc: ["query", "limit"],
      msg: "Input should be a valid integer, unable to parse string as an integer", input: "abc",
    }] } },
  { name: "limit-min", method: "GET", path: "/api/chats?limit=0", body: null,
    expected: { detail: [{
      type: "greater_than_equal", loc: ["query", "limit"],
      msg: "Input should be greater than or equal to 1", input: "0", ctx: { ge: 1 },
    }] } },
  { name: "limit-max", method: "GET", path: "/api/chats?limit=101", body: null,
    expected: { detail: [{
      type: "less_than_equal", loc: ["query", "limit"],
      msg: "Input should be less than or equal to 100", input: "101", ctx: { le: 100 },
    }] } },
  { name: "semantic-id", method: "POST", path: messages,
    body: '{"request_id":"bad","message":"вопрос"}',
    expected: semantic("Неверный request_id") },
  { name: "semantic-empty-message", method: "POST", path: messages,
    body: '{"request_id":"bad","message":"  "}',
    expected: semantic("Сообщение не должно быть пустым") },
  { name: "semantic-empty-title", method: "POST", path: "/api/chats", body: '{"title":"  "}',
    expected: semantic("Название должно содержать от 1 до 80 символов") },
];
