#nullable enable
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace TerraMind.State
{
    // Wire shape MUST match the backend's Pydantic StatePayload EXACTLY
    // (backend/app/domain/bot.py) or POST /bot/ask 422s in Phase 4.3.
    // Explicit [JsonPropertyName] on every field — snake_case, no reliance on a
    // serializer naming policy. NOTE: game_version is TOP-LEVEL (not in world);
    // name and biome are NON-nullable strings ("" / "forest"); only prefix and
    // weapon are nullable.

    public class ItemRefDto
    {
        [JsonPropertyName("item_id")]
        public int ItemId { get; set; }

        // Non-nullable on the backend (default ""): send "" for a nameless item.
        [JsonPropertyName("name")]
        public string Name { get; set; } = "";

        // Nullable: null when the item has no prefix/modifier.
        [JsonPropertyName("prefix")]
        public string? Prefix { get; set; }

        [JsonPropertyName("stack")]
        public int Stack { get; set; } = 1;
    }

    public class GearDto
    {
        [JsonPropertyName("armor")]
        public List<ItemRefDto> Armor { get; set; } = new();

        [JsonPropertyName("accessories")]
        public List<ItemRefDto> Accessories { get; set; } = new();

        // Nullable: null when no weapon/held item.
        [JsonPropertyName("weapon")]
        public ItemRefDto? Weapon { get; set; }
    }

    public class StatsDto
    {
        [JsonPropertyName("life")]
        public int Life { get; set; }

        [JsonPropertyName("max_life")]
        public int MaxLife { get; set; }

        [JsonPropertyName("mana")]
        public int Mana { get; set; }

        [JsonPropertyName("max_mana")]
        public int MaxMana { get; set; }

        [JsonPropertyName("defense")]
        public int Defense { get; set; }
    }

    public class WorldDto
    {
        [JsonPropertyName("hardmode")]
        public bool Hardmode { get; set; }

        [JsonPropertyName("downed_bosses")]
        public List<string> DownedBosses { get; set; } = new();

        // Non-nullable on the backend (default "forest").
        [JsonPropertyName("biome")]
        public string Biome { get; set; } = "forest";
    }

    public class StatePayloadDto
    {
        [JsonPropertyName("game_version")]
        public string GameVersion { get; set; } = "1.4.4.9";

        [JsonPropertyName("gear")]
        public GearDto Gear { get; set; } = new();

        [JsonPropertyName("inventory")]
        public List<ItemRefDto> Inventory { get; set; } = new();

        [JsonPropertyName("stats")]
        public StatsDto Stats { get; set; } = new();

        [JsonPropertyName("world")]
        public WorldDto World { get; set; } = new();
    }
}
