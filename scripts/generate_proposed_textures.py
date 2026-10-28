"""Generate the proposed MineZ item textures by recolouring Classic Faithful 32x base textures region by region.

Every output keeps Faithful's silhouette and shading: a blade, limb, cover or liquid region is mapped
by luminance onto a target colour, the same transfer this pack's existing recolours use.

Usage (from the repo root):
    python scripts/generate_proposed_textures.py
    python scripts/generate_proposed_textures.py --faithful "../CF32PA-2026r19.zip" --out proposed_textures

--faithful  the Classic Faithful 32x pack, as a .zip or an extracted folder.
            Default: the newest CF32PA-*.zip in the parent folder of this repo (the resourcepacks folder).
--out       output folder. Default: <repo>/proposed_textures (it is deleted and rebuilt).

Requires Pillow (pip install pillow).
"""
from PIL import Image, ImageDraw
import argparse, colorsys, glob, io, os, shutil, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# existing pack textures: the archived originals once assets/ has been rebuilt, else the live assets/
PACK = os.path.join(REPO, "archived_assets") if os.path.isdir(os.path.join(REPO, "archived_assets")) else os.path.join(REPO, "assets")
OURS = os.path.join(PACK, "minecraft", "textures")
OUT = os.path.join(REPO, "proposed_textures")
MANIFEST = []  # (relative path, base item, description)


class Source:
    """Reads assets/minecraft/textures/<rel> from a resource-pack zip or an extracted folder."""
    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if os.path.isfile(path) else None
    def open(self, rel):
        inner = "assets/minecraft/textures/" + rel
        if self.zip:
            return Image.open(io.BytesIO(self.zip.read(inner))).convert("RGBA")
        return Image.open(os.path.join(self.path, inner)).convert("RGBA")
    def has(self, rel):
        inner = "assets/minecraft/textures/" + rel
        return inner in self.zip.namelist() if self.zip else os.path.exists(os.path.join(self.path, inner))

SRC = None  # set in main()

# ---------- colour helpers ----------
def hx(h):
    h = h.lstrip('#'); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
def mul(c, f):
    return tuple(max(0, min(255, int(round(v * f)))) for v in c)
def mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))
def lum(c):
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
def sat_boost(c, k):
    h, s, v = colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)
    s = min(1, s * k); r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))
def load(rel):
    return SRC.open(rel)
def load_ours(rel):
    return Image.open(os.path.join(OURS, rel)).convert("RGBA")
def save(img, rel, base, desc):
    p = os.path.join(OUT, rel); os.makedirs(os.path.dirname(p), exist_ok=True); img.save(p)
    MANIFEST.append((rel, base, desc))

# ---------- generic recolour helpers ----------
def recolor(img, region, target, curve=None, ref=None):
    """Recolour pixels whose RGB is in `region` (hex list) to `target` scaled by luminance.
    ref = the region colour that maps to target unscaled (default: lightest in region)."""
    region = {hx(c) for c in region}
    tgt = hx(target)
    ref_l = lum(hx(ref)) if ref else max(lum(c) for c in region)
    px = img.load(); W, H = img.size
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            if p[3] == 0 or p[:3] not in region: continue
            f = lum(p[:3]) / ref_l
            if curve: f = curve(f)
            px[x, y] = mul(tgt, min(f, 1.0)) + (p[3],) if f <= 1.0 else mix(tgt, (255, 255, 255), min(1, (f - 1) * 0.8)) + (p[3],)
    return img

def recolor_map(img, mapping):
    """Exact colour->colour mapping (hex keys/values)."""
    m = {hx(k): hx(v) for k, v in mapping.items()}
    px = img.load(); W, H = img.size
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            if p[3] and p[:3] in m: px[x, y] = m[p[:3]] + (p[3],)
    return img

def recolor_greys(img, target, ref=216, white_mix=0.45, sat=1.0):
    """For antialiased grey layers: every grey pixel -> target * (g/ref); pure white -> lighter tint."""
    tgt = sat_boost(hx(target), sat)
    px = img.load(); W, H = img.size
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            if p[3] == 0: continue
            g = lum(p[:3])
            if g >= 250: px[x, y] = mix(tgt, (255, 255, 255), white_mix) + (p[3],)
            else: px[x, y] = mul(tgt, min(1.0, g / ref)) + (p[3],)
    return img

def _hash(x, y, seed):
    h = (x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFF

def rust(img, region, seed=3, density=7):
    """Deterministic, clustered rust patches on pixels of the region (hashed, not a lattice)."""
    region = {hx(c) for c in region}
    px = img.load(); W, H = img.size
    seeds = [(x, y) for y in range(H) for x in range(W)
             if px[x, y][3] and px[x, y][:3] in region and _hash(x, y, seed) % (density * 3) == 0]
    for (sx, sy) in seeds:
        for (dx, dy) in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 0), (0, -1)):
            x, y = sx + dx, sy + dy
            if not (0 <= x < W and 0 <= y < H): continue
            p = px[x, y]
            if p[3] == 0 or p[:3] not in region: continue
            if (dx, dy) != (0, 0) and _hash(x, y, seed + 1) % 3 == 0: continue
            dark = _hash(x, y, seed + 2) % 2 == 0 or lum(p[:3]) < 120
            px[x, y] = ((0x6E, 0x40, 0x22) if dark else (0xA0, 0x66, 0x3A)) + (p[3],)
    return img

def put(img, pts, color):
    px = img.load(); c = hx(color)
    for (x, y) in pts: px[x, y] = c + (255,)
    return img

# ---------- Faithful palettes (32x, CF32PA-2026r19) ----------
BLADE = ["ffffff", "d8d8d8", "969696", "6b6b6b", "444444", "282828"]
BLADE_ONLY = ["ffffff", "d8d8d8", "444444"]      # blade body + its outline
GUARD = ["969696", "6b6b6b", "282828"]           # crossguard bar + pommel (Faithful silver)
BLADE_OUTLINE = ["444444"]
HANDLE = ["896727", "684e1e", "493615", "281e0b", "372910", "594319"]
LIMB = ["896727", "684e1e", "493615", "281e0b", "594319"]
STRING = ["969696", "6b6b6b", "444444"]
ARROWHEAD = ["ffffff", "d8d8d8", "b1b1b1"]
GRIP = ["969696", "6b6b6b"]                      # grey hand pad at the bow's elbow (the string itself is all 444444)
ARMOR_LIGHT = "c6c6c6"; ARMOR_MID = "969696"
CHAIN = ["c6c6c6", "969696", "6d6d6d", "555555"]
LEATHER = ["ededed", "b6b6b6", "a1a1a1"]
TOOLHEAD = ["ffffff", "d8d8d8", "c1c1c1", "969696", "444444", "828282"]
STONEHEAD = ["9a9a9a", "898989", "7f7f7f", "6c6c6c", "494949"]
WOODBLADE = ["372910", "866526", "755821", "6b511f"]
COVER = {"654b17": 1.0, "543e13": 0.82, "38280c": 0.55, "261b08": 0.38, "161005": 0.22}
GOLD = "D9A520"
HEAL_RED = "D8354F"   # healing family: Lone Sword, Masamune, Tenseiga, Heal Bow
# Smite / Sharpness level ladder, shared by the sword crossguard and the Axis book glyph:
# I iron (gunmetal), II copper, III bronze, IV silver, V gold
METAL = {1: "6E7480", 2: "B87333", 3: "B08D57", 4: "DCDCDC", 5: "E5B80B"}
KB_HANDLE = "7A1A1A"   # Knockback I: dark-red handle wrap (same cue as the red Punch string)

