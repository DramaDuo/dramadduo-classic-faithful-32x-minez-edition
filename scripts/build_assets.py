"""Build assets/ from proposed_textures/ (textures) + archived_assets/ (the previous wiring).

Run from the repo root after generate_proposed_textures.py:
    python scripts/build_assets.py

What it does
  * assets/ is deleted and rebuilt (it refuses to run unless archived_assets/ exists, so the originals are never lost).
  * Textures come only from proposed_textures/ (generated + copied-unchanged files).
  * Existing wiring (items/*.json, models, optifine/cit rules) is copied from archived_assets/ and extended:
      - name-matched items get a CIT rule (optifine/cit/<name>/, pattern on custom_name, colour-insensitive)
        AND an items/*.json case with the formatting guessed from the nearest existing item of the same kind;
      - enchantment-matched items (Smite/Knockback swords, Spire and Pristine/Studded armour, Fortune tools,
        Lure rods, Punch/Infinity bows) get an items/*.json `select` on the enchantments component, and for
        armour a CIT armor rule with enchantments= / enchantmentLevels= for the worn layer;
      - bows are wired only through items/bow.json: the installed CIT fork cannot override the pulling states;
      - every name-matched case/rule also gets a custom_model_data twin: MineZ stamps named items with
        minecraft:custom_model_data {strings:["minez:<id>"]} (see cmd_id for how <id> is derived from the name).
        items/*.json get an outer select on that string with the old name select kept as fallback; every CIT folder
        gets a <rule>_cmd.properties next to the name rule (archived rules included);
      - leather (two-layer) icons use CIT model= instead of texture=: texture= only rewrites layer0 and the overlay
        layer then trips "Multiple atlases" (the hand fix of 2026-09-03, now generated).
  * CIT textures are copied next to their .properties (CIT paths are relative), so those PNGs exist twice.
  * archived_assets/minecraft/textures/entity/equipment/humanoid/*.png are not carried over: nothing references
    them (no assets/minecraft/equipment/*.json); the worn layers live in the CIT folders.

Verify in-game before trusting a new item (see the memory notes on probe ladders): exact names / bold / colour of
the items/*.json cases are guesses; the CIT rules do not depend on colour but do depend on the item carrying
`custom_name` (swords and tools also get an `item_name` variant because this pack matches swords on item_name).
"""
import copy, glob, json, os, re, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
P = os.path.join(REPO, "proposed_textures")
A = os.path.join(REPO, "archived_assets", "minecraft")
OUT = os.path.join(REPO, "assets", "minecraft")

NOTES = []   # things to verify in-game

