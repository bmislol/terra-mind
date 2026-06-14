#nullable enable
using Terraria.ModLoader;
using TerraMind.Transport;

namespace TerraMind
{
    // The production chat surface (D-002). Phase 4.2: /bot reads live character
    // state and logs the StatePayload JSON. Phase 4.3 adds the authed HTTP call.
    public class TerraMind : Mod
    {
        // Commit 2: restore a persisted login on launch so /bot works without
        // re-typing credentials. A missing/corrupt token.json → null → no session
        // restored (the player runs /bot login). The stored access token may be
        // expired on a late restart (30-min TTL); commit 3 adds the /auth/refresh
        // exchange for durability beyond that window.
        public override void Load()
        {
            StoredTokens? saved = AuthStore.Load();
            if (saved == null)
                return;
            Session.AccessToken = saved.AccessToken;
            Session.RefreshToken = saved.RefreshToken;
            Logger.Info("token.json loaded — session restored from a previous login");
        }
    }
}
