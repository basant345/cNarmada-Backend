"""
Dependency-free (Pillow + numpy only) GeoTIFF -> colored PNG overlay converter.

Reads the GeoTIFF tiepoint + pixel scale tags directly (no GDAL/rasterio needed)
to compute the lat/lon bounding box, downsamples the raster to a manageable
size, applies a colormap, and writes a PNG + a small JSON sidecar with the
bounds (for use with Leaflet's L.imageOverlay).
"""
import json
import os
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _geo_bounds(img):
    tags = img.tag_v2
    w, h = tags.get(256), tags.get(257)
    sx, sy, _ = tags.get(33550)
    _, _, _, ox, oy, _ = tags.get(33922)
    # top-left corner is (ox, oy); pixels increase x eastward, y is decreasing northward
    west, north = ox, oy
    east = ox + w * sx
    south = oy - h * sy
    return {"west": west, "south": south, "east": east, "north": north}, (w, h)


NODATA_CANDIDATES = (-32768, -9999, 65535, -3.4028235e+38)

# Standard MODIS IGBP land-cover palette (class id -> RGB), used for the LULC rasters
LULC_COLORS = {
    1:  (0, 100, 0),     # Evergreen Needleleaf
    2:  (0, 130, 0),     # Evergreen Broadleaf
    3:  (60, 160, 60),   # Deciduous Needleleaf
    4:  (90, 180, 90),   # Deciduous Broadleaf
    5:  (60, 150, 30),   # Mixed Forest
    6:  (150, 180, 60),  # Closed Shrublands
    7:  (190, 200, 100), # Open Shrublands
    8:  (170, 190, 110), # Woody Savannas
    9:  (210, 210, 120), # Savannas
    10: (160, 220, 80),  # Grasslands
    11: (110, 180, 220), # Permanent Wetlands
    12: (240, 200, 80),  # Croplands
    13: (200, 30, 30),   # Urban & Built-up
    14: (230, 220, 100), # Cropland/Natural mosaic
    15: (240, 240, 250), # Snow & Ice
    16: (200, 180, 150), # Barren
    17: (60, 100, 180),  # Water
}


def _color_for_lulc(value):
    if value is None or np.isnan(value):
        return (0, 0, 0, 0)
    base = int(round(value))
    return (*LULC_COLORS.get(base, (120, 120, 120)), 235)


def lulc_to_png(tif_path, out_png_path, max_dim=900):
    img = Image.open(tif_path)
    bounds, (w, h) = _geo_bounds(img)

    scale = max(1, max(w, h) // max_dim)
    img.draft(None, (w // scale, h // scale))
    target_size = (max(1, w // scale), max(1, h // scale))
    small = img.resize(target_size, Image.NEAREST)
    arr = np.array(small).astype(np.float32)

    rgba = np.zeros((*arr.shape, 4), dtype=np.uint8)
    flat = arr.reshape(-1, 1)
    unique_vals = np.unique(arr[~np.isnan(arr)])
    for v in unique_vals:
        color = _color_for_lulc(v)
        mask = arr == v
        rgba[mask] = color
    rgba[np.isnan(arr)] = (0, 0, 0, 0)

    out_img = Image.fromarray(rgba, mode="RGBA")
    out_img.save(out_png_path, optimize=True)
    return bounds


def dem_to_png(tif_path, out_png_path, max_dim=1000):
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
        raise ValueError("No valid elevation data found")
    vmin, vmax = np.percentile(valid, [1, 99])

    norm = np.clip((arr - vmin) / (vmax - vmin + 1e-9), 0, 1)

    # Simple terrain-style colormap: low=green, mid=yellow/brown, high=white
    stops = [
        (0.00, (40, 110, 60)),
        (0.25, (110, 160, 70)),
        (0.50, (190, 170, 90)),
        (0.75, (150, 110, 70)),
        (1.00, (250, 250, 250)),
    ]
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

    out_img = Image.fromarray(rgba, mode="RGBA")
    out_img.save(out_png_path, optimize=True)
    return bounds, float(vmin), float(vmax)


if __name__ == "__main__":
    import sys
    kind = sys.argv[1]
    tif_path = sys.argv[2]
    out_png = sys.argv[3]
    if kind == "lulc":
        b = lulc_to_png(tif_path, out_png)
        print(json.dumps(b))
    elif kind == "dem":
        b, vmin, vmax = dem_to_png(tif_path, out_png)
        print(json.dumps({**b, "min_elev": vmin, "max_elev": vmax}))
