"""
Public, read-only data API for the cNARMADA "Data" section.

All routes are prefixed with /api and read from pre-processed JSON/GeoJSON/PNG
files under app/static/data (built once by scripts/process_data.py).

Every endpoint in this file is PUBLIC. Viewing, charting and mapping the data
requires no login at all.

Downloading is separate: the gated equivalents live in export_routes.py and
require a verified @iiti.ac.in session. The one exception here is the report
PDF download below, which cannot be moved because its URL is already public
and must keep working.
"""
import os
import json
from flask import Blueprint, jsonify, current_app, send_from_directory, abort, request

from app.auth_guard import (
    require_iiti_user, current_user,
    make_download_token, verify_download_token, lookup_bearer_session,
)

data_bp = Blueprint("data", __name__, url_prefix="/api")

# Maps the short source ids used in districts.json to their actual report filenames
# (as found in reports_index.json), so the frontend can link each fact straight to its PDF.
DISTRICT_SOURCE_FILES = {
    "demography": "Demography-of-NRB.pdf",
    "agriculture": "Agricultural-Profile-of-Narmada-River-Basin_20250924.pdf",
    "water": "Water-Demand-and-Supply-in-NRB.pdf",
    "flood": "Flood-Hazard-Model-of-narmada-River-Basin.pdf",
    "pollution": "pollution-load-in-narmada-river-basin_20260314.pdf",
}

