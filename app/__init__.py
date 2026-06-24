import os
from flask import Flask


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
    try:
        from flask_cors import CORS
        CORS(
            app,
            resources={r"/api/*": {"origins": "*"}, r"/static/*": {"origins": "*"}},
            supports_credentials=True,
        )
    except ImportError:
        @app.after_request
        def _add_cors_headers(response):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            return response

    app.config["DATA_DIR"] = os.path.join(app.static_folder, "data")

    # Max upload size: 10 MB (for sewer outfall photos)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

    # ── Blueprints ─────────────────────────────────────────────────────────
    from app.routes.data_routes import data_bp
    app.register_blueprint(data_bp)

    from app.routes.visits_routes import visits_bp
    app.register_blueprint(visits_bp)

    from app.routes.sewer_outfall_routes import sewer_bp
    app.register_blueprint(sewer_bp)

    # ── NEW: OTP Authentication ────────────────────────────────────────────
    from app.routes.auth_routes import auth_bp
    app.register_blueprint(auth_bp)

    @app.route("/api/health")
    def health():
        return {"status": "ok", "service": "cnarmada-backend"}

    return app
