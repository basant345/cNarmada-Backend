"""
Build the Water Body Atlas layers and the shared district boundaries.

Inputs, exactly as supplied
--------------------------
  Narmada_Waterbodies/Upper.shp, Middle.shp, Lower.shp
      8,630 water body polygons (WGS 84), attributes:
      OBJECTID, year, area_m2, count, area_km2, water, waterType,
      Shape_Leng, Shape_Area, Name, Remarks/Remark.
      A feature is "named" when its Name field is not empty; the rest are
      unnamed. Nothing is renamed, merged, simplified or invented here.

  Narmada_District.geojson (or the Narmada district shapefile)
      40 district polygons with their own attributes (NAME_0/1/2, ID_*,
      HASC_2, TYPE_2, VARNAME_2 ...). Copied through untouched, so the
      district boundaries drawn on the site are the supplied ones.

Output (app/static/data/water_atlas/)
-------------------------------------
  named_water_bodies.geojson(.gz)     Name is present
  unnamed_water_bodies.geojson(.gz)   Name is empty
  districts.geojson(.gz)              the supplied district boundaries
  catalog.json                        style, draw order, popup labels

The only attribute this script adds is `sub_basin` (Upper / Middle /
Lower), which records which of the three supplied files a polygon came
from. Every other attribute and every coordinate is passed through as
read from the shapefile.

Usage (from the backend folder):
    python scripts/build_water_atlas.py \
        --waterbodies "path/to/Narmada_Waterbodies" \
        --districts "path/to/Narmada_District.geojson"
"""

import argparse
import gzip
import json
import os
import sys

try:
    import shapefile  # pyshp
except ImportError:
    sys.exit("Needs pyshp: pip install pyshp")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "app", "static", "data", "water_atlas"))

SUB_BASINS = ["Upper", "Middle", "Lower"]
NAME_FIELD = "Name"

# Popup rows, in the order the supplied attributes are worth reading.
WB_FIELDS = [
    {"key": "Name", "label": "Name", "label_hi": "नाम"},
    {"key": "sub_basin", "label": "Sub-basin", "label_hi": "उप-बेसिन"},
    {"key": "area_km2", "label": "Area", "label_hi": "क्षेत्रफल", "unit": "km²"},
    {"key": "area_m2", "label": "Area", "label_hi": "क्षेत्रफल", "unit": "m²"},
    {"key": "waterType", "label": "Water type", "label_hi": "जल प्रकार"},
    {"key": "year", "label": "Year", "label_hi": "वर्ष"},
    {"key": "OBJECTID", "label": "Object ID", "label_hi": "ऑब्जेक्ट आईडी"},
    {"key": "Remarks", "label": "Remarks", "label_hi": "टिप्पणी"},
    {"key": "Remark", "label": "Remarks", "label_hi": "टिप्पणी"},
]

DISTRICT_FIELDS = [
    {"key": "NAME_2", "label": "District", "label_hi": "जिला"},
    {"key": "NAME_1", "label": "State", "label_hi": "राज्य"},
    {"key": "NAME_0", "label": "Country", "label_hi": "देश"},
    {"key": "TYPE_2", "label": "Type", "label_hi": "प्रकार"},
    {"key": "ENGTYPE_2", "label": "Type (English)", "label_hi": "प्रकार (अंग्रेज़ी)"},
    {"key": "HASC_2", "label": "HASC code", "label_hi": "HASC कोड"},
    {"key": "VARNAME_2", "label": "Other names", "label_hi": "अन्य नाम"},
    {"key": "ID_2", "label": "District ID", "label_hi": "जिला आईडी"},
]

# Values the supplied files use for "nothing recorded here".
ABSENT = ["", "<Null>", "0"]


