"""
River Atlas API for cNARMADA.

Endpoints
---------
  GET /api/river-atlas/layers        catalogue: every layer, its style, draw
                                     order, default visibility and popup
                                     field labels
  GET /api/river-atlas/layer/<id>    one layer as GeoJSON

The catalogue is the contract. The River Atlas page draws whatever the
catalogue lists — layer toggles, legend swatches, colours, popup rows are
all read from it, none of them hardcoded in the frontend. Publishing an
extra River Atlas dataset therefore takes no frontend change at all:

  1. put <new_layer>.geojson in app/static/data/river_atlas/
  2. add an entry to catalog.json in that folder

`id` is validated against the catalogue rather than used to build a path,
so a request can only ever reach a file the catalogue names.

Everything here is read-only and public, matching the other map layers in
data_routes.py. Gated downloads live in export_routes.py.
"""

import gzip
import json
import os
import zlib

from flask import Blueprint, Response, current_app, jsonify, request, send_file

river_atlas_bp = Blueprint("river_atlas", __name__, url_prefix="/api/river-atlas")

FOLDER = "river_atlas"
CATALOG_FILE = "catalog.json"


def _dir():
    return os.path.join(current_app.config["DATA_DIR"], FOLDER)


def _load_catalog():
    """Read catalog.json, or None if the dataset has not been built yet."""
    path = os.path.join(_dir(), CATALOG_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# Result of the integrity check below, keyed by path and invalidated whenever
# the file's mtime or size changes. The check decompresses the whole stream,
# so it runs at most once per file per process.
_GZIP_OK = {}


def _gzip_matches(gz_path, plain_path):
    """
    Is this .gz a sound twin of the plain file next to it?

    Serving a damaged .gz is worse than not serving one at all: the browser
    aborts with ERR_CONTENT_DECODING_FAILED and the layer silently fails to
    draw. Falling back to the plain file keeps the map working.

    The check that matters is a full decompress. Reading the stream to the end
    validates the CRC, and comparing the byte count to the plain file catches
    truncation. Header and trailer checks alone are not enough: a Windows
    checkout rewriting LF to CRLF inside the binary corrupts the compressed
    body while leaving the magic bytes and the size trailer looking correct.

    The result is cached against the file's mtime and size, so the cost is one
    decompress per file per process, not one per request.
    """
    try:
        stamp = os.stat(gz_path)
        key = (stamp.st_mtime_ns, stamp.st_size)
        plain_size = os.path.getsize(plain_path)
    except OSError:
        return False

    cached = _GZIP_OK.get(gz_path)
    if cached is not None and cached[0] == key:
        return cached[1]

    ok = False
    try:
        with gzip.open(gz_path, "rb") as fh:
            total = 0
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
        ok = total == plain_size
    except (OSError, EOFError, zlib.error):
        ok = False

    _GZIP_OK[gz_path] = (key, ok)
    return ok


def _public_catalog(catalog):
    """Add the fetch URL for each layer, and drop server-side-only keys."""
    out = dict(catalog)
    layers = []
    for layer in catalog.get("layers", []):
        entry = {k: v for k, v in layer.items() if k != "file"}
        entry["url"] = f"/api/river-atlas/layer/{layer['id']}"
        entry["available"] = os.path.exists(os.path.join(_dir(), layer["file"]))
        layers.append(entry)
    # Draw order is data, not an accident of file order.
    layers.sort(key=lambda entry: entry.get("z_index", 0))
    out["layers"] = layers
    return out


@river_atlas_bp.route("/layers")
def layers():
    catalog = _load_catalog()
    if catalog is None:
        return jsonify({
            "error": "River Atlas data has not been built on this server.",
            "hint": "Run scripts/build_river_atlas.py to generate "
                    "app/static/data/river_atlas/.",
        }), 404
    return jsonify(_public_catalog(catalog))


@river_atlas_bp.route("/layer/<layer_id>")
def layer(layer_id):
    catalog = _load_catalog()
    if catalog is None:
        return jsonify({"error": "River Atlas data has not been built on this server."}), 404

    entry = next((l for l in catalog.get("layers", []) if l.get("id") == layer_id), None)
    if entry is None:
        known = [l.get("id") for l in catalog.get("layers", [])]
        return jsonify({"error": f"Unknown River Atlas layer: {layer_id}",
                        "available": known}), 404

    path = os.path.join(_dir(), entry["file"])
    if not os.path.exists(path):
        return jsonify({"error": f"Layer file missing on the server: {entry['file']}"}), 404

    # build_river_atlas.py writes a pre-compressed twin next to each layer.
    # Serving that to clients advertising gzip turns a ~6 MB download into
    # ~1 MB without compressing anything per request. Clients that do not
    # advertise gzip (curl with no flags, for instance) get the plain file,
    # so the endpoint stays usable from a terminal.
    gz_path = path + ".gz"
    accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "").lower()
    use_gzip = accepts_gzip and os.path.exists(gz_path) and _gzip_matches(gz_path, path)

    if accepts_gzip and os.path.exists(gz_path) and not use_gzip:
        current_app.logger.warning(
            "River Atlas: %s.gz is damaged or does not match %s, serving the "
            "uncompressed file instead. Re-copy it and make sure Git treats "
            "*.gz as binary.", entry["file"], entry["file"],
        )

    if use_gzip:
        with open(gz_path, "rb") as fh:
            body = fh.read()
        response = Response(body, mimetype="application/geo+json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(body))
        response.headers["Vary"] = "Accept-Encoding"
    else:
        response = send_file(path, mimetype="application/geo+json",
                             conditional=True)
        response.headers["Vary"] = "Accept-Encoding"

    # These layers change only when the shapefiles are rebuilt and
    # redeployed, so let the browser keep them for a day.
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response
