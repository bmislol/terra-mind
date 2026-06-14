using System.Collections.Generic;
using Terraria;
using Terraria.Localization;

namespace TerraMind.State
{
    // Reads live character + world state into a StatePayloadDto. Every
    // Main.LocalPlayer / Item / Player.Zone* access below is "believed correct"
    // but UNVERIFIED here (no compiler/runtime) — a wrong field name is a
    // compiler error isolated to this file. Scrutinise the logged JSON in-game
    // (see RUNBOOK §10) against the real character.
    public static class StateReader
    {
        private const string GameVersion = "1.4.4.9"; // D-016

        // Player.armor layout: [0..2] head/body/legs armor, [3..9] accessory
        // slots, [10..19] vanity/social (ignored).
        private const int ArmorFrom = 0;
        private const int ArmorTo = 2;
        private const int AccessoryFrom = 3;
        private const int AccessoryTo = 9;
        private const int InventoryMainTo = 49; // [0..49] main inventory; 50+ coins/ammo

        public static StatePayloadDto Read()
        {
            Player p = Main.LocalPlayer;

            var inventory = new List<ItemRefDto>();
            for (int i = 0; i <= InventoryMainTo && i < p.inventory.Length; i++)
            {
                Item it = p.inventory[i];
                if (it != null && !it.IsAir)
                    inventory.Add(ToRef(it));
            }

            return new StatePayloadDto
            {
                GameVersion = GameVersion,
                Gear = new GearDto
                {
                    Armor = ReadSlots(p.armor, ArmorFrom, ArmorTo),
                    Accessories = ReadSlots(p.armor, AccessoryFrom, AccessoryTo),
                    Weapon = p.HeldItem != null && !p.HeldItem.IsAir
                        ? ToRef(p.HeldItem)
                        : null,
                },
                Inventory = inventory,
                Stats = new StatsDto
                {
                    Life = p.statLife,
                    MaxLife = p.statLifeMax2,   // effective max (crystals/fruit/buffs)
                    Mana = p.statMana,
                    MaxMana = p.statManaMax2,
                    Defense = p.statDefense,
                },
                World = new WorldDto
                {
                    Hardmode = Main.hardMode,
                    DownedBosses = BossFlags.Read(),
                    Biome = ReadBiome(p),
                },
            };
        }

        private static List<ItemRefDto> ReadSlots(Item[] slots, int from, int to)
        {
            var result = new List<ItemRefDto>();
            for (int i = from; i <= to && i < slots.Length; i++)
            {
                Item it = slots[i];
                if (it != null && !it.IsAir)
                    result.Add(ToRef(it));
            }
            return result;
        }

        private static ItemRefDto ToRef(Item it) => new ItemRefDto
        {
            ItemId = it.type,             // == Cargo Items.itemid (D-026 class detection)
            Name = it.Name ?? "",         // non-nullable on the backend
            Prefix = it.prefix > 0 ? Lang.prefix[it.prefix]?.Value : null,
            Stack = it.stack,
        };

        // Best-effort current biome (informational; backend default "forest").
        private static string ReadBiome(Player p)
        {
            if (p.ZoneUnderworldHeight) return "underworld";
            if (p.ZoneDungeon) return "dungeon";
            if (p.ZoneCorrupt) return "corruption";
            if (p.ZoneCrimson) return "crimson";
            if (p.ZoneHallow) return "hallow";
            if (p.ZoneJungle) return "jungle";
            if (p.ZoneSnow) return "snow";
            if (p.ZoneDesert) return "desert";
            if (p.ZoneBeach) return "ocean";
            return "forest";
        }
    }
}
