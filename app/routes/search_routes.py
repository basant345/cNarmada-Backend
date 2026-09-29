"""
Site-wide keyword search for the cNARMADA header.

  GET /api/search?q=<terms>&limit=<n>

The index is assembled from what the site actually publishes: the pages and
dataset sections, the report library, the monitoring stations, and the API
catalogue. It is built once per process and rebuilt whenever one of those
files changes on disk, so results never drift away from the data.

Matching is a small prefix-aware scorer in the standard library. No search
engine, no extra dependency, nothing to keep running between requests, which
is what makes it safe on a free Render dyno. The whole index is a few hundred
short documents.
"""

import json
import os
import re
from collections import Counter

from flask import Blueprint, current_app, jsonify, request

search_bp = Blueprint("search", __name__, url_prefix="/api")

MAX_QUERY_CHARS = 120
DEFAULT_LIMIT = 8
MAX_LIMIT = 30

# Site structure lives here, on the server, so the frontend does not hold a
# second copy of the navigation that could drift out of step with it.
PAGES = [
    ("Home", "/", "page", "Overview of the cNARMADA centre and the Narmada basin"),
    ("About cNARMADA", "/about", "page", "The centre, its objectives, vision and mission"),
    ("Data", "/data", "page", "All published datasets for the Narmada basin"),
    ("Time Series Data", "/data/time-series", "dataset",
     "Streamflow, water level and surface water quality by monitoring station"),
    ("Geo Spatial Data", "/data/geo-spatial", "dataset",
     "Basin map layers: boundary, centre line, network, dams, waterbodies, STP, "
     "land use, elevation, precipitation, temperature, geomorphology"),
    ("Ground Water Quality", "/data/ground-water-quality", "dataset",
     "Ground water quality by parameter and location for the upper and middle basin"),
    ("Agriculture", "/data/agriculture", "dataset",
     "Crop and irrigated area, orchards and horticulture"),
    ("Solid Waste & Industrial Profile", "/data/solid-waste", "dataset",
     "Solid, hazardous, biomedical, plastic, electronic and construction waste; "
     "industrial categorisation, industrial parks and monitoring stations"),
    ("Basin Demography", "/data/basin-demography", "dataset",
     "District-wise population, sex ratio, literacy, workforce, SC and ST shares"),
    ("Biodiversity", "/data/biodiversity", "dataset",
     "Species tree by basin zone, group, class and species: plankton, macrobenthos, "
     "macrophytes, fish, birds, reptiles, amphibians"),
    ("River Atlas", "/river-atlas", "dataset",
     "Narmada basin, centre line, named and unnamed stream networks with full metadata"),
    ("Water Body Atlas", "/water-body-atlas", "dataset",
     "Named and unnamed water bodies of the Narmada basin, filterable by district"),
    ("API Catalog", "/data/api-catalog", "page", "Every public read endpoint on the portal"),
    ("User Manual", "/data/user-manual", "page", "How to use the portal and its datasets"),
    ("Reports", "/reports", "page", "Published basin reports and studies"),
    ("Events & News", "/events", "page", "Workshops, meetings, field visits and publications"),
    ("Important Links", "/links", "page", "Related organisations and resources"),
    ("Contact Us", "/contact", "page", "Reach the cNARMADA team at IIT Indore"),
    ("Careers", "/careers", "page", "Opportunities with the cNARMADA project"),
    ("Report Sewer Outfall", "/report-sewer-outfall", "page",
     "Report a sewer outfall into the river with location and photographs"),
]

_CACHE = {"stamp": None, "docs": None}


def _data(*parts):
    return os.path.join(current_app.config["DATA_DIR"], *parts)


def _read(*parts):
    path = _data(*parts)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _stamp():
    """Cheap fingerprint of the files the index is built from."""
    out = []
    for parts in (("reports_index.json",), ("stations.json",),
                  ("river_atlas", "catalog.json")):
        path = _data(*parts)
        out.append(os.path.getmtime(path) if os.path.exists(path) else 0)
    return tuple(out)


def tokenize(text):
    return [w for w in re.findall(r"[a-z0-9]+|[ऀ-ॿ]+", str(text).lower()) if w]


