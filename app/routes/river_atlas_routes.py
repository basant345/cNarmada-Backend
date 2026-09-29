"""
River Atlas API for cNARMADA.

Endpoints
---------
  GET /api/river-atlas/layers        catalogue: every layer, its style, draw
                                     order, default visibility and popup
                                     field labels
  GET /api/river-atlas/layer/<id>    one layer as GeoJSON
  GET /api/river-atlas/layer/<id>/tile/<band>/<z>/<x>/<y>
                                     one tile of a tiled layer, for layers
                                     too large to send whole (the catalogue
                                     entry's "tiles" block lists them)
  GET /api/river-atlas/layer/<id>/raster/<z>/<x>/<y>.png
                                     a pre-drawn image tile of a layer too
                                     dense to draw as vectors when zoomed
                                     out (the entry's "raster" block)

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


def _raster_dir(layer_id):
    return os.path.join(_dir(), "tiles", layer_id, "raster")


def _raster_present(layer_id, raster):
    """True when the zoom folders the catalogue promises exist and hold tiles."""
    root = _raster_dir(layer_id)
    for z in range(raster.get("min_zoom", 0), raster.get("max_zoom", -1) + 1):
        zdir = os.path.join(root, str(z))
        if not os.path.isdir(zdir) or not os.listdir(zdir):
            return False
    return os.path.isdir(root)


def _stamp(*paths):
    """
    A short version tag from the files' modification times and sizes.

    Added to every data URL as ?v=..., so when a layer or its tiles are
    replaced the browser fetches the new copy instead of reusing a cached
    one. Responses are cached for a day, which is right for unchanged data
    and wrong the moment the data changes; the tag keeps both true.
    """
    parts = []
    for path in paths:
        try:
            st = os.stat(path)
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return format(zlib.crc32("|".join(parts).encode()) & 0xFFFFFFFF, "08x")


# The district boundaries live once, in the water atlas folder, and are
# published to both atlas pages. If this catalogue does not carry its own
# districts layer, the shared one is added here, so district filtering
# works whether or not a copy of the boundaries sits beside the river
# layers.
WATER_FOLDER = "water_atlas"


def _water_catalog():
    path = os.path.join(current_app.config["DATA_DIR"], WATER_FOLDER, CATALOG_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _shared_district_entry(out):
    """The district layer as the water atlas publishes it, served from there."""
    water = _water_catalog()
    if not water:
        return None
    layer_id = water.get("district_layer", "districts")
    source = next((l for l in water.get("layers", []) if l.get("id") == layer_id), None)
    if not source:
        return None
    path = os.path.join(current_app.config["DATA_DIR"], WATER_FOLDER, source["file"])

    entry = {k: v for k, v in source.items() if k != "file"}
    entry["url"] = f"/api/atlas/districts?v={_stamp(path)}"
    entry["available"] = os.path.exists(path)
    # Under everything else: the boundaries are context for the rivers.
    entry["z_index"] = min([l.get("z_index", 0) for l in out.get("layers", [])] or [1]) - 1
    entry["default_visible"] = False
    out.setdefault("district_layer", layer_id)
    out.setdefault("district_name_field", water.get("district_name_field", "NAME_2"))
    out.setdefault("district_state_field", water.get("district_state_field", "NAME_1"))
    return entry


def _public_catalog(catalog):
    """Add the fetch URL for each layer, and drop server-side-only keys."""
    out = dict(catalog)
    layers = []
    for layer in catalog.get("layers", []):
        entry = {k: v for k, v in layer.items() if k != "file"}
        layer_path = os.path.join(_dir(), layer["file"])
        entry["url"] = f"/api/river-atlas/layer/{layer['id']}?v={_stamp(layer_path)}"
        entry["available"] = os.path.exists(os.path.join(_dir(), layer["file"]))
        # Image tiles are only advertised when they are actually on disk.
        # Without them the page draws the layer's vectors as usual, so a
        # missing or misplaced tiles folder can never hide the layer.
        if entry.get("raster") and not _raster_present(layer["id"], entry["raster"]):
            current_app.logger.warning(
                "River Atlas: image tiles for %s not found under tiles/%s/raster/. "
                "Drawing its vectors instead.", layer["id"], layer["id"])
            entry.pop("raster")
        if entry.get("raster"):
            raster = dict(entry["raster"])
            zoom_dirs = [os.path.join(_raster_dir(layer["id"]), str(z))
                         for z in range(raster["min_zoom"], raster["max_zoom"] + 1)]
            raster["url"] = f"{raster['url']}?v={_stamp(*zoom_dirs)}"
            entry["raster"] = raster
        # A hairline drawn on a canvas is only as clickable as it is wide,
        # so line layers get a hit tolerance unless the catalogue sets its
        # own. Filled layers get none: a tolerance there would take clicks
        # meant for whatever lies underneath.
        if (entry.get("canvas") and "hit_tolerance" not in entry
                and "LineString" in str(entry.get("geometry_type") or "")):
            entry["hit_tolerance"] = 8
        if entry.get("tiles"):
            tiles = dict(entry["tiles"])
            band_dirs = [os.path.join(_dir(), "tiles", layer["id"], b["id"], str(b["tile_zoom"]))
                         for b in tiles.get("bands", [])]
            tiles["url"] = f"{tiles['url']}?v={_stamp(os.path.join(_dir(), CATALOG_FILE), *band_dirs)}"
            entry["tiles"] = tiles
        layers.append(entry)
    out["layers"] = layers
    if not any(l.get("id") == out.get("district_layer", "districts") for l in layers):
        shared = _shared_district_entry(out)
        if shared:
            layers.append(shared)
    # Draw order is data, not an accident of file order.
    layers.sort(key=lambda entry: entry.get("z_index", 0))
    out["layers"] = layers
    return out


# Tiles are small and numerous, so each one is checked once per process,
# the first time it is served: a full decompress validates its CRC.
_TILE_OK = {}


def _tile_sound(path):
    try:
        stamp = os.stat(path)
    except OSError:
        return False
    key = (stamp.st_mtime_ns, stamp.st_size)
    cached = _TILE_OK.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        with gzip.open(path, "rb") as fh:
            while fh.read(1 << 20):
                pass
        ok = True
    except (OSError, EOFError, zlib.error):
        ok = False
    _TILE_OK[path] = (key, ok)
    return ok


@river_atlas_bp.route("/layer/<layer_id>/tile/<band_id>/<int:z>/<int:x>/<int:y>")
def tile(layer_id, band_id, z, x, y):
    """
    One tile of a tiled layer.

    Tiles are stored gzip-only, as tiles/<layer>/<band>/<z>/<x>/<y>.geojson.gz.
    The path is built from the catalogue's own ids and from integers, never
    from free text, so a request can only reach a tile the catalogue names.
    A tile inside the band that holds no features answers with an empty
    FeatureCollection rather than a 404, so the map treats it as done.
    """
    catalog = _load_catalog()
    if catalog is None:
        return jsonify({"error": "River Atlas data has not been built on this server."}), 404

    entry = next((l for l in catalog.get("layers", []) if l.get("id") == layer_id), None)
    tiles_cfg = (entry or {}).get("tiles") or {}
    band = next((b for b in tiles_cfg.get("bands", []) if b.get("id") == band_id), None)
    if entry is None or band is None:
        return jsonify({"error": f"Unknown tiled layer or band: {layer_id}/{band_id}"}), 404
    if z != band.get("tile_zoom"):
        return jsonify({"error": f"Band {band_id} is tiled at zoom {band.get('tile_zoom')} only."}), 404

    path = os.path.join(_dir(), "tiles", layer_id, band_id, str(z), str(x), f"{y}.geojson.gz")
    if not os.path.exists(path):
        body = json.dumps({"type": "FeatureCollection", "features": []})
        response = Response(body, mimetype="application/geo+json")
        response.headers["Cache-Control"] = "no-store"
    elif not _tile_sound(path):
        current_app.logger.warning("River Atlas: tile %s is damaged. Re-copy it "
                                   "and make sure Git treats *.gz as binary.", path)
        return jsonify({"error": "This tile is damaged on the server."}), 500
    elif "gzip" in request.headers.get("Accept-Encoding", "").lower():
        with open(path, "rb") as fh:
            body = fh.read()
        response = Response(body, mimetype="application/geo+json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(body))
    else:
        # A client that does not take gzip (curl with no flags) still works.
        with gzip.open(path, "rb") as fh:
            response = Response(fh.read(), mimetype="application/geo+json")

    response.headers["Vary"] = "Accept-Encoding"
    response.headers.setdefault("Cache-Control", "public, max-age=86400")
    return response


@river_atlas_bp.route("/layers")
def layers():
    catalog = _load_catalog()
    if catalog is None:
        return jsonify({
            "error": "River Atlas data has not been built on this server.",
            "hint": "Run scripts/build_river_atlas.py to generate "
                    "app/static/data/river_atlas/.",
        }), 404
    response = jsonify(_public_catalog(catalog))
    # Always re-read, so new ?v= tags reach the page straight away.
    response.headers["Cache-Control"] = "no-cache"
    return response


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


# A fully transparent 256x256 PNG, answered for any tile inside the raster's
# zoom range that has nothing drawn on it. Built once, on first use.
_BLANK_PNG = None


def _blank_png():
    global _BLANK_PNG
    if _BLANK_PNG is None:
        import struct

        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        row = b"\x00" + b"\x00\x00\x00\x00" * 256
        _BLANK_PNG = (b"\x89PNG\r\n\x1a\n"
                      + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 6, 0, 0, 0))
                      + chunk(b"IDAT", zlib.compress(row * 256, 9))
                      + chunk(b"IEND", b""))
    return _BLANK_PNG


@river_atlas_bp.route("/layer/<layer_id>/raster/<int:z>/<int:x>/<int:y>.png")
def raster_tile(layer_id, z, x, y):
    """
    One pre-drawn image tile, stored as tiles/<layer>/raster/<z>/<x>/<y>.png.

    As with the vector tiles, the path is built from a catalogue id and
    integers only. Inside the raster's zoom range an empty spot gets a
    transparent tile, so the map never shows a broken image.
    """
    catalog = _load_catalog()
    if catalog is None:
        return jsonify({"error": "River Atlas data has not been built on this server."}), 404

    entry = next((l for l in catalog.get("layers", []) if l.get("id") == layer_id), None)
    raster = (entry or {}).get("raster")
    if not raster:
        return jsonify({"error": f"Layer {layer_id} has no image tiles."}), 404
    if not raster.get("min_zoom", 0) <= z <= raster.get("max_zoom", -1):
        return jsonify({"error": "Zoom outside this layer's image tiles."}), 404

    if not _raster_present(layer_id, raster):
        return jsonify({"error": f"Image tiles for {layer_id} are not on this server.",
                        "expected": f"app/static/data/river_atlas/tiles/{layer_id}/raster/<z>/<x>/<y>.png"}), 404

    path = os.path.join(_raster_dir(layer_id), str(z), str(x), f"{y}.png")
    if os.path.exists(path):
        response = send_file(path, mimetype="image/png", conditional=True)
    else:
        # A stand-in, not data: never let the browser keep it.
        response = Response(_blank_png(), mimetype="image/png")
        response.headers["Cache-Control"] = "no-store"
        return response
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response
