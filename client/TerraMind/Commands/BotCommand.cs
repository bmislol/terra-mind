using System.Text.Json;
using Terraria;
using Terraria.ModLoader;
using TerraMind.State;

namespace TerraMind.Commands
{
    // /bot <message> — invoked from the in-game chat box (proven in the Phase 1.2
    // spike, RUNBOOK §9). Phase 4.2: read live state → log the StatePayload JSON
    // → print a chat summary. NO backend call yet (Phase 4.3 wires the captured
    // message to an authed POST /bot/ask).
    public class BotCommand : ModCommand
    {
        public override CommandType Type => CommandType.Chat;
        public override string Command => "bot";
        public override string Usage => "/bot <message>";

        private static readonly JsonSerializerOptions JsonOpts = new()
        {
            WriteIndented = true,
        };

        public override void Action(CommandCaller caller, string input, string[] args)
        {
            // Capture the message now even though 4.2 doesn't send it — keeps the
            // 4.3 HTTP wiring a small change, not a restructure (spike pattern).
            string message = string.Join(" ", args);

            StatePayloadDto state = StateReader.Read();
            string json = JsonSerializer.Serialize(state, JsonOpts);

            // Full payload → the mod log (tModLoader-Logs/client.log): untruncated
            // source of truth to eyeball against the real character (RUNBOOK §10).
            Mod.Logger.Info($"/bot message=\"{message}\"\nStatePayload:\n{json}");

            // Short confirmation → in-game chat (chat lines truncate; the log has
            // the full JSON).
            Print(
                $"[TerraMind] state logged — armor:{state.Gear.Armor.Count} "
                + $"acc:{state.Gear.Accessories.Count} inv:{state.Inventory.Count} "
                + $"bosses:{state.World.DownedBosses.Count} "
                + $"hardmode:{state.World.Hardmode} (full JSON in client.log)"
            );
        }

        // Main-thread-safe UI print. In 4.2 Action runs on the game thread, so a
        // direct Main.NewText would also be safe — but the spike's CRITICAL
        // finding (RUNBOOK §9) is that after an `await` you are on a BACKGROUND
        // thread and any Main.* call MUST be marshaled with QueueMainThreadAction
        // or it crashes intermittently. 4.3's async HTTP continuation depends on
        // exactly this, so the pattern is carried from day one.
        internal static void Print(string text)
        {
            Main.QueueMainThreadAction(() => Main.NewText(text));
        }
    }
}
