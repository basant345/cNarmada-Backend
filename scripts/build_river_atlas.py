"""
Build the River Atlas GeoJSON layers and their catalogue from the source
shapefiles.

The River Atlas page is fully data-driven: the frontend fetches
/api/river-atlas/layers, and everything it draws — layer list, legend,
colours, draw order, default visibility, popup field labels — comes from
the catalogue this script writes. Adding a new River Atlas dataset later
means dropping a .geojson into app/static/data/river_atlas/ and adding one
entry to catalog.json; no frontend change is needed.

Usage
-----
    python scripts/build_river_atlas.py \
        --named  "path/to/NARMADA_NAMED_NETWORK.shp" \
        --unnamed "path/to/Unnamed_Streams_Narmada.shp" \
        [--min-order 4]

The basin polygon is taken from the existing
app/static/data/geojson/basin_boundary.geojson, so the River Atlas and the
GeoSpatial page always show the same basin outline.

Source CRS
----------
  NARMADA_NAMED_NETWORK  : EPSG:32643 (WGS 84 / UTM zone 43N) -> reprojected
  Unnamed_Streams_Narmada: EPSG:4326 already (geographic, degrees)

Nothing is written until every layer has been built and validated, so a
failure part-way through can never leave a half-written dataset on disk.
"""

import argparse
import gzip
import json
import os
import sys
from datetime import date

try:
    import shapefile  # pyshp
except ImportError:  # pragma: no cover
    sys.exit("pyshp is required:  pip install pyshp")

try:
    from pyproj import Transformer
except ImportError:  # pragma: no cover
    sys.exit("pyproj is required:  pip install pyproj")


# ── Paths ────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "app", "static", "data")
GEOJSON_DIR = os.path.join(DATA_DIR, "geojson")
OUT_DIR = os.path.join(DATA_DIR, "river_atlas")

# The single feature in the named network that is the Narmada main stem.
CENTRE_LINE_NAME = "Narmada River"

# Source fields that carry no information in these files and are dropped so
# popups do not show empty rows. Re-check with --audit if the source changes.
DROP_FIELDS = {"C_Bank"}

COORD_DP = 5           # ~1.1 m — finer than the source data warrants
TOL_NAMED = 0.00010    # ~11 m  Douglas-Peucker tolerance, degrees
TOL_UNNAMED = 0.00010  # ~11 m

# Fields whose value is 0 means "none / not applicable" rather than a
# measurement of zero, so the row is omitted from the popup instead of
# showing a meaningless "0".
ZERO_IS_ABSENT = {"_overlap_p"}


