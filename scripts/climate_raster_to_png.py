"""
Year-wise Precipitation / Mean Temperature GeoTIFF -> colored PNG overlay
converter, for the Spatial Map's "Precipitation (Year-wise)" and "Mean
Temperature (Year-wise)" layers.

Same dependency-free approach as raster2png.py (Pillow + numpy only, reads
the GeoTIFF tiepoint/pixel-scale tags directly — no GDAL/rasterio needed).
Reuses that file's `_geo_bounds` / `NODATA_CANDIDATES` helpers rather than
duplicating them.

USAGE (run once per year, per variable, whenever a new year's raster is
available):

    python3 climate_raster_to_png.py precipitation /path/to/precip_2015.tif 2015
    python3 climate_raster_to_png.py mean_temperature /path/to/temp_2015.tif 2015

By default this writes into ../app/static/data/rasters (same folder as the
existing dem.png / lulc_*.png) and merges the new year into
precipitation_index.json / mean_temperature_index.json — so you can process
years one at a time without wiping out ones you already did.

Each index file looks like:
{
  "_meta": {"unit": "mm", "stops": [[0.0,[r,g,b]], [0.25,[r,g,b]], ...]},
  "2015": {"file": "rasters/precipitation_2015.png", "bounds": {...}, "min": 412.3, "max": 1780.9},
  "2016": {...}
}

The API (GET /api/rasters/precipitation, /api/rasters/mean-temperature) and
the "sample a point" endpoint (GET /api/rasters/sample) both read this file
directly — the "_meta.stops" ramp is what lets the sample endpoint invert a
pixel color back into an approximate value, so it MUST stay in sync with
whatever ramp this script actually painted with (it always is, since both
live in the same _meta block written here).
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from raster2png import _geo_bounds, NODATA_CANDIDATES  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

# Colorbrewer-style ramps: low value -> high value.
RAMPS = {
    "precipitation": {
        "unit": "mm",
        "stops": [
            (0.00, (247, 251, 255)),
            (0.25, (198, 219, 239)),
            (0.50, (107, 174, 214)),
            (0.75, (33, 113, 181)),
            (1.00, (8, 48, 107)),
        ],
    },
    "mean_temperature": {
        "unit": "\u00b0C",
        "stops": [
            (0.00, (49, 54, 149)),
            (0.25, (145, 191, 219)),
            (0.50, (255, 255, 191)),
            (0.75, (252, 141, 89)),
            (1.00, (165, 0, 38)),
        ],
    },
}


def _continuous_to_png(tif_path, out_png_path, stops, max_dim=1000):
    """Same colorize-a-continuous-raster approach as raster2png.dem_to_png,
    generalized to any ramp of (position, RGB) stops."""
    img = Image.open(tif_path)
    bounds, (w, h) = _geo_bounds(img)

    scale = max(1, max(w, h) // max_dim)
    img.draft(None, (w // scale, h // scale))
    target_size = (max(1, w // scale), max(1, h // scale))
    small = img.resize(target_size, Image.NEAREST)
    arr = np.array(small).astype(np.float32)

    for nd in NODATA_CANDIDATES:
        arr[arr == nd] = np.nan

    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        raise ValueError(f"No valid data found in {tif_path}")
    vmin, vmax = np.percentile(valid, [1, 99])

    norm = np.clip((arr - vmin) / (vmax - vmin + 1e-9), 0, 1)

    rgba = np.zeros((*arr.shape, 4), dtype=np.uint8)
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        mask = (norm >= p0) & (norm <= p1)
        t = np.clip((norm[mask] - p0) / (p1 - p0 + 1e-9), 0, 1)
        for ch in range(3):
            rgba[..., ch][mask] = (c0[ch] + t * (c1[ch] - c0[ch])).astype(np.uint8)
    rgba[..., 3] = 235
    rgba[np.isnan(arr)] = (0, 0, 0, 0)

    Image.fromarray(rgba, mode="RGBA").save(out_png_path, optimize=True)
    return bounds, float(vmin), float(vmax)


def process_year(variable, tif_path, year, rasters_dir):
    if variable not in RAMPS:
        raise ValueError(f"Unknown variable '{variable}'. Use 'precipitation' or 'mean_temperature'.")

    ramp = RAMPS[variable]
    filename = f"{variable}_{year}.png"
    out_png_path = os.path.join(rasters_dir, filename)
    bounds, vmin, vmax = _continuous_to_png(tif_path, out_png_path, ramp["stops"])

    index_path = os.path.join(rasters_dir, f"{variable}_index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path) as f:
            index = json.load(f)

    index["_meta"] = {"unit": ramp["unit"], "stops": [[p, list(c)] for p, c in ramp["stops"]]}
    index[str(year)] = {
        "file": f"rasters/{filename}",
        "bounds": bounds,
        "min": round(vmin, 2),
        "max": round(vmax, 2),
    }

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

    print(f"Wrote {out_png_path}")
    print(f"Updated {index_path} — years now: {sorted(k for k in index if k != '_meta')}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        print("\nUsage: python3 climate_raster_to_png.py <precipitation|mean_temperature> <tif_path> <year> [rasters_dir]")
        sys.exit(1)

    variable_arg = sys.argv[1]
    tif_path_arg = sys.argv[2]
    year_arg = sys.argv[3]
    rasters_dir_arg = sys.argv[4] if len(sys.argv) > 4 else os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "data", "rasters"
    )
    process_year(variable_arg, tif_path_arg, year_arg, rasters_dir_arg)
