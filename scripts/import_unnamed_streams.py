"""
Import the verified unnamed stream network into the River Atlas, complete.

Source: Narmada_Unnamed_Streams.geojson (CRS84, one feature per line, as
written by ogr2ogr). 488,755 reaches, about 350 MB.

Every reach is published, and every reach is published exactly as it is in
the source: each feature is copied byte for byte from its source line. No
simplification, no coordinate rounding, no property cleaning.

Why the layer is split
----------------------
350 MB is too much for one file. It is over GitHub's 100 MB file limit,
too big for Render's free tier to hold, and far more than a browser can
download and draw at once. So the same features are split by Strahler
order, the way a printed atlas shows more detail as the scale grows:

  overview   order >= 4    one file, drawn at every zoom level
  order_3    order 3       tiles, drawn once the map is zoomed in
  order_0_2  orders 0-2    tiles, drawn once the map is zoomed in further

The three parts do not overlap. Each source feature lands in exactly one
file, in the tile that holds the centre of its bounding box. The script
checks this at the end: the published features, taken together, are the
source features, one for one, with nothing added, dropped or changed.

Output (app/static/data/river_atlas/):
  unnamed_streams.geojson(.gz)                       the overview
  tiles/unnamed_streams/<band>/<z>/<x>/<y>.geojson.gz the tiles (gzip only)
  catalog.json                        only the unnamed_streams entry changes

Then run render_unnamed_raster.py, which draws all of them as map images
for the zoomed-out view.

Usage (from the backend folder):
    python scripts/import_unnamed_streams.py \
        --source "path/to/Narmada_Unnamed_Streams.geojson"

Needs about 1.5 GB of free RAM while it runs.
"""

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "app", "static", "data", "river_atlas"))
LAYER_ID = "unnamed_streams"
OVERVIEW_NAME = "unnamed_streams.geojson"
TILE_ROOT = os.path.join(OUT_DIR, "tiles", LAYER_ID)

# Everything at or above this order goes into the overview file.
OVERVIEW_MIN_ORDER = 4

# The tiled bands. tile_zoom is the XYZ grid the band is cut on; min_zoom is
# the map zoom from which the page starts drawing it. Both were chosen from
# measured tile sizes so one screenful stays at a few MB, and both are
# published in the catalogue, so the page reads them rather than knowing them.
BANDS = [
    {"id": "order_3", "orders": [3], "tile_zoom": 10, "min_zoom": 10},
    {"id": "order_0_2", "orders": [0, 1, 2], "tile_zoom": 11, "min_zoom": 12},
]

# The source uses "0" for "this reach has no name" and 0.0 for "no overlap
# with the named network". The data keeps those values; the catalogue tells
# the popup to treat them as empty.
ABSENT_VALUES = {"River_Name": ["0", ""], "_overlap_p": [0]}


# ── XYZ (Web Mercator) tile maths, the same scheme Leaflet uses ──────────
def tile_x(lon, z):
    n = 2 ** z
    return min(n - 1, max(0, int((lon + 180.0) / 360.0 * n)))


def tile_y(lat, z):
    n = 2 ** z
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return min(n - 1, max(0, int(y)))


def bbox(geom):
    xs, ys = [], []
    parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
    for part in parts:
        for p in part:
            xs.append(p[0])
            ys.append(p[1])
    return min(xs), min(ys), max(xs), max(ys), sum(len(part) for part in parts)


# ── Source reading ────────────────────────────────────────────────────────
def read_source(path):
    """Return (header_lines, iterator of (text, feature))."""
    header = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for raw in fh:
            if raw.strip().startswith('{ "type": "Feature"'):
                break
            header.append(raw.rstrip("\r\n"))

    def features():
        with open(path, "r", encoding="utf-8", newline="") as fh:
            for raw in fh:
                s = raw.strip()
                if not s.startswith('{ "type": "Feature"'):
                    continue
                text = s[:-1] if s.endswith(",") else s
                yield text, json.loads(text)

    return header, features()


def collection_text(header, lines):
    """A FeatureCollection with the source's own header and verbatim features."""
    return "\n".join(header) + "\n" + ",\n".join(lines) + "\n]\n}\n"


def digest(text):
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest()


def write_gz(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) as gz:
            gz.write(data)