def handle_map(target):
    t = hx(target)
    return {"896727": "%02x%02x%02x" % mul(t, 1.0), "684e1e": "%02x%02x%02x" % mul(t, 0.78),
            "493615": "%02x%02x%02x" % mul(t, 0.55), "281e0b": "%02x%02x%02x" % mul(t, 0.35),
            "372910": "%02x%02x%02x" % mul(t, 0.45), "594319": "%02x%02x%02x" % mul(t, 0.7)}
def limb_map(target):
    t = hx(target)
    return {"896727": "%02x%02x%02x" % t, "684e1e": "%02x%02x%02x" % mul(t, 0.85),
            "594319": "%02x%02x%02x" % mul(t, 0.85),
            "493615": "%02x%02x%02x" % mul(t, 0.6), "281e0b": "%02x%02x%02x" % mul(t, 0.5)}
def string_map(target):
    t = hx(target)
    return {"969696": "%02x%02x%02x" % t, "6b6b6b": "%02x%02x%02x" % mul(t, 0.71), "444444": "%02x%02x%02x" % mul(t, 0.45)}
def armor_map(target, mid_factor=0.72):
    t = hx(target); m = sat_boost(mul(t, mid_factor), 1.25)
    return {"c6c6c6": "%02x%02x%02x" % t, "969696": "%02x%02x%02x" % m}
def chain_map(target):
    t = hx(target)
    return {"c6c6c6": "%02x%02x%02x" % t, "969696": "%02x%02x%02x" % mul(t, 0.72), "6d6d6d": "%02x%02x%02x" % mul(t, 0.52), "555555": "%02x%02x%02x" % mul(t, 0.41)}
def leather_map(target):
    t = hx(target)
    return {"ededed": "%02x%02x%02x" % t, "b6b6b6": "%02x%02x%02x" % mul(t, 0.76), "a1a1a1": "%02x%02x%02x" % mul(t, 0.66)}

# ---------- SWORDS ----------
def guard_tips(img, gold, depth=3):
    """Gold cap on both crossguard ends, `depth` px in from each tip (upper-left tip corner = (5, 12)). The Faithful sword
    is symmetric about its own axis, so the lower-right end is the mirror (x, y) -> (31 - y, 31 - x) of the upper-left one.
    Reads the Faithful greys, so it runs before the blade recolour; the ends hold only 6b6b6b fill + 282828 outline.
    (User feedback: depth 4, the bows' gold_tips depth, was too big.)"""
    px = img.load(); t = hx(gold); guard = {hx(c) for c in GUARD}; ref_l = lum(hx("6b6b6b"))
    for y in range(32):
        for x in range(32):
            p = px[x, y]
            if p[3] and p[:3] in guard and ((x <= 5 + depth and y <= 11 + depth) or (x >= 20 - depth and y >= 26 - depth)):
                px[x, y] = mul(t, min(1.0, lum(p[:3]) / ref_l)) + (p[3],)
    return img

def sword(name, blade=None, handle=None, base="iron_sword", outline=None, rusty=False, pips=None, guard=None, tips=None, desc=""):
    """guard: None = crossguard/pommel follow the blade colour (pack convention);
    'keep' = leave Faithful silver; hex = recolour crossguard/pommel to that metal.
    tips: hex = gold caps on the crossguard ends (elite marker)."""
    img = load(f"item/{base}.png")
    if tips: guard_tips(img, tips)         # first: it reads the Faithful greys
    if blade:
        if guard is None: recolor(img, BLADE if base != "stone_sword" else STONEHEAD + ["3c3c3c", "5a5a5a"], blade)
        else: recolor(img, BLADE_ONLY, blade)
    if guard and guard != "keep": recolor(img, GUARD, guard, ref="969696")
    if outline: recolor(img, BLADE_OUTLINE, outline)   # only if blade recolour didn't consume it
    if handle: recolor_map(img, handle_map(handle))
    if rusty: rust(img, BLADE, seed=5, density=8)
    if pips: put(img, pips, "C82A2A")
    save(img, f"swords/{name}.png", base.replace("_", " "), desc)

def gen_swords():
    # elites: gold handle + gold crossguard tips
    sword("agnis_rage", "EA3333", GOLD, tips=GOLD, desc="scarlet blade, gold hilt + crossguard tips (elite marker)")
    sword("dentrils_fear", "505050", GOLD, tips=GOLD, desc="charcoal blade, gold hilt + crossguard tips")
    sword("pluvias_storm", "5770ED", GOLD, tips=GOLD, desc="royal blue blade, gold hilt + crossguard tips")
    sword("simoons_song", "E050E0", GOLD, tips=GOLD, desc="magenta blade, gold hilt + crossguard tips")
    sword("therums_strength", "E6E600", GOLD, tips=GOLD, desc="lemon blade, gold hilt + crossguard tips")
    # healing trio: red blade, metal ladder on crossguard + pommel, Faithful handle
    sword("lone_sword", HEAL_RED, None, guard="B87333", desc="healing red blade, bronze crossguard + pommel")
    sword("masamune", HEAL_RED, None, guard="keep", desc="healing red blade, Faithful silver crossguard + pommel")
    sword("tenseiga", HEAL_RED, None, guard=GOLD, desc="healing red blade, gold crossguard + pommel (Agni's gold is on the handle)")
    # new iron
    sword("corsairs_edge", "2E3D8A", "F4F4F4", desc="navy blade, white hilt")
    sword("forsakens_blade", "B39CDB", "5A3E8C", desc="lilac blade, purple hilt")
    sword("muramasa", "E8E0C8", "8A1020", desc="ivory blade, crimson hilt")
    sword("nights_shadow", "4A2A8A", "202020", desc="violet blade, black hilt")
    sword("phantom_blade", "BFE6F2", "F4F4F4", desc="ice blade, white hilt")
    sword("vampyr", "8A1028", "202020", desc="crimson blade, black hilt")
    sword("rusted_iron_sword", None, None, rusty=True, desc="Faithful blade with rust patches")
    # Smite I-V on iron swords: metal crossguard + pommel (blade untouched), Knockback = dark-red handle
    metal_name = {1: "iron", 2: "copper", 3: "bronze", 4: "silver", 5: "gold"}
    for lvl in range(1, 6):
        sword(f"smite{lvl}_iron", None, None, guard=METAL[lvl], desc=f"Smite {lvl}: {metal_name[lvl]} crossguard + pommel")
        sword(f"smite{lvl}_knockback1_iron", None, KB_HANDLE, guard=METAL[lvl], desc=f"Smite {lvl} + Knockback I: {metal_name[lvl]} guard, dark-red handle")
    # stone
    sword("endeavour", "26806F", "202020", desc="dark teal blade, black hilt (stone sword)")
    sword("gamble", "34A066", "F4F4F4", pips=[(24, 7), (18, 13)], desc="emerald blade, white hilt, red dice pips (stone sword)")
    # wooden
    sword("kikuichimonji", None, "4E9331", desc="white steel blade on the wooden-sword slot, poison-green hilt")
    sword("robbers_blade", "3A3A3A", None, desc="black blade, Faithful hilt (wooden sword)")
    # diamond
    sword("helm_splitter", "7E9CB8", "202020", desc="steel blue-grey blade, black hilt (diamond sword)")
    img = load("item/iron_sword.png"); recolor(img, [c for c in BLADE if c != "444444"], "3A3A3A"); recolor(img, ["444444"], "33EBCB"); recolor_map(img, handle_map("8A1020"))
    save(img, "swords/overkill.png", "diamond sword", "black blade, diamond-teal edge, red hilt")
    sword("peace", "8FA86A", "F4F4F4", desc="sage blade, white hilt (diamond sword)")
    # golden
    sword("flail", "8A8A8A", "202020", desc="mid-grey blade, black hilt (golden sword)")
    sword("ipses_folly", "B89A3C", "8A1020", desc="tarnished gold blade, red hilt (golden sword)")

