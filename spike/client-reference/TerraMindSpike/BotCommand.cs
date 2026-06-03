using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Terraria;
using Terraria.ModLoader;

namespace TerraMindSpike
{
    public class BotCommand : ModCommand
    {
        public override CommandType Type => CommandType.Chat;   // usable from the in-game chat box
        public override string Command => "bot";                // invoked as: /bot <message>
        public override string Usage => "/bot <message>";

        // One shared HttpClient for the mod's lifetime (creating one per call leaks sockets).
        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(10)
        };

        public override void Action(CommandCaller caller, string input, string[] args)
        {
            string message = string.Join(" ", args);
            int hp = Main.LocalPlayer.statLife;   // live state read — current HP

            Main.NewText("[TerraMind] thinking...");

            // Fire-and-forget so we never block the game thread. The continuation
            // marshals the UI update back onto the main thread.
            _ = AskAsync(message, hp);
        }

        private static async Task AskAsync(string message, int hp)
        {
            try
            {
                var payload = JsonSerializer.Serialize(new { message, hp });
                var content = new StringContent(payload, Encoding.UTF8, "application/json");

                HttpResponseMessage response = await Http.PostAsync(
                    "http://localhost:8000/echo", content);
                string body = await response.Content.ReadAsStringAsync();

                using var doc = JsonDocument.Parse(body);
                string reply = doc.RootElement.GetProperty("reply").GetString();

                // Main.QueueMainThreadAction: NewText must run on the game thread,
                // and we're currently on a background thread after the await.
                Main.QueueMainThreadAction(() => Main.NewText($"[TerraMind] {reply}"));
            }
            catch (Exception e)
            {
                Main.QueueMainThreadAction(() =>
                    Main.NewText($"[TerraMind] error: {e.Message}"));
            }
        }
    }
}