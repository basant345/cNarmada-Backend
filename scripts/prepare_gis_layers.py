"""
Converts the uploaded GIS datasets (Dam_Details, Narmada_Waterbodies,
STP_Narmada, Geomorphological_Feature_Layer) into the formats the Spatial
Map's backend/frontend already know how to serve: GeoJSON for discrete
features (dams, waterbodies, STP districts), and a colored PNG + legend
JSON for the geomorphology class-coverage layer (same pattern as LULC,
since it's 15,635 polygons / 5.1M vertices — far too heavy to ship to the
browser as raw vector data).

Run once (or whenever the source data changes):

    python3 prepare_gis_layers.py /path/to/Data_For_Website30_07_2026

Requires pyshp (shapefile reading), pyproj (CRS reprojection — the Named
Network and STP shapefiles are in UTM, not lat/lon), numpy and Pillow
(already used by raster2png.py / climate_raster_to_png.py).

WHAT THIS DELIBERATELY DOES NOT PROCESS, AND WHY:
  - Narmada_Reservoirs/Reservoir_narmada.shp — verified empty (0 features,
    100-byte .shp = header only). There is no reservoir data to add; this
    script will refuse to run for it rather than fabricate anything.
  - "Narmada named network.rar" — verified to be the exact same 1,041-
    feature dataset already powering the site's existing "Tributary
    Network" layer (identical feature count, identical first record,
    identical Length values). Not reprocessed, to avoid duplicating an
    existing layer.
"""
import csv
import json
import os
import sys
import zipfile

import numpy as np
import shapefile
from PIL import Image, ImageDraw
from pyproj import Transformer

Image.MAX_IMAGE_PIXELS = None