# ---------- BOWS ----------
INF_ICON = {(18, 15): "444444", (17, 16): "444444", (18, 16): None, (19, 16): "444444", (16, 17): "444444",
            (18, 17): "444444", (15, 18): "444444", (16, 18): None, (17, 18): "444444", (16, 19): "444444"}
def add_inf_icon(img):
    px = img.load()
    for (x, y), c in INF_ICON.items():
        px[x, y] = (0, 0, 0, 0) if c is None else hx(c) + (255,)
    return img

def gold_tips(img, gold):
    """Gold-ify the ends of both limbs (brown pixels near the top-right and bottom-left extremes)."""
    px = img.load(); W, H = img.size
    limb = {hx(c) for c in LIMB}
    pts = [(x, y) for y in range(H) for x in range(W) if px[x, y][3] and px[x, y][:3] in limb]
    if not pts: return img
    maxx = max(p[0] for p in pts); miny = min(p[1] for p in pts); minx = min(p[0] for p in pts); maxy = max(p[1] for p in pts)
    gm = limb_map(gold)
    for (x, y) in pts:
        if (x >= maxx - 3 and y <= miny + 3) or (x <= minx + 3 and y >= maxy - 3):
            c = px[x, y][:3]; key = "%02x%02x%02x" % c
            px[x, y] = hx(gm.get(key, gold)) + (255,)
    return img

def bow(name, limb=None, string=None, elite_gold=None, icon=False, copy_from=None, desc=""):
    for fr in ["bow", "bow_pulling_0", "bow_pulling_1", "bow_pulling_2"]:
        img = load_ours(f"item/bows/{copy_from}/{fr}.png") if copy_from else load(f"item/{fr}.png")
        if elite_gold:  # gold tips first, they are read from the brown palette
            gold_tips(img, elite_gold)
            recolor(img, GRIP, elite_gold)  # gold hand pad, the bow's counterpart of the elite swords' gold handle
            if fr != "bow": recolor(img, ARROWHEAD, elite_gold)  # gold arrowhead on drawn frames
        if limb: recolor_map(img, limb_map(limb))
        if string: recolor_map(img, string_map(string))
        if icon and fr == "bow": add_inf_icon(img)
        save(img, f"bows/{name}/{fr}.png", "bow", desc)

def gen_bows():
    bow("agnis_fury", "CC0000", None, GOLD, desc="red limbs, gold tips + hand pad + arrowhead")
    bow("dentrils_fright", "3A3A3A", None, GOLD, desc="charcoal limbs, gold tips + hand pad + arrowhead")
    bow("pluvias_rain", "1030D0", None, GOLD, desc="royal blue limbs, gold tips + hand pad + arrowhead")
    bow("simoons_melody", "C000C0", None, GOLD, desc="magenta limbs, gold tips + hand pad + arrowhead")
    bow("therums_power", "D0D000", None, GOLD, desc="lemon limbs, gold tips + hand pad + arrowhead")
    bow("heal_bow", HEAL_RED, None, desc="healing red limbs (same red as the healing swords), Faithful string")
    bow("binding_bow", "6C8CA8", "2A2A2A", desc="slate blue-grey limbs, dark string")
    bow("blunderbuss", "4A2E14", "C87A3C", desc="espresso limbs, copper string")
    bow("grapeshot", "6A3AA0", "2A2A2A", desc="grape purple limbs, dark string")
    bow("quiet", "BFE0DA", "2A2A2A", desc="ghost pale-teal limbs, dark string")
    bow("rocksteady", "D2B48C", "2A2A2A", desc="sandstone limbs, dark string")
    bow("shotbow", "7A1F1F", "141414", desc="maroon limbs, black string")
    bow("spike_thrower", "6B7B3A", "141414", desc="olive limbs, black string")
    bow("stomper", "E8641C", "2A2A2A", desc="ember orange limbs, dark string")
    bow("truth_bow", "F4F4F4", "3CB371", desc="white limbs, mint string")
    bow("venom_bow", "B5E61D", "4A1E6E", desc="acid lime limbs, purple string")
    bow("web_shot", "36347A", "FFFFFF", desc="navy limbs, white string")
    bow("punch_1", None, "B14F4F", desc="Faithful limbs, red string (Punch I)")
    bow("punch_1_inf", None, "B14F4F", icon=True, desc="Punch I + Infinity icon")
    bow("power_1_inf", None, None, icon=True, copy_from="power_1", desc="existing Power I + Infinity icon")

# ---------- ARMOUR ----------
HEM = [(x, y) for y in (28, 29) for x in range(9, 23)]   # lowest two body rows of the icon (row 30 is the outline)
TRIM_STYLE = "straps"   # "straps" = 2-px gold strap along each shoulder slope + hem; "pads" = whole shoulder lobes + hem; "crest" = chest emblem only
BODY_GREYS = {hx("c6c6c6"), hx("969696"), hx("ffffff")}
def trim_icon(img, trim, style=None):
    """Trim in the given colour, shaded from the Faithful greys underneath. Applied before the body recolour."""
    style = style or TRIM_STYLE
    px = img.load(); t = hx(trim); W, H = img.size
    shade = {hx("c6c6c6"): t, hx("969696"): mul(t, 0.7), hx("ffffff"): mix(t, (255, 255, 255), 0.35)}
    def paint(x, y, c=None):
        p = px[x, y]
        if p[3] and p[:3] in shade: px[x, y] = (c or shade[p[:3]]) + (255,)
    if style == "pads":
        for y in range(5, 10):
            for x in range(W): paint(x, y)
    elif style == "straps":
        # for every column of the two shoulder lobes, the top two body pixels under the outline;
        # columns 12-13 and 18-19 are skipped: their first body pixels sit in the neck V and formed two gold wedges
        for x in list(range(3, 12)) + list(range(20, 29)):
            body = [y for y in range(4, 11) if px[x, y][3] and px[x, y][:3] in BODY_GREYS]
            for y in body[:2]: paint(x, y)
    elif style == "crest":
        for (x, y) in [(16, 13), (15, 14), (16, 14), (17, 14), (14, 15), (15, 15), (16, 15), (17, 15), (18, 15), (15, 16), (16, 16), (17, 16), (16, 17)]:
            paint(x, y, mul(t, 0.7))
        for (x, y) in [(16, 14), (15, 15), (16, 15), (17, 15), (16, 16)]: paint(x, y, t)
    if style != "crest":
        for (x, y) in HEM:
            if px[x, y][3] and px[x, y][:3] in BODY_GREYS: px[x, y] = (t if y == HEM[0][1] else mul(t, 0.7)) + (255,)
    return img

