"""
Water Body Atlas API for cNARMADA.

Endpoints
---------
  GET /api/atlas/water/layers        catalogue for the Water Body Atlas:
                                     district boundaries, named water
                                     bodies, unnamed water bodies
  GET /api/atlas/water/layer/<id>    one of those layers as GeoJSON
  GET /api/atlas/districts           the district boundaries on their own,
                                     shared by both atlas pages

The catalogue is the contract, exactly as it is for the River Atlas: the
page draws whatever the catalogue lists (style, draw order, popup field
labels, which layer the district filter reads), so nothing about the data
is written into the frontend.

The layer files come from scripts/build_water_atlas.py, which reads the
supplied shapefiles and the supplied district boundaries and keeps their
attributes and coordinates as they are. This module only serves them.

The River Atlas endpoints in river_atlas_routes.py are untouched; the two
share the gzip-twin serving helpers below.
"""

import json
import os

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from app.routes.river_atlas_routes import _gzip_matches, _stamp

atlas_bp = Blueprint("atlas", __name__, url_prefix="/api/atlas")

# Atlas id -> folder under DATA_DIR. The River Atlas keeps its own routes,
# so only the water atlas is served here.
ATLASES = {"water": "water_atlas"}
CATALOG_FILE = "catalog.json"
DISTRICT_ATLAS = "water"
DISTRICT_LAYER = "districts"


def _dir(atlas_id):
    return os.path.join(current_app.config["DATA_DIR"], ATLASES[atlas_id])


def _load_catalog(atlas_id):
    path = os.path.join(_dir(atlas_id), CATALOG_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# The Narmada centre line belongs to the River Atlas, and is drawn on the
# Water Body Atlas too so the water bodies can be read against the river.
# It is served from its own atlas rather than copied, so there is one file
# and one style for it.
RIVER_FOLDER = "river_atlas"
SHARED_FROM_RIVER = ["centre_line"]


def _river_catalog():
    path = os.path.join(current_app.config["DATA_DIR"], RIVER_FOLDER, CATALOG_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _river_entries(existing_ids, top_z):
    """River Atlas layers the water atlas also shows, served from there."""
    river = _river_catalog()
    if not river:
        return []
    out = []
    for layer_id in SHARED_FROM_RIVER:
        if layer_id in existing_ids:
            continue
        source = next((l for l in river.get("layers", []) if l.get("id") == layer_id), None)
        if not source:
            continue
        path = os.path.join(current_app.config["DATA_DIR"], RIVER_FOLDER, source["file"])
        entry = {k: v for k, v in source.items() if k != "file"}
        entry["url"] = f"/api/river-atlas/layer/{layer_id}?v={_stamp(path)}"
        entry["available"] = os.path.exists(path)
        top_z += 1
        entry["z_index"] = top_z          # drawn over the water bodies
        entry["default_visible"] = True
        out.append(entry)
    return out


def _public_catalog(atlas_id, catalog):
    """Add each layer's fetch URL and drop server-side-only keys."""
    out = dict(catalog)
    layers = []
    for layer in catalog.get("layers", []):
        entry = {k: v for k, v in layer.items() if k != "file"}
        path = os.path.join(_dir(atlas_id), layer["file"])
        entry["url"] = f"/api/atlas/{atlas_id}/layer/{layer['id']}?v={_stamp(path)}"
        entry["available"] = os.path.exists(path)
        layers.append(entry)
    top_z = max([l.get("z_index", 0) for l in layers] or [0])
    layers.extend(_river_entries({l["id"] for l in layers}, top_z))
    layers.sort(key=lambda entry: entry.get("z_index", 0))
    out["layers"] = layers
    return out


def _serve_geojson(path):
    """Send the pre-compressed twin when the client takes gzip, else the file."""
    gz_path = path + ".gz"
    accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "").lower()
    use_gzip = accepts_gzip and os.path.exists(gz_path) and _gzip_matches(gz_path, path)

    if accepts_gzip and os.path.exists(gz_path) and not use_gzip:
        current_app.logger.warning(
            "Atlas: %s.gz is damaged or does not match %s, serving the "
            "uncompressed file instead. Re-copy it and make sure Git treats "
            "*.gz as binary.", os.path.basename(path), os.path.basename(path),
        )

    if use_gzip:
        with open(gz_path, "rb") as fh:
            body = fh.read()
        response = Response(body, mimetype="application/geo+json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(body))
    else:
        response = send_file(path, mimetype="application/geo+json", conditional=True)

    response.headers["Vary"] = "Accept-Encoding"
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@atlas_bp.route("/<atlas_id>/layers")
def layers(atlas_id):
    if atlas_id not in ATLASES:
        return jsonify({"error": f"Unknown atlas: {atlas_id}",
                        "available": sorted(ATLASES)}), 404
    catalog = _load_catalog(atlas_id)
    if catalog is None:
        return jsonify({
            "error": "Water Body Atlas data has not been built on this server.",
            "hint": "Run scripts/build_water_atlas.py to generate "
                    "app/static/data/water_atlas/.",
        }), 404
    response = jsonify(_public_catalog(atlas_id, catalog))
    # Always re-read, so a rebuilt layer's new ?v= tag reaches the page.
    response.headers["Cache-Control"] = "no-cache"
    return response


@atlas_bp.route("/<atlas_id>/layer/<layer_id>")
def layer(atlas_id, layer_id):
    if atlas_id not in ATLASES:
        return jsonify({"error": f"Unknown atlas: {atlas_id}",
                        "available": sorted(ATLASES)}), 404
    catalog = _load_catalog(atlas_id)
    if catalog is None:
        return jsonify({"error": "Water Body Atlas data has not been built on this server."}), 404

    entry = next((l for l in catalog.get("layers", []) if l.get("id") == layer_id), None)
    if entry is None:
        return jsonify({"error": f"Unknown atlas layer: {atlas_id}/{layer_id}",
                        "available": [l.get("id") for l in catalog.get("layers", [])]}), 404

    path = os.path.join(_dir(atlas_id), entry["file"])
    if not os.path.exists(path):
        return jsonify({"error": f"Layer file missing on the server: {entry['file']}"}), 404
    return _serve_geojson(path)


@atlas_bp.route("/districts")
def districts():
    """
    The supplied district boundaries.

    Both atlas pages filter their features by district, so the boundaries
    are published on their own rather than being duplicated per atlas.
    """
    catalog = _load_catalog(DISTRICT_ATLAS)
    if catalog is None:
        return jsonify({"error": "District boundaries have not been built on this server.",
                        "hint": "Run scripts/build_water_atlas.py."}), 404

    entry = next((l for l in catalog.get("layers", [])
                  if l.get("id") == catalog.get("district_layer", DISTRICT_LAYER)), None)
    if entry is None:
        return jsonify({"error": "The catalogue names no district layer."}), 404

    path = os.path.join(_dir(DISTRICT_ATLAS), entry["file"])
    if not os.path.exists(path):
        return jsonify({"error": f"District file missing on the server: {entry['file']}"}), 404
    return _serve_geojson(path)
