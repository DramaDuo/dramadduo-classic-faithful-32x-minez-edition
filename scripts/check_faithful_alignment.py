"""Check that this pack's recoloured textures still line up with the current Classic Faithful 32x base files.

For every texture in assets/minecraft/textures that is a recolour of a Faithful item, it reports:
  - silhouette IoU  (alpha-mask overlap; 1.000 = same outline pixel for pixel)
  - shading corr    (luminance correlation on shared pixels; high = same highlight/shadow structure)
Run it after every Faithful update. A silhouette below 1.0 (other than the Infinity bows, which add an icon)
means Faithful redrew that item and the recolour should be regenerated.

Usage (from the repo root):
    python scripts/check_faithful_alignment.py
    python scripts/check_faithful_alignment.py --faithful "../CF32PA-2026r19.zip"

Requires Pillow.
"""
from PIL import Image
import argparse, glob, io, math, os, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OURS = os.path.join(REPO, "assets", "minecraft", "textures")

# our texture (relative to assets/minecraft/textures) -> Faithful base (same relative root)
PAIRS = []
for f in sorted(glob.glob(os.path.join(OURS, "item", "swords", "*.png"))):
    PAIRS.append((f"item/swords/{os.path.basename(f)}", "item/iron_sword.png"))
for f in sorted(glob.glob(os.path.join(OURS, "item", "chestplates", "*.png"))):
    PAIRS.append((f"item/chestplates/{os.path.basename(f)}", "item/iron_chestplate.png"))
for f in sorted(glob.glob(os.path.join(OURS, "item", "books", "*.png"))):
    PAIRS.append((f"item/books/{os.path.basename(f)}", "item/book.png"))
for f in sorted(glob.glob(os.path.join(OURS, "item", "potions", "*.png"))):
    PAIRS.append((f"item/potions/{os.path.basename(f)}", "item/potion.png+overlay"))
for d in sorted(glob.glob(os.path.join(OURS, "item", "bows", "*"))):
    for fr in ("bow", "bow_pulling_0", "bow_pulling_1", "bow_pulling_2"):
        PAIRS.append((f"item/bows/{os.path.basename(d)}/{fr}.png", f"item/{fr}.png"))
for f in sorted(glob.glob(os.path.join(OURS, "entity", "equipment", "humanoid", "*.png"))):
    PAIRS.append((f"entity/equipment/humanoid/{os.path.basename(f)}", "entity/equipment/humanoid/iron.png"))
PAIRS += [("block/black_concrete.png", "block/black_concrete.png"), ("block/purple_concrete.png", "block/purple_concrete.png"),
          ("entity/chest/trapped.png", "entity/chest/trapped.png")]
PAIRS += [(f"gui/sprites/hud/heart/{n}.png", f"gui/sprites/hud/heart/{n}.png") for n in
          ("withered_full", "withered_half", "withered_full_blinking", "withered_half_blinking")]


class Source:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path) if os.path.isfile(path) else None; self.path = path
    def open(self, rel):
        inner = "assets/minecraft/textures/" + rel
        if self.zip:
            return Image.open(io.BytesIO(self.zip.read(inner))).convert("RGBA")
        return Image.open(os.path.join(self.path, inner)).convert("RGBA")

def mask(im):
    return [1 if a > 0 else 0 for a in im.getchannel("A").getdata()]
def iou(a, b):
    ma, mb = mask(a), mask(b)
    i = sum(1 for x, y in zip(ma, mb) if x and y); u = sum(1 for x, y in zip(ma, mb) if x or y)
    return i / u if u else 0.0
def corr(a, b):
    pa, pb = list(a.getdata()), list(b.getdata())
    pairs = [((0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]), (0.299 * q[0] + 0.587 * q[1] + 0.114 * q[2]))
             for p, q in zip(pa, pb) if p[3] and q[3]]
    if len(pairs) < 10: return 0.0
    mx = sum(p[0] for p in pairs) / len(pairs); my = sum(p[1] for p in pairs) / len(pairs)
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    da = math.sqrt(sum((p[0] - mx) ** 2 for p in pairs)); db = math.sqrt(sum((p[1] - my) ** 2 for p in pairs))
    return num / (da * db) if da and db else 0.0

def find_faithful():
    cands = sorted(glob.glob(os.path.join(os.path.dirname(REPO), "CF32PA-*.zip")))
    if not cands: raise SystemExit("No CF32PA-*.zip found next to the repo; pass --faithful <zip or folder>.")
    return cands[-1]

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--faithful", help="Classic Faithful 32x pack (.zip or extracted folder)")
    args = ap.parse_args()
    src = Source(args.faithful or find_faithful())
    print(f"faithful: {src.path}\n")
    print(f"{'texture':52s} {'size':9s} {'silhouette':>10s} {'shading':>8s}  note")
    bad = 0
    for ours_rel, base_rel in PAIRS:
        p = os.path.join(OURS, ours_rel)
        if not os.path.exists(p): continue
        a = Image.open(p).convert("RGBA")
        if base_rel.endswith("+overlay"):
            bottle = src.open("item/potion.png"); ov = src.open("item/potion_overlay.png")
            b = Image.alpha_composite(ov, bottle)
        else:
            b = src.open(base_rel)
        if a.size != b.size:
            print(f"{ours_rel:52s} {str(a.size):9s} {'SIZE':>10s} {'':>8s}  Faithful is {b.size}"); bad += 1; continue
        c = corr(a, b)
        note = ""
        if ours_rel.startswith("entity/equipment/"):
            # the pack's layers keep only the chest region, so test containment (ours inside Faithful), not overlap
            ma, mb = mask(a), mask(b)
            inside = sum(1 for x, y in zip(ma, mb) if x and y); ours = sum(ma)
            s = inside / ours if ours else 0.0
            if s < 0.999: note = "PIXELS OUTSIDE FAITHFUL LAYER"; bad += 1
            else: note = "partial layer, inside Faithful"
        else:
            s = iou(a, b)
            if s < 0.999:
                note = "icon added" if "/inf" in ours_rel or "_inf/" in ours_rel else "OUTLINE CHANGED"
                if note == "OUTLINE CHANGED": bad += 1
        print(f"{ours_rel:52s} {str(a.size):9s} {s:10.3f} {c:8.3f}  {note}")
    print(f"\n{bad} texture(s) need attention." if bad else "\nAll silhouettes match the current Faithful base.")

if __name__ == "__main__":
    main()
