# cNARMADA Backend (Flask)

A read-only Flask API serving the Narmada basin datasets (stations, streamflow,
water level, water quality, GIS layers, rasters, and PDF reports) to the
cNARMADA React frontend's **Data Download** section.

All the heavy raw data (shapefiles, GeoTIFFs, messy CSVs, Excel workbooks) has
already been processed once into clean JSON / GeoJSON / PNG files under
`app/static/data/`. The Flask app just serves those files — it does **not**
re-process anything at request time, so it stays fast and simple.

## Project layout

```
backend/
├── app/
│   ├── __init__.py            # Flask app factory (CORS, blueprint registration)
│   ├── routes/
│   │   └── data_routes.py     # All /api/* endpoints
│   └── static/data/           # Pre-processed data served by the API
│       ├── geojson/           # basin_boundary, centerline, named_network
│       ├── rasters/           # DEM + LULC PNG overlays, with bounds JSON
│       ├── reports/           # 24 PDF reports
│       ├── timeseries/        # per-station streamflow & water-level JSON
│       ├── stations.json
│       ├── reports_index.json
│       └── water_quality.json
├── scripts/                   # One-time ETL scripts (see below)
│   ├── process_data.py        # Master ETL — raw zip -> app/static/data
│   ├── shp2geojson.py         # Dependency-free .shp -> GeoJSON converter
│   └── raster2png.py          # Dependency-free GeoTIFF -> PNG overlay converter
├── requirements.txt
└── run.py                     # Local dev entry point
```

## 1. Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> **Windows + pandas build error?** If `pip install` tries to compile pandas
> from source (a Meson/`vswhere.exe` error), run `pip install --upgrade pip`
> first, then retry. `requirements.txt` uses version ranges (e.g.
> `pandas>=2.2.3`) specifically so pip can pick a release with a pre-built
> wheel for your Python version instead of compiling — an up-to-date pip is
> what makes that resolution work correctly.

## 2. Run

```bash
python3 run.py
```

The API will be available at **http://localhost:5000**. Check it's alive:

```bash
curl http://localhost:5000/api/health
# {"service": "cnarmada-backend", "status": "ok"}
```

## 3. Endpoints

See `GET /api/catalog` for the full machine-readable list, or the frontend's
**Data Download → API Catalog** page. Highlights:

| Endpoint | Description |
|---|---|
| `GET /api/overview` | Summary stats for the Data landing page |
| `GET /api/stations` | All monitoring stations (name, lat/lon, available datasets) |
| `GET /api/stations/<slug>` | One station's full streamflow/water-level time series |
| `GET /api/geojson/basin_boundary` | Narmada basin boundary polygon |
| `GET /api/geojson/centerline` | Narmada river centerline (Amarkantak -> Gulf of Khambhat) |
| `GET /api/geojson/named_network` | Named tributary network (1000+ features) |
| `GET /api/rasters/lulc` | Land Use/Land Cover PNG overlays by year (2018-2024) |
| `GET /api/rasters/dem` | Elevation PNG overlay + bounds + min/max elevation |
| `GET /api/water-quality/parameters` | List of parameters & sampling locations |
| `GET /api/water-quality/<parameter>` | Time series for one parameter, optional `?location=` filter |
| `GET /api/reports` | Catalogue of downloadable PDF reports |
| `GET /api/reports/<filename>` | Download a specific report PDF |

## 4. Re-running the data ETL (optional)

You only need this if you want to regenerate `app/static/data/` from the raw
`Cnarmada Data` folder (e.g. you received updated source data).

```bash
cd scripts
python3 process_data.py "/path/to/Cnarmada Data" ../app
```

This will:
1. Convert the 3 shapefiles (basin boundary, centerline, named network) to GeoJSON, with no GDAL/geopandas dependency — it's a small pure-Python `.shp`/`.dbf` parser.
2. Convert the DEM and all 7 years of LULC GeoTIFFs into colored PNG overlays with their geographic bounds (also dependency-free — reads GeoTIFF tags directly via Pillow).
3. Parse all streamflow and water-level CSVs (which have a 2-line title header before the real header row) into clean per-station JSON.
4. Match each CSV's filename (e.g. `AshwinAtHaripura.csv`) against `Station_Location.csv` (`Ashwin at Haripura`) to attach lat/lon, even though the two sources spell station names differently.
5. Parse the multi-sheet `Combined_All_Params.xlsx` water quality workbook into one JSON keyed by parameter.
6. Copy the 24 PDF reports and build an index with file sizes.

Requires `pandas` and `openpyxl` (already in `requirements.txt`) for step 5.

## 5. Notes on the data processing decisions

- **No GDAL/geopandas/rasterio.** These need system-level GIS libraries that
  aren't always easy to install. Everything here uses only `Pillow`, `numpy`,
  and the standard library, so `pip install -r requirements.txt` is enough.
- **DEM and LULC are downsampled** for web display (the source DEM is
  34284x8895 pixels — far more detail than a browser needs at basin scale).
  Bounds stay geographically accurate; only resolution is reduced.
- **The named tributary network is simplified** (point-thinning) from ~650k
  vertices down to a browser-friendly size while preserving line shape.
- **`NotInNamed_stream_features.shp`** (the very dense unnamed-stream
  catchment layer, ~89MB) is intentionally **not** served — it's too detailed
  for basin-level visualization and would bloat the frontend for little
  visual benefit. The raw file is still in your original data zip if you need
  it for GIS analysis.
- **One duplicate file removed**: `DEM-...` was accidentally nested inside the
  `Water Level` folder in the original zip (verified identical via md5) — the
  ETL only reads the canonical top-level copy.

## 6. Auth

This phase intentionally ships **without** the OTP/login flow wired up — all
`/api/*` endpoints are public and read-only, matching the "Data Download"
section being open data. The frontend's existing Viewer/Collaborator/Admin
login pages and CORS config are unaffected and can be connected to this same
Flask app later (e.g. add a `routes/auth_routes.py` blueprint) without
changing anything here.