API_CATALOG = [
    {"method": "GET", "path": "/api/overview", "description": "Summary stats: station counts, report counts, available LULC years, water quality coverage."},
    {"method": "GET", "path": "/api/stations", "description": "List all monitoring stations with name, lat/lon, and which datasets each has. Add ?mapped_only=true to only return stations with coordinates."},
    {"method": "GET", "path": "/api/stations/<slug>", "description": "Full detail for one station, including its streamflow and/or water-level time series."},
    {"method": "GET", "path": "/api/geojson/basin_boundary", "description": "Narmada basin boundary polygon (GeoJSON)."},
    {"method": "GET", "path": "/api/geojson/centerline", "description": "Narmada river centerline, Amarkantak to the Gulf of Khambhat (GeoJSON LineString)."},
    {"method": "GET", "path": "/api/geojson/named_network", "description": "Named tributary network across the basin (GeoJSON, 1000+ features)."},
    {"method": "GET", "path": "/api/geojson/basin_demography", "description": "District-wise basin demography (population, sex ratio, literacy, workforce, SC/ST) as GeoJSON polygons."},
    {"method": "GET", "path": "/api/geojson/dams", "description": "Dam locations within the Narmada basin (GeoJSON points) with height, capacity, purpose, year completed, and other attributes."},
    {"method": "GET", "path": "/api/geojson/waterbodies", "description": "Waterbodies across the Upper/Middle/Lower Narmada sub-basins (GeoJSON polygons, ~8,600 features)."},
    {"method": "GET", "path": "/api/geojson/stp", "description": "Sewage Treatment Plant (STP) coverage by district (GeoJSON polygons) — operational STP count and capacity (MLD) per district."},
    {"method": "GET", "path": "/api/rasters/lulc", "description": "Land Use / Land Cover raster overlays by year (2018-2024) as PNG image bounds for map display."},
    {"method": "GET", "path": "/api/rasters/dem", "description": "Digital Elevation Model overlay (PNG) with geographic bounds and elevation min/max."},
    {"method": "GET", "path": "/api/rasters/geomorphology", "description": "Geomorphological classification overlay (PNG, 75 classes) with geographic bounds and a class/color legend."},
    {"method": "GET", "path": "/api/rasters/precipitation", "description": "Year-wise precipitation raster overlays (PNG image bounds + min/max mm) for map display. Empty until an admin processes yearly rasters."},
    {"method": "GET", "path": "/api/rasters/mean-temperature", "description": "Year-wise mean temperature raster overlays (PNG image bounds + min/max \u00b0C) for map display. Empty until an admin processes yearly rasters."},
    {"method": "GET", "path": "/api/rasters/sample", "description": "Sample a LULC / geomorphology / precipitation / mean-temperature layer at a lat/lon (year required for LULC/precipitation/mean-temperature) — powers the Spatial Map's click-a-district popups. Falls back to the nearest pixel with real data if the exact point is right at the dataset's coverage edge. Params: layer, year, lat, lon."},
    {"method": "GET", "path": "/api/water-quality/parameters", "description": "List of all measured water quality parameters and monitoring locations."},
    {"method": "GET", "path": "/api/water-quality/<parameter>", "description": "Time series records for one water quality parameter (e.g. pH, BOD, Alkalinity). Add ?location=... to filter."},
    {"method": "GET", "path": "/api/reports", "description": "Catalogue of downloadable PDF reports."},
    {"method": "GET", "path": "/api/reports/<filename>", "description": "Download a specific report PDF."},
    {"method": "GET", "path": "/api/districts", "description": "List of districts near the Narmada basin with summary location info, plus the source reports they're drawn from."},
    {"method": "GET", "path": "/api/districts/<slug>", "description": "Full report-sourced profile for one district: overview, land use, water resources, and insights & alerts, each citing its source report."},
    {"method": "GET", "path": "/api/water-quality-10yr", "description": "10-year comparative water quality data (2015-16 to 2024-25) — Avg/Max/Min per station and parameter, by year."},
    {"method": "GET", "path": "/api/ground-water", "description": "Ground water quality: Avg/Min/Max per parameter and station, for the Middle and Upper Narmada basin CGWB network."},
    {"method": "GET", "path": "/api/solid-waste", "description": "District-wise solid, hazardous, biomedical, electronic, C&D and plastic waste generation and management status."},
    {"method": "GET", "path": "/api/geojson/agriculture/<layer>", "description": "Agriculture GeoJSON layers: crop_irrigated_area, orchards_horticulture."},
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
# GeoJSON layers (basin boundary, river centerline, named tributary network,
# basin demography)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/geojson/<layer>")
def geojson_layer(layer):
    allowed = {
        "basin_boundary": "basin_boundary.geojson",
        "centerline": "centerline.geojson",
        "named_network": "named_network.geojson",
        "basin_demography": "final_demographic_data.geojson",
        "dams": "dams.geojson",
        "waterbodies": "waterbodies.geojson",
        "stp": "stp.geojson",
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


@data_bp.route("/rasters/geomorphology")
def geomorphology_meta():
    """Single classified layer (not year-indexed, unlike LULC) — 75 classes
    generated from the source Geomorphological_Feature_Layer shapefile by
    scripts/prepare_gis_layers.py. Empty {} until that script has been run."""
    path = _data_path("rasters", "geomorphology_meta.json")
    if not os.path.exists(path):
        return jsonify({})
    meta = _read_json("rasters", "geomorphology_meta.json")
    meta["url"] = f"/static/data/{meta['file']}"
    return jsonify(meta)


# ──────────────────────────────────────────────────────────────────────────
# Rasters (Precipitation / Mean Temperature — year-wise, same pattern as LULC)
#
# These are empty ({}) until scripts/climate_raster_to_png.py has been run
# for at least one year — the frontend treats an empty response as "no data
# uploaded yet" rather than an error, so the layer toggle is always safe to
# show even before any yearly raster has been processed.
# ──────────────────────────────────────────────────────────────────────────
def _climate_index(variable):
    path = _data_path("rasters", f"{variable}_index.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        idx = json.load(f)
    meta = idx.pop("_meta", {})
    out = {"unit": meta.get("unit", ""), "stops": meta.get("stops", []), "years": {}}
    for year, info in idx.items():
        out["years"][year] = {
            "bounds": info["bounds"],
            "url": f"/static/data/{info['file']}",
            "min": info.get("min"),
            "max": info.get("max"),
        }
    return out


@data_bp.route("/rasters/precipitation")
def precipitation_index():
    return jsonify(_climate_index("precipitation"))


@data_bp.route("/rasters/mean-temperature")
def mean_temperature_index():
    return jsonify(_climate_index("mean_temperature"))


# Same MODIS IGBP palette as scripts/raster2png.py's LULC_COLORS — duplicated
# (rather than imported from scripts/, which isn't guaranteed to be on the
# Python path in production) so the sample endpoint can reverse a pixel color
# back into a class name. Keep in sync with that file if the palette changes.
_LULC_CLASS_NAMES = {
    (0, 100, 0): "Evergreen Needleleaf Forest",
    (0, 130, 0): "Evergreen Broadleaf Forest",
    (60, 160, 60): "Deciduous Needleleaf Forest",
    (90, 180, 90): "Deciduous Broadleaf Forest",
    (60, 150, 30): "Mixed Forest",
    (150, 180, 60): "Closed Shrublands",
    (190, 200, 100): "Open Shrublands",
    (170, 190, 110): "Woody Savannas",
    (210, 210, 120): "Savannas",
    (160, 220, 80): "Grasslands",
    (110, 180, 220): "Permanent Wetlands",
    (240, 200, 80): "Croplands",
    (200, 30, 30): "Urban & Built-up",
    (230, 220, 100): "Cropland / Natural Vegetation Mosaic",
    (240, 240, 250): "Snow & Ice",
    (200, 180, 150): "Barren",
    (60, 100, 180): "Water",
}


def _nearest_lulc_class(rgb):
    best, best_dist = None, None
    for color, name in _LULC_CLASS_NAMES.items():
        dist = sum((a - b) ** 2 for a, b in zip(color, rgb))
        if best_dist is None or dist < best_dist:
            best, best_dist = name, dist
    return best


def _nearest_named_color(rgb, classes):
    """classes: [{"name": ..., "color": "rgb(r,g,b)"}, ...] — used for
    geomorphology, whose palette is generated at processing time (75
    classes) rather than a fixed hand-picked one like LULC's."""
    best, best_dist = None, None
    for c in classes:
        r, g, b = (int(x) for x in c["color"][4:-1].split(","))
        dist = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if best_dist is None or dist < best_dist:
            best, best_dist = c["name"], dist
    return best


def _pixel_at(png_path, bounds, lat, lon, search_radius_px=80):
    """Read a pixel's RGBA out of a rendered overlay PNG at a given lat/lon.

    If the exact pixel is nodata (alpha==0), spirals outward pixel-ring by
    pixel-ring to the nearest opaque pixel instead of immediately giving up.
    This is the actual fix for districts whose official centroid sits right
    at the edge of a dataset's precise coverage (very common — the coarse
    1-degree temperature grid, for instance, has gaps of tens of km between
    cell centers) previously coming back as "no data": now they get the
    nearest real value the dataset actually has, honestly labeled as such.

    Returns (pixel, is_exact). (None, False) if nothing is found at all
    (i.e. the point is nowhere near this dataset's coverage).
    """
    from PIL import Image

    with Image.open(png_path) as img:
        img = img.convert("RGBA")
        w, h = img.size
        x = (lon - bounds["west"]) / (bounds["east"] - bounds["west"]) * w
        y = (bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * h
        x0, y0 = int(min(max(x, 0), w - 1)), int(min(max(y, 0), h - 1))

        pixel = img.getpixel((x0, y0))
        if pixel[3] != 0:
            return pixel, True

        best, best_dist = None, None
        for r in range(1, search_radius_px + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue  # only test the ring at this exact radius
                    xx, yy = x0 + dx, y0 + dy
                    if not (0 <= xx < w and 0 <= yy < h):
                        continue
                    p = img.getpixel((xx, yy))
                    if p[3] == 0:
                        continue
                    dist = dx * dx + dy * dy
                    if best_dist is None or dist < best_dist:
                        best, best_dist = p, dist
            if best is not None:
                return best, False
        return None, False


def _invert_continuous(rgb, stops, vmin, vmax):
    """Given a pixel color painted with `stops` between vmin/vmax, find the
    closest point on the ramp and return the approximate source value."""
    best_t, best_dist = 0.0, None
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        for step in range(11):  # sample the segment finely enough for a good match
            t = step / 10
            pos = p0 + t * (p1 - p0)
            color = tuple(c0[k] + t * (c1[k] - c0[k]) for k in range(3))
            dist = sum((a - b) ** 2 for a, b in zip(color, rgb))
            if best_dist is None or dist < best_dist:
                best_dist, best_t = dist, pos
    return round(vmin + best_t * (vmax - vmin), 1)


@data_bp.route("/rasters/sample")
def rasters_sample():
    """Sample the LULC / precipitation / mean-temperature / geomorphology
    overlay at a point (for LULC/precipitation/mean-temperature, also for a
    given year) — this is what powers the Spatial Map's click-a-district
    popups (see GeoSpatialData.jsx). Falls back to the nearest pixel with
    real data if the exact point is right at a dataset's coverage edge —
    see _pixel_at's docstring for why that matters."""
    layer = request.args.get("layer")
    year = request.args.get("year")
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon (numbers) are required"}), 400

    if layer == "lulc":
        idx = _read_json("rasters", "lulc_index.json") if os.path.exists(_data_path("rasters", "lulc_index.json")) else {}
        info = idx.get(year)
        if not info:
            return jsonify({"available": False, "reason": "No LULC data for that year."})
        pixel, is_exact = _pixel_at(_data_path(info["file"]), info["bounds"], lat, lon)
        if pixel is None:
            return jsonify({"available": False, "reason": "No data anywhere near this location."})
        return jsonify({
            "available": True,
            "layer": "lulc",
            "year": year,
            "class_name": _nearest_lulc_class(pixel[:3]),
            "approximate": not is_exact,
        })

    if layer == "geomorphology":
        meta_path = _data_path("rasters", "geomorphology_meta.json")
        if not os.path.exists(meta_path):
            return jsonify({"available": False, "reason": "No geomorphology data uploaded yet."})
        with open(meta_path) as f:
            meta = json.load(f)
        pixel, is_exact = _pixel_at(_data_path(meta["file"]), meta["bounds"], lat, lon)
        if pixel is None:
            return jsonify({"available": False, "reason": "No data anywhere near this location."})
        class_name = _nearest_named_color(pixel[:3], meta["classes"])
        return jsonify({
            "available": True,
            "layer": "geomorphology",
            "class_name": class_name,
            "approximate": not is_exact,
        })

    if layer in ("precipitation", "mean_temperature"):
        data = _climate_index(layer)
        info = data.get("years", {}).get(year)
        if not info:
            return jsonify({
                "available": False,
                "reason": f"No {layer.replace('_', ' ')} data uploaded for {year} yet. "
                          f"An admin can add it via scripts/climate_csv_to_png.py.",
            })
        png_path = _data_path(info["url"].replace("/static/data/", ""))
        pixel, is_exact = _pixel_at(png_path, info["bounds"], lat, lon)
        if pixel is None:
            return jsonify({"available": False, "reason": "No data anywhere near this location."})
        value = _invert_continuous(pixel[:3], [(p, tuple(c)) for p, c in data["stops"]], info["min"], info["max"])
        return jsonify({
            "available": True,
            "layer": layer,
            "year": year,
            "value": value,
            "unit": data["unit"],
            "approximate": not is_exact,
        })

    return jsonify({"error": "layer must be one of: lulc, geomorphology, precipitation, mean_temperature"}), 400


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
    """
    Downloading a report requires a verified @iiti.ac.in session.

    Accepts either an Authorization: Bearer header, or a short-lived signed
    link minted by /reports/<filename>/link. The signed form exists because a
    plain <a href> cannot send headers. Both paths are checked on the server,
    so editing the frontend or calling this URL directly does not help.
    """
    reports = _read_json("reports_index.json")
    if not any(r["filename"] == filename for r in reports):
        abort(404, description="Report not found")

    email = request.args.get("u", "")
    token = request.args.get("t", "")
    authorised = bool(email and token and verify_download_token(token, email, filename))
    if not authorised:
        authorised = lookup_bearer_session() is not None

    if not authorised:
        return jsonify({
            "error": "authentication_required",
            "message": "Downloads are restricted to IIT Indore (@iiti.ac.in) accounts. "
                       "Please sign in to download this report.",
        }), 401

    return send_from_directory(_data_path("reports"), filename, as_attachment=True)


@data_bp.route("/reports/<path:filename>/link")
@require_iiti_user
def report_download_link(filename):
    """Mint a 5-minute signed URL the browser can follow for a file download."""
    reports = _read_json("reports_index.json")
    if not any(r["filename"] == filename for r in reports):
        abort(404, description="Report not found")
    user = current_user()
    return jsonify({
        "url": f"/api/reports/{filename}?u={user['email']}&t="
               f"{make_download_token(user['email'], filename)}",
        "expires_in": 300,
    })


# ──────────────────────────────────────────────────────────────────────────
# Water Quality — 10 Year Comparative Analysis
# (built from the MPPCB "Narmada River Comparative" workbooks, 2015-16 → 2024-25)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/water-quality-10yr")
def water_quality_10yr():
    return jsonify(_read_json("water_quality_10yr.json"))


# ──────────────────────────────────────────────────────────────────────────
# Ground Water Quality (Middle & Upper Narmada basin, CGWB network)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/ground-water")
def ground_water():
    return jsonify(_read_json("ground_water.json"))


# ──────────────────────────────────────────────────────────────────────────
# Solid Waste (district-wise generation & management status)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/solid-waste")
def solid_waste():
    return jsonify(_read_json("solid_waste.json"))


# ──────────────────────────────────────────────────────────────────────────
# Agriculture GeoJSON layers (crop & irrigated area, orchards & horticulture)
# ──────────────────────────────────────────────────────────────────────────
@data_bp.route("/geojson/agriculture/<layer>")
def agriculture_geojson_layer(layer):
    allowed = {
        "crop_irrigated_area": "crop_irrigated_area.geojson",
        "orchards_horticulture": "orchards_horticulture.geojson",
    }
    if layer not in allowed:
        abort(404, description=f"Unknown layer '{layer}'. Available: {list(allowed)}")
    return send_from_directory(_data_path("geojson", "agriculture"), allowed[layer])