# ── Geometry helpers ─────────────────────────────────────────────────────
def _perp_dist(p, a, b):
    """Perpendicular distance from p to segment a-b, in degrees."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def simplify(points, tol):
    """Douglas-Peucker, iterative so long lines cannot blow the stack."""
    if tol <= 0 or len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        worst, wi = -1.0, -1
        a, b = points[lo], points[hi]
        for i in range(lo + 1, hi):
            d = _perp_dist(points[i], a, b)
            if d > worst:
                worst, wi = d, i
        if worst > tol:
            keep[wi] = True
            stack.append((lo, wi))
            stack.append((wi, hi))
    out = [p for p, k in zip(points, keep) if k]
    return out if len(out) >= 2 else points[:2]


def round_pts(points, dp=COORD_DP):
    """Round, then drop consecutive duplicates the rounding created."""
    out = []
    for x, y in points:
        p = [round(x, dp), round(y, dp)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def line_geometry(shape, transform=None, tol=0.0):
    """Shapefile polyline -> LineString / MultiLineString, or None."""
    pts = shape.points
    if transform is not None:
        pts = [transform(x, y) for x, y in pts]
    bounds = list(shape.parts) + [len(pts)]
    parts = []
    for a, b in zip(bounds, bounds[1:]):
        seg = round_pts(simplify(pts[a:b], tol))
        if len(seg) >= 2:
            parts.append(seg)
    if not parts:
        return None
    if len(parts) == 1:
        return {"type": "LineString", "coordinates": parts[0]}
    return {"type": "MultiLineString", "coordinates": parts}


def count_vertices(geom):
    t = geom["type"]
    c = geom["coordinates"]
    if t == "LineString":
        return len(c)
    if t in ("MultiLineString", "Polygon"):
        return sum(len(p) for p in c)
    if t == "MultiPolygon":
        return sum(len(r) for p in c for r in p)
    return 1


def clean_props(raw):
    """Drop empty / placeholder values so popups show real data only."""
    out = {}
    for k, v in raw.items():
        if k in DROP_FIELDS:
            continue
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            # "0" is the source's placeholder for "this reach has no name".
            if v == "" or v == "0":
                continue
        elif isinstance(v, float):
            if v != v:  # NaN
                continue
            v = round(v, 5)
        if k in ZERO_IS_ABSENT and not v:
            continue
        out[k] = v
    return out


def hoist_constants(features):
    """
    Move fields that carry the same value on every feature out of the
    features and return them separately.

    A field like STATUS="UNNAMED", identical on 29,887 reaches, is a
    property of the layer rather than of any one reach. Repeating it per
    feature costs close to a megabyte and tells the reader nothing new, so
    it is published once in the catalogue instead. No information is lost:
    the River Atlas popup shows catalogue constants alongside the
    per-feature values.
    """
    if not features:
        return {}
    shared = None
    for feat in features:
        props = feat.get("properties") or {}
        if shared is None:
            shared = dict(props)
            continue
        for key in list(shared):
            if key not in props or props[key] != shared[key]:
                del shared[key]
        if not shared:
            break
    shared = shared or {}
    # A field present on only some features is per-feature data, not a
    # layer constant, so require full coverage before hoisting.
    shared = {k: v for k, v in shared.items()
              if all(k in (f.get("properties") or {}) for f in features)}
    if shared:
        for feat in features:
            for key in shared:
                feat["properties"].pop(key, None)
    return shared


def read_records(path):
    r = shapefile.Reader(path)
    names = [f[0] for f in r.fields if f[0] != "DeletionFlag"]
    for shape, rec in zip(r.iterShapes(), r.iterRecords()):
        yield shape, dict(zip(names, list(rec)))
    r.close()


# ── Layer builders ───────────────────────────────────────────────────────
def build_named(shp_path):
    """Named network -> (named_streams FC, centre_line FC)."""
    to_wgs84 = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
    tf = lambda x, y: to_wgs84.transform(x, y)  # noqa: E731

    named, centre = [], []
    for shape, props in read_records(shp_path):
        geom = line_geometry(shape, transform=tf, tol=TOL_NAMED)
        if geom is None:
            continue
        feature = {"type": "Feature", "geometry": geom,
                   "properties": clean_props(props)}
        is_centre = str(props.get("River_Name", "")).strip() == CENTRE_LINE_NAME
        (centre if is_centre else named).append(feature)

    if not centre:
        raise ValueError(
            f"No feature named {CENTRE_LINE_NAME!r} in {shp_path} — cannot "
            "separate the centre line from the named network."
        )
    return (
        {"type": "FeatureCollection", "features": named},
        {"type": "FeatureCollection", "features": centre},
    )


def build_unnamed(shp_path, min_order):
    """Unnamed network, filtered to Strahler order >= min_order."""
    features = []
    src_count = 0
    src_km = 0.0
    kept_km = 0.0
    for shape, props in read_records(shp_path):
        src_count += 1
        length_m = float(props.get("Length") or 0.0)
        src_km += length_m / 1000.0
        if int(props.get("River_Orde") or 0) < min_order:
            continue
        geom = line_geometry(shape, tol=TOL_UNNAMED)
        if geom is None:
            continue
        kept_km += length_m / 1000.0
        features.append({"type": "Feature", "geometry": geom,
                         "properties": clean_props(props)})
    stats = {
        "min_stream_order": min_order,
        "served_features": len(features),
        "source_features": src_count,
        "served_length_km": round(kept_km, 1),
        "source_length_km": round(src_km, 1),
    }
    return {"type": "FeatureCollection", "features": features}, stats


def build_basin():
    """Reuse the basin polygon the GeoSpatial page already serves."""
    src = os.path.join(GEOJSON_DIR, "basin_boundary.geojson")
    if not os.path.exists(src):
        raise FileNotFoundError(f"Missing {src}")
    with open(src, encoding="utf-8") as fh:
        fc = json.load(fh)
    for feat in fc.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            geom["coordinates"] = [round_pts(r) for r in geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            geom["coordinates"] = [[round_pts(r) for r in p]
                                   for p in geom["coordinates"]]
        feat["properties"] = clean_props(feat.get("properties") or {})
    return fc


# ── Catalogue ────────────────────────────────────────────────────────────
STREAM_FIELDS_NAMED = [
    {"key": "River_Name", "label": "River name", "label_hi": "नदी का नाम"},
    {"key": "Basin", "label": "Basin", "label_hi": "बेसिन"},
    {"key": "River_Code", "label": "River code", "label_hi": "नदी कोड"},
    {"key": "Length", "label": "Length", "label_hi": "लंबाई", "unit": "km"},
    {"key": "Shape_Leng", "label": "Mapped length", "label_hi": "मानचित्रित लंबाई", "unit": "m"},
    {"key": "START_X", "label": "Start longitude", "label_hi": "प्रारंभ देशांतर", "unit": "°E"},
    {"key": "START_Y", "label": "Start latitude", "label_hi": "प्रारंभ अक्षांश", "unit": "°N"},
    {"key": "END_X", "label": "End longitude", "label_hi": "अंत देशांतर", "unit": "°E"},
    {"key": "END_Y", "label": "End latitude", "label_hi": "अंत अक्षांश", "unit": "°N"},
    {"key": "OBJECTID", "label": "Feature ID", "label_hi": "फ़ीचर आईडी"},
]

STREAM_FIELDS_UNNAMED = [
    {"key": "River_Name", "label": "River name", "label_hi": "नदी का नाम"},
    {"key": "River_Orde", "label": "Stream order", "label_hi": "धारा क्रम"},
    {"key": "Length", "label": "Length", "label_hi": "लंबाई", "unit": "m"},
    {"key": "_overlap_p", "label": "Overlap with named network",
     "label_hi": "नामित नेटवर्क से अतिव्यापन", "unit": "%"},
    {"key": "STATUS", "label": "Status", "label_hi": "स्थिति"},
]


def make_catalog(counts, unnamed_stats, constants):
    get_const = lambda lid: constants.get(lid) or {}  # noqa: E731
    return {
        "generated_on": date.today().isoformat(),
        "title": "Narmada River Atlas",
        "title_hi": "नर्मदा नदी एटलस",
        "fit_layer": "basin",
        "attribution": "cNARMADA, Indian Institute of Technology Indore",
        "layers": [
            {
                "id": "basin",
                "file": "basin.geojson",
                "name": "Narmada Basin",
                "name_hi": "नर्मदा बेसिन",
                "description": "Outer boundary of the Narmada river basin.",
                "description_hi": "नर्मदा नदी बेसिन की बाहरी सीमा।",
                "geometry_type": "Polygon",
                "feature_count": counts["basin"],
                "default_visible": True,
                "z_index": 1,
                "canvas": False,
                "style": {"color": "#14532d", "weight": 1.4, "opacity": 1,
                          "fill": True, "fillColor": "#ecfdf3", "fillOpacity": 0.7},
                "highlight_style": {"color": "#052e16", "weight": 2.6, "fillOpacity": 0.3},
                "legend": {"type": "fill", "color": "#14532d", "fillColor": "#ecfdf3"},
                "label_field": "Name",
                "fields": [{"key": "Name", "label": "Basin", "label_hi": "बेसिन"},
                           {"key": "id", "label": "Feature ID", "label_hi": "फ़ीचर आईडी"}],
                "source": "cNARMADA basin boundary dataset",
                "constants": get_const("basin"),
            },
            {
                "id": "unnamed_streams",
                "file": "unnamed_streams.geojson",
                "name": "Unnamed Stream Network",
                "name_hi": "अनाम धारा नेटवर्क",
                "description": "Unnamed stream reaches draining the basin, carrying "
                               "Strahler stream order and reach length.",
                "description_hi": "बेसिन को अपवाहित करने वाली अनाम धाराएँ, जिनमें "
                                  "स्ट्रालर धारा क्रम और लंबाई दर्ज है।",
                "geometry_type": "LineString",
                "feature_count": counts["unnamed_streams"],
                "default_visible": False,
                "z_index": 2,
                "canvas": True,
                "style": {"color": "#000000", "weight": 0.6, "opacity": 0.85},
                "highlight_style": {"color": "#000000", "weight": 2.5, "opacity": 1},
                "legend": {"type": "line", "color": "#000000", "weight": 1.5},
                "label_field": None,
                "fields": STREAM_FIELDS_UNNAMED,
                "source": "Unnamed_Streams_Narmada (basin-wide stream delineation)",
                "constants": get_const("unnamed_streams"),
                "coverage": unnamed_stats,
                "note": "Large layer — drawn on a canvas renderer and off by default. "
                        "Served at Strahler order {min_stream_order} and above "
                        "({served_features:,} of {source_features:,} source reaches)."
                        .format(**unnamed_stats),
                "note_hi": "बड़ी परत — कैनवास रेंडरर पर बनाई जाती है और डिफ़ॉल्ट रूप से बंद है। "
                           "स्ट्रालर क्रम {min_stream_order} और उससे ऊपर पर उपलब्ध "
                           "({served_features:,} / {source_features:,} स्रोत खंड)।"
                           .format(**unnamed_stats),
            },
            {
                "id": "named_streams",
                "file": "named_streams.geojson",
                "name": "Named Stream Network",
                "name_hi": "नामित धारा नेटवर्क",
                "description": "Named tributaries of the Narmada, with river code, "
                               "length and end-point coordinates.",
                "description_hi": "नर्मदा की नामित सहायक नदियाँ, नदी कोड, लंबाई और "
                                  "छोर के निर्देशांक सहित।",
                "geometry_type": "LineString",
                "feature_count": counts["named_streams"],
                "default_visible": True,
                "z_index": 3,
                "canvas": False,
                "style": {"color": "#2f7fd0", "weight": 1.1, "opacity": 0.95},
                "highlight_style": {"color": "#0b3d91", "weight": 3, "opacity": 1},
                "legend": {"type": "line", "color": "#2f7fd0", "weight": 2},
                "label_field": "River_Name",
                "fields": STREAM_FIELDS_NAMED,
                "source": "NARMADA_NAMED_NETWORK (reprojected from UTM zone 43N)",
                "constants": get_const("named_streams"),
            },
            {
                "id": "centre_line",
                "file": "centre_line.geojson",
                "name": "Narmada Centre Line",
                "name_hi": "नर्मदा केंद्र रेखा",
                "description": "Main stem of the Narmada, Amarkantak to the Gulf of Khambhat.",
                "description_hi": "नर्मदा की मुख्य धारा, अमरकंटक से खंभात की खाड़ी तक।",
                "geometry_type": "LineString",
                "feature_count": counts["centre_line"],
                "default_visible": True,
                "z_index": 4,
                "canvas": False,
                "style": {"color": "#1f6fc4", "weight": 3.2, "opacity": 1,
                          "lineCap": "round", "lineJoin": "round"},
                "highlight_style": {"color": "#0b3d91", "weight": 5, "opacity": 1},
                "legend": {"type": "line", "color": "#1f6fc4", "weight": 4},
                "label_field": "River_Name",
                "fields": STREAM_FIELDS_NAMED,
                "source": "NARMADA_NAMED_NETWORK (reprojected from UTM zone 43N)",
                "constants": get_const("centre_line"),
            },
        ],
    }


# ── Validation ───────────────────────────────────────────────────────────
BASIN_BBOX = (72.0, 21.0, 82.5, 24.5)  # generous box around the Narmada basin


def validate(name, fc, expect_min=1):
    feats = fc.get("features", [])
    if len(feats) < expect_min:
        raise ValueError(f"{name}: only {len(feats)} features, expected >= {expect_min}")
    verts = 0
    xs_bad = 0
    for f in feats:
        g = f.get("geometry")
        if not g or not g.get("coordinates"):
            raise ValueError(f"{name}: a feature has no geometry")
        verts += count_vertices(g)
        coords = g["coordinates"]
        flat = coords if g["type"] == "LineString" else [p for part in coords for p in part]
        for x, y in flat[:4]:
            if not (BASIN_BBOX[0] <= x <= BASIN_BBOX[2] and BASIN_BBOX[1] <= y <= BASIN_BBOX[3]):
                xs_bad += 1
                break
    if xs_bad:
        raise ValueError(
            f"{name}: {xs_bad} features fall outside the Narmada bounding box — "
            "the source is probably projected and was not reprojected."
        )
    return len(feats), verts


def main():
    ap = argparse.ArgumentParser(description="Build the River Atlas layers.")
    ap.add_argument("--named", required=True, help="NARMADA_NAMED_NETWORK.shp")
    ap.add_argument("--unnamed", required=True, help="Unnamed_Streams_Narmada.shp")
    ap.add_argument("--min-order", type=int, default=4,
                    help="Lowest Strahler stream order to publish for the "
                         "unnamed network (default 4). Lower means a much "
                         "larger file: order 3 is ~3x, order 1 is ~16x.")
    args = ap.parse_args()

    for p in (args.named, args.unnamed):
        if not os.path.exists(p):
            sys.exit(f"Not found: {p}")

    print("Reading basin boundary ...")
    basin = build_basin()

    print("Reading named network (reprojecting UTM 43N -> WGS84) ...")
    named, centre = build_named(args.named)

    print(f"Reading unnamed network (order >= {args.min_order}) ...")
    unnamed, unnamed_stats = build_unnamed(args.unnamed, args.min_order)

    layers = {
        "basin": basin,
        "named_streams": named,
        "centre_line": centre,
        "unnamed_streams": unnamed,
    }

    # Validate everything BEFORE writing anything.
    print("\nValidating ...")
    counts = {}
    for lid, fc in layers.items():
        n, v = validate(lid, fc)
        counts[lid] = n
        print(f"  {lid:<16} {n:>7,} features  {v:>9,} vertices")

    if counts["centre_line"] != 1:
        raise ValueError(f"centre_line should hold exactly 1 feature, got {counts['centre_line']}")

    # Fields identical on every feature of a layer are published once in the
    # catalogue instead of being repeated on each feature. Only worthwhile
    # on the large layers; on a one- or two-feature layer every field would
    # trivially qualify and the features would be left empty.
    constants = {}
    for lid, fc in layers.items():
        if len(fc["features"]) >= 50:
            shared = hoist_constants(fc["features"])
            if shared:
                constants[lid] = shared
                print(f"  {lid}: hoisted constant field(s) "
                      + ", ".join(f"{k}={v!r}" for k, v in shared.items()))

    catalog = make_catalog(counts, unnamed_stats, constants)

    os.makedirs(OUT_DIR, exist_ok=True)
    print()
    for layer in catalog["layers"]:
        path = os.path.join(OUT_DIR, layer["file"])
        payload = json.dumps(layers[layer["id"]], separators=(",", ":"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload)

        # A pre-compressed twin. The layer endpoint serves this, with
        # Content-Encoding: gzip, to any client that accepts gzip — which is
        # every browser — and falls back to the plain file otherwise. Doing
        # it here rather than per request keeps a free-tier dyno from
        # re-compressing several megabytes on every page load, and avoids
        # adding a compression dependency that would affect every other
        # endpoint in the app.
        gz_path = path + ".gz"
        with gzip.GzipFile(gz_path, "wb", compresslevel=9, mtime=0) as gz:
            gz.write(payload.encode("utf-8"))

        print(f"  wrote {layer['file']:<26} {os.path.getsize(path)/1e6:>7.2f} MB"
              f"   (gzip {os.path.getsize(gz_path)/1e6:.2f} MB)")

    cat_path = os.path.join(OUT_DIR, "catalog.json")
    with open(cat_path, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
    print(f"  wrote {'catalog.json':<26} {os.path.getsize(cat_path)/1e6:>7.2f} MB")

    print(f"\nUnnamed network: {unnamed_stats['served_features']:,} of "
          f"{unnamed_stats['source_features']:,} reaches "
          f"({unnamed_stats['served_length_km']:,.0f} of "
          f"{unnamed_stats['source_length_km']:,.0f} km)")
    print("Done.")


if __name__ == "__main__":
    main()
