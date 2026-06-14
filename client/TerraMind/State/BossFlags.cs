using System.Collections.Generic;
using Terraria;

namespace TerraMind.State
{
    // NPC.downed* flags → canonical boss-name strings. The names must normalise
    // (lower + strip spaces/'-'/apostrophes) to the tokens the backend's
    // progression logic checks — verified against app/agent/tools.py::_normalize
    // (e.g. "Eye of Cthulhu" → "eyeofcthulhu").
    //
    // CONFIRM-IN-GAME: every NPC.downed* / WorldGen field below is "believed
    // correct" — I cannot compile here. A wrong static-field name is a COMPILER
    // ERROR isolated to this file (one-line fix from the build output). The
    // extended set's names are more obscure than the core set → likeliest to be
    // wrong; if the extended block fails to compile, that block can be trimmed
    // without touching the core progression set.
    public static class BossFlags
    {
        public static List<string> Read()
        {
            var downed = new List<string>();

            // ── Core progression set (drives suggest_next_boss / _progression_stage) ──
            if (NPC.downedBoss1) downed.Add("Eye of Cthulhu");
            // downedBoss2 is shared by both world-evil bosses; the world's evil
            // type disambiguates (crimson world → Brain, else → Eater).
            if (NPC.downedBoss2)
                downed.Add(WorldGen.crimson ? "Brain of Cthulhu" : "Eater of Worlds");
            if (NPC.downedBoss3) downed.Add("Skeletron");
            if (Main.hardMode) downed.Add("Wall of Flesh"); // hardmode ⇒ WoF beaten
            if (NPC.downedMechBoss1) downed.Add("The Destroyer");
            if (NPC.downedMechBoss2) downed.Add("The Twins");
            if (NPC.downedMechBoss3) downed.Add("Skeletron Prime");
            if (NPC.downedPlantBoss) downed.Add("Plantera");
            if (NPC.downedGolemBoss) downed.Add("Golem");
            if (NPC.downedAncientCultist) downed.Add("Lunatic Cultist");
            if (NPC.downedMoonlord) downed.Add("Moon Lord");

            // ── Extended informational set (obscurer flag names — confirm first) ──
            if (NPC.downedQueenBee) downed.Add("Queen Bee");
            if (NPC.downedSlimeKing) downed.Add("King Slime");
            if (NPC.downedFishron) downed.Add("Duke Fishron");
            if (NPC.downedQueenSlime) downed.Add("Queen Slime");
            if (NPC.downedEmpressOfLight) downed.Add("Empress of Light");
            if (NPC.downedDeerclops) downed.Add("Deerclops");

            return downed;
        }
    }
}
