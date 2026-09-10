#!/usr/bin/env python3
"""
Build app/static/data/industrial_profile.json from the MPIDC / MSME / MPPCB CSVs.

    python scripts/build_industrial_profile.py "path/to/csv folder"

Three datasets come out of eight CSVs:

  1. Industry categorisation (Red / Orange / Green)
     "Red_Green_and_Orange_industries.csv" - one row per district with the
     count of industries in each MPPCB pollution category. Mandla is recorded
     as "NA" in all three columns and is reported separately rather than being
     charted as zero, which would misstate it.

  2. Industrial parks
     Four distinct files: MPIDC and MSME, each split Upper / Middle basin.
     Note that "MPIDC_Middle_-_Copy.csv" and "MPIDC_Middle_Industrial_parks.csv"
     are byte-identical, as are the two MPIDC Upper files, so each pair is read
     once. Rows carry only district and coordinates - there are no park names in
     the source. District spelling varies in case ("JABALPUR" and "Jabalpur"),
     so a title-cased display name is used for grouping while the original
     spelling is kept.

  3. Real-time monitoring stations
     "Real-Time_Monitoring_Stations_in_different_Industries.csv" - 49 named
     industries with a sector and coordinates.

Exact duplicate rows within a park file are dropped and counted; nothing else
is altered.
"""

import csv
import json
import re
import sys
from pathlib import Path

OUT = Path("app/static/data/industrial_profile.json")

# Only one file of each byte-identical pair is read.
PARK_FILES = [
    ("MPIDC", "upper", "MPIDC_Upper_-_Copy.csv"),
    ("MPIDC", "middle", "MPIDC_Middle_-_Copy.csv"),
    ("MSME", "upper", "MSME_Industrial_Park_Upper_-_Copy.csv"),
    ("MSME", "middle", "MSME_Industrial_Park_Middle_-_Copy.csv"),
]
CATEGORY_FILE = "Red_Green_and_Orange_industries.csv"
MONITORING_FILE = "Real-Time_Monitoring_Stations_in_different_Industries_-_Copy.csv"


def find(folder, wanted):
    """Match a file regardless of any numeric upload prefix."""
    target = wanted.lower()
    for path in sorted(Path(folder).glob("*.csv")):
        name = path.name.lower()
        if name == target or name.endswith("_" + target) or name.endswith(target):
            return path
    # fall back to a loose match on the distinctive part of the name
    stem = re.sub(r"[^a-z0-9]", "", target)
    for path in sorted(Path(folder).glob("*.csv")):
        if re.sub(r"[^a-z0-9]", "", path.name.lower()).endswith(stem):
            return path
    return None


def read_rows(path):
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_int(value):
    text = clean(value)
    if text is None:
        return None
    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return None          # "NA" and anything else non-numeric


def display_district(name):
    """'KHARGAONE (W.N..)' -> 'Khargaone (W.N..)'; merges case variants."""
    text = clean(name) or ""
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), text)


# ── 1. Red / Orange / Green ──────────────────────────────────────────────────

def build_categorisation(folder):
    path = find(folder, CATEGORY_FILE)
    if path is None:
        return None
    districts, unavailable = [], []
    for row in read_rows(path):
        name = clean(row.get("Districts"))
        if not name:
            continue
        red = to_int(row.get("Red"))
        orange = to_int(row.get("Orange"))
        green = to_int(row.get("Green"))
        if red is None and orange is None and green is None:
            # Recorded as "NA" in the source; not the same as zero.
            unavailable.append({"district": name, "raw": clean(row.get("Red"))})
            continue
        districts.append({
            "district": name,
            "red": red or 0,
            "orange": orange or 0,
            "green": green or 0,
            "total": (red or 0) + (orange or 0) + (green or 0),
        })
    districts.sort(key=lambda d: -d["total"])
    return {
        "source": path.name,
        "categories": ["Red", "Orange", "Green"],
        "districts": districts,
        "unavailable": unavailable,
        "totals": {
            "red": sum(d["red"] for d in districts),
            "orange": sum(d["orange"] for d in districts),
            "green": sum(d["green"] for d in districts),
        },
    }


# ── 2. Industrial parks ──────────────────────────────────────────────────────

