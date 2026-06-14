using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace TerraMind.Transport
{
    // All backend HTTP for the mod. ONE static HttpClient for the mod's lifetime —
    // a client-per-call leaks sockets (spike finding, RUNBOOK §9).
    //
    // The encoding split is the easy-to-miss trap: /auth/jwt/login is FastAPI's
    // OAuth2PasswordRequestForm, so it takes FORM-URLENCODED username/password
    // fields (NOT JSON). /bot/ask is JSON + a Bearer access token. Methods throw
    // BackendException on a non-2xx or empty body; the command continuation
    // catches it and renders a readable chat line, never a crash.
    public static class BackendClient
    {
        private static readonly HttpClient Http = new HttpClient
        {
            // Generous: the agent path (router + retrieval + LLM) can take several
            // seconds. Tunable; 30s is comfortably above what's been observed.
            Timeout = TimeSpan.FromSeconds(30),
        };

        // POST /auth/jwt/login — form-encoded, returns the access+refresh pair.
        // The password lives only in this call's arguments; nothing here stores
        // or logs it.
        public static async Task<LoginResponseDto> LoginAsync(
            string baseUrl, string username, string password)
        {
            using var form = new FormUrlEncodedContent(new Dictionary<string, string>
            {
                ["username"] = username,
                ["password"] = password,
            });

            using HttpResponseMessage resp =
                await Http.PostAsync(baseUrl + "/auth/jwt/login", form);
            if (!resp.IsSuccessStatusCode)
                throw new BackendException($"login failed (HTTP {(int)resp.StatusCode})", (int)resp.StatusCode);

            string body = await resp.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<LoginResponseDto>(body)
                ?? throw new BackendException("login returned an empty body");
        }

        // POST /bot/ask — JSON body (AskRequest) + Bearer access token. Parses the
        // REAL AskResponse (answer + session_id).
        public static async Task<AskResponseDto> AskAsync(
            string baseUrl, string accessToken, AskRequestDto request)
        {
            string json = JsonSerializer.Serialize(request);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            using var msg = new HttpRequestMessage(HttpMethod.Post, baseUrl + "/bot/ask")
            {
                Content = content,
            };
            msg.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);

            using HttpResponseMessage resp = await Http.SendAsync(msg);
            if (!resp.IsSuccessStatusCode)
                throw new BackendException($"/bot/ask failed (HTTP {(int)resp.StatusCode})", (int)resp.StatusCode);

            string body = await resp.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<AskResponseDto>(body)
                ?? throw new BackendException("/bot/ask returned an empty body");
        }

        // POST /auth/refresh — JSON {refresh_token} → a fresh access token. This is
        // the mod's saved-token exchange (D-027; /client/token folded in here).
        public static async Task<string> RefreshAsync(string baseUrl, string refreshToken)
        {
            string json = JsonSerializer.Serialize(new RefreshRequestDto { RefreshToken = refreshToken });
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            using HttpResponseMessage resp = await Http.PostAsync(baseUrl + "/auth/refresh", content);
            if (!resp.IsSuccessStatusCode)
                throw new BackendException($"/auth/refresh failed (HTTP {(int)resp.StatusCode})", (int)resp.StatusCode);
            string body = await resp.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<RefreshResponseDto>(body)?.AccessToken
                ?? throw new BackendException("/auth/refresh returned an empty body");
        }

        // POST /auth/logout — JSON {refresh_token} → 204. Denylists the refresh jti
        // server-side (D-029). Best-effort: the caller has already cleared the local
        // token, so a failure here only skips the server-side revoke.
        public static async Task LogoutAsync(string baseUrl, string refreshToken)
        {
            string json = JsonSerializer.Serialize(new RefreshRequestDto { RefreshToken = refreshToken });
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            using HttpResponseMessage resp = await Http.PostAsync(baseUrl + "/auth/logout", content);
            if (!resp.IsSuccessStatusCode)
                throw new BackendException($"/auth/logout failed (HTTP {(int)resp.StatusCode})", (int)resp.StatusCode);
        }
    }

    // An expected backend failure (non-2xx / empty body). Caught in the command
    // continuation and shown in chat; keeps it distinct from an unexpected crash.
    public class BackendException : Exception
    {
        public int StatusCode { get; }

        public BackendException(string message, int statusCode = 0) : base(message)
        {
            StatusCode = statusCode;
        }
    }
}