def chest_icon(name, base_mat, body, trim=None, extras=None, rusty=False, desc=""):
    img = load(f"item/{base_mat}_chestplate.png")
    if trim: trim_icon(img, trim)          # before the body recolour: it reads the Faithful greys
    if body:
        if base_mat == "iron": recolor_map(img, armor_map(body))
        elif base_mat == "chainmail": recolor_map(img, chain_map(body))
        else: recolor_map(img, leather_map(body))
    if rusty: rust(img, [ARMOR_LIGHT, ARMOR_MID], seed=2, density=9)
    if extras: extras(img)
    save(img, f"armor/chestplates/{name}.png", f"{base_mat} chestplate", desc)

# worn layer (128x64, Faithful 2x humanoid layout): right-arm box x80-112 (top face y32-40, sides y40+); torso faces x32-80
ARM_X = range(80, 112); ARM_TOP_Y = range(32, 40); ARM_BAND_Y = range(40, 44); TORSO_X = range(32, 80)
def trim_layer(img, trim):
    """Paint half shoulder pads (arm top face + upper half of the 8-px sleeve) and a 2-px torso hem in the
    trim colour, shaded by the Faithful iron layer's luminance. (User preference: the half pad over a full sleeve.)"""
    ref = load("entity/equipment/humanoid/iron.png").load()
    px = img.load(); t = hx(trim); W, H = img.size
    def paint(x, y):
        p = px[x, y]
        if p[3] == 0: return
        g = lum(ref[x, y][:3]) if ref[x, y][3] else 200
        px[x, y] = (mix(t, (255, 255, 255), 0.4) if g >= 250 else mul(t, min(1.0, g / 216))) + (p[3],)
    for x in ARM_X:
        for y in ARM_TOP_Y: paint(x, y)
        for y in ARM_BAND_Y: paint(x, y)
    for x in TORSO_X:
        ys = [y for y in range(32, H) if px[x, y][3]]
        for y in ys[-2:]: paint(x, y)
    return img

def piece_icon(kind, name, base_mat, body, extras=None, rusty=False, desc=""):
    img = load(f"item/{base_mat}_{kind}.png")
    if body:
        if base_mat == "iron": recolor_map(img, armor_map(body))
        elif base_mat == "chainmail": recolor_map(img, chain_map(body))
        else: recolor_map(img, leather_map(body))
    if rusty: rust(img, [ARMOR_LIGHT, ARMOR_MID], seed=4, density=9)
    if extras: extras(img)
    folder = {"helmet": "helmets", "boots": "boots", "leggings": "leggings"}[kind]
    save(img, f"armor/{folder}/{name}.png", f"{base_mat} {kind}", desc)

def layer(name, base_mat, body, which=1, rusty=False, trim=None, desc=""):
    src = f"entity/equipment/{'humanoid' if which == 1 else 'humanoid_leggings'}/{base_mat}.png"
    img = load(src)
    if body: recolor_greys(img, body, ref=216 if base_mat != "leather" else 236)
    if rusty:
        region = {"%02x%02x%02x" % p[:3] for p in img.getdata() if p[3] and lum(p[:3]) > 100}
        rust(img, region, seed=8, density=12)
    if trim: trim_layer(img, trim)
    save(img, f"armor/layers/{name}_layer_{which}.png", f"{base_mat} armour layer {which}", desc)

def layer_from_pack(name, trim, desc=""):
    """Take the pack's existing hand-made worn layer and add the trim on top."""
    img = load_ours(f"entity/equipment/humanoid/{name}.png")
    trim_layer(img, trim)
    save(img, f"armor/layers/{name}_layer_1.png", "iron armour layer 1", desc)

LEATHER_BASE = LEATHER + ["535353", "353535"]   # body greys + outline: the game's dye tint multiplies the whole base layer
OVERLAY_REF = "955e3b"                           # lightest brown of Faithful's leather overlay (brim, soles, belt)
def leather_icon(kind, name, body, desc=""):
    """Dyed-leather icon baked into one layer (its CIT rule uses model=, which is single-layer): the Faithful base
    layer is tinted whole, outline included, and the brown overlay is rescaled per channel so OVERLAY_REF lands on `body`."""
    base = recolor(load(f"item/leather_{kind}.png"), LEATHER_BASE, body)
    img = Image.new("RGBA", base.size, (0, 0, 0, 0)); img.alpha_composite(base)
    if SRC.has(f"item/leather_{kind}_overlay.png"):   # Faithful ships no chestplate overlay
        ov = load(f"item/leather_{kind}_overlay.png"); px = ov.load(); t = hx(body); r = hx(OVERLAY_REF)
        for y in range(ov.size[1]):
            for x in range(ov.size[0]):
                p = px[x, y]
                if p[3]: px[x, y] = tuple(min(255, int(round(p[i] * t[i] / r[i]))) for i in range(3)) + (p[3],)
        img.alpha_composite(ov)
    folder = {"chestplate": "chestplates", "helmet": "helmets", "boots": "boots", "leggings": "leggings"}[kind]
    save(img, f"armor/{folder}/{name}.png", f"leather {kind}", desc)

