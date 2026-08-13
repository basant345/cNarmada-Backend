"""
Admin Panel API for cNARMADA — Part 2: Structured Dataset Records (CRUD).

Gives the Admin Panel real add / edit / delete / search-and-filter access to
every "table-shaped" dataset on the site — the ones that already power a
page with a variable dropdown, chart, or map (Stations, Agriculture, Basin
Demography) — without hand-writing a bespoke endpoint per dataset.

A dataset is "table-shaped" if it's either:
  - a flat JSON array of objects (e.g. stations.json), or
  - a GeoJSON FeatureCollection, where each *feature* is one record and its
    `properties` dict holds the editable fields (e.g. the Agriculture and
    Basin Demography layers).

Adding a new manageable dataset later is a one-entry change to DATASETS
below — no new route code required.

Routes:
  GET    /api/admin/datasets                                — list every registered dataset + record counts
  GET    /api/admin/datasets/<id>/records?q=&field=&value=   — list/search/filter records
  POST   /api/admin/datasets/<id>/records                    — add a record
  PUT    /api/admin/datasets/<id>/records/<record_id>        — edit a record
  DELETE /api/admin/datasets/<id>/records/<record_id>        — delete a record
"""
import os
import json
import shutil

from flask import Blueprint, jsonify, request, current_app, abort

from .admin_routes import _require_admin

admin_records_bp = Blueprint("admin_records", __name__, url_prefix="/api/admin")

# ── Dataset registry ─────────────────────────────────────────────────────
# path is relative to DATA_DIR. format is "json_array" (top-level list of
# objects) or "geojson" (FeatureCollection; records = feature.properties).
DATASETS = {
    "stations": {
        "label": "Monitoring Stations",
        "section": "Stations",
        "path": "stations.json",
        "format": "json_array",
        "id_field": "slug",
    },
    "agriculture_crop": {
        "label": "Agriculture — Crop & Irrigated Area",
        "section": "Agriculture",
        "path": "geojson/agriculture/crop_irrigated_area.geojson",
        "format": "geojson",
        "id_field": "district",
    },
    "agriculture_orchard": {
        "label": "Agriculture — Orchards & Horticulture",
        "section": "Agriculture",
        "path": "geojson/agriculture/orchards_horticulture.geojson",
        "format": "geojson",
        "id_field": "district",
    },
    "basin_demography": {
        "label": "Basin Demography",
        "section": "Basin Demography",
        "path": "geojson/final_demographic_data.geojson",
        "format": "geojson",
        "id_field": "District",
    },
}


def _dataset(dataset_id):
    ds = DATASETS.get(dataset_id)
    if not ds:
        abort(404, description=f"Unknown dataset '{dataset_id}'. Valid: {', '.join(DATASETS)}")
    return ds


def _full_path(ds):
    return os.path.join(current_app.config["DATA_DIR"], ds["path"])


def _read(ds):
    path = _full_path(ds)
    if not os.path.exists(path):
        return [] if ds["format"] == "json_array" else {"type": "FeatureCollection", "features": []}
    with open(path) as f:
        return json.load(f)


def _write(ds, data):
    """Atomic write with a one-deep .bak safety copy of the previous version."""
    path = _full_path(ds)
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def _records(ds, data):
    """Return the list of record dicts for a dataset document."""
    if ds["format"] == "json_array":
        return list(data)
    return [f.get("properties", {}) for f in data.get("features", [])]


def _record_id(ds, record):
    return record.get(ds["id_field"])


# ── GET /api/admin/datasets ──────────────────────────────────────────────
@admin_records_bp.route("/datasets")
def list_datasets():
    _, err = _require_admin()
    if err:
        return err

    out = []
    for did, ds in DATASETS.items():
        data = _read(ds)
        recs = _records(ds, data)
        out.append({
            "id": did,
            "label": ds["label"],
            "section": ds["section"],
            "format": ds["format"],
            "id_field": ds["id_field"],
            "record_count": len(recs),
        })
    return jsonify(out)


