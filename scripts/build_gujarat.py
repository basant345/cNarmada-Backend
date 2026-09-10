#!/usr/bin/env python3
"""
Build the three Gujarat datasets into app/static/data/.

    python scripts/build_gujarat.py "path/to/Data from reports"

Reads, and writes one JSON each:

  1. Narmada river water quality  -> gujarat_water_quality.json
     Three station workbooks under "Narmada river water quality data/".
     Two different layouts: Garudeshwar and Panetha put a title in row 1 and
     the header in row 2; Zanor has the header in row 1, a "Sample Point"
     column, dd/mm/yyyy dates and extra pesticide columns. The header row is
     therefore located by finding "Collection Date" rather than assumed.

  2. DEP22 pollution report       -> gujarat_solid_waste.json
     A stacked key/value sheet: a category name on its own row, an optional
     header row, then "area -> value" pairs. Values are free text with mixed
     units ("97", "~7 TPD", "1597kg/day", "5TPD=1825MT/Yr", "Not quantified"),
     so each is kept verbatim alongside a parsed number and unit where one can
     be read. Nothing is converted between per-day and per-year units, because
     that would require assuming operating days per year.

  3. CWC suspended sediment       -> gujarat_sediment.json
     40,170 daily readings, 11 stations, 1973-2025. Aggregated to station x
     year (count, mean, min, max) because the raw file is 5.9 MB.

Values are only ever read from the source. Anything unparseable is preserved as
text and reported, never guessed at.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

OUT_DIR = Path("app/static/data")

# Readings that are qualifiers rather than numbers, e.g. below detection limit
# or still in the laboratory. Kept as counts so the page can report coverage.
QUALIFIER_RE = re.compile(r"^(bdl|in\s*process|nd|na|not\s*detected|<.*)$", re.I)

# "97" / "~7 TPD" / "1597kg/day" / "0.5MT/Yr" / "12,53,485" / "28MLD"
VALUE_RE = re.compile(
    r"^[~≈about\s]*([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(TPD|MT\s*/\s*Yr|MT\s*/\s*year|MT|kg\s*/\s*day|Kg\s*/\s*day|KG\s*per\s*day|kg|Kg|KG|MLD|MT/Annum)?",
    re.I,
)

UNIT_CANON = {
    "tpd": "TPD",
    "mt/yr": "MT/year", "mt/year": "MT/year", "mt": "MT",
    "kg/day": "kg/day", "kgperday": "kg/day", "kg": "kg",
    "mld": "MLD", "mt/annum": "MT/year",
}


def clean(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def to_float(text):
    if text is None:
        return None
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ── 1. Water quality ─────────────────────────────────────────────────────────

DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


def parse_date(value):
    """Return ISO yyyy-mm-dd, or None. Handles both layouts' date styles."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def build_water_quality(folder):
    stations = []
    series = {}
    qualifiers = {}
    all_params = []

    files = sorted(Path(folder).glob("*.xlsx"))
    for path in files:
        workbook = load_workbook(path, data_only=True)
        sheet = workbook[workbook.sheetnames[0]]
        rows = [[clean(c) for c in r] for r in sheet.iter_rows(values_only=True)]

        # Locate the header by content, not position: the two layouts differ.
        header_idx = next(
            (i for i, r in enumerate(rows[:5]) if r and "Collection Date" in r), None
        )
        if header_idx is None:
            print(f"  ! no 'Collection Date' header, skipped: {path.name}", file=sys.stderr)
            continue
        header = rows[header_idx]
        date_col = header.index("Collection Date")

        # Station name: the title row above the header, else the Sample Point
        # column, else the file name.
        name = None
        if header_idx > 0 and rows[header_idx - 1] and rows[header_idx - 1][0]:
            name = rows[header_idx - 1][0]
        if not name and "Sample Point" in header:
            point_col = header.index("Sample Point")
            for r in rows[header_idx + 1:]:
                if point_col < len(r) and r[point_col]:
                    name = r[point_col]
                    break
        if not name:
            name = path.stem
        # The Zanor sheet spells its sample point differently on nearly every
        # row, so the file name is the only stable label for it.
        if "zanor" in path.stem.lower():
            name = "River Narmada at Zanor"

        # Columns that are parameters: everything except the index, date and
        # descriptive columns.
        skip = {"Sr. No.", "Sample ID", "Collection Date", "Sample Point", "act"}
        param_cols = [
            (i, h) for i, h in enumerate(header)
            if h and h not in skip
        ]

        dates = []
        values = defaultdict(list)
        quals = defaultdict(int)
        seen = set()
        duplicates = 0

        for row in rows[header_idx + 1:]:
            if not row or date_col >= len(row):
                continue
            iso = parse_date(row[date_col])
            if not iso:
                continue
            if iso in seen:
                duplicates += 1
                continue
            seen.add(iso)
            dates.append(iso)
            for col, param in param_cols:
                raw = row[col] if col < len(row) else None
                number = to_float(raw)
                if number is None and raw is not None and QUALIFIER_RE.match(str(raw)):
                    quals[param] += 1
                values[param].append(number)

        order = sorted(range(len(dates)), key=lambda i: dates[i])
        dates = [dates[i] for i in order]

        kept = {}
        for _, param in param_cols:
            column = [values[param][i] for i in order]
            if any(v is not None for v in column):      # drop wholly empty ones
                kept[param] = column
                if param not in all_params:
                    all_params.append(param)

        series[name] = {"dates": dates, "values": kept}
        qualifiers[name] = dict(quals)
        stations.append({
            "name": name,
            "source": path.name,
            "records": len(dates),
            "from": dates[0] if dates else None,
            "to": dates[-1] if dates else None,
            "parameters": sorted(kept),
            "duplicateDatesDropped": duplicates,
        })

    return {
        "stations": stations,
        "parameters": sorted(all_params),
        "series": series,
        "qualifiers": qualifiers,
    }


