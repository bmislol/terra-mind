using System.Threading.Tasks;
using Terraria.ModLoader;
using TerraMind.Commands;
using TerraMind.Config;
using TerraMind.Transport;

namespace TerraMind.Players
{
    // Surfaces auth state to the player on world entry, and (commit 3) refreshes a
    // restored token on launch. Mod.Load() restores a token too early to message
    // anyone or make a network call — no world/chat yet — so the confirmation, and
    // the refresh that backs it, land here in OnEnterWorld (chat live, async OK).
    //
    // Threading: OnEnterWorld runs on the game thread, but rendering still goes
    // through Print() (QueueMainThreadAction) — same rule as the rest of the async
    // path, and the refresh continuation is on a background thread after the await.
    public class TerraMindPlayer : ModPlayer
    {
        // NOTE: tModLoader 1.4.4 ModPlayer.OnEnterWorld is parameterless (the
        // Player is `this.Player`); the older `OnEnterWorld(Player)` was removed.
        // If a build ever complains, that's the one-line signature fix.
        public override void OnEnterWorld()
        {
            if (!Session.IsLoggedIn)
            {
                // Quiet nudge so the "not logged in" state is visible too.
                BotCommand.Print("[TerraMind] not logged in — use /bot login <user> <pass>");
                return;
            }

            if (Session.Email != null)
            {
                // Fresh login this session — access token already valid, just confirm.
                BotCommand.Print($"[TerraMind] logged in as {Session.Email}");
                return;
            }

            // Token-only restore from token.json: the stored access token may be
            // expired (30-min TTL), so refresh it on launch (D-027) before
            // confirming. Async — Print() marshals the result back to the game thread.
            _ = RefreshOnEnterAsync();
        }

        private async Task RefreshOnEnterAsync()
        {
            string baseUrl = ModContent.GetInstance<TerraMindConfig>().BaseUrl();
            if (await AuthFlow.TryRefreshAsync(baseUrl))
            {
                Mod.Logger.Info("/auth/refresh on launch ok — session restored");
                BotCommand.Print("[TerraMind] session restored — logged in");
            }
            else
            {
                Mod.Logger.Warn("/auth/refresh on launch failed — re-login required");
                BotCommand.Print("[TerraMind] session expired — use /bot login <user> <pass>");
            }
        }
    }
}
