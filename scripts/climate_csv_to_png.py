"""
Year-wise Precipitation / Mean Temperature CSV-grid -> colored PNG overlay
converter, for the Spatial Map's "Precipitation (Year-wise)" and "Mean
Temperature (Year-wise)" layers.

Unlike climate_raster_to_png.py (which expects a GeoTIFF), this reads the
gridded CSV export format actually produced for this project: one row per
grid cell, columns X (lon), Y (lat), and a value column. Precipitation
files have a value column called "Annual_Sum"; Temperature files have Max/
and Min/ subfolders each with a "Mean" column — this script averages the
two into a single "mean temperature" value per grid cell per year.

Both variables here are on a *regular* lat/lon grid but only include the
cells that fall inside the basin (so the grid is sparse/basin-shaped, not a
full rectangle) — this script figures out each variable's cell size
automatically from the data and paints exactly the cells present, leaving
everything else transparent.

Writes into the SAME precipitation_index.json / mean_temperature_index.json
shape as climate_raster_to_png.py, so the backend API (data_routes.py) and
the Spatial Map frontend (GeoSpatialData.jsx) work with this data with zero
code changes — they were already built to read that shape.

USAGE:
    python3 climate_csv_to_png.py precipitation /path/to/Precipitation 2015 2023
    python3 climate_csv_to_png.py mean_temperature /path/to/Temperature 2015 2023

For precipitation, <folder> must contain YYYY.csv files directly (X,Y,Annual_Sum).
For mean_temperature, <folder> must contain Max/YYYY.csv and Min/YYYY.csv (X,Y,Mean).
"""
import csv
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from climate_raster_to_png import RAMPS  # noqa: E402 — reuse the exact same color ramps

Image.MAX_IMAGE_PIXELS = None


def _read_grid_csv(path, value_col):
    points = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            points.append((float(row["X"]), float(row["Y"]), float(row[value_col])))
    return points


def _cell_size(coords):
    """Smallest positive gap between consecutive sorted unique coordinates —
    i.e. the grid's cell size along that axis."""
    uniq = sorted(set(round(c, 6) for c in coords))
    if len(uniq) < 2:
        return 0.25  # fallback for a degenerate single-row/column grid
    gaps = [b - a for a, b in zip(uniq, uniq[1:])]
    return min(gaps)


def _grid_to_png(points, ramp, out_png_path, max_dim=900):
    """points: list of (lon, lat, value). Renders each grid cell as a solid
    block of pixels sized to roughly max_dim on the longer axis, colored by
    `ramp`'s stops between the data's own 1st/99th percentile."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    values = np.array([p[2] for p in points], dtype=np.float32)

    cell_w = _cell_size(xs)
    cell_h = _cell_size(ys)

    west, east = min(xs) - cell_w / 2, max(xs) + cell_w / 2
    south, north = min(ys) - cell_h / 2, max(ys) + cell_h / 2
    bounds = {"west": west, "south": south, "east": east, "north": north}

    n_cols = round((east - west) / cell_w)
    n_rows = round((north - south) / cell_h)
    px_per_cell = max(1, min(40, max_dim // max(n_cols, n_rows, 1)))
    img_w, img_h = n_cols * px_per_cell, n_rows * px_per_cell
    grid = np.full((n_rows, n_cols), np.nan, dtype=np.float32)
    for lon, lat, val in points:
        col = int(round((lon - west - cell_w / 2) / cell_w))
        row = n_rows - 1 - int(round((lat - south - cell_h / 2) / cell_h))
        if 0 <= row < n_rows and 0 <= col < n_cols:
            grid[row, col] = val

    vmin, vmax = float(np.nanpercentile(values, 1)), float(np.nanpercentile(values, 99))
    norm = np.clip((grid - vmin) / (vmax - vmin + 1e-9), 0, 1)

    stops = ramp["stops"]
    rgba = np.zeros((n_rows, n_cols, 4), dtype=np.uint8)
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        mask = (norm >= p0) & (norm <= p1) & ~np.isnan(grid)
        t = np.clip((norm[mask] - p0) / (p1 - p0 + 1e-9), 0, 1)
        for ch in range(3):
            rgba[..., ch][mask] = (c0[ch] + t * (c1[ch] - c0[ch])).astype(np.uint8)
    rgba[..., 3][~np.isnan(grid)] = 235

    out_img = Image.fromarray(rgba).resize((img_w, img_h), Image.NEAREST)
    out_img.save(out_png_path, optimize=True)
    return bounds, vmin, vmax


def _update_index(rasters_dir, variable, year, filename, bounds, vmin, vmax):
    ramp = RAMPS[variable]
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
    return index


def process_precipitation_year(source_dir, year, rasters_dir):
    csv_path = os.path.join(source_dir, f"{year}.csv")
    points = _read_grid_csv(csv_path, "Annual_Sum")
    filename = f"precipitation_{year}.png"
    bounds, vmin, vmax = _grid_to_png(points, RAMPS["precipitation"], os.path.join(rasters_dir, filename))
    idx = _update_index(rasters_dir, "precipitation", year, filename, bounds, vmin, vmax)
    print(f"precipitation {year}: {len(points)} cells, {vmin:.1f}-{vmax:.1f} mm -> {filename}")
    return idx


def process_mean_temperature_year(source_dir, year, rasters_dir):
    max_points = _read_grid_csv(os.path.join(source_dir, "Max", f"{year}.csv"), "Mean")
    min_points = _read_grid_csv(os.path.join(source_dir, "Min", f"{year}.csv"), "Mean")
    min_by_xy = {(round(x, 4), round(y, 4)): v for x, y, v in min_points}

    mean_points = []
    for x, y, vmax_ in max_points:
        vmin_ = min_by_xy.get((round(x, 4), round(y, 4)))
        if vmin_ is not None:
            mean_points.append((x, y, (vmax_ + vmin_) / 2))

    filename = f"mean_temperature_{year}.png"
    bounds, vmin, vmax = _grid_to_png(mean_points, RAMPS["mean_temperature"], os.path.join(rasters_dir, filename))
    idx = _update_index(rasters_dir, "mean_temperature", year, filename, bounds, vmin, vmax)
    print(f"mean_temperature {year}: {len(mean_points)} cells, {vmin:.1f}-{vmax:.1f} \u00b0C -> {filename}")
    return idx


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        print("\nUsage: python3 climate_csv_to_png.py <precipitation|mean_temperature> <source_dir> <start_year> [end_year] [rasters_dir]")
        sys.exit(1)

    variable_arg = sys.argv[1]
    source_dir_arg = sys.argv[2]
    start_year = int(sys.argv[3])
    end_year = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else start_year
    rasters_dir_arg = sys.argv[5] if len(sys.argv) > 5 else os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "data", "rasters"
    )
    os.makedirs(rasters_dir_arg, exist_ok=True)

    for yr in range(start_year, end_year + 1):
        if variable_arg == "precipitation":
            process_precipitation_year(source_dir_arg, yr, rasters_dir_arg)
        elif variable_arg == "mean_temperature":
            process_mean_temperature_year(source_dir_arg, yr, rasters_dir_arg)
        else:
            print(f"Unknown variable '{variable_arg}'. Use 'precipitation' or 'mean_temperature'.")
            sys.exit(1)
