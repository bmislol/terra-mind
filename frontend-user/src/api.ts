// Thin API client for the backend. Login is FORM-encoded (OAuth2PasswordRequestForm);
// everything else is JSON. Authed calls attach the Bearer access token and, on a
// 401, try one /auth/refresh + retry before giving up (then the caller re-logs-in).

import { clearTokens, loadTokens, saveTokens } from "./auth";
import type { Preferences } from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn a FastAPI error body into a readable message (never raw JSON to the user). */
async function readError(resp: Response): Promise<string> {
  try {
    const data: unknown = await resp.json();
    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((d) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg: unknown }).msg)
              : String(d),
          )
          .join("; ");
      }
    }
    return `Request failed (HTTP ${resp.status}).`;
  } catch {
    return resp.statusText || `Request failed (HTTP ${resp.status}).`;
  }
}

// ── Public (unauthenticated) ──────────────────────────────────────────────────

export async function register(email: string, password: string): Promise<void> {
  const resp = await fetch(`${BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!resp.ok) throw new ApiError(resp.status, await readError(resp));
}

export async function login(email: string, password: string): Promise<void> {
  // OAuth2PasswordRequestForm → form-encoded, username = email.
  const body = new URLSearchParams({ username: email, password });
  const resp = await fetch(`${BASE}/auth/jwt/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!resp.ok) throw new ApiError(resp.status, await readError(resp));
  const data = await resp.json();
  saveTokens(data.access_token, data.refresh_token);
}

export async function guest(): Promise<void> {
  const resp = await fetch(`${BASE}/auth/guest`, { method: "POST" });
  if (!resp.ok) throw new ApiError(resp.status, await readError(resp));
  const data = await resp.json();
  saveTokens(data.access_token, null); // access-only — guests get no refresh token
}

export async function getVersions(): Promise<string[]> {
  const resp = await fetch(`${BASE}/versions`);
  if (!resp.ok) throw new ApiError(resp.status, await readError(resp));
  const data = await resp.json();
  return data.versions as string[];
}

// ── Authed ────────────────────────────────────────────────────────────────────

async function tryRefresh(): Promise<boolean> {
  const { refresh } = loadTokens();
  if (!refresh) return false;
  const resp = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!resp.ok) {
    clearTokens();
    return false;
  }
  const data = await resp.json();
  saveTokens(data.access_token, refresh);
  return true;
}

/** Authed fetch: attach Bearer, and on 401 try one refresh + retry. */
async function authed(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const { access } = loadTokens();
  if (access) headers.set("Authorization", `Bearer ${access}`);

  let resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (resp.status === 401 && (await tryRefresh())) {
    const { access: fresh } = loadTokens();
    if (fresh) headers.set("Authorization", `Bearer ${fresh}`);
    resp = await fetch(`${BASE}${path}`, { ...init, headers });
  }
  return resp;
}

/** True when an authed call still 401s after a refresh attempt — session is dead. */
export class SessionExpiredError extends Error {}

export async function getPreferences(): Promise<Preferences> {
  const resp = await authed("/me/preferences");
  if (resp.status === 401) throw new SessionExpiredError();
  if (!resp.ok) throw new ApiError(resp.status, await readError(resp));
  return (await resp.json()) as Preferences;
}

export async function updatePreferences(prefs: Preferences): Promise<Preferences> {
  const resp = await authed("/me/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
  if (resp.status === 401) throw new SessionExpiredError();
  if (!resp.ok) throw new ApiError(resp.status, await readError(resp));
  return (await resp.json()) as Preferences;
}

export async function eraseMe(): Promise<void> {
  const resp = await authed("/me", { method: "DELETE" });
  if (resp.status === 401) throw new SessionExpiredError();
  if (!resp.ok && resp.status !== 204) {
    throw new ApiError(resp.status, await readError(resp));
  }
}
