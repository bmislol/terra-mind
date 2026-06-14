#nullable enable
using System.Text.Json.Serialization;
using TerraMind.State;

namespace TerraMind.Transport
{
    // Wire DTOs for the backend auth + bot endpoints. Field names are pinned with
    // explicit [JsonPropertyName] to the REAL backend schemas (verified against
    // backend/app/api/auth.py + backend/app/api/bot.py) — no naming-policy guess,
    // and no echo-stub shape (the spike's KeyNotFoundException came from parsing
    // "reply" against the real "answer"/"session_id").

    // POST /auth/jwt/login response → TokenPairResponse.
    public class LoginResponseDto
    {
        [JsonPropertyName("access_token")]
        public string AccessToken { get; set; } = "";

        [JsonPropertyName("refresh_token")]
        public string RefreshToken { get; set; } = "";

        [JsonPropertyName("token_type")]
        public string TokenType { get; set; } = "bearer";
    }

    // POST /bot/ask request body → AskRequest {message, state, session_id?}.
    // state reuses the schema-verified StatePayloadDto from Phase 4.2.
    public class AskRequestDto
    {
        [JsonPropertyName("message")]
        public string Message { get; set; } = "";

        [JsonPropertyName("state")]
        public StatePayloadDto? State { get; set; }

        // null on the first turn; the backend creates a session and returns its
        // id, which we thread back here so the conversation keeps short-term
        // memory continuity (backend 4.1b).
        [JsonPropertyName("session_id")]
        public string? SessionId { get; set; }
    }

    // POST /bot/ask response → AskResponse. We consume answer + session_id;
    // routing is surfaced as a debug signal in the log/chat; source_chunks is
    // intentionally ignored (not needed client-side).
    public class AskResponseDto
    {
        [JsonPropertyName("answer")]
        public string Answer { get; set; } = "";

        [JsonPropertyName("session_id")]
        public string SessionId { get; set; } = "";

        [JsonPropertyName("routing")]
        public string Routing { get; set; } = "";
    }

    // POST /auth/refresh + /auth/logout request body → {refresh_token}.
    public class RefreshRequestDto
    {
        [JsonPropertyName("refresh_token")]
        public string RefreshToken { get; set; } = "";
    }

    // POST /auth/refresh response → AccessTokenResponse {access_token}.
    public class RefreshResponseDto
    {
        [JsonPropertyName("access_token")]
        public string AccessToken { get; set; } = "";
    }
}
