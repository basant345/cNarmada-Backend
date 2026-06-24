"""
Master ETL: raw 'Cnarmada Data' folder -> clean assets consumed by the Flask backend.

Run once locally:
    python3 process_data.py /path/to/extracted/"Cnarmada Data" /path/to/backend/app

Produces (under <backend>/app/static/data/):
  geojson/basin_boundary.geojson
  geojson/centerline.geojson
  geojson/named_network.geojson
  rasters/lulc_<year>.png            (+ rasters/lulc_index.json with bounds per year)
  rasters/dem.png                    (+ bounds/min/max in rasters/dem_meta.json)
  reports/<files>.pdf                (copied as-is)
  reports_index.json
  stations.json                      (merged station metadata: lat/lon + which datasets exist)
  timeseries/streamflow_<station>.json
  timeseries/waterlevel_<station>.json
  water_quality.json                 (parsed Combined_All_Params.xlsx, all sheets/params)
"""
import csv
import io
import json
import os
import re
import shutil
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
from shp2geojson import shp_to_geojson
from raster2png import lulc_to_png, dem_to_png


def slugify(name):
    """Display-friendly slug: lowercase, words separated by single underscores."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[\s_]+", "_", name)


def match_key(name):
    """
    Aggressive normalization used ONLY for matching a CSV filename to a station
    name from Station_Location.csv. Strips ALL separators/spaces/underscores so
    'AshwinAtHaripura' and 'Ashwin at Haripura' produce the same key.
    """
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-zA-Z0-9]", "", name).lower()
    return name


def parse_river_authority_csv(path):
    """
    Parses the 'Daily River Authority trends...' CSV format used for both
    streamflow and water-level station files. Returns list of row dicts plus
    the parsed title line (for date range / display name).
    """
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    title = lines[0].strip() if lines else ""
    # find the actual header row (starts with "Dates")
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Dates"):
            header_idx = i
            break
    if header_idx is None:
        return title, []

    reader = csv.DictReader(lines[header_idx:])
    rows = []
    for row in reader:
        if not row.get("Dates"):
            continue
        clean = {}
        for k, v in row.items():
            if k is None:
                continue
            key = k.strip()
            v = (v or "").strip().strip('"')
            if v in ("", "-", "NA", "N/A"):
                clean[key] = None
            else:
                try:
                    clean[key] = float(v)
                except ValueError:
                    clean[key] = v
        rows.append(clean)
    return title, rows


def load_station_locations(path):
    """Returns dict keyed by match_key(name) -> {name, lat, lon, slug}."""
    stations = {}
    with open(path, "rb") as f:
        text = f.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        try:
            lat = float(row["Lat"])
            lon = float(row["Long"])
        except (KeyError, ValueError, TypeError):
            continue
        stations[match_key(name)] = {"name": name, "lat": lat, "lon": lon, "slug": slugify(name)}
    return stations


def process(src_root, backend_app_dir):
    static_data = os.path.join(backend_app_dir, "static", "data")
    geojson_dir = os.path.join(static_data, "geojson")
    raster_dir = os.path.join(static_data, "rasters")
    reports_dir = os.path.join(static_data, "reports")
    ts_dir = os.path.join(static_data, "timeseries")
    for d in (geojson_dir, raster_dir, reports_dir, ts_dir):
        os.makedirs(d, exist_ok=True)

    log = []

    # ---------------------------------------------------------------
    # 1. Shapefiles -> GeoJSON
    # ---------------------------------------------------------------
    boundary_shp = os.path.join(
        src_root, "Narmada_Shapefiles_Basic-20260618T114330Z-3-001",
        "Narmada_Shapefiles_Basic", "Narmada_Basin_Boundary.shp")
    gj = shp_to_geojson(boundary_shp)
    with open(os.path.join(geojson_dir, "basin_boundary.geojson"), "w") as f:
        json.dump(gj, f)
    log.append(f"basin_boundary.geojson: {len(gj['features'])} features")

    centerline_shp = os.path.join(
        src_root, "Narmada_Centerline-20260619T053627Z-3-001",
        "Narmada_Centerline", "Narmada_centerline.shp")
    gj = shp_to_geojson(centerline_shp, simplify_tolerance=3)
    with open(os.path.join(geojson_dir, "centerline.geojson"), "w") as f:
        json.dump(gj, f)
    log.append(f"centerline.geojson: {len(gj['features'])} features")

    network_shp = os.path.join(
        src_root, "River_Atlas-20260618T114337Z-3-001",
        "River_Atlas", "NARMADA_NAMED_NETWORK.shp")
    gj = shp_to_geojson(
        network_shp, simplify_tolerance=8,
        property_keys=["River_Name", "Length"])
    with open(os.path.join(geojson_dir, "named_network.geojson"), "w") as f:
        json.dump(gj, f)
    log.append(f"named_network.geojson: {len(gj['features'])} features")

    # ---------------------------------------------------------------
    # 2. Rasters -> PNG overlays
    # ---------------------------------------------------------------
    lulc_index = {}
    lulc_dir = os.path.join(src_root, "LULC-20260619T053601Z-3-001", "LULC")
    for fname in sorted(os.listdir(lulc_dir)):
        if not fname.lower().endswith(".tif"):
            continue
        m = re.search(r"(\d{4})_\d{4}", fname)
        year = m.group(1) if m else fname
        out_name = f"lulc_{year}.png"
        bounds = lulc_to_png(os.path.join(lulc_dir, fname), os.path.join(raster_dir, out_name))
        lulc_index[year] = {"file": f"rasters/{out_name}", "bounds": bounds}
        log.append(f"LULC {year} -> {out_name}")
    with open(os.path.join(raster_dir, "lulc_index.json"), "w") as f:
        json.dump(lulc_index, f, indent=2)

    dem_tif = os.path.join(src_root, "DEM-20260618T114259Z-3-001", "DEM", "NRSC_SHAPEFILE_CORRECTED_DEM.tif")
    bounds, vmin, vmax = dem_to_png(dem_tif, os.path.join(raster_dir, "dem.png"))
    with open(os.path.join(raster_dir, "dem_meta.json"), "w") as f:
        json.dump({"bounds": bounds, "min_elev": vmin, "max_elev": vmax, "file": "rasters/dem.png"}, f, indent=2)
    log.append("DEM -> dem.png")

    # ---------------------------------------------------------------
    # 3. Station locations
    # ---------------------------------------------------------------
    station_loc_path = os.path.join(
        src_root, "Narmada_StreamflowData-20260619T053602Z-3-001",
        "Narmada_StreamflowData", "Station_Location.csv")
    stations = load_station_locations(station_loc_path)

    # ---------------------------------------------------------------
    # 4. Streamflow CSVs -> per-station JSON time series
    # ---------------------------------------------------------------
    streamflow_dir = os.path.join(
        src_root, "Narmada_StreamflowData-20260619T053602Z-3-001", "Narmada_StreamflowData")
    streamflow_stations = set()
    for fname in sorted(os.listdir(streamflow_dir)):
        if not fname.lower().endswith(".csv") or fname == "Station_Location.csv":
            continue
        path = os.path.join(streamflow_dir, fname)
        station_raw_name = re.sub(
            r"(_\d{2}_\d{2}_\d{4}.*$)|(_streamflow$)|(_\d{4}_\d{4}$)|(\+.*$)",
            "", os.path.splitext(fname)[0], flags=re.I)
        # insert spaces before capitals for CamelCase filenames (AshwinAtHaripura -> Ashwin At Haripura)
        display_name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", station_raw_name).replace("_", " ").strip()
        key = match_key(station_raw_name)
        loc = stations.get(key)
        slug = loc["slug"] if loc else slugify(display_name)
        title, rows = parse_river_authority_csv(path)
        if not rows:
            continue
        out = {
            "station_slug": slug,
            "station_name_raw": loc["name"] if loc else display_name,
            "source_title": title,
            "source_file": fname,
            "n_records": len(rows),
            "data": rows,
        }
        out_path = os.path.join(ts_dir, f"streamflow_{slug}.json")
        # merge if multiple files map to same slug (keep the longer one)
        if os.path.exists(out_path):
            with open(out_path) as f:
                existing = json.load(f)
            if existing["n_records"] >= len(rows):
                continue
        with open(out_path, "w") as f:
            json.dump(out, f)
        streamflow_stations.add(slug)
    log.append(f"Streamflow: {len(streamflow_stations)} stations processed")

    # ---------------------------------------------------------------
    # 5. Water Level CSVs -> per-station JSON time series
    # ---------------------------------------------------------------
    waterlevel_dir = os.path.join(src_root, "Water Level-20260619T053612Z-3-001", "Water Level")
    waterlevel_stations = set()
    for fname in sorted(os.listdir(waterlevel_dir)):
        if not fname.lower().endswith(".csv"):
            continue
        path = os.path.join(waterlevel_dir, fname)
        station_raw_name = os.path.splitext(fname)[0]
        display_name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", station_raw_name).replace("_", " ").strip()
        key = match_key(station_raw_name)
        loc = stations.get(key)
        slug = loc["slug"] if loc else slugify(display_name)
        title, rows = parse_river_authority_csv(path)
        if not rows:
            continue
        out = {
            "station_slug": slug,
            "station_name_raw": loc["name"] if loc else display_name,
            "source_title": title,
            "source_file": fname,
            "n_records": len(rows),
            "data": rows,
        }
        with open(os.path.join(ts_dir, f"waterlevel_{slug}.json"), "w") as f:
            json.dump(out, f)
        waterlevel_stations.add(slug)
    log.append(f"Water level: {len(waterlevel_stations)} stations processed")

    # ---------------------------------------------------------------
    # 6. Merge station metadata + dataset availability flags
    # ---------------------------------------------------------------
    loc_by_slug = {v["slug"]: v for v in stations.values()}
    all_slugs = set(loc_by_slug.keys()) | streamflow_stations | waterlevel_stations
    merged = []
    for slug in sorted(all_slugs):
        meta = loc_by_slug.get(slug)
        merged.append({
            "slug": slug,
            "name": meta["name"] if meta else slug.replace("_", " ").title(),
            "lat": meta["lat"] if meta else None,
            "lon": meta["lon"] if meta else None,
            "has_streamflow": slug in streamflow_stations,
            "has_waterlevel": slug in waterlevel_stations,
        })
    with open(os.path.join(static_data, "stations.json"), "w") as f:
        json.dump(merged, f, indent=2)
    log.append(f"stations.json: {len(merged)} stations "
               f"({sum(1 for s in merged if s['lat'] is not None)} with coordinates)")

    # ---------------------------------------------------------------
    # 7. Water quality Excel -> JSON
    # ---------------------------------------------------------------
    import pandas as pd
    wq_path = os.path.join(
        src_root, "WaterQualityData-20260619T053610Z-3-001",
        "WaterQualityData", "Combined_All_Params (1).xlsx")
    xl = pd.ExcelFile(wq_path)
    wq_out = {"parameters": [], "locations": set(), "data": {}}
    for sheet in xl.sheet_names:
        if sheet.lower() == "nan":
            continue
        df = xl.parse(sheet)
        df = df.dropna(how="all")
        if "Year" not in df.columns:
            continue
        df["Year"] = df["Year"].ffill()
        location_cols = [c for c in df.columns if c not in ("Year", "Month")]
        records = []
        for _, row in df.iterrows():
            if pd.isna(row.get("Month")):
                continue
            for loc in location_cols:
                val = row.get(loc)
                if pd.isna(val):
                    continue
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue
                records.append({
                    "year": int(row["Year"]) if not pd.isna(row["Year"]) else None,
                    "month": str(row["Month"]),
                    "location": loc,
                    "value": val,
                })
                wq_out["locations"].add(loc)
        if records:
            wq_out["parameters"].append(sheet)
            wq_out["data"][sheet] = records
    wq_out["locations"] = sorted(wq_out["locations"])
    with open(os.path.join(static_data, "water_quality.json"), "w") as f:
        json.dump(wq_out, f)
    log.append(f"water_quality.json: {len(wq_out['parameters'])} parameters, "
               f"{len(wq_out['locations'])} locations")

    # ---------------------------------------------------------------
    # 8. Reports -> copy PDFs + build index
    # ---------------------------------------------------------------
    reports_src = os.path.join(src_root, "All_Reports-20260618T114109Z-3-001", "All_Reports")
    reports_index = []
    for fname in sorted(os.listdir(reports_src)):
        if not fname.lower().endswith(".pdf"):
            continue
        shutil.copy2(os.path.join(reports_src, fname), os.path.join(reports_dir, fname))
        size_mb = round(os.path.getsize(os.path.join(reports_dir, fname)) / (1024 * 1024), 2)
        title = os.path.splitext(fname)[0].replace("-", " ").replace("_", " ")
        reports_index.append({"title": title, "filename": fname, "size_mb": size_mb})
    with open(os.path.join(static_data, "reports_index.json"), "w") as f:
        json.dump(reports_index, f, indent=2)
    log.append(f"Reports: {len(reports_index)} PDFs copied")

    return log


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/data/extracted_full/Cnarmada Data"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/home/claude/backend/app"
    for line in process(src, dst):
        print("✓", line)