def write_pair(path, obj):
    """Write the GeoJSON and its gzip twin, the way the API serves them."""
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)
    with open(path + ".gz", "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) as gz:
            gz.write(raw)
    with gzip.open(path + ".gz", "rb") as fh:
        if fh.read() != raw:
            sys.exit(f"gzip round-trip failed for {path}")
    return len(raw), os.path.getsize(path + ".gz")


def clean(value):
    """Trim strings; leave everything else exactly as the shapefile has it."""
    if isinstance(value, str):
        return value.strip()
    return value


def read_water_bodies(folder):
    """Every polygon of the three supplied files, split into named / unnamed."""
    named, unnamed = [], []
    per_zone = {}
    for zone in SUB_BASINS:
        base = os.path.join(folder, zone)
        if not os.path.exists(base + ".shp"):
            sys.exit(f"Missing {base}.shp")
        reader = shapefile.Reader(base)
        keys = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]
        n_named = n_unnamed = n_skipped = 0
        for shape, record in zip(reader.iterShapes(), reader.iterRecords()):
            geom = shape.__geo_interface__      # coordinates exactly as stored
            if not geom or not geom.get("coordinates"):
                n_skipped += 1                  # empty geometry: nothing to draw
                continue
            props = {k: clean(v) for k, v in zip(keys, list(record))}
            props["sub_basin"] = zone
            feature = {"type": "Feature", "geometry": geom, "properties": props}
            if str(props.get(NAME_FIELD) or "").strip():
                named.append(feature)
                n_named += 1
            else:
                unnamed.append(feature)
                n_unnamed += 1
        reader.close()
        per_zone[zone] = {"named": n_named, "unnamed": n_unnamed, "skipped": n_skipped}
        print(f"  {zone:<7} named {n_named:>5}   unnamed {n_unnamed:>5}"
              + (f"   skipped (no geometry) {n_skipped}" if n_skipped else ""))
    return named, unnamed, per_zone


def read_districts(path):
    """The supplied district boundaries, passed through as they are."""
    if path.lower().endswith(".geojson") or path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        features = data.get("features") or []
        for f in features:
            f["properties"] = {k: clean(v) for k, v in (f.get("properties") or {}).items()}
        return features
    reader = shapefile.Reader(os.path.splitext(path)[0])
    keys = [f[0] for f in reader.fields if f[0] != "DeletionFlag"]
    features = []
    for shape, record in zip(reader.iterShapes(), reader.iterRecords()):
        geom = shape.__geo_interface__
        if not geom or not geom.get("coordinates"):
            continue
        features.append({"type": "Feature", "geometry": geom,
                         "properties": {k: clean(v) for k, v in zip(keys, list(record))}})
    reader.close()
    return features


def bounds(features):
    xs, ys = [], []

    def walk(coords):
        if coords and isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
            return
        for c in coords:
            walk(c)

    for f in features:
        walk(f["geometry"]["coordinates"])
    if not xs:
        return None
    return [[min(ys), min(xs)], [max(ys), max(xs)]]