def gen_armor():
    # elites (icons); layers only regenerated where colour changes
    chest_icon("agnis_wrath", "iron", "EA5656", GOLD, desc="scarlet, gold shoulder pads + hem")
    layer_from_pack("agnis_wrath", GOLD, desc="existing layer + gold shoulders and hem")
    chest_icon("dentrils_terror", "iron", "4A4A4A", GOLD, desc="charcoal, gold shoulder pads + hem (was light grey)")
    layer("dentrils_terror", "iron", "4A4A4A", trim=GOLD, desc="charcoal worn layer, gold shoulders + hem")
    chest_icon("pluvias_tempest", "iron", "5770ED", GOLD, desc="royal blue, gold shoulder pads + hem")
    layer_from_pack("pluvias_tempest", GOLD, desc="existing layer + gold shoulders and hem")
    chest_icon("simoons_sonata", "iron", "E050E0", GOLD, desc="magenta, gold shoulder pads + hem")
    layer_from_pack("simoons_sonata", GOLD, desc="existing layer + gold shoulders and hem")
    chest_icon("therums_force", "iron", "E6E600", GOLD, desc="lemon, gold shoulder pads + hem")
    layer_from_pack("therums_force", GOLD, desc="existing layer + gold shoulders and hem")
    chest_icon("rubber_shield", "iron", "2A2A2A", "8A5A2A", desc="black, rubber-brown shoulder pads + hem")
    layer("rubber_shield", "iron", "262626", trim="8A5A2A", desc="black worn layer, brown shoulders + hem")
    chest_icon("fire_protection_chestplate", "iron", "D8B0B0", desc="rose-grey (Spire, Fire Protection IV)")
    layer("fire_protection_chestplate", "iron", "D8B0B0", desc="rose-grey worn layer")
    chest_icon("rimeguard", "iron", "8ED8F0", "F4F4F4", desc="icy cyan-blue, white shoulder pads + hem (assumed chestplate)")
    layer("rimeguard", "iron", "8ED8F0", trim="F4F4F4", desc="icy worn layer, white shoulders + hem")
    chest_icon("rusted_chestplate", "iron", None, rusty=True, desc="Faithful iron with rust patches")
    layer("rusted_iron", "iron", None, rusty=True, desc="rust patches on the iron layer (helmet/chest/boots)")
    layer("rusted_iron", "iron", None, which=2, rusty=True, desc="rust patches on the iron leggings layer")
    chest_icon("pristine_chain_chestplate", "chainmail", "E4E4E4", desc="bright white chain")
    layer("pristine_chain", "chainmail", "E4E4E4", desc="bright chain layer 1")
    layer("pristine_chain", "chainmail", "E4E4E4", which=2, desc="bright chain layer 2")
    leather_icon("chestplate", "studded_leather_chestplate", "6A4A2A", desc="dark brown leather, no studs (Faithful leather icon, darker tint)")
    layer("studded_leather", "leather", "6A4A2A", desc="brown leather layer 1 (fixed colour, no dye)")
    layer("studded_leather", "leather", "6A4A2A", which=2, desc="brown leather layer 2")
    # helmets
    def slate_band(img):
        px = img.load()
        for y in (14, 15):
            for x in range(6, 26):
                p = px[x, y]
                if p[3] and p[:3] in (hx("c6c6c6"), hx("969696"), hx("2d2d2d"), hx("191919")): px[x, y] = (0x6C, 0x8C, 0xA8, 255) if y == 14 else (0x3E, 0x56, 0x70, 255)
        return img
    piece_icon("helmet", "binding_helmet", "iron", None, extras=slate_band, desc="Faithful iron helmet, slate-blue band (slowness)")
    layer("binding_helmet", "iron", None, desc="unchanged iron layer (band is icon-only); optional")
    def gorgon_eyes(img):
        return put(img, [(12, 17), (13, 17), (19, 17), (20, 17)], "C82A2A")
    piece_icon("helmet", "gorgons_gaze", "iron", "3E8A4E", extras=gorgon_eyes, desc="snake green, red eyes")
    layer("gorgons_gaze", "iron", "3E8A4E", desc="snake green layer")
    piece_icon("helmet", "gorgons_gaze_legacy", "chainmail", "3E8A4E", extras=gorgon_eyes, desc="snake green on chain (legacy item)")
    layer("gorgons_gaze_legacy", "chainmail", "3E8A4E", desc="snake green chain layer")
    def lamp(img):
        put(img, [(x, y) for x in range(13, 17) for y in range(9, 12)], "F6D65A")
        put(img, [(13, 11), (16, 11)], "D9A520"); return img
    piece_icon("helmet", "miners_lamp", "iron", None, extras=lamp, desc="Faithful iron helmet with a yellow lamp")
    piece_icon("helmet", "projectile_protection_helmet", "iron", "A8A878", desc="khaki")
    layer("projectile_protection", "iron", "A8A878", desc="khaki layer (helmet + boots)")
    piece_icon("helmet", "respiration_helmet", "iron", "B0D0D8", desc="aqua-grey (Spire)")
    layer("respiration_helmet", "iron", "B0D0D8", desc="aqua-grey layer")
    piece_icon("helmet", "rusted_helmet", "iron", None, rusty=True, desc="rust patches")
    piece_icon("helmet", "pristine_chain_helmet", "chainmail", "E4E4E4", desc="bright chain")
    leather_icon("helmet", "studded_leather_helmet", "6A4A2A", desc="dark brown leather, no studs")
    # boots
    def frost_rim(img):
        px = img.load()
        for y in (6, 7):
            for x in range(32):
                p = px[x, y]
                if p[3]: px[x, y] = (0xF4, 0xFA, 0xFF, 255) if y == 7 and p[:3] != hx("2d2d2d") else px[x, y]
        return img
    piece_icon("boots", "frost_walker", "iron", "7FB8D0", extras=frost_rim, desc="ice blue, white frost rim")
    layer("frost_walker", "iron", "7FB8D0", desc="ice blue layer")
    piece_icon("boots", "ninja_sandals", "chainmail", "2A3A3A", desc="near-black chain boots, teal cast")
    layer("ninja_sandals", "chainmail", "2A3A3A", desc="near-black chain layer")
    def penguin_toes(img):   # orange toe caps on the lowest three body rows of each boot
        px = img.load()
        for y in (22, 23, 24):
            for x in range(32):
                p = px[x, y]
                if p[3] and p[:3] not in (hx("2d2d2d"), hx("191919")):   # every body pixel, outline stays dark
                    px[x, y] = (hx("F0A830") if lum(p[:3]) > 200 else hx("C07A18")) + (255,)
        return img
    piece_icon("boots", "penguin_feet", "iron", "D0ECF8", extras=penguin_toes, desc="snow-ice boots, orange penguin toes (holiday; paler than Frost Walker)")
    layer("penguin_feet", "iron", "D0ECF8", desc="snow-ice layer (iron; official item can be any boot material)")
    def waist_rim(img):
        px = img.load()
        for x in range(32):
            p = px[x, 5]
            if p[3] and p[:3] not in (hx("2d2d2d"), hx("191919")): px[x, 5] = (0xF4, 0xFA, 0xFF, 255)
        return img
    piece_icon("leggings", "chimney_sweep", "iron", "8ED8F0", extras=waist_rim, desc="icy leggings, white waist rim (holiday)")
    layer("chimney_sweep", "iron", "8ED8F0", which=2, desc="icy leggings layer")
    piece_icon("boots", "projectile_protection_boots", "iron", "A8A878", desc="khaki")
    piece_icon("boots", "depth_strider_boots", "iron", "A8B8D8", desc="blue-grey (Spire)")
    layer("depth_strider", "iron", "A8B8D8", desc="blue-grey layer 1 (boots)")
    layer("depth_strider", "iron", "A8B8D8", which=2, desc="blue-grey layer 2 (leggings)")
    def feathers(img):
        return put(img, [(9, 12), (10, 13), (21, 12), (22, 13)], "FFFFFF")
    piece_icon("boots", "feather_falling_boots", "iron", "D8D0A8", extras=feathers, desc="light khaki, white feather pixels")
    layer("feather_falling_boots", "iron", "D8D0A8", desc="light khaki layer")
    piece_icon("boots", "rusted_boots", "iron", None, rusty=True, desc="rust patches")
    piece_icon("boots", "pristine_chain_boots", "chainmail", "E4E4E4", desc="bright chain")
    leather_icon("boots", "studded_leather_boots", "6A4A2A", desc="dark brown leather, no studs")
    # leggings
    piece_icon("leggings", "depth_strider_leggings", "iron", "A8B8D8", desc="blue-grey (Spire)")
    piece_icon("leggings", "rusted_leggings", "iron", None, rusty=True, desc="rust patches")
    piece_icon("leggings", "pristine_chain_leggings", "chainmail", "E4E4E4", desc="bright chain")
    leather_icon("leggings", "studded_leather_leggings", "6A4A2A", desc="dark brown leather, no studs")

