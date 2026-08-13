"""
Admin Panel API for cNARMADA — Part 1: Auth + Universal File Manager.

Reuses the existing OTP authentication system (see auth_routes.py) — there
is NO separate admin login form or parallel auth system. An admin signs in
through the exact same POST /api/auth/send-otp + POST /api/auth/verify-otp
flow already used for Data Download access. The token that flow returns is
then checked here (GET /api/admin/check) against an admin allowlist
(ADMIN_EMAILS env var, comma-separated emails).

Routes:
  GET    /api/admin/check                          — Is this token's email an admin?
  GET    /api/admin/login-attempts                 — List login attempts (?status=Success|Failed|Incomplete)
  GET    /api/admin/sections                       — List every manageable file section (name, folder, allowed types)
  GET    /api/admin/files?section=<name>            — List files in a section (admin view). Defaults to "Reports".
  POST   /api/admin/files                           — Upload/replace a file (multipart/form-data: file, section, title, replace_filename?)
  DELETE /api/admin/files/<filename>?section=<name> — Delete a file
  GET    /api/admin/files/<filename>/preview?section=<name>  — Text/JSON/image preview for the admin panel
  GET    /api/admin/files/<filename>/download?section=<name> — Admin download (works for every section, not just Reports)

Every section except "Reports" is brand new: this file introduces a
universal file manager over every data folder used by the site (agriculture
GeoJSON, boundary/network GeoJSON, rasters, timeseries, sewer outfall
images, and the flat "core dataset" JSON files at the data root), so any
file type — CSV, Excel, GeoJSON, JSON, TIFF/DEM, images, PDF — can be
listed, uploaded, replaced, downloaded, previewed and deleted from the
Admin Panel, exactly like PDFs already could.

"Reports" keeps its exact original behaviour (same reports_index.json
format, same /reports folder) so the public GET /api/reports routes in
data_routes.py — and any code that already reads reports_index.json — are
completely unaffected.
"""
import os
import json
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app, send_from_directory, abort

from .auth_routes import _get_conn as _auth_conn, _verify_token_signature

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# ── File sections ────────────────────────────────────────────────────────
# Every section the Admin Panel's file manager can browse. `dir` is
# relative to DATA_DIR ("" = the data root itself). `exts` are the file
# extensions accepted for upload into that section.
SECTIONS = {
    "Reports": {
        "dir": "reports",
        "exts": {"csv", "xlsx", "xls", "tif", "tiff", "dem", "asc", "pdf"},
    },
    "Agriculture": {
        "dir": "geojson/agriculture",
        "exts": {"geojson", "json", "csv", "xlsx", "xls"},
    },
    "Basin Boundary & Network": {
        "dir": "geojson",
        "exts": {"geojson", "json"},
    },
    "Rasters (LULC / DEM)": {
        "dir": "rasters",
        "exts": {"png", "tif", "tiff", "json"},
    },
    "Timeseries (Streamflow / Water Level)": {
        "dir": "timeseries",
        "exts": {"json", "csv"},
    },
    "Sewer Outfall Images": {
        "dir": "sewer_outfall_images",
        "exts": {"jpg", "jpeg", "png"},
    },
    "Core Datasets": {
        "dir": "",
        "exts": {"json", "csv", "xlsx", "xls"},
    },
}

# Files that live at the data root but are internal bookkeeping, not
# content — never list/upload/delete these through "Core Datasets".
_ROOT_RESERVED = {"reports_index.json", "admin_files_meta.json"}

TYPE_BY_EXT = {
    "csv": "CSV", "xlsx": "Excel", "xls": "Excel",
    "geojson": "GeoJSON", "json": "JSON",
    "tif": "DEM / Raster", "tiff": "DEM / Raster", "dem": "DEM / Raster", "asc": "DEM / Raster",
    "png": "Image", "jpg": "Image", "jpeg": "Image",
    "pdf": "PDF Report",
}
PREVIEWABLE_TEXT_EXTS = {"csv", "json", "geojson"}
PREVIEWABLE_IMAGE_EXTS = {"png", "jpg", "jpeg"}


