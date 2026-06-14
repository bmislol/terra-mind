using System.ComponentModel;
using Terraria.ModLoader.Config;

namespace TerraMind.Config
{
    // Client-side mod config. Holds the backend base URL ONLY (D-028) — no
    // credentials. A tModLoader ModConfig auto-persists to disk
    // (Main.SavePath/ModConfigs/TerraMind_TerraMindConfig.json), so a username/
    // password here would be a plaintext password on disk — exactly what D-027's
    // token-only model exists to avoid. Credentials come via the /bot login chat
    // command: in-memory for the single /auth/jwt/login call, then discarded.
    public class TerraMindConfig : ModConfig
    {
        public override ConfigScope Mode => ConfigScope.ClientSide;

        // Default matches the compose-local demo target (D-028). Editable from the
        // in-game Mod Configuration menu; "point at a hosted backend" is then a
        // one-line config change, not a code change.
        [DefaultValue("http://localhost:8000")]
        public string BackendUrl { get; set; } = "http://localhost:8000";

        // Normalized base for URL building (trailing slash stripped). A method, not
        // a property, so the ModConfig serializer doesn't try to persist it.
        public string BaseUrl() => (BackendUrl ?? "http://localhost:8000").TrimEnd('/');
    }
}