# ---------------------------------------------------------------- helpers
def ensure(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
def cp(src, dst):
    ensure(dst); shutil.copyfile(src, dst)
def write_json(rel, obj):
    p = os.path.join(OUT, rel); ensure(p)
    with open(p, "w", encoding="utf-8") as f: json.dump(obj, f, indent=2); f.write("\n")
def read_json(rel):
    with open(os.path.join(A, rel), encoding="utf-8") as f: return json.load(f)
def write_props(rel, lines):
    p = os.path.join(OUT, rel); ensure(p)
    with open(p, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")

def model(rel, texture, parent="item/generated"):
    if os.path.exists(os.path.join(OUT, "models", "item", f"{rel}.json")): return   # keep the archived model byte-identical
    write_json(f"models/item/{rel}.json", {"parent": parent, "textures": {"layer0": f"item/{texture}"}})
def m(model_path):
    return {"type": "model", "model": f"item/{model_path}"}
def select(component, cases, fallback):
    return {"type": "select", "property": "component", "component": component, "cases": cases, "fallback": fallback}
def case(when, model_obj):
    return {"when": when, "model": model_obj}
def when_custom(name, color=None):
    w = {"italic": False, "text": name, "bold": True}
    if color: w["color"] = color
    return w
def when_item(name):
    return {"text": name, "bold": True}
def ench(d):
    return {f"minecraft:{k}": v for k, v in d.items()}
def pat(name):
    """CIT pattern: leading wildcard (MineZ names can carry prefixes), apostrophes wildcarded (' vs ’)."""
    return "*" + name.replace("'", "*")

# custom_model_data ids: MineZ stamps named items with minecraft:custom_model_data {strings:["minez:<id>"]} where <id> is
# the display name lower-cased, apostrophes dropped, runs of other non-alphanumerics -> "_" ("Pluvia's Rain" ->
# minez:pluvias_rain). Verified in-game for Pluvia's Rain only (2026-09-18) and consistent with legendary_id=support_kit;
# every other id below is derived by that rule, so put confirmed exceptions in CMD_ID_OVERRIDES (display name -> id).
CMD_ID_OVERRIDES = {}
def cmd_id(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "").replace("’", "")).strip("_")
    return "minez:" + CMD_ID_OVERRIDES.get(name, s)
def cmd_conds(name):
    return [f"components.minecraft:custom_model_data.strings.0={cmd_id(name)}"]
def select_cmd(cases, fallback):
    return {"type": "select", "property": "minecraft:custom_model_data", "index": 0, "cases": cases, "fallback": fallback}

def cit_item(folder, fname, match_items, tex_src, conds, weight=100, use_model=False):
    cp(tex_src, os.path.join(OUT, "optifine", "cit", folder, f"{fname}.png"))
    if use_model:   # two-layer vanilla models (leather armour, potions): texture= leaves the overlay on the items atlas
        write_json(f"optifine/cit/{folder}/{fname}.json", {"parent": "minecraft:item/generated", "textures": {"layer0": fname}})
    write_props(f"optifine/cit/{folder}/{fname}.properties",
                ["type=item", f"matchItems={match_items}", f"{'model' if use_model else 'texture'}={fname}", f"weight={weight}"] + conds)

def cit_armor(folder, fname, match_items, layer_src, layer_key, conds, weight=100):
    lname = os.path.basename(layer_src)[:-4]
    cp(layer_src, os.path.join(OUT, "optifine", "cit", folder, f"{lname}.png"))
    keys = layer_key if isinstance(layer_key, list) else [layer_key]
    write_props(f"optifine/cit/{folder}/{fname}.properties",
                ["type=armor", f"matchItems={match_items}"] + [f"texture.{k}={lname}" for k in keys] + [f"weight={weight}"] + conds)

def name_conds(name, component="custom_name"):
    return [f"components.minecraft:{component}=pattern:{pat(name)}"]
def ench_conds(d):
    """One enchantment: CIT's enchantments= / enchantmentLevels= pair. Several: those two are whitespace-split OR lists
    (any listed id, any listed level - "4,1" is a parse error and "4 1" would also match a lone Smite I), so "all of
    these" needs one components. path per id. The 26.2 enchantments component encodes as a flat {id: level} map."""
    if len(d) == 1:
        (k, v), = d.items(); return [f"enchantments=minecraft:{k}", f"enchantmentLevels={v}"]
    return [f"components.minecraft:enchantments.minecraft:{k}={v}" for k, v in d.items()]

# ---------------------------------------------------------------- specs
SWORDS_NAMED = [  # (file, display name, base item)
    ("corsairs_edge", "Corsair's Edge", "iron_sword"), ("forsakens_blade", "Forsaken's Blade", "iron_sword"),
    ("muramasa", "Muramasa", "iron_sword"), ("nights_shadow", "Night's Shadow", "iron_sword"),
    ("phantom_blade", "Phantom Blade", "iron_sword"), ("vampyr", "Vampyr", "iron_sword"),
    ("rusted_iron_sword", "Rusted Iron Sword", "iron_sword"),
    ("endeavour", "Endeavour", "stone_sword"), ("gamble", "Gamble", "stone_sword"),
    ("kikuichimonji", "Kikuichimonji", "wooden_sword"), ("robbers_blade", "Robber's Blade", "wooden_sword"),
    ("helm_splitter", "Helm Splitter", "diamond_sword"), ("overkill", "Overkill", "diamond_sword"), ("peace", "Peace", "diamond_sword"),
    ("flail", "Flail", "golden_sword"), ("ipses_folly", "Ipse's Folly", "golden_sword"),
]
SWORDS_ENCH = {   # Smite I-V on iron swords only (metal crossguard ladder), each with and without Knockback I
    "iron_sword": [({"smite": l}, f"smite{l}_iron") for l in range(1, 6)] +
                  [({"smite": l, "knockback": 1}, f"smite{l}_knockback1_iron") for l in range(1, 6)],
    "stone_sword": [], "diamond_sword": [], "wooden_sword": [], "golden_sword": [],
}
BOWS_NAMED = [("binding_bow", "Binding Bow"), ("blunderbuss", "Blunderbuss"), ("grapeshot", "Grapeshot"), ("quiet", "Quiet"),
              ("rocksteady", "Rocksteady"), ("shotbow", "Shotbow"), ("spike_thrower", "Spike Thrower"), ("stomper", "Stomper"),
              ("truth_bow", "Truth Bow"), ("venom_bow", "Venom Bow"), ("web_shot", "Web Shot")]
BOWS_ENCH = [({"punch": 1}, "punch_1"), ({"punch": 1, "infinity": 1}, "punch_1_inf"), ({"power": 1, "infinity": 1}, "power_1_inf")]

# (file, display name, kind, material, layer file or None)
ARMOR_NAMED = [
    ("binding_helmet", "Binding Helmet", "helmet", "iron", "binding_helmet_layer_1"),
    ("gorgons_gaze", "Gorgon's Gaze", "helmet", "iron", "gorgons_gaze_layer_1"),
    ("gorgons_gaze_legacy", "Gorgon's Gaze", "helmet", "chainmail", "gorgons_gaze_legacy_layer_1"),
    ("miners_lamp", "Miner's Lamp", "helmet", "iron", None),
    ("frost_walker", "Frost Walker", "boots", "iron", "frost_walker_layer_1"),
    ("ninja_sandals", "Ninja Sandals", "boots", "chainmail", "ninja_sandals_layer_1"),
    ("rimeguard", "RimeGuard", "chestplate", "iron", "rimeguard_layer_1"),
    ("penguin_feet", "Penguin Feet", "boots", "iron", "penguin_feet_layer_1"),
    ("chimney_sweep", "Chimney Sweep", "leggings", "iron", "chimney_sweep_layer_2"),
]
# the official pack matches Penguin Feet on every boot material; the CIT rules do the same, the items/*.json case is iron only
MULTI_MATERIAL = {"penguin_feet": ("minecraft:iron_boots minecraft:golden_boots minecraft:leather_boots minecraft:chainmail_boots minecraft:diamond_boots",
                                   ["iron_layer_1", "gold_layer_1", "leather_layer_1", "chainmail_layer_1", "diamond_layer_1"])}
RUSTED = [("rusted_helmet", "helmet", "rusted_iron_layer_1"), ("rusted_chestplate", "chestplate", "rusted_iron_layer_1"),
          ("rusted_leggings", "leggings", "rusted_iron_layer_2"), ("rusted_boots", "boots", "rusted_iron_layer_1")]
# (file, kind, material, enchantments, layer file)
ARMOR_ENCH = [
    ("fire_protection_chestplate", "chestplate", "iron", {"fire_protection": 4}, "fire_protection_chestplate_layer_1"),
    ("respiration_helmet", "helmet", "iron", {"respiration": 1}, "respiration_helmet_layer_1"),
    ("projectile_protection_helmet", "helmet", "iron", {"projectile_protection": 1}, "projectile_protection_layer_1"),
    ("projectile_protection_boots", "boots", "iron", {"projectile_protection": 1}, "projectile_protection_layer_1"),
    ("depth_strider_boots", "boots", "iron", {"depth_strider": 1}, "depth_strider_layer_1"),
    ("depth_strider_leggings", "leggings", "iron", {"depth_strider": 1}, "depth_strider_layer_2"),
    ("feather_falling_boots", "boots", "iron", {"feather_falling": 4}, "feather_falling_boots_layer_1"),
] + [(f"pristine_chain_{k}", k, "chainmail", {"protection": 1}, "pristine_chain_layer_2" if k == "leggings" else "pristine_chain_layer_1")
     for k in ("helmet", "chestplate", "leggings", "boots")] \
  + [(f"studded_leather_{k}", k, "leather", {"protection": 1}, "studded_leather_layer_2" if k == "leggings" else "studded_leather_layer_1")
     for k in ("helmet", "chestplate", "leggings", "boots")]

POTIONS_NAMED = [  # (file, name, base item, json colour or None = CIT only)
    ("eillom_ale", "Eillom Ale", "potion", None), ("giants_brew", "Giant's Brew", "potion", None), ("green_beer", "Green Beer", "potion", None),
    ("manzana_cider", "Manzana Cider", "potion", "red"), ("witchs_brew", "Witch's Brew", "potion", "dark_purple"),
    ("cleansing_elixir", "Cleansing Elixir", "potion", "green"), ("frozen_marghoulita", "Frozen Mar'Ghoul'ita", "potion", "aqua"),
    ("acid_vial", "Acid Vial", "lingering_potion", None),
]
BOOKS_NEW = ["astrum_alpha", "astrum_wau", "astrum_beta", "astrum_theta"] + \
            [f"astra_{g}" for g in ("alpha", "wau", "beta", "theta", "mu", "omicron", "sigma", "phi", "gamma", "omega")]
def book_name(f):
    series, glyph = f.split("_", 1); return f"{series.capitalize()} {glyph.capitalize()}"

TOOLS_NAMED = [  # (file, name, base item, weight)
    ("earth_shaker", "Earth Shaker", "iron_axe", 100), ("rusted_earth_shaker", "Rusted Earth Shaker", "stone_axe", 110),
    ("deaths_scythe", "Death's Scythe", "iron_hoe", 100), ("crowbar", "Crowbar", "iron_hoe", 100), ("rusty_crowbar", "Rusty Crowbar", "iron_hoe", 110),
    ("blast_pickaxe", "Blast Pickaxe", "iron_pickaxe", 100), ("rusted_pickaxe", "Rusted Pickaxe", "iron_pickaxe", 100),
    ("weak_grapple", "Weak Grapple", "fishing_rod", 100), ("kindling", "Kindling", "stick", 100), ("rod_of_reclamation", "Rod of Reclamation", "stick", 100),
]
HANDHELD = {"iron_sword", "stone_sword", "wooden_sword", "diamond_sword", "golden_sword", "iron_axe", "stone_axe", "iron_hoe", "wooden_hoe",
            "iron_pickaxe", "iron_shovel", "stick"}
def parent_for(base):
    if base == "fishing_rod": return "item/handheld_rod"
    return "item/handheld" if base in HANDHELD else "item/generated"

# ---------------------------------------------------------------- build
def copy_textures():
    tex = os.path.join(OUT, "textures")
    for f in glob.glob(os.path.join(P, "swords", "*.png")): cp(f, os.path.join(tex, "item", "swords", os.path.basename(f)))
    for d in glob.glob(os.path.join(P, "bows", "*")):
        for f in glob.glob(os.path.join(d, "*.png")): cp(f, os.path.join(tex, "item", "bows", os.path.basename(d), os.path.basename(f)))
    for kind in ("chestplates", "helmets", "boots", "leggings"):
        for f in glob.glob(os.path.join(P, "armor", kind, "*.png")): cp(f, os.path.join(tex, "item", kind, os.path.basename(f)))
    for kind in ("potions", "books", "tools"):
        for f in glob.glob(os.path.join(P, kind, "*.png")): cp(f, os.path.join(tex, "item", kind, os.path.basename(f)))
    for f in glob.glob(os.path.join(P, "misc", "*.png")): cp(f, os.path.join(tex, "item", "misc", os.path.basename(f)))
    for f in glob.glob(os.path.join(P, "misc", "grass_blocks", "*.png")): cp(f, os.path.join(tex, "item", "grass_blocks", os.path.basename(f)))
    for f in glob.glob(os.path.join(P, "other", "block", "*.png")): cp(f, os.path.join(tex, "block", os.path.basename(f)))
    for f in glob.glob(os.path.join(P, "other", "entity", "chest", "*.png")): cp(f, os.path.join(tex, "entity", "chest", os.path.basename(f)))
    for f in glob.glob(os.path.join(P, "other", "gui", "hud", "heart", "*.png")): cp(f, os.path.join(tex, "gui", "sprites", "hud", "heart", os.path.basename(f)))

def copy_archived_wiring():
    for f in glob.glob(os.path.join(A, "items", "*.json")): cp(f, os.path.join(OUT, "items", os.path.basename(f)))
    for root, _, files in os.walk(os.path.join(A, "models")):
        for f in files: cp(os.path.join(root, f), os.path.join(OUT, "models", os.path.relpath(os.path.join(root, f), os.path.join(A, "models"))))
    for root, _, files in os.walk(os.path.join(A, "optifine")):
        for f in files: cp(os.path.join(root, f), os.path.join(OUT, "optifine", os.path.relpath(os.path.join(root, f), os.path.join(A, "optifine"))))
    # refresh the PNGs inside the archived CIT folders from proposed_textures
    for n in ("agnis_wrath", "dentrils_terror", "pluvias_tempest", "simoons_sonata", "therums_force", "rubber_shield"):
        cp(os.path.join(P, "armor", "chestplates", f"{n}.png"), os.path.join(OUT, "optifine", "cit", n, f"{n}.png"))
        cp(os.path.join(P, "armor", "layers", f"{n}_layer_1.png"), os.path.join(OUT, "optifine", "cit", n, f"{n}_layer_1.png"))
    for f in glob.glob(os.path.join(P, "misc", "support_kit", "*.png")): cp(f, os.path.join(OUT, "optifine", "cit", "support_kit", os.path.basename(f)))

def build_models():
    for f in glob.glob(os.path.join(P, "swords", "*.png")): model(f"swords/{os.path.basename(f)[:-4]}", f"swords/{os.path.basename(f)[:-4]}", "item/handheld")
    for d in glob.glob(os.path.join(P, "bows", "*")):
        b = os.path.basename(d)
        for fr in ("bow", "bow_pulling_0", "bow_pulling_1", "bow_pulling_2"): model(f"bows/{b}/{fr}", f"bows/{b}/{fr}", "item/bow")
    for kind in ("chestplates", "helmets", "boots", "leggings"):
        for f in glob.glob(os.path.join(P, "armor", kind, "*.png")): model(f"{kind}/{os.path.basename(f)[:-4]}", f"{kind}/{os.path.basename(f)[:-4]}")
    for kind in ("potions", "books"):
        for f in glob.glob(os.path.join(P, kind, "*.png")): model(f"{kind}/{os.path.basename(f)[:-4]}", f"{kind}/{os.path.basename(f)[:-4]}")
    tool_base = {t[0]: t[2] for t in TOOLS_NAMED}
    tool_base.update({"fortune1_wooden_hoe": "wooden_hoe", "fortune2_wooden_hoe": "wooden_hoe", "fortune1_iron_shovel": "iron_shovel",
                      "fortune2_iron_shovel": "iron_shovel", "lure1_fishing_rod": "fishing_rod", "lure2_fishing_rod": "fishing_rod"})
    for f in glob.glob(os.path.join(P, "tools", "*.png")):
        n = os.path.basename(f)[:-4]; model(f"tools/{n}", f"tools/{n}", parent_for(tool_base.get(n, "")))
    model("misc/mummys_cloth", "misc/mummys_cloth")

def bow_case_model(folder):
    """Same condition/range_dispatch shape the existing bow.json cases use."""
    return {"type": "minecraft:condition", "property": "minecraft:using_item",
            "on_false": {"type": "minecraft:model", "model": f"minecraft:item/bows/{folder}/bow"},
            "on_true": {"type": "minecraft:range_dispatch", "property": "minecraft:use_duration", "scale": 0.05,
                        "fallback": {"type": "minecraft:model", "model": f"minecraft:item/bows/{folder}/bow_pulling_0"},
                        "entries": [{"model": {"type": "minecraft:model", "model": f"minecraft:item/bows/{folder}/bow_pulling_1"}, "threshold": 0.65},
                                    {"model": {"type": "minecraft:model", "model": f"minecraft:item/bows/{folder}/bow_pulling_2"}, "threshold": 0.9}]}}

def build_swords():
    by_base = {}
    for f, name, base in SWORDS_NAMED:
        by_base.setdefault(base, []).append((f, name))
        cit_item(f, f, f"minecraft:{base}", os.path.join(P, "swords", f"{f}.png"), name_conds(name), 100)
        cit_item(f, f"{f}_item_name", f"minecraft:{base}", os.path.join(P, "swords", f"{f}.png"), name_conds(name, "item_name"), 100)
    for base, enchs in SWORDS_ENCH.items():
        for d, f in enchs:
            # the Smite-only rule also matches a Smite + Knockback sword, so the more specific rule has to outweigh it
            cit_item(f, f, f"minecraft:{base}", os.path.join(P, "swords", f"{f}.png"), ench_conds(d), 9 + len(d))
    # items json: iron_sword.json exists (item_name cases); others are new
    for base in ("iron_sword", "stone_sword", "wooden_sword", "diamond_sword", "golden_sword"):
        ench_sel = select("enchantments", [case(ench(d), m(f"swords/{f}")) for d, f in SWORDS_ENCH[base]], {"type": "model", "model": f"minecraft:item/{base}"}) \
            if SWORDS_ENCH[base] else {"type": "model", "model": f"minecraft:item/{base}"}
        new_cases = [case(when_item(name), m(f"swords/{f}")) for f, name in by_base.get(base, [])]
        if base == "iron_sword":
            j = read_json("items/iron_sword.json"); j["model"]["cases"] += new_cases; j["model"]["fallback"] = ench_sel
        else:
            j = {"model": select("item_name", new_cases, ench_sel)}
        write_json(f"items/{base}.json", j)
    NOTES.append("Swords: items/*.json cases use item_name {text, bold} like Lone Sword; CIT rules exist on both custom_name and item_name.")

def build_bows():
    j = read_json("items/bow.json")
    for f, name in BOWS_NAMED:
        j["model"]["cases"].append(case(when_custom(name), bow_case_model(f)))
        j["model"]["cases"].append(case(when_custom(name, "white"), bow_case_model(f)))
    for d, f in BOWS_ENCH:
        j["model"]["fallback"]["cases"].append(case(ench(d), bow_case_model(f)))
    write_json("items/bow.json", j)
    NOTES.append("Bows: wired only in items/bow.json (CIT fork has no pulling-state overrides); each new bow has two guessed name cases (no colour / white).")

def armor_item(kind):
    return {"helmet": "helmet", "chestplate": "chestplate", "leggings": "leggings", "boots": "boots"}[kind]
def layer_key(material, layer_file):
    return f"{material}_layer_{'2' if layer_file.endswith('_2') else '1'}"

def build_armor():
    icons = {}   # (material, kind) -> list of cases
    enchs = {}   # (material, kind) -> list of cases
    kind_dir = {"helmet": "helmets", "chestplate": "chestplates", "leggings": "leggings", "boots": "boots"}
    for f, name, kind, mat, lay in ARMOR_NAMED:
        item = f"minecraft:{mat}_{armor_item(kind)}"
        match, keys = MULTI_MATERIAL.get(f, (item, layer_key(mat, lay) if lay else None))
        cit_item(f, f"{f}_item", match, os.path.join(P, "armor", kind_dir[kind], f"{f}.png"), name_conds(name), 100)
        if lay: cit_armor(f, f"{f}_armor", match, os.path.join(P, "armor", "layers", f"{lay}.png"), keys, name_conds(name), 100)
        icons.setdefault((mat, kind), []).append(case(when_custom(name), m(f"{kind_dir[kind]}/{f}")))
    for f, kind, lay in RUSTED:
        item = f"minecraft:iron_{armor_item(kind)}"
        cit_item(f, f"{f}_item", item, os.path.join(P, "armor", kind_dir[kind], f"{f}.png"), ["components.minecraft:custom_name=pattern:Rusted*"], 90)
        cit_armor(f, f"{f}_armor", item, os.path.join(P, "armor", "layers", f"{lay}.png"), layer_key("iron", lay), ["components.minecraft:custom_name=pattern:Rusted*"], 90)
    for f, kind, mat, d, lay in ARMOR_ENCH:
        item = f"minecraft:{mat}_{armor_item(kind)}"
        cit_item(f, f"{f}_item", item, os.path.join(P, "armor", kind_dir[kind], f"{f}.png"), ench_conds(d), 10, use_model=(mat == "leather"))
        cit_armor(f, f"{f}_armor", item, os.path.join(P, "armor", "layers", f"{lay}.png"), layer_key(mat, lay), ench_conds(d), 10)
        enchs.setdefault((mat, kind), []).append(case(ench(d), m(f"{kind_dir[kind]}/{f}")))
    for mat in ("iron", "chainmail", "leather"):
        for kind in ("helmet", "chestplate", "leggings", "boots"):
            base = f"{mat}_{armor_item(kind)}"
            if mat == "leather":
                vanilla = {"type": "model", "model": f"minecraft:item/{base}", "tints": [{"type": "minecraft:dye", "default": -6265536}]}
            else:
                vanilla = {"type": "model", "model": f"minecraft:item/{base}"}
            ench_sel = select("enchantments", enchs[(mat, kind)], vanilla) if (mat, kind) in enchs else vanilla
            named = icons.get((mat, kind), [])
            if base == "iron_chestplate":
                j = read_json("items/iron_chestplate.json"); j["model"]["cases"] += named; j["model"]["fallback"] = ench_sel
            elif named or (mat, kind) in enchs:
                j = {"model": select("custom_name", named, ench_sel)} if named else {"model": ench_sel}
            else:
                continue
            write_json(f"items/{base}.json", j)
    NOTES.append("Armour: name cases use custom_name {italic:false, text, bold} like Rubber Shield; enchant matches are exact (an extra enchant on the piece breaks the items/*.json match, the CIT rule still matches).")
    NOTES.append("Rusted armour set: CIT only (pattern 'Rusted*'); RimeGuard assumed iron chestplate.")

def build_potions():
    j = read_json("items/potion.json")
    known = {name: f for f, name, base, color in POTIONS_NAMED if color and base == "potion"}
    for c in j["model"]["cases"]:
        t = c["when"].get("text")
        if t in known: c["model"] = m(f"potions/{known[t]}")
    write_json("items/potion.json", j)
    for f, name, base, color in POTIONS_NAMED:
        cit_item(f, f, f"minecraft:{base}", os.path.join(P, "potions", f"{f}.png"), name_conds(name), 100)
    NOTES.append("Potions: Eillom Ale, Giant's Brew, Green Beer, Acid Vial are CIT-only (name colour unknown); the four Halloween/utility drinks now use baked models instead of tints.")

def build_books():
    j = read_json("items/book.json")
    for f in BOOKS_NEW:
        name = book_name(f)
        j["model"]["cases"].append(case(when_custom(name, "aqua"), m(f"books/{f}")))
        cit_item(f, f, "minecraft:book", os.path.join(P, "books", f"{f}.png"), name_conds(name), 100)
    write_json("items/book.json", j)
    NOTES.append("Books: Astra cases copy the Astrum formatting (bold aqua); confirm the Astra colour in-game.")

def build_tools():
    for f, name, base, w in TOOLS_NAMED:
        cit_item(f, f, f"minecraft:{base}", os.path.join(P, "tools", f"{f}.png"), name_conds(name), w)
        cit_item(f, f"{f}_item_name", f"minecraft:{base}", os.path.join(P, "tools", f"{f}.png"), name_conds(name, "item_name"), w)
    cit_item("mummys_cloth", "mummys_cloth", "minecraft:paper", os.path.join(P, "misc", "mummys_cloth.png"), name_conds("Mummy's Cloth"), 100)
    # fortune tools: json + cit
    for base, files in (("iron_shovel", ("fortune1_iron_shovel", "fortune2_iron_shovel")), ("wooden_hoe", ("fortune1_wooden_hoe", "fortune2_wooden_hoe"))):
        cases = []
        for lvl, f in enumerate(files, 1):
            cases.append(case(ench({"fortune": lvl}), m(f"tools/{f}")))
            cit_item(f, f, f"minecraft:{base}", os.path.join(P, "tools", f"{f}.png"), ench_conds({"fortune": lvl}), 10)
        write_json(f"items/{base}.json", {"model": select("enchantments", cases, {"type": "model", "model": f"minecraft:item/{base}"})})
    # lure rods: json only (keeps the cast state)
    def rod(model_path):
        return {"type": "condition", "property": "fishing_rod/cast", "on_false": model_path, "on_true": {"type": "model", "model": "minecraft:item/fishing_rod_cast"}}
    cases = [case(ench({"lure": lvl}), rod(m(f"tools/lure{lvl}_fishing_rod"))) for lvl in (1, 2)]
    write_json("items/fishing_rod.json", {"model": select("enchantments", cases, rod({"type": "model", "model": "minecraft:item/fishing_rod"}))})
    NOTES.append("Tools: CIT on custom_name and item_name; Fortune tools also in items/*.json; Lure rods items/*.json only (cast state kept, cast texture stays Faithful).")

def add_cmd_layer_items():
    """items/*.json whose top-level select is on custom_name/item_name: wrap it in a select on custom_model_data string 0,
    one case per distinct derived id pointing at the same model, the name select kept as the fallback."""
    n = 0
    for f in glob.glob(os.path.join(OUT, "items", "*.json")):
        with open(f, encoding="utf-8") as fh: j = json.load(fh)
        m = j["model"]
        if m.get("type") != "select" or m.get("property") != "component" or m.get("component") not in ("custom_name", "item_name"): continue
        cases, seen = [], set()
        for c in m["cases"]:
            for w in (c["when"] if isinstance(c["when"], list) else [c["when"]]):
                i = cmd_id(w["text"])
                if i not in seen: seen.add(i); cases.append(case(i, c["model"]))
        j["model"] = select_cmd(cases, m)
        write_json(os.path.relpath(f, OUT), j); n += len(cases)
    return n

def add_cmd_layer_cit():
    """Every CIT rule whose only condition is a full-name pattern on custom_name (archived rules included) gets a sibling
    <stem>_cmd.properties with that condition swapped for the custom_model_data id. *_item_name twins are skipped (their
    custom_name twin already produced the _cmd file); prefix patterns like 'Rusted*' name no single item."""
    n = 0
    for p in sorted(glob.glob(os.path.join(OUT, "optifine", "cit", "*", "*.properties"))):
        stem = os.path.basename(p)[:-len(".properties")]
        if stem.endswith("_item_name") or stem.endswith("_cmd"): continue
        with open(p, encoding="utf-8") as fh: lines = fh.read().splitlines()
        conds = [l for l in lines if l.startswith(("components.", "enchantment", "nbt."))]
        if len(conds) != 1 or not conds[0].startswith("components.minecraft:custom_name=pattern:*"): continue
        pattern = conds[0].split("pattern:", 1)[1]
        if pattern.endswith("*"): continue
        name = pattern.lstrip("*").replace("*", "")   # pat() turned apostrophes into *; cmd_id drops apostrophes anyway
        write_props(f"optifine/cit/{os.path.basename(os.path.dirname(p))}/{stem}_cmd.properties",
                    [cmd_conds(name)[0] if l == conds[0] else l for l in lines]); n += 1
    return n

def validate():
    n = 0
    for root, _, files in os.walk(OUT):
        for f in files:
            if f.endswith(".json"):
                with open(os.path.join(root, f), encoding="utf-8") as fh: json.load(fh)
                n += 1
    pngs = sum(1 for r, _, fs in os.walk(OUT) for f in fs if f.endswith(".png"))
    props = sum(1 for r, _, fs in os.walk(OUT) for f in fs if f.endswith(".properties"))
    return n, pngs, props

def main():
    if not os.path.isdir(A): raise SystemExit("archived_assets/minecraft not found: move the current assets/ to archived_assets/ first.")
    if not os.path.isdir(P): raise SystemExit("proposed_textures/ not found: run scripts/generate_proposed_textures.py first.")
    if os.path.isdir(os.path.join(REPO, "assets")): shutil.rmtree(os.path.join(REPO, "assets"))
    copy_archived_wiring(); copy_textures(); build_models()
    build_swords(); build_bows(); build_armor(); build_potions(); build_books(); build_tools()
    n_cases = add_cmd_layer_items(); n_rules = add_cmd_layer_cit()
    NOTES.append(f"custom_model_data: {n_cases} items/*.json cases and {n_rules} CIT rules use ids derived from the display name; "
                 "only minez:pluvias_rain is confirmed, record any other id that differs in CMD_ID_OVERRIDES.")
    n, pngs, props = validate()
    print(f"assets/ rebuilt: {n} json, {pngs} png, {props} cit rules")
    print("\nVerify in-game:")
    for x in NOTES: print(" -", x)

if __name__ == "__main__":
    main()
