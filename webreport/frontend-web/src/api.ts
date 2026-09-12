let token = "";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Workspace-Token": token,
        ...init.headers,
      },
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Связь с сервером потеряна.", 0);
  }
  if (response.status === 403 && retry && path !== "/workspace") {
    await api("/workspace");
    return api(path, init, false);
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("Сервер временно недоступен.", response.status);
  }
  if (!response.ok)
    throw new ApiError(
      typeof body.detail === "string"
        ? body.detail
        : "Проверьте заполненные поля.",
      response.status,
    );
  if (path === "/workspace") token = body.csrf_token;
  return body;
}
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
export const number = (n: unknown) =>
  typeof n === "number"
    ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(n)
    : String(n ?? "—");
export const dayLabel = (value: string) =>
  new Date(value.slice(0, 10) + "T12:00:00")
    .toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
    .replace(".", "");