# ── Admin auth (reuses auth_routes' token + auth_sessions, adds an allowlist) ──
def _admin_emails():
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _current_admin_email():
    """Return the requesting user's email if their existing OTP-auth token
    is valid AND their email is in the admin allowlist — else None."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
    if not token or not _verify_token_signature(token):
        return None

    conn = _auth_conn()
    try:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            "SELECT email FROM auth_sessions WHERE token=? AND expires_at>?",
            (token, now)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    email = row["email"].strip().lower()
    admins = _admin_emails()
    if not admins or email not in admins:
        return None
    return email


def _require_admin():
    email = _current_admin_email()
    if not email:
        return None, (jsonify({"error": "Admin access required"}), 403)
    return email, None


# ── GET /api/admin/check ────────────────────────────────────────────────
@admin_bp.route("/check")
def check_admin():
    email = _current_admin_email()
    return jsonify({"is_admin": bool(email), "email": email})


# ── GET /api/admin/login-attempts ───────────────────────────────────────
@admin_bp.route("/login-attempts")
def login_attempts():
    _, err = _require_admin()
    if err:
        return err

    status = request.args.get("status")
    valid_statuses = {"Success", "Failed", "Incomplete"}
    conn = _auth_conn()
    try:
        if status and status in valid_statuses:
            rows = conn.execute(
                "SELECT * FROM login_attempts WHERE status=? ORDER BY id DESC LIMIT 500",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM login_attempts ORDER BY id DESC LIMIT 500"
            ).fetchall()
    finally:
        conn.close()

    return jsonify([dict(r) for r in rows])


# ── File helpers ─────────────────────────────────────────────────────────
def _data_path(*parts):
    return os.path.join(current_app.config["DATA_DIR"], *parts)


def _section(name):
    sec = SECTIONS.get(name)
    if not sec:
        abort(400, description=f"Unknown section '{name}'. Valid: {', '.join(SECTIONS)}")
    return sec


def _section_dir(name):
    sec = _section(name)
    path = _data_path(sec["dir"]) if sec["dir"] else _data_path()
    os.makedirs(path, exist_ok=True)
    return path


def _ext(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _safe_filename(name):
    keep = "".join(c for c in name if c.isalnum() or c in "._- ").strip()
    return keep.replace(" ", "-") or f"file-{uuid.uuid4().hex[:8]}"


def _read_reports_index():
    path = _data_path("reports_index.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _write_reports_index(items):
    with open(_data_path("reports_index.json"), "w") as f:
        json.dump(items, f, indent=2)


def _read_meta():
    """Bookkeeping (title / uploaded_by / upload_date) for every non-Reports
    section, keyed by "Section/filename". Files that were already part of
    the project (not uploaded through the panel) simply won't have an
    entry here — we synthesize sensible metadata for those on read."""
    path = _data_path("admin_files_meta.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _write_meta(meta):
    with open(_data_path("admin_files_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def _file_entry(section, filename, meta):
    sec_dir = _section_dir(section)
    full = os.path.join(sec_dir, filename)
    ext = _ext(filename)
    key = f"{section}/{filename}"
    m = meta.get(key, {})
    stat = os.stat(full)
    return {
        "filename": filename,
        "section": section,
        "title": m.get("title", filename),
        "type": TYPE_BY_EXT.get(ext, ext.upper() or "File"),
        "size_mb": round(stat.st_size / (1024 * 1024), 3),
        "uploaded_by": m.get("uploaded_by", "—"),
        "upload_date": m.get("upload_date") or datetime.utcfromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "previewable": ext in PREVIEWABLE_TEXT_EXTS or ext in PREVIEWABLE_IMAGE_EXTS,
    }


# ── GET /api/admin/sections ──────────────────────────────────────────────
@admin_bp.route("/sections")
def list_sections():
    _, err = _require_admin()
    if err:
        return err
    return jsonify([
        {"name": name, "exts": sorted(cfg["exts"])}
        for name, cfg in SECTIONS.items()
    ])


# ── GET /api/admin/files ─────────────────────────────────────────────────
@admin_bp.route("/files")
def list_files():
    _, err = _require_admin()
    if err:
        return err

    section = request.args.get("section", "Reports")

    if section == "Reports":
        # Unchanged legacy behaviour — same records the site's public
        # Reports/Download section (and reports_index.json) already uses.
        return jsonify(_read_reports_index())

    _section(section)  # validates the name
    sec_dir = _section_dir(section)
    exts = SECTIONS[section]["exts"]
    meta = _read_meta()

    names = []
    for fn in sorted(os.listdir(sec_dir)):
        full = os.path.join(sec_dir, fn)
        if not os.path.isfile(full):
            continue
        if section == "Core Datasets" and fn in _ROOT_RESERVED:
            continue
        if _ext(fn) not in exts:
            continue
        names.append(fn)

    return jsonify([_file_entry(section, fn, meta) for fn in names])


# ── POST /api/admin/files ────────────────────────────────────────────────
@admin_bp.route("/files", methods=["POST"])
def upload_file():
    email, err = _require_admin()
    if err:
        return err

    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"error": "No file provided"}), 400

    section = (request.form.get("section") or "Reports").strip()
    _section(section)  # validates the name

    f = request.files["file"]
    ext = _ext(f.filename)
    allowed = SECTIONS[section]["exts"]
    if ext not in allowed:
        return jsonify({
            "error": f"File type '.{ext}' isn't allowed in '{section}'. Allowed: {', '.join(sorted(allowed))}"
        }), 400

    title = (request.form.get("title") or f.filename.rsplit(".", 1)[0]).strip()
    replace_filename = (request.form.get("replace_filename") or "").strip()

    if section == "Reports":
        # ── Unchanged legacy path: same folder, same reports_index.json ──
        reports_dir = _section_dir("Reports")
        items = _read_reports_index()

        if replace_filename:
            old_path = os.path.join(reports_dir, replace_filename)
            if os.path.exists(old_path):
                os.remove(old_path)
            items = [it for it in items if it.get("filename") != replace_filename]

        stored_name = _safe_filename(f.filename)
        dest = os.path.join(reports_dir, stored_name)
        if os.path.exists(dest):
            stored_name = f"{uuid.uuid4().hex[:8]}-{stored_name}"
            dest = os.path.join(reports_dir, stored_name)

        f.save(dest)
        size_mb = round(os.path.getsize(dest) / (1024 * 1024), 2)

        new_entry = {
            "title": title,
            "filename": stored_name,
            "size_mb": size_mb,
            "type": TYPE_BY_EXT.get(ext, ext.upper()),
            "uploaded_by": email,
            "upload_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        }
        items = [it for it in items if it.get("filename") != stored_name]
        items.append(new_entry)
        _write_reports_index(items)

        return jsonify({"message": "File uploaded", "file": new_entry}), 201

    # ── Every other section: generic path, tracked in admin_files_meta.json ──
    sec_dir = _section_dir(section)
    meta = _read_meta()

    if replace_filename:
        old_path = os.path.join(sec_dir, replace_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
        meta.pop(f"{section}/{replace_filename}", None)

    stored_name = _safe_filename(f.filename)
    dest = os.path.join(sec_dir, stored_name)
    if os.path.exists(dest) and stored_name != replace_filename:
        stored_name = f"{uuid.uuid4().hex[:8]}-{stored_name}"
        dest = os.path.join(sec_dir, stored_name)
    elif stored_name == replace_filename:
        dest = os.path.join(sec_dir, stored_name)

    f.save(dest)

    meta[f"{section}/{stored_name}"] = {
        "title": title,
        "uploaded_by": email,
        "upload_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
    }
    _write_meta(meta)

    return jsonify({"message": "File uploaded", "file": _file_entry(section, stored_name, meta)}), 201


# ── DELETE /api/admin/files/<filename> ───────────────────────────────────
@admin_bp.route("/files/<path:filename>", methods=["DELETE"])
def delete_file(filename):
    _, err = _require_admin()
    if err:
        return err

    section = request.args.get("section", "Reports")

    if section == "Reports":
        items = _read_reports_index()
        match = next((it for it in items if it.get("filename") == filename), None)
        if not match:
            return jsonify({"error": "File not found"}), 404
        items = [it for it in items if it.get("filename") != filename]
        _write_reports_index(items)
        path = _data_path("reports", filename)
        if os.path.exists(path):
            os.remove(path)
        return jsonify({"message": "File deleted"}), 200

    _section(section)  # validates the name
    sec_dir = _section_dir(section)
    path = os.path.join(sec_dir, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    os.remove(path)
    meta = _read_meta()
    meta.pop(f"{section}/{filename}", None)
    _write_meta(meta)

    return jsonify({"message": "File deleted"}), 200


# ── GET /api/admin/files/<filename>/preview ──────────────────────────────
@admin_bp.route("/files/<path:filename>/preview")
def preview_file(filename):
    _, err = _require_admin()
    if err:
        return err

    section = request.args.get("section", "Reports")
    sec_dir = _section_dir(section)
    path = os.path.join(sec_dir, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    ext = _ext(filename)

    if ext in PREVIEWABLE_IMAGE_EXTS:
        return jsonify({
            "type": "image",
            "url": f"/api/admin/files/{filename}/download?section={section}",
        })

    if ext in PREVIEWABLE_TEXT_EXTS:
        max_bytes = 60_000
        with open(path, "r", errors="replace") as fh:
            content = fh.read(max_bytes)
        truncated = os.path.getsize(path) > max_bytes
        return jsonify({"type": "text", "content": content, "truncated": truncated})

    return jsonify({"type": "none"})


# ── GET /api/admin/files/<filename>/download ─────────────────────────────
@admin_bp.route("/files/<path:filename>/download")
def download_file(filename):
    _, err = _require_admin()
    if err:
        return err

    section = request.args.get("section", "Reports")
    sec_dir = _section_dir(section)
    if not os.path.exists(os.path.join(sec_dir, filename)):
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(sec_dir, filename, as_attachment=True)