# ---------- POTIONS ----------
CORK = ["d46d49", "c8613d", "bc5531", "b24e2b", "a94725", "c15c39", "b5502d", "aa4521", "a03e1b", "973716", "ccafa5"]
GLASS = ["e4e4e4", "cecece", "bababa"]
def potion(name, liquid, cork=None, kind="potion", foam=False, desc=""):
    bottle = load(f"item/{kind}.png")
    ov = load("item/potion_overlay.png")
    liq = hx(liquid); px = ov.load(); W, H = ov.size
    top = None
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            if p[3] == 0: continue
            if top is None: top = y
            f = lum(p[:3]) / 0xCA
            px[x, y] = (mul(liq, min(f, 1.0)) if f <= 1 else mix(liq, (255, 255, 255), min(1, (f - 1) * 1.5))) + (p[3],)
            if foam and y <= top + 1: px[x, y] = (0xF4, 0xF0, 0xE0, p[3])
    bp = bottle.load()
    for y in range(H):
        for x in range(W):
            p = bp[x, y]
            if p[3] and p[:3] in {hx(c) for c in GLASS}: bp[x, y] = mix(p[:3], liq, 0.22) + (p[3],)
    if cork: recolor(bottle, CORK, cork, ref="d46d49")
    out = Image.alpha_composite(ov, bottle)
    save(out, f"potions/{name}.png", kind.replace("_", " "), desc)

def gen_potions():
    potion("agnis_ire", "B00020", GOLD, desc="dark red liquid, gold cork")
    potion("dentrils_dread", "4A4A4A", GOLD, desc="charcoal smoke liquid, gold cork")
    potion("pluvias_hail", "0040C0", GOLD, desc="royal blue liquid, gold cork")
    potion("simoons_tune", "9000C0", GOLD, desc="purple liquid, gold cork")
    potion("therums_might", "C0C000", GOLD, desc="yellow liquid, gold cork")
    potion("eillom_ale", "4A2C14", foam=True, desc="stout brown with foam")
    potion("giants_brew", "6B8E23", desc="olive")
    potion("green_beer", "1E7A30", desc="kelly green (seasonal)")
    potion("manzana_cider", "C8862A", desc="amber cider (was maroon = Agni's Ire clash)")
    potion("witchs_brew", "3A6B2A", desc="swamp green (was purple = Simoon's Tune clash)")
    potion("cleansing_elixir", "2ECC40", desc="softer green than the current 00FF00 tint")
    potion("acid_vial", "7FFF00", kind="lingering_potion", desc="acid green on the lingering bottle")
    potion("frozen_marghoulita", "53E9FD", desc="same cyan as the existing tint, baked so it matches the other bottles")

# ---------- BOOKS ----------
GLYPH = [(16, 6), (18, 6), (17, 7), (18, 8), (19, 8), (17, 9), (20, 9), (22, 9), (18, 10), (21, 10), (22, 11)]
KB_MARK = [(11, 9), (10, 10), (11, 11), (12, 12), (11, 13), (13, 13)]
def book(name, cover=None, glyph_metal=None, kb=False, gold_spine=False, desc=""):
    img = load("item/book.png")
    if cover:
        c = hx(cover); recolor_map(img, {k: "%02x%02x%02x" % mul(c, f) for k, f in COVER.items()})
    if gold_spine: recolor(img, ["543e13"], GOLD) if not cover else recolor_map(img, {"%02x%02x%02x" % mul(hx(cover), 0.82): GOLD})
    if glyph_metal: put(img, GLYPH, glyph_metal)
    if kb: put(img, KB_MARK, glyph_metal or "E5B80B")
    save(img, f"books/{name}.png", "book", desc)

def gen_books():
    seals = {"seal_of_entropy": "661616", "seal_of_gravity": "661666", "seal_of_space": "666616", "seal_of_time": "162066"}
    for n, c in seals.items(): book(n, c, gold_spine=True, desc="existing cover colour, gold spine (elite marker)")
    names = {1: ("alpha", "wau"), 2: ("beta", "theta"), 3: ("mu", "omicron"), 4: ("sigma", "phi"), 5: ("gamma", "omega")}
    metal_name = {1: "iron", 2: "copper", 3: "bronze", 4: "silver", 5: "gold"}
    for lvl in range(1, 6):   # all ten Astrum (Smite) books regenerated so the glyph metal matches the sword guards
        a, b = names[lvl]
        book(f"astrum_{a}", None, METAL[lvl], desc=f"Smite {lvl}: {metal_name[lvl]} glyph")
        book(f"astrum_{b}", None, METAL[lvl], kb=True, desc=f"Smite {lvl} + Knockback: {metal_name[lvl]} glyph + mark")
    for lvl in range(1, 6):
        a, b = names[lvl]
        book(f"astra_{a}", "2E5E3A", METAL[lvl], desc=f"Sharpness {lvl}: green cover, {metal_name[lvl]} glyph")
        book(f"astra_{b}", "2E5E3A", METAL[lvl], kb=True, desc=f"Sharpness {lvl} + Knockback: {metal_name[lvl]} glyph + mark")

# ---------- TOOLS & MISC ----------
def tool(name, base, head=None, handle=None, outline=None, rusty=False, extras=None, region=None, desc=""):
    img = load(f"item/{base}.png")
    reg = region or (STONEHEAD if base.startswith("stone") else (WOODBLADE if base == "wooden_hoe" else TOOLHEAD))
    if head:
        if outline: recolor(img, [c for c in reg if c != "444444"], head); recolor(img, ["444444"], outline)
        else: recolor(img, reg, head)
    if handle: recolor_map(img, handle_map(handle))
    if rusty: rust(img, reg, seed=1, density=6)
    if extras: extras(img)
    save(img, f"tools/{name}.png", base.replace("_", " "), desc)

