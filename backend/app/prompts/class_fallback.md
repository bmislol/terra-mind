Given a Terraria player's equipped gear and inventory, infer their combat class. Respond with exactly one word: melee, ranger, mage, summoner, or unknown.

Base the inference on weapon damage type, armor set bonuses, and accessories:
- Swords, spears, yoyos, and melee armor (Molten, Shadow, Crimson) → melee
- Guns, bows, and ranger armor (Fossil, Necro, Shroomite) → ranger
- Spell tomes, staves, magic guns, and mage armor (Meteor, Jungle, Spectre) → mage
- Summon staves, whips, and summoner armor (Bee, Spider, Tiki) → summoner

If the gear is mixed across classes with no clear lean, or the player has only starter/no equipment, respond unknown. Do not explain — output only the single class word.

Examples:
- Armor: Fossil Helmet, Fossil Plate, Fossil Greaves; Weapon: Megashark → ranger
- Armor: Spectre Hood, Spectre Robe; Weapon: Razorblade Typhoon → mage
- Armor: (none); Weapon: Copper Shortsword; Inventory: Dirt Block → unknown
