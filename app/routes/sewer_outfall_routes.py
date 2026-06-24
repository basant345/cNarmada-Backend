"""
Sewer Outfall Reporting API for cNARMADA.

Routes:
  POST /api/sewer-outfalls          — Submit a new sewer outfall report (multipart/form-data)
  GET  /api/sewer-outfalls          — List all reports (supports ?status=, ?district=, ?limit=)
  GET  /api/sewer-outfalls/<id>     — Get one report by ID
  PATCH /api/sewer-outfalls/<id>/status — Update report status (admin)

Images are saved to app/static/data/sewer_outfall_images/
Report data is stored in SQLite at app/routes/sewer_outfalls.db
"""
import os
import uuid
import sqlite3
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app

sewer_bp = Blueprint("sewer", __name__, url_prefix="/api")

# ── DB path: alongside other route DB files (visits.db pattern) ───────────
_DB_PATH = os.path.join(os.path.dirname(__file__), "sewer_outfalls.db")

# ── Allowed image extensions ───────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# ── Districts in the Narmada basin (mirrors frontend dropdown) ─────────────
NARMADA_DISTRICTS = [
    "Amarkantak", "Anuppur", "Dindori", "Mandla", "Jabalpur", "Narsimhapur",
    "Hoshangabad", "Harda", "Dewas", "Khandwa (East Nimar)", "Khargone (West Nimar)",
    "Barwani", "Dhar", "Alirajpur", "Vadodara", "Bharuch", "Narmadapuram",
    "Raisen", "Sehore", "Other"
]


def _get_conn():
    """Open connection and ensure the sewer_outfalls table exists."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sewer_outfalls (
            id            TEXT PRIMARY KEY,
            reporter_name TEXT,
            mobile        TEXT,
            email         TEXT,
            district      TEXT NOT NULL,
            river_type    TEXT NOT NULL,
            tributary_name TEXT,
            description   TEXT NOT NULL,
            latitude      REAL NOT NULL,
            longitude     REAL NOT NULL,
            image_path    TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            status        TEXT DEFAULT 'Pending'
        )
    """)
    conn.commit()
    return conn


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_image_dir():
    """Return the absolute path to the sewer outfall images directory, creating it if needed."""
    # Mirrors the existing static/data/ hierarchy
    image_dir = os.path.join(
        os.path.dirname(__file__),  # app/routes/
        "..",                        # app/
        "static",
        "data",
        "sewer_outfall_images"
    )
    image_dir = os.path.abspath(image_dir)
    os.makedirs(image_dir, exist_ok=True)
    return image_dir


def _row_to_dict(row):
    d = dict(row)
    # Build a public URL for the image if one was saved
    if d.get("image_path"):
        d["image_url"] = f"/static/data/sewer_outfall_images/{os.path.basename(d['image_path'])}"
    else:
        d["image_url"] = None
    return d