def build_docs():
    docs = []

    for title, to, kind, blurb in PAGES:
        docs.append({"title": title, "to": to, "kind": kind, "detail": blurb})

    for report in (_read("reports_index.json") or []):
        title = report.get("title") or report.get("filename")
        if not title:
            continue
        size = report.get("size_mb")
        docs.append({
            "title": title,
            "to": "/reports",
            "kind": "report",
            "detail": f"Report · {size} MB" if size else "Report",
        })

    for station in (_read("stations.json") or []):
        name = station.get("name")
        if not name:
            continue
        has = []
        if station.get("has_streamflow"):
            has.append("streamflow")
        if station.get("has_waterlevel"):
            has.append("water level")
        docs.append({
            "title": name,
            "to": "/data/time-series",
            "kind": "station",
            "detail": "Monitoring station" + (" · " + ", ".join(has) if has else ""),
        })

    atlas = _read("river_atlas", "catalog.json") or {}
    for layer in atlas.get("layers", []):
        docs.append({
            "title": layer.get("name", layer.get("id", "")),
            "to": "/river-atlas",
            "kind": "layer",
            "detail": f"River Atlas layer · {layer.get('feature_count', 0):,} features",
        })

    water = _read("water_atlas", "catalog.json") or {}
    for layer in water.get("layers", []):
        docs.append({
            "title": layer.get("name", layer.get("id", "")),
            "to": "/water-body-atlas",
            "kind": "layer",
            "detail": f"Water Body Atlas layer · {layer.get('feature_count', 0):,} features",
        })

    try:
        from app.routes.data_routes import API_CATALOG
        for item in API_CATALOG:
            docs.append({
                "title": item.get("path", ""),
                "to": "/data/api-catalog",
                "kind": "api",
                "detail": item.get("description", ""),
            })
    except Exception:  # pragma: no cover - the catalogue is optional here
        pass

    for doc in docs:
        doc["tokens"] = Counter(tokenize(doc["title"]) * 3 + tokenize(doc["detail"]))
    return docs


def get_docs():
    stamp = _stamp()
    if _CACHE["stamp"] != stamp:
        _CACHE.update({"stamp": stamp, "docs": build_docs()})
    return _CACHE["docs"]


# Results from these kinds are preferred when scores are close, so a page a
# visitor can actually open outranks a raw API path.
KIND_BOOST = {"page": 1.25, "dataset": 1.3, "layer": 1.1, "report": 1.0,
              "station": 0.95, "api": 0.8}


def rank(query, docs, limit):
    terms = tokenize(query)
    if not terms:
        return []

    results = []
    for doc in docs:
        hits = 0.0
        for term in terms:
            exact = doc["tokens"].get(term, 0)
            if exact:
                hits += exact
                continue
            # Prefix match, so "biodiv" still finds Biodiversity, at a
            # discount so a full word always wins.
            partial = sum(c for t, c in doc["tokens"].items() if t.startswith(term))
            if partial:
                hits += partial * 0.45
        if hits <= 0:
            continue
        covered = sum(
            1 for term in terms
            if doc["tokens"].get(term) or any(t.startswith(term) for t in doc["tokens"])
        )
        # Require every term to land once more than one is given, so extra
        # words narrow the result set instead of widening it.
        if len(terms) > 1 and covered < len(terms):
            continue
        score = hits * KIND_BOOST.get(doc["kind"], 1.0)
        if doc["title"].lower().startswith(query.strip().lower()):
            score *= 1.6
        results.append((score, doc))

    results.sort(key=lambda r: (-r[0], r[1]["title"]))
    return [{
        "title": d["title"], "url": d["to"], "kind": d["kind"], "detail": d["detail"],
    } for _, d in results[:limit]]


@search_bp.route("/search")
def search():
    query = (request.args.get("q") or "")[:MAX_QUERY_CHARS].strip()
    try:
        limit = min(max(int(request.args.get("limit", DEFAULT_LIMIT)), 1), MAX_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    if len(query) < 2:
        return jsonify({"query": query, "count": 0, "results": []})

    docs = get_docs()
    results = rank(query, docs, limit)
    return jsonify({"query": query, "count": len(results),
                    "indexed": len(docs), "results": results})
