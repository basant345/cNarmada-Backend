# -*- coding: utf-8 -*-
"""
export_routes.py  --  gated dataset downloads.

Every endpoint here requires a verified @iiti.ac.in session. They exist so
that the public view endpoints in data_routes.py can stay completely open:
anyone may chart, map and browse the data without logging in, while pulling
a dataset out as a file requires an institutional account.

The check runs on the server for every request. Editing the frontend, calling
these URLs directly, or replaying a request without a token all return 401.
A session belonging to a non-institutional address is refused as well, because
the domain is re-checked per request rather than trusted from the token.
"""
import os

from flask import Blueprint, jsonify, current_app, send_from_directory, abort

from app.auth_guard import require_iiti_user, current_user

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


def _data_path(*parts):
    return os.path.join(current_app.config["DATA_DIR"], *parts)


def _read_json(*parts):
    import json
    path = _data_path(*parts)
    if not os.path.exists(path):
        abort(404, description=f"{'/'.join(parts)} not found")
    with open(path) as f:
        return json.load(f)


@export_bp.route("/whoami")
@require_iiti_user
def whoami():
    """Lets the frontend confirm a session is still good before exporting."""
    return jsonify({"email": current_user()["email"], "name": current_user()["name"]})


@export_bp.route("/water-quality-10yr")
@require_iiti_user
def export_water_quality_10yr():
    return jsonify(_read_json("water_quality_10yr.json"))


@export_bp.route("/ground-water")
@require_iiti_user
def export_ground_water():
    return jsonify(_read_json("ground_water.json"))


@export_bp.route("/solid-waste")
@require_iiti_user
def export_solid_waste():
    return jsonify(_read_json("solid_waste.json"))


# ──────────────────────────────────────────────────────────────────────────
# Industrial profile and the Gujarat datasets.
#
# data_routes.py serves each of these openly so the charts and maps render for
# everyone. These gated twins exist so the Excel downloads go through the same
# @iiti.ac.in check as every other export. Without them the frontend would call
# the public endpoint, get a 200, and save the file without ever prompting.
# ──────────────────────────────────────────────────────────────────────────
@export_bp.route("/industrial-profile")
@require_iiti_user
def export_industrial_profile():
    return jsonify(_read_json("industrial_profile.json"))


@export_bp.route("/gujarat/water-quality")
@require_iiti_user
def export_gujarat_water_quality():
    return jsonify(_read_json("gujarat_water_quality.json"))


@export_bp.route("/gujarat/solid-waste")
@require_iiti_user
def export_gujarat_solid_waste():
    return jsonify(_read_json("gujarat_solid_waste.json"))


@export_bp.route("/gujarat/sediment")
@require_iiti_user
def export_gujarat_sediment():
    return jsonify(_read_json("gujarat_sediment.json"))


@export_bp.route("/basin-demography")
@require_iiti_user
def export_basin_demography():
    # Same file data_routes serves publicly as /api/geojson/basin_demography.
    return send_from_directory(_data_path("geojson"), "final_demographic_data.geojson")


@export_bp.route("/water-quality")
@require_iiti_user
def export_water_quality():
    return jsonify(_read_json("water_quality.json"))


# Same layer map data_routes serves publicly for the maps. Viewing a layer on
# the map is open; pulling the GeoJSON file down is not.
_GEOJSON_LAYERS = {
    "basin_boundary": "basin_boundary.geojson",
    "centerline": "centerline.geojson",
    "named_network": "named_network.geojson",
    "basin_demography": "final_demographic_data.geojson",
    "dams": "dams.geojson",
    "waterbodies": "waterbodies.geojson",
    "stp": "stp.geojson",
}


@export_bp.route("/geojson/<layer>")
@require_iiti_user
def export_geojson(layer):
    if layer not in _GEOJSON_LAYERS:
        abort(404, description=f"Unknown layer '{layer}'. Available: {list(_GEOJSON_LAYERS)}")
    return send_from_directory(_data_path("geojson"), _GEOJSON_LAYERS[layer])


@export_bp.route("/stations/<slug>")
@require_iiti_user
def export_station(slug):
    """Full station record including its streamflow / water level series."""
    import json
    stations = _read_json("stations.json")
    match = next((s for s in stations if s["slug"] == slug), None)
    if not match:
        abort(404, description=f"Unknown station '{slug}'")

    result = dict(match)
    for kind in ("streamflow", "waterlevel"):
        if match.get(f"has_{kind}"):
            path = _data_path("timeseries", f"{kind}_{slug}.json")
            if os.path.exists(path):
                with open(path) as f:
                    result[kind] = json.load(f)
    return jsonify(result)


_AGRI_LAYERS = {
    "crop_irrigated_area": "crop_irrigated_area.geojson",
    "orchards_horticulture": "orchards_horticulture.geojson",
}


@export_bp.route("/agriculture/<layer>")
@require_iiti_user
def export_agriculture(layer):
    if layer not in _AGRI_LAYERS:
        abort(404, description=f"Unknown layer '{layer}'. Available: {list(_AGRI_LAYERS)}")
    return send_from_directory(_data_path("geojson", "agriculture"), _AGRI_LAYERS[layer])
