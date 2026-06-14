using System;
using System.Threading.Tasks;
using Terraria;
using Terraria.ModLoader;
using TerraMind.Config;
using TerraMind.State;
using TerraMind.Transport;

namespace TerraMind.Commands
{
    // /bot — the in-game chat command (CommandType.Chat, proven in the Phase 1.2
    // spike). Four forms:
    //   /bot login <user> <pass>  → authenticate; password used once, never stored
    //   /bot <question>           → POST /bot/ask with live state, render the answer
    //   /bot logout               → revoke + delete the saved token (D-029)
    //   /bot                      → usage hint
    //
    // Threading contract (the #1 crash risk, RUNBOOK §9): Action runs on the GAME
    // thread, so all game-state reads (StateReader.Read → Main.LocalPlayer) happen
    // here, synchronously, BEFORE any await. The network call runs on a fired-and-
    // forgotten Task; after the await we are on a BACKGROUND thread, so every
    // Main.* call in the continuation goes through Print() (QueueMainThreadAction).
    // The whole continuation is wrapped in try/catch — a failure renders a chat
    // line, never an unmarshaled Main.* call (intermittent crash) or a frozen
    // thread.
    public class BotCommand : ModCommand
    {
        public override CommandType Type => CommandType.Chat;
        public override string Command => "bot";
        public override string Usage => "/bot login <user> <pass>  |  /bot <question>  |  /bot logout";

        public override void Action(CommandCaller caller, string input, string[] args)
        {
            string baseUrl = ResolveBaseUrl();

            if (args.Length == 0)
            {
                Print("[TerraMind] usage: /bot login <user> <pass>  then  /bot <question>");
                return;
            }

            // --- /bot login <user> <pass> ---
            if (args[0].Equals("login", StringComparison.OrdinalIgnoreCase))
            {
                if (args.Length < 3)
                {
                    Print("[TerraMind] usage: /bot login <username> <password>");
                    return;
                }
                string username = args[1];
                // Join the remainder so a password may contain spaces. This local
                // is the ONLY place the password exists; never stored, never logged.
                string password = string.Join(" ", args, 2, args.Length - 2);
                Mod.Logger.Info("/bot login → POST /auth/jwt/login (credentials not logged)");
                Print("[TerraMind] logging in…");
                _ = LoginAsync(baseUrl, username, password);
                return;
            }

            // --- /bot logout ---
            if (args[0].Equals("logout", StringComparison.OrdinalIgnoreCase))
            {
                _ = LogoutAsync(baseUrl);
                return;
            }

            // --- /bot <question> ---
            if (!Session.IsLoggedIn)
            {
                Print("[TerraMind] not logged in — use /bot login <user> <pass> first");
                return;
            }

            string message = string.Join(" ", args);
            string accessToken = Session.AccessToken!;     // non-null per IsLoggedIn
            StatePayloadDto state = StateReader.Read();     // GAME THREAD, pre-await

            Mod.Logger.Info(
                $"/bot ask → {baseUrl}/bot/ask message=\"{message}\" "
                + $"session_id={Session.SessionId ?? "(new)"}");
            Print("[TerraMind] thinking…");
            _ = RunAskAsync(baseUrl, accessToken, message, state);
        }

        private async Task LoginAsync(string baseUrl, string username, string password)
        {
            try
            {
                LoginResponseDto tokens =
                    await BackendClient.LoginAsync(baseUrl, username, password);
                Session.AccessToken = tokens.AccessToken;
                Session.RefreshToken = tokens.RefreshToken;
                Session.Email = username;  // in-memory only; names the confirmation, never persisted/logged
                Mod.Logger.Info(
                    "/bot login ok: access+refresh received (held in memory; token values not logged)");

                // Persist for next launch (commit 2). Best-effort: a write failure
                // leaves the in-memory session working this run, just not durable.
                try
                {
                    AuthStore.Save(tokens.AccessToken, tokens.RefreshToken);
                    Mod.Logger.Info("/bot login: token pair persisted to token.json");
                }
                catch (Exception e)
                {
                    Mod.Logger.Warn(
                        $"/bot login: token persist failed (session works this run, not durable): {e.Message}");
                }

                Print($"[TerraMind] logged in as {username} — ask away: /bot <question>");
            }
            catch (Exception e)
            {
                Mod.Logger.Warn($"/bot login failed: {e.Message}");
                Print($"[TerraMind] login failed: {e.Message}");
            }
        }

        private async Task RunAskAsync(
            string baseUrl, string accessToken, string message, StatePayloadDto state)
        {
            var request = new AskRequestDto
            {
                Message = message,
                State = state,
                SessionId = Session.SessionId,   // null on the first turn
            };

            try
            {
                OnAskOk(await BackendClient.AskAsync(baseUrl, accessToken, request));
            }
            catch (BackendException be) when (be.StatusCode == 401)
            {
                // Access token likely expired (30-min TTL). One-shot refresh + retry
                // (D-027). If the refresh token is also dead, drop to re-login.
                Mod.Logger.Info("/bot ask got 401 — attempting /auth/refresh + retry");
                if (!await AuthFlow.TryRefreshAsync(baseUrl))
                {
                    Mod.Logger.Warn("/auth/refresh failed (refresh token dead) — re-login required");
                    Print("[TerraMind] session expired — use /bot login <user> <pass>");
                    return;
                }
                try
                {
                    OnAskOk(await BackendClient.AskAsync(baseUrl, Session.AccessToken!, request));
                }
                catch (Exception e)
                {
                    Mod.Logger.Warn($"/bot ask failed after refresh: {e.Message}");
                    Print($"[TerraMind] error: {e.Message}");
                }
            }
            catch (Exception e)
            {
                Mod.Logger.Warn($"/bot ask failed: {e.Message}");
                Print($"[TerraMind] error: {e.Message}");
            }
        }

        // Thread the session id for memory continuity, log, and render the answer.
        private void OnAskOk(AskResponseDto resp)
        {
            Session.SessionId = resp.SessionId;
            Mod.Logger.Info(
                $"/bot ask ok: routing={resp.Routing} session_id={resp.SessionId}\n"
                + $"answer: {resp.Answer}");
            Print($"[TerraMind] {resp.Answer}");
        }

        private async Task LogoutAsync(string baseUrl)
        {
            var refresh = Session.RefreshToken;   // capture before clearing
            // Local logout always succeeds: clear in-memory state + delete token.json.
            AuthFlow.ClearSession();
            AuthStore.Delete();
            Mod.Logger.Info("/bot logout: local token cleared + token.json deleted");
            Print("[TerraMind] logged out");

            // Best-effort server-side revoke (denylist the refresh jti, D-029).
            if (!string.IsNullOrEmpty(refresh))
            {
                try
                {
                    await BackendClient.LogoutAsync(baseUrl, refresh);
                    Mod.Logger.Info("/bot logout: refresh token revoked server-side (denylisted)");
                }
                catch (Exception e)
                {
                    Mod.Logger.Warn(
                        $"/bot logout: server revoke failed (local logout already applied): {e.Message}");
                }
            }
        }

        private static string ResolveBaseUrl()
        {
            return ModContent.GetInstance<TerraMindConfig>().BaseUrl();
        }

        // Main-thread-safe chat print. After an await we are on a background
        // thread; Main.NewText MUST be marshaled or it crashes intermittently (the
        // spike's critical finding, RUNBOOK §9). Used from both Action (game
        // thread — safe directly, but routed here for one code path) and the async
        // continuations (background thread — marshaling is mandatory).
        internal static void Print(string text)
        {
            Main.QueueMainThreadAction(() => Main.NewText(text));
        }
    }
}
