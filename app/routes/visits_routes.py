"""
Visit counter API for cNARMADA.

Routes:
  POST /api/visits  — record one visit, return updated total
  GET  /api/visits  — return total without recording

Uses a lightweight SQLite DB (visits.db) stored alongside the app package,
so no extra dependencies are needed beyond what Flask already pulls in.
"""
import os
import sqlite3

from flask import Blueprint, jsonify

visits_bp = Blueprint("visits", __name__, url_prefix="/api")

# DB lives at  backend/app/visits.db  — next to the app package
_DB_PATH = os.path.join(os.path.dirname(__file__), "visits.db")


def _get_conn():
    """Open a connection and ensure the table exists."""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS visits "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        " ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return conn


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]


@visits_bp.route("/visits", methods=["GET"])
def get_visits():
    """Return the current visit total."""
    conn = _get_conn()
    count = _count(conn)
    conn.close()
    return jsonify({"count": count})


@visits_bp.route("/visits", methods=["POST"])
def record_visit():
    """Record a new visit and return the updated total."""
    conn = _get_conn()
    conn.execute("INSERT INTO visits DEFAULT VALUES")
    conn.commit()
    count = _count(conn)
    conn.close()
    return jsonify({"count": count}), 201