# ── 2. DEP22 pollution report ────────────────────────────────────────────────

def parse_dep_value(raw):
    """Return (number, unit) read from the cell, or (None, None).

    The leading number is only accepted when nothing but a unit, a bracketed
    aside or an "=" restatement follows it. That rejects cells such as
    "5 tehsils 222 GP (150 KG per day)", where the leading 5 counts tehsils
    rather than measuring waste.
    """
    if raw is None:
        return None, None
    text = str(raw).strip()
    m = VALUE_RE.match(text)
    if not m:
        return None, None

    remainder = text[m.end():].strip()
    if remainder and not remainder[0] in "(=[,;":
        return None, None

    number = to_float(m.group(1))
    unit_raw = (m.group(2) or "").replace(" ", "").lower()
    return number, UNIT_CANON.get(unit_raw)


def build_solid_waste(path):
    workbook = load_workbook(path, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    rows = [[clean(c) for c in r] for r in sheet.iter_rows(values_only=True)]

    # Categories are separated by a blank row. A label with no value that does
    # NOT follow a blank row is a sub-heading inside the current category
    # ("Bharuch" sits mid-way through Solid Waste), so it must not start a new
    # one, otherwise Solid Waste gets split in two.
    categories = []
    current = None
    after_blank = True
    for row in rows:
        label = row[0] if row else None
        value = row[1] if row and len(row) > 1 else None

        if not label:
            after_blank = True
            continue

        if value is None:
            if after_blank or current is None:
                current = {"name": label, "valueLabel": None, "rows": []}
                categories.append(current)
            # else: a sub-heading; its rows belong to the category already open
            after_blank = False
            continue

        after_blank = False
        if current is None:
            continue
        if current["valueLabel"] is None and not current["rows"] and (
            label.lower().startswith(("area", "district", "block", "village"))
            and "waste" in str(value).lower()
        ):
            current["valueLabel"] = value           # this row is the header
            continue

        number, unit = parse_dep_value(value)
        current["rows"].append({
            "area": label,
            "raw": value,
            "value": number,
            "unit": unit,
            "approx": bool(re.match(r"^\s*[~≈]", str(value))),
        })

    categories = [c for c in categories if c["rows"]]
    return {"categories": categories}


# ── 3. CWC suspended sediment ────────────────────────────────────────────────

SED_DATE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
SED_COL = "Manual Daily Suspended Sediments (g/L)"


def build_sediment(path):
    meta = {}
    buckets = defaultdict(list)          # (station, year) -> [values]
    seen = set()
    duplicates = 0
    unparsed_dates = 0
    non_numeric = 0

    with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            station = (row.get("Station") or "").strip()
            stamp = (row.get("Data Acquisition Time") or "").strip()
            if not station or not stamp:
                continue

            key = (station, stamp)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)

            m = SED_DATE.match(stamp)
            if not m:
                unparsed_dates += 1
                continue
            year = int(m.group(3))

            value = to_float(row.get(SED_COL))
            if value is None:
                non_numeric += 1
                continue

            buckets[(station, year)].append(value)

            if station not in meta:
                meta[station] = {
                    "name": station,
                    "river": (row.get("River") or "").strip() or None,
                    "basin": (row.get("Basin") or "").strip() or None,
                    "tributary": (row.get("Tributary") or "").strip().strip("-") or None,
                    "district": (row.get("District") or "").strip() or None,
                    "tehsil": (row.get("Tehsil") or "").strip().strip("-") or None,
                    "agency": (row.get("Agency") or "").strip() or None,
                    "latitude": to_float(row.get("Latitude")),
                    "longitude": to_float(row.get("Longitude")),
                }

    series = defaultdict(list)
    for (station, year), values in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        series[station].append({
            "year": year,
            "n": len(values),
            "avg": round(sum(values) / len(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        })

    stations = []
    for name, info in meta.items():
        rows = series[name]
        info = dict(info)
        info["records"] = sum(r["n"] for r in rows)
        info["from"] = rows[0]["year"] if rows else None
        info["to"] = rows[-1]["year"] if rows else None
        stations.append(info)
    stations.sort(key=lambda s: s["name"].lower())

    years = sorted({r["year"] for rows in series.values() for r in rows})

    return {
        "parameter": SED_COL,
        "unit": "g/L",
        "years": years,
        "stations": stations,
        "series": dict(series),
        "quality": {
            "duplicateRowsDropped": duplicates,
            "unparsedDates": unparsed_dates,
            "nonNumericValues": non_numeric,
        },
    }


def write(name, payload):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUT_DIR / name
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {destination} ({destination.stat().st_size / 1024:.1f} KB)")


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: build_gujarat.py "path/to/Data from reports"')
    root = Path(sys.argv[1])

    wq = build_water_quality(root / "Narmada river water quality data")
    sw_pre = build_solid_waste(root / "data extracted from DEP22 for pollution reports.xlsx") \
        if (root / "data extracted from DEP22 for pollution reports.xlsx").exists() else {"categories": []}
    sed_pre = (root / "gujarat sediment data cwc till 2025.csv").exists()

    # Refuse to write anything unless all three sources were found, so a wrong
    # folder path cannot produce empty datasets that render as blank dropdowns.
    missing = []
    if not wq["stations"]:
        missing.append('"Narmada river water quality data/" (three .xlsx station files)')
    if not sw_pre["categories"]:
        missing.append('"data extracted from DEP22 for pollution reports.xlsx"')
    if not sed_pre:
        missing.append('"gujarat sediment data cwc till 2025.csv"')
    if missing:
        sys.exit(
            f'Nothing written. Not found in "{root}":\n  - ' + "\n  - ".join(missing) +
            "\n\nPoint the script at the folder that holds all of them."
        )

    print(f"water quality: {len(wq['stations'])} stations, {len(wq['parameters'])} parameters")
    for s in wq["stations"]:
        print(f"   {s['name'][:42]:<44} {s['records']:>4} records  {s['from']} .. {s['to']}"
              f"  params={len(s['parameters'])}  dupDates={s['duplicateDatesDropped']}")
    write("gujarat_water_quality.json", wq)

    sw = build_solid_waste(root / "data extracted from DEP22 for pollution reports.xlsx")
    print(f"\nsolid waste: {len(sw['categories'])} categories")
    for c in sw["categories"]:
        numeric = sum(1 for r in c["rows"] if r["value"] is not None)
        print(f"   {c['name'][:26]:<28} {len(c['rows']):>2} rows, {numeric} numeric")
    write("gujarat_solid_waste.json", sw)

    sed = build_sediment(root / "gujarat sediment data cwc till 2025.csv")
    print(f"\nsediment: {len(sed['stations'])} stations, "
          f"{sed['years'][0]}-{sed['years'][-1]}, quality={sed['quality']}")
    for s in sed["stations"]:
        print(f"   {s['name'][:24]:<26} {s['river'] or '-':<12} {s['district'] or '-':<14}"
              f" {s['records']:>6} readings  {s['from']}-{s['to']}")
    write("gujarat_sediment.json", sed)


if __name__ == "__main__":
    main()
