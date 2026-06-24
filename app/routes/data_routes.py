"""
Public, read-only data API for the cNARMADA "Data" section.

All routes are prefixed with /api and read from pre-processed JSON/GeoJSON/PNG
files under app/static/data (built once by scripts/process_data.py).

No auth is applied here on purpose for this phase — these are public datasets
meant to be viewable without logging in. Auth (OTP / viewer / collaborator /
admin) can be layered back in later without changing these endpoints.
"""
import os
import json
from flask import Blueprint, jsonify, current_app, send_from_directory, abort, request

data_bp = Blueprint("data", __name__, url_prefix="/api")

# Maps the short source ids used in districts.json to their actual report filenames
# (as found in reports_index.json), so the frontend can link each fact straight to its PDF.
DISTRICT_SOURCE_FILES = {
    "demography": "Demography-of-NRB.pdf",
    "agriculture": "Agricultural-Profile-of-Narmada-River-Basin_20250924.pdf",
    "water": "Water-Demand-and-Supply-in-NRB.pdf",
    "flood": "Flood-Hazard-Model-of-narmada-River-Basin.pdf",
    "pollution": "pollution-load-report_20251023.pdf",
}

API_CATALOG = [
    {"method": "GET", "path": "/api/overview", "description": "Summary stats: station counts, report counts, available LULC years, water quality coverage."},
    {"method": "GET", "path": "/api/stations", "description": "List all monitoring stations with name, lat/lon, and which datasets each has. Add ?mapped_only=true to only return stations with coordinates."},
    {"method": "GET", "path": "/api/stations/<slug>", "description": "Full detail for one station, including its streamflow and/or water-level time series."},
    {"method": "GET", "path": "/api/geojson/basin_boundary", "description": "Narmada basin boundary polygon (GeoJSON)."},
    {"method": "GET", "path": "/api/geojson/centerline", "description": "Narmada river centerline, Amarkantak to the Gulf of Khambhat (GeoJSON LineString)."},
    {"method": "GET", "path": "/api/geojson/named_network", "description": "Named tributary network across the basin (GeoJSON, 1000+ features)."},
    {"method": "GET", "path": "/api/rasters/lulc", "description": "Land Use / Land Cover raster overlays by year (2018-2024) as PNG image bounds for map display."},
    {"method": "GET", "path": "/api/rasters/dem", "description": "Digital Elevation Model overlay (PNG) with geographic bounds and elevation min/max."},
    {"method": "GET", "path": "/api/water-quality/parameters", "description": "List of all measured water quality parameters and monitoring locations."},
    {"method": "GET", "path": "/api/water-quality/<parameter>", "description": "Time series records for one water quality parameter (e.g. pH, BOD, Alkalinity). Add ?location=... to filter."},
    {"method": "GET", "path": "/api/reports", "description": "Catalogue of downloadable PDF reports."},
    {"method": "GET", "path": "/api/reports/<filename>", "description": "Download a specific report PDF."},
    {"method": "GET", "path": "/api/districts", "description": "List of districts near the Narmada basin with summary location info, plus the source reports they're drawn from."},
    {"method": "GET", "path": "/api/districts/<slug>", "description": "Full report-sourced profile for one district: overview, land use, water resources, and insights & alerts, each citing its source report."},
]


def _data_path(*parts):
    return os.path.join(current_app.config["DATA_DIR"], *parts)


def _read_json(*parts):
    path = _data_path(*parts)
    if not os.path.exists(path):
        abort(404, description=f"{'/'.join(parts)} not found — did you run process_data.py?")
    with open(path) as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────────────────
# API Catalog — for the "Data Download > API Catalog" menu item
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/catalog")
def api_catalog():
    return jsonify(API_CATALOG)


# ──────────────────────────────────────────────────────────────────────────
# Overview / summary — powers a "Data" landing page with quick stats
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/overview")
def overview():
    stations = _read_json("stations.json")
    reports = _read_json("reports_index.json")
    lulc_index = _read_json("rasters", "lulc_index.json")
    wq = _read_json("water_quality.json")
    districts = _read_json("districts.json")

    return jsonify({
        "stations": {
            "total": len(stations),
            "with_coordinates": sum(1 for s in stations if s["lat"] is not None),
            "with_streamflow": sum(1 for s in stations if s["has_streamflow"]),
            "with_waterlevel": sum(1 for s in stations if s["has_waterlevel"]),
        },
        "reports": {"total": len(reports)},
        "lulc_years": sorted(lulc_index.keys()),
        "water_quality": {
            "parameters": len(wq["parameters"]),
            "locations": len(wq["locations"]),
        },
        "districts": {"total": len(districts["districts"])},
    })


