export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const cleared = new Set<() => void>();

export function onSessionCleared(listener: () => void): () => void {
  cleared.add(listener);
  return () => cleared.delete(listener);
}

export const navigation = {
  assign(url: string): void {
    window.location.assign(url);
  },
  currentPath(): string {
    return `${window.location.pathname}${window.location.search}`;
  },
};

function redirectToLogin(): void {
  for (const listener of cleared) {
    listener();
  }
  const path = navigation.currentPath();
  navigation.assign(`/login?redirect=${encodeURIComponent(path)}`);
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  options?: { redirectOn401?: boolean },
): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-Apgar-Request", "1");
  }
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, method, headers, credentials: "include" });
  if (response.status === 401 && !path.startsWith("/api/v1/auth/")) {
    if (options?.redirectOn401 !== false) {
      redirectToLogin();
    }
    throw new ApiError(401, "unauthorized", "unauthorized");
  }
  if (!response.ok) {
    let code = "error";
    let message = response.statusText || "request failed";
    try {
      const body = (await response.json()) as { error?: { code?: string; message?: string } };
      if (body.error?.code) {
        code = body.error.code;
      }
      if (body.error?.message) {
        message = body.error.message;
      }
    } catch {
      // The body was not JSON. Keep the status text.
    }
    throw new ApiError(response.status, code, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}