def _ensure_extracted(source_dir, zip_filename, extracted_dirname):
    """The uploaded ZIP nests Narmada_Waterbodies.zip inside itself — unzip
    it in place the first time this script runs against that source_dir."""
    target = os.path.join(source_dir, extracted_dirname)
    if os.path.isdir(target):
        return target
    zip_path = os.path.join(source_dir, zip_filename)
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Expected either {target} or {zip_path} inside {source_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(source_dir)
    return target


def _round_coords(obj, ndigits=5):
    """Round every coordinate in a GeoJSON geometry's `coordinates` array to
    ndigits decimal places (~1.1m at this latitude) — cuts file size
    substantially versus raw float64 repr, with no visible loss of detail
    at web-map scale."""
    if isinstance(obj, (int, float)):
        return round(obj, ndigits)
    if isinstance(obj, (list, tuple)):
        return [_round_coords(x, ndigits) for x in obj]
    return obj


def _simplify_ring(points, tolerance=0.0003):
    """Douglas-Peucker line simplification (pure Python — the source
    geometry has a few very high-vertex-count outlier polygons; this trims
    them to web-map-appropriate detail without touching the many already-
    simple small features). tolerance is in degrees (~0.0003 deg ~= 30m)."""
    if len(points) <= 4:
        return points

    def perp_dist(pt, a, b):
        (x, y), (ax, ay), (bx, by) = pt, a, b
        dx, dy = bx - ax, by - ay
        if dx == dy == 0:
            return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
        t = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        px, py = ax + t * dx, ay + t * dy
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5

    def dp(pts):
        if len(pts) <= 2:
            return pts
        a, b = pts[0], pts[-1]
        idx, dmax = -1, 0.0
        for i in range(1, len(pts) - 1):
            d = perp_dist(pts[i], a, b)
            if d > dmax:
                idx, dmax = i, d
        if dmax > tolerance:
            left = dp(pts[:idx + 1])
            right = dp(pts[idx:])
            return left[:-1] + right
        return [a, b]

    simplified = dp(points)
    return simplified if len(simplified) >= 4 else points


def _simplify_coords(coords, geom_type, tolerance=0.0003):
    if geom_type == "Polygon":
        return [_simplify_ring(ring, tolerance) for ring in coords]
    if geom_type == "MultiPolygon":
        return [[_simplify_ring(ring, tolerance) for ring in poly] for poly in coords]
    return coords


def _out_paths(rasters_dir=None, geojson_dir=None):
    base = os.path.join(os.path.dirname(__file__), "..", "app", "static", "data")
    return (
        rasters_dir or os.path.join(base, "rasters"),
        geojson_dir or os.path.join(base, "geojson"),
    )


# ── 1. Dams ──────────────────────────────────────────────────────────────
def process_dams(source_dir, geojson_dir):
    """Dam_Details/Dams_OF_MP_within_NRB_corrext.db.dbf.csv already has
    Latitude/Longitude (WGS84) plus every dam attribute — no shapefile
    reprojection needed. Filtered to River_Basi == 'Narmada' using the
    dataset's own field (the source file mixes in a handful of dams from
    neighbouring basins despite its filename)."""
    csv_path = os.path.join(source_dir, "Dam_Details", "Dams_OF_MP_within_NRB_corrext.db.dbf.csv")
    features = []
    skipped_other_basin = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            basin = (row.get("River_Basi") or "").strip()
            if basin and basin != "Narmada":
                skipped_other_basin += 1
                continue
            try:
                lat, lon = float(row["Latitude"]), float(row["Longitude"])
            except (TypeError, ValueError):
                continue
            props = {
                "name": (row.get("Name_of_Da") or "").strip().title(),
                "operated_by": (row.get("Operated__") or "").strip(),
                "year_completed": (row.get("Year_of_Co") or "").strip(),
                "river_basin": basin,
                "river": (row.get("River") or "").strip(),
                "nearest_city": (row.get("Neareast_C") or "").strip(),
                "seismic_zone": (row.get("Seismic_Zo") or "").strip(),
                "dam_type": (row.get("Dam_Type") or "").strip().replace("_", " "),
                "height_m": _num(row.get("Height_abo")),
                "length_m": _num(row.get("Dam_Length")),
                "volume_content": _num(row.get("Volume_Con")),
                "gross_storage_capacity": _num(row.get("Gross_Stor")),
                "reservoir_area": _num(row.get("Reservoir")),
                "effective_storage_capacity": _num(row.get("Effective")),
                "purpose": (row.get("Purpose") or "").strip(),
                "designed_spillway_capacity": _num(row.get("Designed_S")),
            }
            props = {k: v for k, v in props.items() if v not in ("", None)}
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": props,
            })

    fc = {"type": "FeatureCollection", "features": features}
    out_path = os.path.join(geojson_dir, "dams.geojson")
    with open(out_path, "w") as f:
        json.dump(fc, f, indent=2)
    print(f"dams: {len(features)} features written to {out_path} "
          f"({skipped_other_basin} rows skipped — different river basin)")


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ── 2. Waterbodies ───────────────────────────────────────────────────────
def process_waterbodies(source_dir, geojson_dir):
    """Upper/Middle/Lower sub-basin shapefiles, already WGS84 — merged into
    one layer with a sub_basin tag. Internal Shape_Leng/Shape_Area (in
    unprojected degree units, not meaningful to a website visitor) are
    dropped; area_km2 (already present and correctly computed) is kept."""
    features = []
    waterbodies_dir = _ensure_extracted(source_dir, "Narmada_Waterbodies.zip", "Narmada_Waterbodies")
    for sub_basin in ["Upper", "Middle", "Lower"]:
        shp_path = os.path.join(waterbodies_dir, f"{sub_basin}.shp")
        sf = shapefile.Reader(shp_path)
        field_names = [f[0] for f in sf.fields if f[0] != "DeletionFlag"]
        for shape_rec in sf.iterShapeRecords():
            geom = shape_rec.shape.__geo_interface__
            rec = dict(zip(field_names, shape_rec.record))
            name = (rec.get("Name") or "").strip()
            remarks = (rec.get("Remarks") or rec.get("Remark") or "").strip()
            props = {
                "sub_basin": sub_basin,
                "name": name or None,
                "water_type": rec.get("waterType"),
                "area_km2": round(rec.get("area_km2"), 4) if rec.get("area_km2") is not None else None,
                "year": rec.get("year"),
                "remarks": remarks or None,
            }
            props = {k: v for k, v in props.items() if v not in (None, "")}
            simplified = _simplify_coords(geom["coordinates"], geom["type"])
            features.append({"type": "Feature", "geometry": {**geom, "coordinates": _round_coords(simplified)}, "properties": props})

    fc = {"type": "FeatureCollection", "features": features}
    out_path = os.path.join(geojson_dir, "waterbodies.geojson")
    with open(out_path, "w") as f:
        json.dump(fc, f)
    print(f"waterbodies: {len(features)} features written to {out_path}")


