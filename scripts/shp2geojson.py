"""
Minimal, dependency-free Shapefile (.shp + .dbf) -> GeoJSON converter.

Supports shape types: Point(1), PolyLine(3), Polygon(5),
and their Z/M variants are read but Z/M values are dropped (we only need X/Y
since all source data here is already WGS84 lat/lon).

Reference: ESRI Shapefile Technical Description.
"""
import struct
import json
import os
import sys


def _read_dbf(path):
    """Read a .dbf file and return a list of dicts (one per record)."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        data = f.read()

    n_records = struct.unpack("<I", data[4:8])[0]
    header_len = struct.unpack("<H", data[8:10])[0]
    record_len = struct.unpack("<H", data[10:12])[0]

    fields = []
    pos = 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\x00")[0].decode("latin-1")
        ftype = chr(data[pos + 11])
        flen = data[pos + 16]
        fields.append((name, ftype, flen))
        pos += 32

    records = []
    rec_start = header_len
    for i in range(n_records):
        offset = rec_start + i * record_len
        if offset >= len(data):
            break
        deleted = data[offset:offset + 1]
        if deleted == b"*":
            continue
        rec = {}
        fpos = offset + 1
        for name, ftype, flen in fields:
            raw = data[fpos:fpos + flen].decode("latin-1", errors="replace").strip()
            fpos += flen
            if ftype in ("N", "F"):
                try:
                    rec[name] = float(raw) if ("." in raw and raw not in ("", "-")) else (int(raw) if raw not in ("", "-") else None)
                except ValueError:
                    rec[name] = None
            else:
                rec[name] = raw
        records.append(rec)
    return records


def _read_shp(path):
    """Read a .shp file and yield (shape_type, geometry_dict) per record."""
    with open(path, "rb") as f:
        data = f.read()

    shape_type = struct.unpack("<i", data[32:36])[0]
    pos = 100
    geoms = []

    while pos < len(data):
        rec_number = struct.unpack(">i", data[pos:pos + 4])[0]
        content_len_words = struct.unpack(">i", data[pos + 4:pos + 8])[0]
        content_start = pos + 8
        content_len_bytes = content_len_words * 2
        rec_shape_type = struct.unpack("<i", data[content_start:content_start + 4])[0]

        if rec_shape_type == 0:
            geoms.append(None)
        elif rec_shape_type in (1, 11, 21):  # Point / PointZ / PointM
            x, y = struct.unpack("<dd", data[content_start + 4:content_start + 20])
            geoms.append({"type": "Point", "coordinates": [x, y]})
        elif rec_shape_type in (3, 13, 23, 5, 15, 25):  # PolyLine / Polygon (+ Z/M)
            is_polygon = rec_shape_type in (5, 15, 25)
            cur = content_start + 4
            cur += 32  # bounding box (4 doubles)
            num_parts = struct.unpack("<i", data[cur:cur + 4])[0]
            cur += 4
            num_points = struct.unpack("<i", data[cur:cur + 4])[0]
            cur += 4
            parts = list(struct.unpack(f"<{num_parts}i", data[cur:cur + 4 * num_parts]))
            cur += 4 * num_parts
            points = []
            for _ in range(num_points):
                x, y = struct.unpack("<dd", data[cur:cur + 16])
                points.append([x, y])
                cur += 16

            rings = []
            for pi in range(num_parts):
                start = parts[pi]
                end = parts[pi + 1] if pi + 1 < num_parts else num_points
                rings.append(points[start:end])

            if is_polygon:
                geoms.append({"type": "Polygon", "coordinates": rings})
            else:
                if len(rings) == 1:
                    geoms.append({"type": "LineString", "coordinates": rings[0]})
                else:
                    geoms.append({"type": "MultiLineString", "coordinates": rings})
        else:
            geoms.append(None)

        pos = content_start + content_len_bytes

    return shape_type, geoms


def shp_to_geojson(shp_path, simplify_tolerance=None, max_features=None, property_keys=None):
    """
    Convert a .shp (+ matching .dbf) to a GeoJSON FeatureCollection dict.

    simplify_tolerance: if set, applies basic point-skipping simplification
                         (keeps every Nth point) for large line/polygon geometries
                         to keep payload size reasonable for the browser.
    max_features: cap number of features returned (None = all).
    property_keys: list of dbf field names to keep (None = all).
    """
    dbf_path = os.path.splitext(shp_path)[0] + ".dbf"
    shape_type, geoms = _read_shp(shp_path)
    records = _read_dbf(dbf_path) or [{} for _ in geoms]

    features = []
    for i, geom in enumerate(geoms):
        if geom is None:
            continue
        if max_features is not None and len(features) >= max_features:
            break

        if simplify_tolerance:
            geom = _simplify_geom(geom, simplify_tolerance)

        props = records[i] if i < len(records) else {}
        if property_keys:
            props = {k: props.get(k) for k in property_keys if k in props}

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })

    return {"type": "FeatureCollection", "features": features}


def _simplify_geom(geom, every_nth):
    """Cheap simplification: keep every Nth coordinate (plus first/last)."""
    def thin(coords):
        if len(coords) <= 2:
            return coords
        thinned = coords[::every_nth]
        if thinned[-1] != coords[-1]:
            thinned.append(coords[-1])
        return thinned

    t = geom["type"]
    if t == "LineString":
        return {"type": t, "coordinates": thin(geom["coordinates"])}
    if t == "MultiLineString":
        return {"type": t, "coordinates": [thin(line) for line in geom["coordinates"]]}
    if t == "Polygon":
        return {"type": t, "coordinates": [thin(ring) for ring in geom["coordinates"]]}
    return geom


if __name__ == "__main__":
    shp_path = sys.argv[1]
    out_path = sys.argv[2]
    tol = int(sys.argv[3]) if len(sys.argv) > 3 else None
    gj = shp_to_geojson(shp_path, simplify_tolerance=tol)
    with open(out_path, "w") as f:
        json.dump(gj, f)
    print(f"Wrote {len(gj['features'])} features to {out_path}")
