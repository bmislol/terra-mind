// Token storage. The ONLY thing the portal persists is the JWT pair — never the
// password, never any other state (that's React state). Guests have no refresh
// token (access-only), so it may be null.

const ACCESS_KEY = "tm_access";
const REFRESH_KEY = "tm_refresh";

export interface StoredTokens {
  access: string | null;
  refresh: string | null;
}

export function loadTokens(): StoredTokens {
  return {
    access: localStorage.getItem(ACCESS_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
  };
}

export function saveTokens(access: string, refresh: string | null): void {
  localStorage.setItem(ACCESS_KEY, access);
  if (refresh) {
    localStorage.setItem(REFRESH_KEY, refresh);
  } else {
    localStorage.removeItem(REFRESH_KEY);
  }
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

/** A guest session is access-only — /auth/guest issues no refresh token (D-029).
 *  Used to hide account actions (e.g. data erasure) that don't apply to guests. */
export function isGuestSession(): boolean {
  const { access, refresh } = loadTokens();
  return Boolean(access) && !refresh;
}