def main():
    ap = argparse.ArgumentParser(description="Build the Water Body Atlas layers.")
    ap.add_argument("--waterbodies", required=True,
                    help="Folder holding Upper.shp, Middle.shp and Lower.shp")
    ap.add_argument("--districts", required=True,
                    help="Narmada_District.geojson, or the district .shp")
    args = ap.parse_args()

    print("Reading water bodies ...")
    named, unnamed, per_zone = read_water_bodies(args.waterbodies)
    if not named and not unnamed:
        sys.exit("No water body features read. Check --waterbodies.")

    print("Reading district boundaries ...")
    districts = read_districts(args.districts)
    if not districts:
        sys.exit("No district features read. Check --districts.")
    names = sorted({(f["properties"].get("NAME_2") or "") for f in districts})
    print(f"  {len(districts)} districts: {', '.join(n for n in names if n)[:120]} ...")

    os.makedirs(OUT_DIR, exist_ok=True)
    sizes = {}
    for filename, features in (
        ("named_water_bodies.geojson", named),
        ("unnamed_water_bodies.geojson", unnamed),
        ("districts.geojson", districts),
    ):
        fc = {"type": "FeatureCollection",
              "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
              "features": features}
        sizes[filename] = write_pair(os.path.join(OUT_DIR, filename), fc)

    catalog = {
        "id": "water_bodies",
        "title": "Narmada Water Body Atlas",
        "title_hi": "नर्मदा जल निकाय एटलस",
        "fit_layer": "districts",
        "attribution": "cNARMADA, Indian Institute of Technology Indore",
        "district_layer": "districts",
        "district_name_field": "NAME_2",
        "district_state_field": "NAME_1",
        "layers": [
            {
                "id": "districts",
                "file": "districts.geojson",
                "name": "District Boundaries",
                "name_hi": "जिला सीमाएँ",
                "description": "District boundaries of the Narmada basin, as supplied.",
                "description_hi": "नर्मदा बेसिन की जिला सीमाएँ, यथा-प्राप्त।",
                "geometry_type": "MultiPolygon",
                "feature_count": len(districts),
                "default_visible": True,
                "z_index": 1,
                "canvas": False,
                "style": {"color": "#475569", "weight": 1, "opacity": 0.9,
                          "fill": True, "fillColor": "#f8fafc", "fillOpacity": 0.35},
                "highlight_style": {"color": "#0f172a", "weight": 2, "opacity": 1},
                "legend": {"type": "fill", "color": "#475569", "fillColor": "#f8fafc"},
                "label_field": "NAME_2",
                "fields": DISTRICT_FIELDS,
                "absent_values": ABSENT,
                "source": "Narmada_District boundaries (supplied), WGS 84",
            },
            {
                "id": "named_water_bodies",
                "file": "named_water_bodies.geojson",
                "name": "Named Water Bodies",
                "name_hi": "नामित जल निकाय",
                "description": "Water bodies that carry a name in the supplied dataset.",
                "description_hi": "प्रदत्त डेटासेट में नाम वाले जल निकाय।",
                "geometry_type": "Polygon",
                "feature_count": len(named),
                "default_visible": True,
                "z_index": 3,
                "canvas": False,
                "style": {"color": "#1d4ed8", "weight": 1.2, "opacity": 1,
                          "fill": True, "fillColor": "#3b82f6", "fillOpacity": 0.75},
                "highlight_style": {"color": "#0b2f8a", "weight": 2.5, "opacity": 1},
                "legend": {"type": "fill", "color": "#1d4ed8", "fillColor": "#3b82f6"},
                "label_field": "Name",
                "fields": WB_FIELDS,
                "absent_values": ABSENT,
                "source": "Narmada_Waterbodies Upper / Middle / Lower (supplied), WGS 84",
            },
            {
                "id": "unnamed_water_bodies",
                "file": "unnamed_water_bodies.geojson",
                "name": "Unnamed Water Bodies",
                "name_hi": "अनाम जल निकाय",
                "description": "Water bodies with no name recorded in the supplied dataset.",
                "description_hi": "प्रदत्त डेटासेट में बिना नाम वाले जल निकाय।",
                "geometry_type": "Polygon",
                "feature_count": len(unnamed),
                "default_visible": True,
                "z_index": 2,
                "canvas": True,
                "style": {"color": "#0f766e", "weight": 0.7, "opacity": 0.95,
                          "fill": True, "fillColor": "#5eead4", "fillOpacity": 0.7},
                "highlight_style": {"color": "#042f2e", "weight": 2, "opacity": 1},
                "legend": {"type": "fill", "color": "#0f766e", "fillColor": "#5eead4"},
                "label_field": None,
                "fields": WB_FIELDS,
                "absent_values": ABSENT,
                "source": "Narmada_Waterbodies Upper / Middle / Lower (supplied), WGS 84",
            },
        ],
        "coverage": {
            "water_bodies_total": len(named) + len(unnamed),
            "named": len(named),
            "unnamed": len(unnamed),
            "by_sub_basin": per_zone,
            "districts": len(districts),
        },
        "bounds": bounds(districts),
    }

    with open(os.path.join(OUT_DIR, "catalog.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    # The River Atlas filters by district too, so it gets the same supplied
    # boundaries and the same catalogue entry. Its own layers are untouched.
    river_dir = os.path.normpath(os.path.join(OUT_DIR, "..", "river_atlas"))
    river_catalog_path = os.path.join(river_dir, "catalog.json")
    if os.path.exists(river_catalog_path):
        district_entry = next(l for l in catalog["layers"] if l["id"] == "districts")
        write_pair(os.path.join(river_dir, "districts.geojson"),
                   {"type": "FeatureCollection",
                    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
                    "features": districts})
        with open(river_catalog_path, encoding="utf-8") as fh:
            river_catalog = json.load(fh)
        river_catalog["district_layer"] = "districts"
        river_catalog["district_name_field"] = "NAME_2"
        river_catalog["district_state_field"] = "NAME_1"
        entry = dict(district_entry)
        entry["default_visible"] = False        # the basin outline leads here
        entry["z_index"] = 0                    # drawn under the basin and rivers
        others = [l for l in river_catalog["layers"] if l["id"] != "districts"]
        river_catalog["layers"] = [entry] + others
        with open(river_catalog_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(river_catalog, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("Also published the district layer to the River Atlas catalogue.")

    mb = lambda n: n / 1_048_576
    print("\nWritten to app/static/data/water_atlas/")
    for filename, (raw, gz) in sizes.items():
        print(f"  {filename:<28} {mb(raw):6.2f} MB   gz {mb(gz):5.2f} MB")
    print(f"\nWater bodies: {len(named) + len(unnamed):,} "
          f"({len(named):,} named, {len(unnamed):,} unnamed)")
    print(f"Districts   : {len(districts)}")


if __name__ == "__main__":
    main()