def gen_tools():
    tool("earth_shaker", "iron_axe", "9A9AD0", desc="slate blue-purple head")
    tool("rusted_earth_shaker", "stone_axe", None, rusty=True, desc="rust on the stone head")
    tool("deaths_scythe", "iron_hoe", "3A3A3A", outline="E8E0C8", desc="black blade, bone edge")
    tool("crowbar", "iron_hoe", "C82A2A", handle="8B1A1A", desc="red-painted crowbar")
    tool("rusty_crowbar", "iron_hoe", "A0663A", handle="5A3A1A", rusty=True, desc="rust crowbar (dungeon)")
    tool("fortune1_wooden_hoe", "wooden_hoe", "8CC77A", desc="light green blade = Fortune I")
    tool("fortune2_wooden_hoe", "wooden_hoe", "3AA060", desc="emerald blade = Fortune II")
    tool("fortune1_iron_shovel", "iron_shovel", "B8E0A8", desc="light green head = Fortune I")
    tool("fortune2_iron_shovel", "iron_shovel", "3AA060", desc="emerald head = Fortune II")
    tool("blast_pickaxe", "iron_pickaxe", "E04030", desc="TNT-red head (base item assumed iron pickaxe)")
    tool("rusted_pickaxe", "iron_pickaxe", None, rusty=True, desc="rust on the iron head")
    tool("weak_grapple", "fishing_rod", "444444", region=["493615", "684e1e", "896727", "281e0b"], desc="dark iron rod, Faithful line + hook")
    tool("lure1_fishing_rod", "fishing_rod", "3CB371", region=["444444"], desc="green line = Lure I")
    tool("lure2_fishing_rod", "fishing_rod", "5AD08A", region=["444444"], desc="bright green line = Lure II")
    def ember(img):
        px = img.load()
        for y in range(4, 9):
            for x in range(24, 31):
                p = px[x, y]
                if p[3]: px[x, y] = (hx("F6D65A") if y <= 5 else hx("E8641C")) + (255,)
        return img
    tool("kindling", "stick", None, extras=ember, desc="stick with ember tip")
    def crystal(img):
        px = img.load()
        for y in range(4, 9):
            for x in range(24, 31):
                p = px[x, y]
                if p[3]: px[x, y] = (hx("B39CDB") if y <= 5 else hx("6A3AA0")) + (255,)
        return img
    tool("rod_of_reclamation", "stick", None, extras=crystal, desc="stick with purple crystal tip")
    img = load("item/paper.png"); recolor_map(img, {"eaeaea": "F0E8D0", "d6d6d6": "D8C8A0", "515151": "8A7A58"})
    put(img, [(15, 13), (15, 14), (15, 15), (15, 16), (15, 17), (13, 15), (14, 15), (16, 15), (17, 15)], "C82A2A")
    save(img, "misc/mummys_cloth.png", "paper", "tan bandage with red cross")

# ---------- unchanged textures: copied through from the pack so the folder is a complete set ----------
UNCHANGED_BOWS = ["snowbrawler", "zombie_bow", "inf","power_1", "power_1_punch_1", "power_1_punch_1_inf", "power_2", "power_2_inf", "power_2_punch_1"]
UNCHANGED_BOOKS = []   # the Astrum books are regenerated with the shared metal ladder
UNCHANGED_LAYERS = []   # the elite layers now get the gold trim, see layer_from_pack()
UNCHANGED_OTHER = [("block/black_concrete.png", "other/block/black_concrete.png", "black concrete", "brightened block"),
                   ("block/purple_concrete.png", "other/block/purple_concrete.png", "purple concrete", "tweaked block"),
                   ("entity/chest/trapped.png", "other/entity/chest/trapped.png", "trapped chest", "green zombie chest"),
                   ("gui/sprites/hud/heart/withered_full.png", "other/gui/hud/heart/withered_full.png", "HUD heart", "red withered heart"),
                   ("gui/sprites/hud/heart/withered_half.png", "other/gui/hud/heart/withered_half.png", "HUD heart", "red withered heart"),
                   ("gui/sprites/hud/heart/withered_full_blinking.png", "other/gui/hud/heart/withered_full_blinking.png", "HUD heart", "red withered heart"),
                   ("gui/sprites/hud/heart/withered_half_blinking.png", "other/gui/hud/heart/withered_half_blinking.png", "HUD heart", "red withered heart")]

def copy_bytes(src, out_rel, base, desc):
    """Byte-exact copy (no re-encode) so git does not see unchanged textures as modified."""
    p = os.path.join(OUT, out_rel); os.makedirs(os.path.dirname(p), exist_ok=True); shutil.copyfile(src, p)
    MANIFEST.append((out_rel, base, "UNCHANGED, copied from the pack: " + desc))

def copy_through(src_rel, out_rel, base, desc):
    src = os.path.join(OURS, src_rel)
    if not os.path.exists(src): return
    copy_bytes(src, out_rel, base, desc)

def copy_unchanged():
    for b in UNCHANGED_BOWS:
        for fr in ("bow", "bow_pulling_0", "bow_pulling_1", "bow_pulling_2"):
            copy_through(f"item/bows/{b}/{fr}.png", f"bows/{b}/{fr}.png", "bow", "existing bow")
    for b in UNCHANGED_BOOKS:
        copy_through(f"item/books/{b}.png", f"books/{b}.png", "book", "existing Astrum book")
    for n in UNCHANGED_LAYERS:
        copy_through(f"entity/equipment/humanoid/{n}.png", f"armor/layers/{n}_layer_1.png", "iron armour layer 1", "existing elite chestplate layer")
    for f in sorted(glob.glob(os.path.join(OURS, "item", "grass_blocks", "*.png"))):
        n = os.path.basename(f)
        copy_through(f"item/grass_blocks/{n}", f"misc/grass_blocks/{n}", "grass block", "spawn-menu icon")
    cit = os.path.join(PACK, "minecraft", "optifine", "cit", "support_kit")
    for f in sorted(glob.glob(os.path.join(cit, "*.png"))):
        copy_bytes(f, f"misc/support_kit/{os.path.basename(f)}", "shears", "Support Kit module state")
    for src_rel, out_rel, base, desc in UNCHANGED_OTHER:
        copy_through(src_rel, out_rel, base, desc)