# ──────────────────────────────────────────────────────────────────────────
# Stations
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/stations")
def list_stations():
    stations = _read_json("stations.json")
    only_mapped = request.args.get("mapped_only") == "true"
    if only_mapped:
        stations = [s for s in stations if s["lat"] is not None]
    return jsonify(stations)


@data_bp.route("/stations/<slug>")
def station_detail(slug):
    stations = _read_json("stations.json")
    match = next((s for s in stations if s["slug"] == slug), None)
    if not match:
        abort(404, description=f"Unknown station '{slug}'")

    result = dict(match)
    if match["has_streamflow"]:
        path = _data_path("timeseries", f"streamflow_{slug}.json")
        if os.path.exists(path):
            with open(path) as f:
                result["streamflow"] = json.load(f)
    if match["has_waterlevel"]:
        path = _data_path("timeseries", f"waterlevel_{slug}.json")
        if os.path.exists(path):
            with open(path) as f:
                result["waterlevel"] = json.load(f)
    return jsonify(result)


# ──────────────────────────────────────────────────────────────────────────
# GeoJSON layers (basin boundary, river centerline, named tributary network)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/geojson/<layer>")
def geojson_layer(layer):
    allowed = {
        "basin_boundary": "basin_boundary.geojson",
        "centerline": "centerline.geojson",
        "named_network": "named_network.geojson",
    }
    if layer not in allowed:
        abort(404, description=f"Unknown layer '{layer}'. Available: {list(allowed)}")
    return send_from_directory(_data_path("geojson"), allowed[layer])


# ──────────────────────────────────────────────────────────────────────────
# Rasters (LULC year overlays + DEM)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/rasters/lulc")
def lulc_index():
    """List available LULC years + their PNG urls + geo bounds."""
    idx = _read_json("rasters", "lulc_index.json")
    out = {}
    for year, info in idx.items():
        out[year] = {
            "bounds": info["bounds"],
            "url": f"/static/data/{info['file']}",
        }
    return jsonify(out)


@data_bp.route("/rasters/dem")
def dem_meta():
    meta = _read_json("rasters", "dem_meta.json")
    meta["url"] = f"/static/data/{meta['file']}"
    return jsonify(meta)


# ──────────────────────────────────────────────────────────────────────────
# Water quality (Combined_All_Params.xlsx, parsed)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/water-quality/parameters")
def wq_parameters():
    wq = _read_json("water_quality.json")
    return jsonify({"parameters": wq["parameters"], "locations": wq["locations"]})


@data_bp.route("/water-quality/<parameter>")
def wq_parameter_data(parameter):
    wq = _read_json("water_quality.json")
    if parameter not in wq["data"]:
        abort(404, description=f"Unknown parameter '{parameter}'. Available: {wq['parameters']}")
    records = wq["data"][parameter]

    location = request.args.get("location")
    if location:
        records = [r for r in records if r["location"] == location]

    return jsonify({"parameter": parameter, "count": len(records), "records": records})


# ──────────────────────────────────────────────────────────────────────────
# Districts — curated, report-sourced content for the Home page section
# ──────────────────────────────────────────────────────────────────────────
def _hydrate_sources(data):
    """Attach a downloadable report filename/url to each source id."""
    sources = data["sources"]
    hydrated = {}
    for sid, label in sources.items():
        filename = DISTRICT_SOURCE_FILES.get(sid)
        hydrated[sid] = {
            "label": label,
            "filename": filename,
            "url": f"/api/reports/{filename}" if filename else None,
        }
    return hydrated


@data_bp.route("/districts")
def list_districts():
    data = _read_json("districts.json")
    sources = _hydrate_sources(data)
    summary = [
        {"slug": d["slug"], "name": d["name"], "state": d["state"],
         "basin_zone": d["basin_zone"], "lat": d["lat"], "lon": d["lon"],
         "basin_area_sq_km": d.get("basin_area_sq_km")}
        for d in data["districts"]
    ]
    return jsonify({"sources": sources, "districts": summary})


@data_bp.route("/districts/<slug>")
def district_detail(slug):
    data = _read_json("districts.json")
    match = next((d for d in data["districts"] if d["slug"] == slug), None)
    if not match:
        abort(404, description=f"Unknown district '{slug}'")
    result = dict(match)
    result["sources"] = _hydrate_sources(data)
    return jsonify(result)


# ──────────────────────────────────────────────────────────────────────────
# Reports (PDF catalogue + download)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/reports")
def list_reports():
    return jsonify(_read_json("reports_index.json"))


@data_bp.route("/reports/<path:filename>")
def download_report(filename):
    reports = _read_json("reports_index.json")
    if not any(r["filename"] == filename for r in reports):
        abort(404, description="Report not found")
    return send_from_directory(_data_path("reports"), filename, as_attachment=True)
