using System.Threading.Tasks;

namespace TerraMind.Transport
{
    // Shared auth flows used by both the /bot command (refresh-on-401) and the
    // world-entry hook (refresh-on-launch). Pure logic — no chat/log I/O; callers
    // report the outcome with their own Mod.Logger / Print(). Keeps the refresh
    // semantics in one place so the two call sites can't drift.
    public static class AuthFlow
    {
        // Exchange the saved refresh token for a fresh access token (D-027/D-029).
        // On success: updates Session.AccessToken, re-persists token.json, returns
        // true. On failure (no/expired/denylisted refresh token): clears the
        // session + deletes token.json and returns false — the caller then prompts
        // for /bot login.
        public static async Task<bool> TryRefreshAsync(string baseUrl)
        {
            var refresh = Session.RefreshToken;
            if (string.IsNullOrEmpty(refresh))
                return false;

            try
            {
                string newAccess = await BackendClient.RefreshAsync(baseUrl, refresh);
                Session.AccessToken = newAccess;
                try
                {
                    AuthStore.Save(newAccess, refresh);
                }
                catch
                {
                    // Best-effort re-persist; the in-memory token still works this run.
                }
                return true;
            }
            catch
            {
                // Refresh token is dead → drop to a clean logged-out state.
                ClearSession();
                AuthStore.Delete();
                return false;
            }
        }

        // Wipe in-memory auth (used by refresh-failure and /bot logout).
        public static void ClearSession()
        {
            Session.AccessToken = null;
            Session.RefreshToken = null;
            Session.SessionId = null;
            Session.Email = null;
        }
    }
}
