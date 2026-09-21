"""
Render the complete unnamed stream network as map image tiles.

Why this exists
---------------
The River Atlas already publishes all 488,755 unnamed reaches as original
vector data (scripts/import_unnamed_streams.py). A browser cannot draw that
many lines at once, though: 5.7 million vertices would freeze the page long
before the basin view appeared. So at the zoomed-out levels the map shows
the network as pre-drawn PNG tiles instead, rendered here from every
feature in the source file, the same way any web map shows a dense layer.

Nothing in the data changes. The vector layer stays the record: it is still
what a click reads, and from the catalogue's vector_from_zoom onwards it is
what the map draws. The images are only a picture of it.

Style (colour, width, opacity) is read from the layer's own catalogue entry,
so the images match the vector drawing exactly.

Output:
  app/static/data/river_atlas/tiles/unnamed_streams/raster/<z>/<x>/<y>.png
  catalog.json   adds a "raster" block to the unnamed_streams entry

Usage (from the backend folder, after import_unnamed_streams.py):
    pip install pillow numpy
    python scripts/render_unnamed_raster.py \
        --source "path/to/Narmada_Unnamed_Streams.geojson"

Takes a few minutes and about 1.5 GB of RAM.
"""

import argparse
import json
import math
import os
import shutil
import sys

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Needs numpy and Pillow: pip install numpy pillow")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "app", "static", "data", "river_atlas"))
LAYER_ID = "unnamed_streams"
RASTER_ROOT = os.path.join(OUT_DIR, "tiles", LAYER_ID, "raster")

# Zoom levels drawn as images. Below MIN_ZOOM the basin is a few dozen
# pixels wide; from MAX_ZOOM + 1 the map draws the original vectors.
MIN_ZOOM, MAX_ZOOM = 5, 11
TILE = 256
SUPERSAMPLE = 4          # draw at 4x, then shrink: smooth sub-pixel lines


def hex_rgb(value):
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def load_geometry(path):
    """All vertices as Web Mercator unit coordinates, plus part offsets."""
    us, vs, offsets = [], [], [0]
    count = 0
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            s = raw.strip()
            if not s.startswith('{ "type": "Feature"'):
                continue
            feat = json.loads(s[:-1] if s.endswith(",") else s)
            count += 1
            geom = feat["geometry"]
            parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            for part in parts:
                for lon, lat, *_ in part:
                    us.append((lon + 180.0) / 360.0)
                    r = math.radians(lat)
                    vs.append((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0)
                offsets.append(len(us))
    return count, np.array(us), np.array(vs), np.array(offsets, dtype=np.int64)


def main():
    ap = argparse.ArgumentParser(description="Render the unnamed network as PNG tiles.")
    ap.add_argument("--source", required=True, help="Narmada_Unnamed_Streams.geojson")
    args = ap.parse_args()
    if not os.path.isfile(args.source):
        sys.exit(f"Source not found: {args.source}")

    cat_path = os.path.join(OUT_DIR, "catalog.json")
    with open(cat_path, encoding="utf-8") as fh:
        catalog = json.load(fh)
    entry = next((l for l in catalog["layers"] if l["id"] == LAYER_ID), None)
    if entry is None:
        sys.exit("unnamed_streams missing from catalog.json. Run import_unnamed_streams.py first.")

    style = entry.get("style") or {}
    rgb = hex_rgb(style.get("color", "#000000"))
    opacity = float(style.get("opacity", 1.0))
    width_ss = max(1, round(float(style.get("weight", 1.0)) * SUPERSAMPLE))

    print("Reading source ...")
    n_features, U, V, offsets = load_geometry(args.source)
    print(f"  {n_features:,} features, {len(U):,} vertices")

    if os.path.isdir(RASTER_ROOT):
        shutil.rmtree(RASTER_ROOT)

    size_ss = TILE * SUPERSAMPLE
    total_tiles, total_bytes = 0, 0
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        scale = TILE * SUPERSAMPLE * (2 ** z)
        X, Y = U * scale, V * scale
        masks = {}
        for i in range(len(offsets) - 1):
            a, b = offsets[i], offsets[i + 1]
            if b - a < 2:
                continue
            px, py = X[a:b], Y[a:b]
            pad = width_ss
            tx0 = int((px.min() - pad) // size_ss)
            tx1 = int((px.max() + pad) // size_ss)
            ty0 = int((py.min() - pad) // size_ss)
            ty1 = int((py.max() + pad) // size_ss)
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    img = masks.get((tx, ty))
                    if img is None:
                        img = masks[(tx, ty)] = Image.new("L", (size_ss, size_ss), 0)
                    pts = np.column_stack((px - tx * size_ss, py - ty * size_ss)).ravel().tolist()
                    ImageDraw.Draw(img).line(pts, fill=255, width=width_ss)

        written = 0
        for (tx, ty), mask in masks.items():
            small = mask.resize((TILE, TILE), Image.Resampling.BOX)
            if opacity < 1.0:
                small = small.point(lambda p: int(round(p * opacity)))
            if not small.getbbox():
                continue
            tile = Image.new("RGBA", (TILE, TILE), rgb + (0,))
            tile.putalpha(small)
            path = os.path.join(RASTER_ROOT, str(z), str(tx), f"{ty}.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tile.save(path, optimize=True)
            written += 1
            total_bytes += os.path.getsize(path)
        total_tiles += written
        print(f"  zoom {z:>2}: {written:>4} tiles")
        del masks

    # Geographic bounds of the network, so the map only asks for tiles there.
    def lon(u):
        return u * 360.0 - 180.0

    def lat(v):
        return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * v))))

    bounds = [[round(lat(V.max()), 5), round(lon(U.min()), 5)],
              [round(lat(V.min()), 5), round(lon(U.max()), 5)]]

    entry["raster"] = {
        "url": f"/api/river-atlas/layer/{LAYER_ID}/raster/{{z}}/{{x}}/{{y}}.png",
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM,
        # From this zoom the map draws the original vectors instead.
        "vector_from_zoom": MAX_ZOOM + 1,
        "bounds": bounds,
        "features_drawn": n_features,
    }
    # Every reach is now visible at every zoom, so no "zoom in" hint.
    entry.pop("zoom_hint", None)
    entry.pop("zoom_hint_hi", None)

    with open(cat_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"\nDrew all {n_features:,} features into {total_tiles:,} tiles "
          f"({total_bytes / 1_048_576:.1f} MB), zoom {MIN_ZOOM}-{MAX_ZOOM}.")


if __name__ == "__main__":
    main()
