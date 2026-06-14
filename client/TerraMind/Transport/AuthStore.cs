#nullable enable
using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using Terraria;

namespace TerraMind.Transport
{
    // On-disk persistence of the token pair (commit 2). The ONLY thing the mod
    // writes to disk — never a password (D-027). Lives under Main.SavePath (the
    // tModLoader save dir, e.g. ~/.local/share/Terraria/tModLoader — confirmed in
    // the 4.2 client.log "Saves Are Located At").
    //
    // First filesystem touch for the mod, so the read path is fail-soft: a
    // missing OR corrupt/unreadable file returns null and the caller falls back
    // to /bot login — never a crash. The write path is best-effort: a failure is
    // logged but does not break the (already-working) in-memory login.
    public static class AuthStore
    {
        private static string Dir => Path.Combine(Main.SavePath, "TerraMind");
        private static string FilePath => Path.Combine(Dir, "token.json");

        // Persist the token pair. Throws on I/O failure so the caller can log it;
        // the caller treats persistence as best-effort (login still works in
        // memory this run).
        public static void Save(string accessToken, string refreshToken)
        {
            Directory.CreateDirectory(Dir);
            var data = new StoredTokens
            {
                AccessToken = accessToken,
                RefreshToken = refreshToken,
            };
            File.WriteAllText(FilePath, JsonSerializer.Serialize(data));
        }

        // The stored pair, or null if the file is absent / unreadable / corrupt /
        // empty. Never throws — "no saved login" is a normal state, not an error.
        public static StoredTokens? Load()
        {
            try
            {
                if (!File.Exists(FilePath))
                    return null;
                StoredTokens? data =
                    JsonSerializer.Deserialize<StoredTokens>(File.ReadAllText(FilePath));
                if (data == null || string.IsNullOrEmpty(data.AccessToken))
                    return null;
                return data;
            }
            catch (Exception)
            {
                // Corrupt/unreadable → treat as no saved login, fall back to /bot login.
                return null;
            }
        }

        // Remove the saved login (used by /bot logout in commit 3). Best-effort.
        public static void Delete()
        {
            try
            {
                if (File.Exists(FilePath))
                    File.Delete(FilePath);
            }
            catch (Exception)
            {
                // Best-effort; commit 3's /bot logout also revokes server-side (D-029).
            }
        }
    }

    // token.json shape — tokens only, no password, no PII.
    public class StoredTokens
    {
        [JsonPropertyName("access_token")]
        public string AccessToken { get; set; } = "";

        [JsonPropertyName("refresh_token")]
        public string RefreshToken { get; set; } = "";
    }
}
