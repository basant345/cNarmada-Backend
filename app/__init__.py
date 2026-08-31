import os
from flask import Flask, request


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    # ── Load .env file for local development ──────────────────────────────
    # In production (Render), set env vars in the dashboard instead.
    try:
        from dotenv import load_dotenv
        _env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        load_dotenv(_env_path)
    except ImportError:
        pass  # python-dotenv not installed — env vars must be set externally

    # ── CORS ──────────────────────────────────────────────────────────────
    # An explicit allowlist. "origins: *" together with supports_credentials
    # is invalid per the CORS spec, and flask-cors works around it by echoing
    # back whatever Origin it is sent — which means any site could call the
    # API with a token it had obtained.
    _origins = [
        o.strip() for o in os.environ.get(
            "CORS_ORIGINS",
            "https://cnarmada.iiti.ac.in,https://water.iiti.ac.in,http://localhost:5173",
        ).split(",") if o.strip()
    ]

    try:
        from flask_cors import CORS
        CORS(
            app,
            resources={r"/api/*": {"origins": _origins},
                       r"/static/*": {"origins": _origins}},
            supports_credentials=True,
        )
    except ImportError:
        @app.after_request
        def _add_cors_headers(response):
            origin = request.headers.get("Origin", "")
            if origin in _origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            return response

    app.config["DATA_DIR"] = os.path.join(app.static_folder, "data")

    # Max upload size: 200 MB (covers admin-uploaded reports, spreadsheets,
    # and DEM/raster files; still comfortably covers sewer outfall photos)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

    # ── Blueprints ─────────────────────────────────────────────────────────
    from app.routes.data_routes import data_bp
    app.register_blueprint(data_bp)

    # Gated dataset downloads. Kept in their own blueprint so that every
    # endpoint in data_routes can stay public.
    from app.routes.export_routes import export_bp
    app.register_blueprint(export_bp)

    from app.routes.visits_routes import visits_bp
    app.register_blueprint(visits_bp)

    from app.routes.sewer_outfall_routes import sewer_bp
    app.register_blueprint(sewer_bp)

    # ── NEW: OTP Authentication ────────────────────────────────────────────
    from app.routes.auth_routes import auth_bp
    app.register_blueprint(auth_bp)

    # ── NEW: Admin Panel (reuses OTP auth above — no parallel auth system) ──
    from app.routes.admin_routes import admin_bp
    app.register_blueprint(admin_bp)

    # ── NEW: Admin Panel — structured dataset records (CRUD) ────────────────
    from app.routes.admin_records_routes import admin_records_bp
    app.register_blueprint(admin_records_bp)

    @app.route("/api/health")
    def health():
        return {"status": "ok", "service": "cnarmada-backend"}

    return app
