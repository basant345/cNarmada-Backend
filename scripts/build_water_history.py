"""
Turn the Earth Engine exports into the file the Water Body Atlas serves.

Input   nine CSVs from Earth Engine, one per year, 103,560 rows each:
          wb_id, year, month, water_area_m2, valid_fraction, n_images

Output  app/static/data/water_atlas/water_history.json and its .gz twin,
        following the same pre-compressed pattern as the atlas layers.

Shape of the output. Every water body gets two arrays of 108 values, one per
month from January 2018 to December 2026 in order:

    "N00193": {"a": [...areas in m2...], "v": [...percent observed...]}

`v` is the share of the polygon that was actually seen through the clouds.
Anything below MIN_VALID is an unobserved month. The area is still carried so
the figure can be inspected, but the portal must render those as gaps, never
as zero and never joined by a line.

Nothing here modifies the published water body layers. The area attribute in
those files is left exactly as it is, including the twelve features where it
is demonstrably wrong, and is reported beside the satellite measurement rather
than replaced.

    python scripts/build_water_history.py /path/to/csv/folder
"""

import csv
import gzip
import json
import os
import sys

START_YEAR = 2018
END_YEAR = 2026
MONTHS = (END_YEAR - START_YEAR + 1) * 12          # 108
MIN_VALID = 50          # percent of the polygon that must be cloud-free

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "app", "static", "data"))
ATLAS = os.path.join(DATA, "water_atlas")
OUT = os.path.join(ATLAS, "water_history.json")


def slot(year, month):
    """Index of a year/month in the 108-long arrays."""
    return (year - START_YEAR) * 12 + (month - 1)


def ring_area_m2(ring):
    """Shoelace area of a lon/lat ring, in square metres near 22 N."""
    total = 0.0
    for i in range(len(ring) - 1):
        total += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(total) / 2 * (111320 ** 2) * 0.927


def polygon_area_m2(geometry):
    rings = (geometry["coordinates"] if geometry["type"] == "Polygon"
             else [r for poly in geometry["coordinates"] for r in poly])
    return sum(ring_area_m2(r) for r in rings)