# ── GET /api/admin/datasets/<id>/records ─────────────────────────────────
@admin_records_bp.route("/datasets/<dataset_id>/records")
def list_records(dataset_id):
    _, err = _require_admin()
    if err:
        return err

    ds = _dataset(dataset_id)
    data = _read(ds)
    all_recs = _records(ds, data)

    # Field list (union of keys across every record, not just the filtered
    # ones) so the frontend can always build a complete dynamic form/table,
    # even when a search/filter narrows the visible rows down to zero.
    fields = []
    seen = set()
    for r in all_recs:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                fields.append(k)

    recs = all_recs
    q = (request.args.get("q") or "").strip().lower()
    field = request.args.get("field")
    value = request.args.get("value")

    if field and value is not None:
        recs = [r for r in recs if str(r.get(field, "")).strip().lower() == value.strip().lower()]

    if q:
        def matches(r):
            return any(q in str(v).lower() for v in r.values())
        recs = [r for r in recs if matches(r)]

    return jsonify({
        "id_field": ds["id_field"],
        "fields": fields,
        "records": recs,
    })


# ── POST /api/admin/datasets/<id>/records ────────────────────────────────
@admin_records_bp.route("/datasets/<dataset_id>/records", methods=["POST"])
def add_record(dataset_id):
    _, err = _require_admin()
    if err:
        return err

    ds = _dataset(dataset_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object of field: value pairs."}), 400

    new_id = payload.get(ds["id_field"])
    if not new_id:
        return jsonify({"error": f"'{ds['id_field']}' is required to identify this record."}), 400

    data = _read(ds)
    recs = _records(ds, data)
    if any(_record_id(ds, r) == new_id for r in recs):
        return jsonify({"error": f"A record with {ds['id_field']}='{new_id}' already exists."}), 409

    if ds["format"] == "json_array":
        data.append(payload)
    else:
        data.setdefault("features", []).append({
            "type": "Feature",
            "properties": payload,
            "geometry": None,  # no geometry supplied via the admin form —
                                # edit the raw file/GeoJSON if this record
                                # needs to render on the map.
        })

    _write(ds, data)
    return jsonify({"message": "Record added", "record": payload}), 201


# ── PUT /api/admin/datasets/<id>/records/<record_id> ─────────────────────
@admin_records_bp.route("/datasets/<dataset_id>/records/<path:record_id>", methods=["PUT"])
def edit_record(dataset_id, record_id):
    _, err = _require_admin()
    if err:
        return err

    ds = _dataset(dataset_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object of field: value pairs."}), 400

    data = _read(ds)

    if ds["format"] == "json_array":
        idx = next((i for i, r in enumerate(data) if _record_id(ds, r) == record_id), None)
        if idx is None:
            return jsonify({"error": "Record not found"}), 404
        merged = {**data[idx], **payload}
        data[idx] = merged
    else:
        features = data.get("features", [])
        idx = next((i for i, f in enumerate(features) if _record_id(ds, f.get("properties", {})) == record_id), None)
        if idx is None:
            return jsonify({"error": "Record not found"}), 404
        merged = {**features[idx].get("properties", {}), **payload}
        features[idx]["properties"] = merged
        data["features"] = features

    _write(ds, data)
    return jsonify({"message": "Record updated", "record": merged}), 200


# ── DELETE /api/admin/datasets/<id>/records/<record_id> ──────────────────
@admin_records_bp.route("/datasets/<dataset_id>/records/<path:record_id>", methods=["DELETE"])
def delete_record(dataset_id, record_id):
    _, err = _require_admin()
    if err:
        return err

    ds = _dataset(dataset_id)
    data = _read(ds)

    if ds["format"] == "json_array":
        before = len(data)
        data = [r for r in data if _record_id(ds, r) != record_id]
        if len(data) == before:
            return jsonify({"error": "Record not found"}), 404
    else:
        features = data.get("features", [])
        before = len(features)
        features = [f for f in features if _record_id(ds, f.get("properties", {})) != record_id]
        if len(features) == before:
            return jsonify({"error": "Record not found"}), 404
        data["features"] = features

    _write(ds, data)
    return jsonify({"message": "Record deleted"}), 200