# ── POST /api/sewer-outfalls ───────────────────────────────────────────────
@sewer_bp.route("/sewer-outfalls", methods=["POST"])
def create_outfall():
    """
    Accept multipart/form-data.  Required fields: district, river_type, description,
    latitude, longitude.  Optional: reporter_name, mobile, email, tributary_name, image.
    """
    # ── Required fields ────────────────────────────────────────────────────
    required = ["district", "river_type", "description", "latitude", "longitude"]
    missing = [f for f in required if not request.form.get(f, "").strip()]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # ── Validate lat/lon ───────────────────────────────────────────────────
    try:
        lat = float(request.form["latitude"])
        lon = float(request.form["longitude"])
    except ValueError:
        return jsonify({"error": "latitude and longitude must be numeric"}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({"error": "latitude or longitude out of range"}), 400

    # ── Validate river_type ────────────────────────────────────────────────
    river_type = request.form["river_type"].strip()
    if river_type not in ("Main Narmada", "Tributary"):
        return jsonify({"error": "river_type must be 'Main Narmada' or 'Tributary'"}), 400

    tributary_name = request.form.get("tributary_name", "").strip() or None
    if river_type == "Tributary" and not tributary_name:
        return jsonify({"error": "tributary_name is required when river_type is 'Tributary'"}), 400

    # ── Handle image upload ────────────────────────────────────────────────
    image_path = None
    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename and _allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            image_dir = _get_image_dir()
            image_path = os.path.join(image_dir, filename)
            file.save(image_path)
        elif file and file.filename:
            return jsonify({"error": "Unsupported image type. Use PNG, JPG, JPEG, GIF, or WEBP."}), 400

    # ── Build record ───────────────────────────────────────────────────────
    report_id = uuid.uuid4().hex
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO sewer_outfalls
                (id, reporter_name, mobile, email, district, river_type, tributary_name,
                 description, latitude, longitude, image_path, created_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                report_id,
                request.form.get("reporter_name", "").strip() or None,
                request.form.get("mobile", "").strip() or None,
                request.form.get("email", "").strip() or None,
                request.form["district"].strip(),
                river_type,
                tributary_name,
                request.form["description"].strip(),
                lat,
                lon,
                image_path,
                now,
                "Pending",
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sewer_outfalls WHERE id = ?", (report_id,)).fetchone()
    finally:
        conn.close()

    return jsonify({"message": "Report submitted successfully", "report": _row_to_dict(row)}), 201


# ── GET /api/sewer-outfalls ────────────────────────────────────────────────
@sewer_bp.route("/sewer-outfalls", methods=["GET"])
def list_outfalls():
    """
    List all reports.  Optional query params:
      ?status=Pending|Verified|Rejected
      ?district=<name>
      ?limit=<n>   (default 100)
      ?offset=<n>  (default 0)
    """
    status   = request.args.get("status", "").strip()
    district = request.args.get("district", "").strip()
    try:
        limit  = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        limit, offset = 100, 0

    conn = _get_conn()
    try:
        query  = "SELECT * FROM sewer_outfalls WHERE 1=1"
        params = []
        if status:
            query  += " AND status = ?"
            params.append(status)
        if district:
            query  += " AND district = ?"
            params.append(district)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows  = conn.execute(query, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM sewer_outfalls" +
            (" WHERE status = ?" if status else ""),
            ([status] if status else [])
        ).fetchone()[0]
    finally:
        conn.close()

    return jsonify({
        "total":   total,
        "limit":   limit,
        "offset":  offset,
        "reports": [_row_to_dict(r) for r in rows],
    })


# ── GET /api/sewer-outfalls/<id> ──────────────────────────────────────────
@sewer_bp.route("/sewer-outfalls/<report_id>", methods=["GET"])
def get_outfall(report_id):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sewer_outfalls WHERE id = ?", (report_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": "Report not found"}), 404

    return jsonify(_row_to_dict(row))


# ── PATCH /api/sewer-outfalls/<id>/status ─────────────────────────────────
@sewer_bp.route("/sewer-outfalls/<report_id>/status", methods=["PATCH"])
def update_status(report_id):
    """
    Update a report's status.  Body JSON: { "status": "Verified" | "Rejected" | "Pending" }
    Intended for admin use; add auth middleware as needed.
    """
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "").strip()
    if new_status not in ("Pending", "Verified", "Rejected"):
        return jsonify({"error": "status must be Pending, Verified, or Rejected"}), 400

    conn = _get_conn()
    try:
        result = conn.execute(
            "UPDATE sewer_outfalls SET status = ? WHERE id = ?", (new_status, report_id)
        )
        conn.commit()
        if result.rowcount == 0:
            return jsonify({"error": "Report not found"}), 404
        row = conn.execute("SELECT * FROM sewer_outfalls WHERE id = ?", (report_id,)).fetchone()
    finally:
        conn.close()

    return jsonify({"message": "Status updated", "report": _row_to_dict(row)})