def main():
    ap = argparse.ArgumentParser(description="Import the verified unnamed stream GeoJSON.")
    ap.add_argument("--source", required=True, help="Narmada_Unnamed_Streams.geojson")
    args = ap.parse_args()
    if not os.path.isfile(args.source):
        sys.exit(f"Source not found: {args.source}")

    order_to_band = {o: b["id"] for b in BANDS for o in b["orders"]}
    band_by_id = {b["id"]: b for b in BANDS}

    header, feats = read_source(args.source)

    overview = []
    tiles = {b["id"]: collections.defaultdict(list) for b in BANDS}
    band_stats = {b["id"]: {"features": 0, "km": 0.0, "half_extent": 0.0} for b in BANDS}
    source_digests = collections.Counter()
    src_count, src_km = 0, 0.0
    overview_km, overview_vertices = 0.0, 0
    unplaced = collections.Counter()

    print("Reading source ...")
    for text, feat in feats:
        src_count += 1
        source_digests[digest(text)] += 1
        props = feat.get("properties") or {}
        km = float(props.get("Length") or 0.0) / 1000.0
        src_km += km
        order = int(props.get("River_Orde") or 0)
        x0, y0, x1, y1, nverts = bbox(feat["geometry"])

        if order >= OVERVIEW_MIN_ORDER:
            overview.append(text)
            overview_km += km
            overview_vertices += nverts
            continue

        band_id = order_to_band.get(order)
        if band_id is None:
            unplaced[order] += 1
            continue
        band = band_by_id[band_id]
        # Home tile: the tile holding the centre of the feature's bbox.
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        key = (tile_x(cx, band["tile_zoom"]), tile_y(cy, band["tile_zoom"]))
        tiles[band_id][key].append(text)
        st = band_stats[band_id]
        st["features"] += 1
        st["km"] += km
        # How far a feature can reach past its home tile. The page pads the
        # view by this much, so no reach that crosses the screen is missed.
        st["half_extent"] = max(st["half_extent"], (x1 - x0) / 2.0, (y1 - y0) / 2.0)

    if unplaced:
        sys.exit(f"Orders with no band: {dict(unplaced)}. Add them to BANDS.")

    # ── Write the overview ──
    os.makedirs(OUT_DIR, exist_ok=True)
    overview_path = os.path.join(OUT_DIR, OVERVIEW_NAME)
    overview_bytes = collection_text(header, overview).encode("utf-8")
    with open(overview_path + ".tmp", "wb") as fh:
        fh.write(overview_bytes)
    os.replace(overview_path + ".tmp", overview_path)
    write_gz(overview_path + ".gz", overview_bytes)

    # ── Write the tiles (old tiles of each band are removed first; the
    #    image tiles from render_unnamed_raster.py are left alone) ──
    for band in BANDS:
        band_dir = os.path.join(TILE_ROOT, band["id"])
        if os.path.isdir(band_dir):
            shutil.rmtree(band_dir)
    tile_bytes_total = 0
    for band in BANDS:
        z = band["tile_zoom"]
        for (x, y), lines in tiles[band["id"]].items():
            path = os.path.join(TILE_ROOT, band["id"], str(z), str(x), f"{y}.geojson.gz")
            write_gz(path, collection_text(header, lines).encode("utf-8"))
            tile_bytes_total += os.path.getsize(path)

    # ── Verify: read back everything that was written, compare to source ──
    print("Verifying ...")
    published = collections.Counter()
    json.loads(overview_bytes)  # the overview must be valid GeoJSON
    with gzip.open(overview_path + ".gz", "rb") as fh:
        if fh.read() != overview_bytes:
            sys.exit("Overview gzip round-trip failed.")

    def published_lines(text):
        body = text.split('"features": [\n', 1)[1].rsplit("\n]\n}\n", 1)[0]
        return body.split(",\n") if body else []

    for text in published_lines(overview_bytes.decode("utf-8")):
        published[digest(text)] += 1
    for band in BANDS:
        z = band["tile_zoom"]
        for (x, y) in tiles[band["id"]]:
            path = os.path.join(TILE_ROOT, band["id"], str(z), str(x), f"{y}.geojson.gz")
            with gzip.open(path, "rb") as fh:
                text = fh.read().decode("utf-8")
            json.loads(text)  # every tile must be valid GeoJSON
            for line in published_lines(text):
                published[digest(line)] += 1

    if published != source_digests:
        missing = sum((source_digests - published).values())
        extra = sum((published - source_digests).values())
        sys.exit(f"Published set differs from source: {missing} missing, {extra} extra.")
    total_published = sum(published.values())

    # ── Catalogue: update the unnamed_streams entry only ──
    cat_path = os.path.join(OUT_DIR, "catalog.json")
    with open(cat_path, encoding="utf-8") as fh:
        catalog = json.load(fh)
    entry = next((l for l in catalog["layers"] if l["id"] == LAYER_ID), None)
    if entry is None:
        sys.exit("unnamed_streams missing from catalog.json. Run build_river_atlas.py first.")

    entry["file"] = OVERVIEW_NAME
    entry["geometry_type"] = "MultiLineString"
    entry["feature_count"] = total_published
    entry["source"] = "Narmada_Unnamed_Streams.geojson (verified, CRS84), published complete and unmodified"
    entry.pop("constants", None)
    for f in entry.get("fields", []):
        if f["key"] in ABSENT_VALUES:
            f["absent_values"] = ABSENT_VALUES[f["key"]]
        else:
            f.pop("absent_values", None)

    entry["coverage"] = {
        "source_features": src_count,
        "published_features": total_published,
        "source_length_km": round(src_km, 1),
        "overview_min_order": OVERVIEW_MIN_ORDER,
        "overview_features": len(overview),
        "overview_length_km": round(overview_km, 1),
        "overview_vertices": overview_vertices,
    }
    entry["tiles"] = {
        "scheme": "xyz",
        "url": f"/api/river-atlas/layer/{LAYER_ID}/tile/{{band}}/{{z}}/{{x}}/{{y}}",
        "bands": [
            {
                "id": b["id"],
                "orders": b["orders"],
                "tile_zoom": b["tile_zoom"],
                "min_zoom": b["min_zoom"],
                "pad_deg": round(math.ceil(band_stats[b["id"]]["half_extent"] * 1e4) / 1e4, 4),
                "feature_count": band_stats[b["id"]]["features"],
                "length_km": round(band_stats[b["id"]]["km"], 1),
                # Only tiles that exist, so the page never asks for an empty one.
                "tiles": sorted([x, y] for (x, y) in tiles[b["id"]]),
            }
            for b in BANDS
        ],
    }
    # With the image tiles from render_unnamed_raster.py every reach is
    # visible at every zoom. Without them, tell people to zoom in.
    if entry.get("raster"):
        entry.pop("zoom_hint", None)
        entry.pop("zoom_hint_hi", None)
    else:
        first = min(b["min_zoom"] for b in BANDS)
        entry["zoom_hint"] = f"Zoom in to see smaller streams (from zoom {first})."
        entry["zoom_hint_hi"] = f"छोटी धाराएँ देखने के लिए ज़ूम इन करें (ज़ूम {first} से)।"
    def orders_label(orders):
        return str(orders[0]) if len(orders) == 1 else f"{orders[0]}-{orders[-1]}"

    entry["note"] = (
        f"All {total_published:,} reaches, original geometry and attributes, unmodified. "
        f"Order {OVERVIEW_MIN_ORDER}+ at every zoom; "
        + "; ".join(f"order {orders_label(b['orders'])} from zoom {b['min_zoom']}" for b in BANDS)
        + "."
    )
    entry["note_hi"] = (
        f"सभी {total_published:,} खंड, मूल ज्यामिति और गुण, बिना किसी बदलाव के। "
        f"क्रम {OVERVIEW_MIN_ORDER}+ हर ज़ूम पर; छोटे क्रम ज़ूम इन करने पर।"
    )

    with open(cat_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    mb = lambda n: n / 1_048_576
    print(f"\nSource    : {src_count:,} reaches, {src_km:,.1f} km")
    print(f"Published : {total_published:,} reaches (all of them)")
    print(f"  overview (order >= {OVERVIEW_MIN_ORDER}): {len(overview):,} reaches, "
          f"{mb(len(overview_bytes)):.1f} MB, gz {mb(os.path.getsize(overview_path + '.gz')):.1f} MB")
    for b in BANDS:
        st = band_stats[b["id"]]
        print(f"  {b['id']:<10} {st['features']:>8,} reaches in {len(tiles[b['id']]):>4} tiles "
              f"(z{b['tile_zoom']}, drawn from map zoom {b['min_zoom']})")
    print(f"  tiles on disk: {mb(tile_bytes_total):.1f} MB gzip")
    print("Verified: published features equal the source, one for one, byte for byte.")


if __name__ == "__main__":
    main()
