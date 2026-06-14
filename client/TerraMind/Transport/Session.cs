#nullable enable
namespace TerraMind.Transport
{
    // In-memory auth + conversation state for the current game session.
    //
    // Commit 1: tokens live here only — on-disk persistence is commit 2. The
    // PASSWORD is never stored here: it exists only as an argument to
    // BackendClient.LoginAsync and is gone once that call returns. session_id
    // threads short-term-memory continuity across /bot calls (backend 4.1b).
    //
    // Email is set only by a fresh /bot login (so the confirmation can name you);
    // it is IN-MEMORY ONLY and never persisted to token.json — it is PII
    // (SECURITY §7.1). A token-only restore from disk therefore has a null Email,
    // which is how OnEnterWorld tells "restored" from "freshly logged in".
    public static class Session
    {
        public static string? AccessToken { get; set; }
        public static string? RefreshToken { get; set; }
        public static string? SessionId { get; set; }
        public static string? Email { get; set; }

        public static bool IsLoggedIn => !string.IsNullOrEmpty(AccessToken);
    }
}