def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def load_districts():
    """Prepared district polygons with bounding boxes, for assignment."""
    path = os.path.join(ATLAS, "districts.geojson")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        features = json.load(fh)["features"]
    out = []
    for feature in features:
        geom = feature["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        prepared = []
        for rings in polys:
            if not rings or len(rings[0]) < 3:
                continue
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            prepared.append((rings, (min(xs), min(ys), max(xs), max(ys))))
        out.append({
            "name": feature["properties"].get("NAME_2"),
            "state": feature["properties"].get("NAME_1"),
            "polys": prepared,
        })
    return out


def centroid(geometry):
    """Centre of the largest ring, which is where the water body sits."""
    rings = (geometry["coordinates"] if geometry["type"] == "Polygon"
             else [r for poly in geometry["coordinates"] for r in poly])
    biggest = max(rings, key=len)
    xs = [p[0] for p in biggest]
    ys = [p[1] for p in biggest]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def district_of(x, y, districts):
    """
    Which district a water body sits in, by its centroid.

    A water body straddling a boundary is counted once, in the district
    holding its centre. Counting it in both would double its area in the
    per-district totals.
    """
    for d in districts:
        for rings, (minx, miny, maxx, maxy) in d["polys"]:
            if not (minx <= x <= maxx and miny <= y <= maxy):
                continue
            if not point_in_ring(x, y, rings[0]):
                continue
            if any(point_in_ring(x, y, hole) for hole in rings[1:]):
                continue
            return d["name"], d["state"]
    return None, None


def read_water_bodies():
    """wb_id -> published attribute, true geometric area, name, sub-basin, district."""
    districts = load_districts()
    out = {}
    for prefix, filename in (("N", "named_water_bodies.geojson"),
                             ("U", "unnamed_water_bodies.geojson")):
        path = os.path.join(ATLAS, filename)
        with open(path, encoding="utf-8") as fh:
            features = json.load(fh)["features"]
        for i, feature in enumerate(features):
            props = feature["properties"]
            x, y = centroid(feature["geometry"])
            district, state = district_of(x, y, districts)
            out[f"{prefix}{i + 1:05d}"] = {
                "name": (props.get("Name") or "").strip(),
                "sub_basin": props.get("sub_basin"),
                "district": district,
                "state": state,
                "lon": round(x, 5),
                "lat": round(y, 5),
                "published_area_m2": round(props.get("area_m2") or 0),
                "geometry_area_m2": round(polygon_area_m2(feature["geometry"])),
            }
    return out


def confidence(geometry_area_m2):
    """
    How far to trust a 20 m measurement of a polygon this size.

    Derived from comparing the 2021 Sentinel-2 maxima against the real
    polygon geometries: agreement is 95%+ above 2 ha and falls away below it,
    because a small pond is only a handful of pixels and its shoreline
    pixels are mixed water and land.
    """
    if geometry_area_m2 >= 20000:
        return "good"
    if geometry_area_m2 >= 5000:
        return "moderate"
    return "low"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python scripts/build_water_history.py <folder with the CSVs>")
    folder = sys.argv[1]
    csv_files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".csv"))
    if not csv_files:
        sys.exit(f"No CSV files in {folder}")

    bodies = read_water_bodies()
    areas = {k: [None] * MONTHS for k in bodies}
    valid = {k: [0] * MONTHS for k in bodies}

    rows_read = 0
    unknown_ids = set()
    for filename in csv_files:
        with open(os.path.join(folder, filename), newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                wb_id = row["wb_id"]
                if wb_id not in bodies:
                    unknown_ids.add(wb_id)
                    continue
                year = int(float(row["year"]))
                month = int(float(row["month"]))
                if not (START_YEAR <= year <= END_YEAR) or not (1 <= month <= 12):
                    continue
                i = slot(year, month)
                areas[wb_id][i] = round(float(row["water_area_m2"]))
                valid[wb_id][i] = round(float(row["valid_fraction"]) * 100)
                rows_read += 1

    if unknown_ids:
        print(f"  warning: {len(unknown_ids)} wb_id values in the CSVs match no "
              f"water body, e.g. {sorted(unknown_ids)[:3]}")

    # Which periods are usable at all, for the year and month pickers.
    observed = []
    for i in range(MONTHS):
        usable = sum(1 for k in bodies if valid[k][i] >= MIN_VALID)
        observed.append(round(100 * usable / len(bodies)))

    payload = {
        "start_year": START_YEAR,
        "end_year": END_YEAR,
        "months": MONTHS,
        "min_valid_percent": MIN_VALID,
        "source": "Sentinel-2 L2A (COPERNICUS/S2_SR_HARMONIZED), MNDWI > 0, "
                  "SCL cloud mask, 20 m",
        "note": "a[] is water area in m2 inside the published polygon. v[] is "
                "the percent of that polygon seen through cloud. A month with "
                "v below min_valid_percent was not observed and must be shown "
                "as a gap, not as zero.",
        "coverage_percent_by_period": observed,
        "water_bodies": {
            k: {
                "name": bodies[k]["name"],
                "sub_basin": bodies[k]["sub_basin"],
                "district": bodies[k]["district"],
                "state": bodies[k]["state"],
                "lon": bodies[k]["lon"],
                "lat": bodies[k]["lat"],
                "published_area_m2": bodies[k]["published_area_m2"],
                "geometry_area_m2": bodies[k]["geometry_area_m2"],
                "confidence": confidence(bodies[k]["geometry_area_m2"]),
                "a": areas[k],
                "v": valid[k],
            }
            for k in sorted(bodies)
        },
    }

    os.makedirs(ATLAS, exist_ok=True)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    with open(OUT, "wb") as fh:
        fh.write(body)
    with gzip.GzipFile(OUT + ".gz", "wb", compresslevel=9, mtime=0) as gz:
        gz.write(body)

    mb = lambda n: n / 1_048_576
    usable = sum(1 for k in bodies for i in range(MONTHS) if valid[k][i] >= MIN_VALID)
    total = len(bodies) * MONTHS
    tiers = {}
    for k in bodies:
        tiers[confidence(bodies[k]["geometry_area_m2"])] = \
            tiers.get(confidence(bodies[k]["geometry_area_m2"]), 0) + 1

    print(f"  read        {rows_read:,} rows from {len(csv_files)} CSV files")
    print(f"  water bodies {len(bodies):,}, months {MONTHS}")
    print(f"  usable      {usable:,} of {total:,} observations "
          f"({100 * usable / total:.1f}%)")
    print(f"  confidence  " + ", ".join(f"{v:,} {k}" for k, v in sorted(tiers.items())))
    placed = sum(1 for k in bodies if bodies[k]["district"])
    print(f"  districts   {placed:,} of {len(bodies):,} water bodies placed in a district")
    print(f"  wrote       {OUT}  {mb(len(body)):.1f} MB")
    print(f"  wrote       {OUT}.gz  {mb(os.path.getsize(OUT + '.gz')):.1f} MB")


if __name__ == "__main__":
    main()