def build_parks(folder):
    items, sources = [], []
    duplicates = 0
    for agency, zone, filename in PARK_FILES:
        path = find(folder, filename)
        if path is None:
            print(f"  ! not found, skipped: {filename}", file=sys.stderr)
            continue
        sources.append(path.name)
        seen = set()
        for row in read_rows(path):
            raw = clean(row.get("DISTRICT_NAME"))
            lat = to_float(row.get("Latitude"))
            lon = to_float(row.get("Longitude"))
            if not raw or lat is None or lon is None:
                continue
            key = (raw.lower(), round(lat, 7), round(lon, 7))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            items.append({
                "agency": agency,
                "zone": zone,
                "district": display_district(raw),
                "districtRaw": raw,
                "latitude": lat,
                "longitude": lon,
            })

    # counts per district, split by agency and zone, for the chart
    counts = {}
    for item in items:
        key = (item["district"], item["zone"])
        entry = counts.setdefault(key, {
            "district": item["district"], "zone": item["zone"], "MPIDC": 0, "MSME": 0,
        })
        entry[item["agency"]] += 1
    by_district = sorted(
        counts.values(), key=lambda e: -(e["MPIDC"] + e["MSME"])
    )

    return {
        "sources": sources,
        "agencies": ["MPIDC", "MSME"],
        "zones": ["upper", "middle"],
        "items": items,
        "byDistrict": by_district,
        "duplicateRowsDropped": duplicates,
    }


# ── 3. Real-time monitoring stations ─────────────────────────────────────────

def build_monitoring(folder):
    path = find(folder, MONITORING_FILE)
    if path is None:
        return None
    stations = []
    for row in read_rows(path):
        name = clean(row.get("Industry Name"))
        if not name:
            continue
        stations.append({
            "name": name,
            "sector": clean(row.get("Sector")) or "Not stated",
            "latitude": to_float(row.get("Lat")),
            "longitude": to_float(row.get("Long")),
        })

    tally = {}
    for s in stations:
        tally[s["sector"]] = tally.get(s["sector"], 0) + 1
    sectors = sorted(
        ({"sector": k, "count": v} for k, v in tally.items()),
        key=lambda x: (-x["count"], x["sector"]),
    )

    return {
        "source": path.name,
        "stations": sorted(stations, key=lambda s: (s["sector"], s["name"])),
        "sectors": sectors,
        "withoutCoordinates": sum(
            1 for s in stations if s["latitude"] is None or s["longitude"] is None
        ),
    }


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: build_industrial_profile.py "path/to/csv folder"')
    folder = sys.argv[1]

    payload = {
        "categorisation": build_categorisation(folder),
        "parks": build_parks(folder),
        "monitoring": build_monitoring(folder),
    }

    # Refuse to write a half-built file. Previously the JSON was saved before
    # the summary ran, so pointing this script at a folder missing some CSVs
    # produced a file with null sections that then crashed the page.
    missing = []
    if payload["categorisation"] is None:
        missing.append(CATEGORY_FILE)
    if payload["monitoring"] is None:
        missing.append(MONITORING_FILE)
    if not payload["parks"]["items"]:
        missing.append("the MPIDC / MSME park CSVs")
    elif len(payload["parks"]["sources"]) < len(PARK_FILES):
        found = set(payload["parks"]["sources"])
        missing += [
            f for _, _, f in PARK_FILES
            if not any(s.endswith(f) or s == f for s in found)
        ]
    if missing:
        sys.exit(
            "Nothing written. These source files were not found in "
            f'"{folder}":\n  - ' + "\n  - ".join(missing) +
            "\n\nPoint the script at the folder that holds all eight CSVs."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))

    cat = payload["categorisation"]
    print(f"categorisation: {len(cat['districts'])} districts charted, "
          f"{len(cat['unavailable'])} recorded as NA {[u['district'] for u in cat['unavailable']]}")
    print(f"   totals: Red {cat['totals']['red']}, Orange {cat['totals']['orange']}, "
          f"Green {cat['totals']['green']}")

    parks = payload["parks"]
    print(f"\nparks: {len(parks['items'])} locations from {len(parks['sources'])} files, "
          f"{parks['duplicateRowsDropped']} duplicate rows dropped")
    for zone in parks["zones"]:
        for agency in parks["agencies"]:
            n = sum(1 for i in parks["items"] if i["zone"] == zone and i["agency"] == agency)
            print(f"   {zone:<7} {agency:<6} {n:>3}")

    mon = payload["monitoring"]
    print(f"\nmonitoring: {len(mon['stations'])} industries, {len(mon['sectors'])} sectors, "
          f"{mon['withoutCoordinates']} without coordinates")
    print("   " + ", ".join(f"{s['sector']} {s['count']}" for s in mon["sectors"]))

    print(f"\nwrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