# ---------- contact sheets + manifest ----------
def contact_sheet():
    S = 48; cols = 12
    items = [m for m in MANIFEST if not m[0].startswith("armor/layers") and "pulling" not in m[0]]
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * (S + 6) + 6, rows * (S + 18) + 6), (44, 44, 48, 255)); d = ImageDraw.Draw(sheet)
    for i, (rel, base, desc) in enumerate(items):
        im = Image.open(os.path.join(OUT, rel)).convert("RGBA")
        if im.size[0] > 64: continue
        im = im.resize((S, S), Image.NEAREST)
        x = 6 + (i % cols) * (S + 6); y = 6 + (i // cols) * (S + 18)
        sheet.paste(im, (x, y), im)
        label = os.path.basename(rel)[:-4]
        if rel.startswith("bows/"): label = rel.split("/")[1]
        d.text((x, y + S + 1), label[:12], fill=(230, 230, 230, 255))
    sheet.save(os.path.join(OUT, "_contact_sheet.png"))
    bows = sorted(set(m[0].split("/")[1] for m in MANIFEST if m[0].startswith("bows/")))
    bs = Image.new("RGBA", (4 * (S + 6) + 120, len(bows) * (S + 6) + 6), (44, 44, 48, 255)); d = ImageDraw.Draw(bs)
    for i, b in enumerate(bows):
        d.text((4, 6 + i * (S + 6) + S // 2 - 5), b[:16], fill=(230, 230, 230, 255))
        for j, fr in enumerate(["bow", "bow_pulling_0", "bow_pulling_1", "bow_pulling_2"]):
            im = Image.open(os.path.join(OUT, "bows", b, f"{fr}.png")).convert("RGBA").resize((S, S), Image.NEAREST)
            bs.paste(im, (120 + j * (S + 6), 6 + i * (S + 6)), im)
    bs.save(os.path.join(OUT, "_bows_sheet.png"))
    lay = [m for m in MANIFEST if m[0].startswith("armor/layers")]
    ls = Image.new("RGBA", (2 * 262, ((len(lay) + 1) // 2) * 140 + 6), (44, 44, 48, 255)); d = ImageDraw.Draw(ls)
    for i, (rel, base, desc) in enumerate(lay):
        im = Image.open(os.path.join(OUT, rel)).convert("RGBA").resize((256, 128), Image.NEAREST)
        x = 3 + (i % 2) * 262; y = 3 + (i // 2) * 140
        ls.paste(im, (x, y), im); d.text((x, y + 128), os.path.basename(rel)[:-4], fill=(230, 230, 230, 255))
    ls.save(os.path.join(OUT, "_layers_sheet.png"))

def smite_sheet():
    """Review sheet of the Smite / Sharpness metal ladder: iron-sword guards and Axis book glyphs, I..V, with Knockback rows."""
    glyphs = {1: ("alpha", "wau"), 2: ("beta", "theta"), 3: ("mu", "omicron"), 4: ("sigma", "phi"), 5: ("gamma", "omega")}
    rows = [("iron sword", [f"swords/smite{l}_iron.png" for l in range(1, 6)]),
            ("iron sword + Knockback I", [f"swords/smite{l}_knockback1_iron.png" for l in range(1, 6)]),
            ("Astrum (Smite) book", [f"books/astrum_{glyphs[l][0]}.png" for l in range(1, 6)]),
            ("Astrum + Knockback I", [f"books/astrum_{glyphs[l][1]}.png" for l in range(1, 6)]),
            ("Astra (Sharpness) book", [f"books/astra_{glyphs[l][0]}.png" for l in range(1, 6)]),
            ("Astra + Knockback I", [f"books/astra_{glyphs[l][1]}.png" for l in range(1, 6)])]
    S = 72; W = 200 + 5 * (S + 6) + 8; H = 30 + len(rows) * (S + 44) + 8
    sheet = Image.new("RGBA", (W, H), (44, 44, 48, 255)); d = ImageDraw.Draw(sheet)
    d.text((200, 8), "I iron        II copper       III bronze      IV silver       V gold", fill=(255, 220, 120, 255))
    for r, (label, files) in enumerate(rows):
        y = 30 + r * (S + 44); d.text((8, y + S // 2 - 6), label, fill=(230, 230, 230, 255))
        inv = Image.new("RGBA", (5 * 20 + 4, 20), (139, 139, 139, 255))
        for c, rel in enumerate(files):
            im = Image.open(os.path.join(OUT, rel)).convert("RGBA"); x = 200 + c * (S + 6)
            big = im.resize((S, S), Image.NEAREST); sheet.paste(big, (x, y), big)
            sm = im.resize((16, 16), Image.BOX); inv.paste(sm, (2 + c * 20, 2), sm)
        inv = inv.resize((inv.size[0] * 2, inv.size[1] * 2), Image.NEAREST); sheet.paste(inv, (200, y + S + 2))
    sheet.save(os.path.join(OUT, "_smite_ladder_sheet.png"))

def manifest(faithful_path):
    lines = ["# Proposed textures", "",
             f"Generated by `scripts/generate_proposed_textures.py` from Classic Faithful 32x base textures (`{os.path.basename(faithful_path)}`) by region recolour, so every file keeps Faithful's shading and silhouette.",
             "Nothing here is wired into the pack; copy a file into `assets/minecraft/textures/...` and add the matching `items/*.json` case or CIT rule.",
             "Armour layers are full recolours of Faithful's `entity/equipment/humanoid[_leggings]/<material>.png`; only the piece that owns the rule renders.",
             "Rows marked UNCHANGED are copied through from the pack as-is so this folder is a complete set (Snowbrawler, Power/Punch/Infinity bows, the six Astrum books, four elite layers, spawn icons, Support Kit states, blocks and HUD).",
             "", "| File | Base item | What it is |", "|---|---|---|"]
    for rel, base, desc in MANIFEST:
        if "pulling" in rel: continue
        lines.append(f"| `{rel}` | {base} | {desc} |")
    lines += ["", "Bows: each folder also holds `bow_pulling_0/1/2.png`.",
              "Smite / Sharpness ladder (iron-sword crossguard and Axis book glyph): I iron 6E7480, II copper B87333, III bronze B08D57, IV silver DCDCDC, V gold E5B80B; Knockback I = dark-red handle 7A1A1A. See `_smite_ladder_sheet.png`.",
              "Assumptions: RimeGuard drawn as an iron chestplate, Blast Pickaxe as an iron pickaxe (verify in-game).",
              "Not generated: Seafarer's Grog, Valarian Champion set, Gate Stones and the other wiki-only items (base item unknown); Power I / Power II bows unchanged (gold stays on Power II by request).",
              "", "Regenerate from the repo root: `python scripts/generate_proposed_textures.py` (see the script docstring for the `--faithful` and `--out` options)."]
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f: f.write("\n".join(lines))

def find_faithful():
    cands = sorted(glob.glob(os.path.join(os.path.dirname(REPO), "CF32PA-*.zip")))
    if not cands: raise SystemExit("No CF32PA-*.zip found next to the repo; pass --faithful <zip or folder>.")
    return cands[-1]

def main():
    global SRC, OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--faithful", help="Classic Faithful 32x pack (.zip or extracted folder)")
    ap.add_argument("--out", help="output folder (deleted and rebuilt)")
    args = ap.parse_args()
    faithful = args.faithful or find_faithful()
    if args.out: OUT = os.path.abspath(args.out)
    SRC = Source(faithful)
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    gen_swords(); gen_bows(); gen_armor(); gen_potions(); gen_books(); gen_tools()
    copy_unchanged()
    contact_sheet(); smite_sheet(); manifest(faithful)
    copied = sum(1 for m in MANIFEST if m[2].startswith("UNCHANGED"))
    print(f"faithful: {faithful}\nout: {OUT}\nfiles: {len(MANIFEST)} ({len(MANIFEST) - copied} generated, {copied} copied unchanged)")

if __name__ == "__main__":
    main()