# ── 3. STP (district-level) ──────────────────────────────────────────────
def process_stp(source_dir, geojson_dir):
    """STPAdded.sjp.shp is district polygons in UTM Zone 44N with several
    redundant duplicate fields (an artifact of a prior join) — reprojected
    to WGS84 and de-duplicated to one clean attribute set per district."""
    shp_path = os.path.join(source_dir, "STP_Narmada", "STPAdded.sjp.shp")
    sf = shapefile.Reader(shp_path)
    transformer = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True)

    def reproject_rings(rings):
        return [[list(transformer.transform(x, y)) for x, y in ring] for ring in rings]

    features = []
    for shape_rec in sf.iterShapeRecords():
        shp = shape_rec.shape
        rec = shape_rec.record.as_dict()
        geo = shp.__geo_interface__
        if geo["type"] == "Polygon":
            coords = reproject_rings(geo["coordinates"])
        elif geo["type"] == "MultiPolygon":
            coords = [reproject_rings(poly) for poly in geo["coordinates"]]
        else:
            continue

        operational_stp = rec.get("Operationa")
        cap_mld = rec.get("Cap_MLD")
        props = {
            "district": (rec.get("District") or "").strip().title(),
            "state": (rec.get("STATE") or "").strip().title(),
            "sub_basin": rec.get("Sub_Basin") or None,
            "operational_stp_count": int(operational_stp) if operational_stp else 0,
            "capacity_mld": round(cap_mld, 2) if cap_mld else 0,
            "remarks": (rec.get("REMARKS") or "").strip() or None,
        }
        props = {k: v for k, v in props.items() if v is not None}
        simplified = _simplify_coords(coords, geo["type"], tolerance=0.0008)
        features.append({"type": "Feature", "geometry": {"type": geo["type"], "coordinates": _round_coords(simplified)}, "properties": props})

    fc = {"type": "FeatureCollection", "features": features}
    out_path = os.path.join(geojson_dir, "stp.geojson")
    with open(out_path, "w") as f:
        json.dump(fc, f)
    with_data = sum(1 for f in features if f["properties"].get("operational_stp_count", 0) > 0)
    print(f"stp: {len(features)} district polygons written to {out_path} ({with_data} with STP data)")


# ── 4. Geomorphology (rasterized — 15,635 polygons / 5.1M vertices is far
#      too heavy for the browser to render as vector data) ────────────────
def _class_color(index, total):
    """Deterministic, evenly-spaced, perceptually distinct color per class."""
    import colorsys
    hue = (index / max(total, 1)) % 1.0
    sat = 0.55 + 0.3 * ((index * 7) % 3) / 2  # vary saturation a bit so nearby hues stay distinguishable
    val = 0.75 + 0.2 * ((index * 5) % 2)
    r, g, b = colorsys.hsv_to_rgb(hue, min(sat, 0.9), min(val, 0.95))
    return int(r * 255), int(g * 255), int(b * 255)


def process_geomorphology(source_dir, rasters_dir, max_dim=1400):
    shp_path = os.path.join(
        source_dir, "Geomorphological_Feature_Layer", "Geomorphological_Feature_Layer_Final_Clipped.shp"
    )
    sf = shapefile.Reader(shp_path)
    bbox = sf.bbox  # [xmin, ymin, xmax, ymax], already WGS84

    classes = sorted({rec["GEOMORPHOL"] for rec in sf.records() if rec["GEOMORPHOL"]})
    class_color = {cls: _class_color(i, len(classes)) for i, cls in enumerate(classes)}

    west, south, east, north = bbox
    w_span, h_span = east - west, north - south
    if w_span >= h_span:
        img_w = max_dim
        img_h = max(1, round(max_dim * h_span / w_span))
    else:
        img_h = max_dim
        img_w = max(1, round(max_dim * w_span / h_span))

    def to_px(lon, lat):
        x = (lon - west) / w_span * img_w
        y = (north - lat) / h_span * img_h
        return x, y

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for shape_rec in sf.iterShapeRecords():
        cls = shape_rec.record["GEOMORPHOL"]
        if not cls:
            continue
        color = class_color[cls] + (235,)
        shp = shape_rec.shape
        if not shp.points:
            continue
        parts = list(shp.parts) + [len(shp.points)]
        for i in range(len(parts) - 1):
            ring = shp.points[parts[i]:parts[i + 1]]
            if len(ring) < 3:
                continue
            px_ring = [to_px(lon, lat) for lon, lat in ring]
            draw.polygon(px_ring, fill=color)

    out_png = os.path.join(rasters_dir, "geomorphology.png")
    img.save(out_png, optimize=True)

    meta = {
        "file": "rasters/geomorphology.png",
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "classes": [{"name": cls, "color": f"rgb({r},{g},{b})"} for cls, (r, g, b) in class_color.items()],
    }
    with open(os.path.join(rasters_dir, "geomorphology_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"geomorphology: {len(classes)} classes, {len(sf)} source polygons -> {out_png} ({img_w}x{img_h}px)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage: python3 prepare_gis_layers.py /path/to/Data_For_Website30_07_2026 [rasters_dir] [geojson_dir]")
        sys.exit(1)

    source_dir_arg = sys.argv[1]
    rasters_dir_arg, geojson_dir_arg = _out_paths(
        sys.argv[2] if len(sys.argv) > 2 else None,
        sys.argv[3] if len(sys.argv) > 3 else None,
    )
    os.makedirs(rasters_dir_arg, exist_ok=True)
    os.makedirs(geojson_dir_arg, exist_ok=True)

    process_dams(source_dir_arg, geojson_dir_arg)
    process_waterbodies(source_dir_arg, geojson_dir_arg)
    process_stp(source_dir_arg, geojson_dir_arg)
    process_geomorphology(source_dir_arg, rasters_dir_arg)
