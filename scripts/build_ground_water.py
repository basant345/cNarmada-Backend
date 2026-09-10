#!/usr/bin/env python3
"""
Rebuild app/static/data/ground_water.json from the two CGWB workbooks.

    python scripts/build_ground_water.py  Upper_GW_.xlsx  Middle_GW.xlsx

Every parameter sheet in those workbooks is a station x year matrix:

    state | name | New Station Code | 2000 | 2001 | ... | 2022 | Avg | Min | Max

The previous ground_water.json kept only the Avg/Min/Max columns, which threw
away the 23-year time axis. This script keeps the yearly values and derives the
summary statistics itself.

Two deliberate differences from the workbook:

  * Avg / Min / Max are RECOMPUTED from the year cells rather than copied from
    the sheet. Four rows in the Middle workbook (station "Dehari" in PH, SO4,
    CL and NO3) have an Avg whose formula range overruns by one cell, so the
    copied value disagreed with its own data.

  * The NO3 sheet is included. It exists in both workbooks but was missing from
    the published JSON, so nitrate never reached the site.

Output shape:

    { "<zone>": { "<parameter>": {
          "years":   ["2000", ...],
          "yearly":  { "2000": {"avg":…, "min":…, "max":…, "n":…}, ... },
          "stations":[ {"station":…, "code":…, "avg":…, "min":…, "max":…,
                        "values": {"2000": 7.7, ...}} ]
    } } }
"""

import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

YEAR_RE = re.compile(r"^(19\d{2}|20[0-3]\d)$")
META_COLS = {"state", "name", "new station code", "station code", "avg", "min", "max"}
ROUND_TO = 4


def clean(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def as_number(value):
    """Year cells are usually numeric but occasionally arrive as text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parameter_name(sheet_name):
    """'Upper- PH' -> 'PH'.  'ALK-TOT' -> 'ALK-TOT'.

    Only the zone prefix is stripped; the rest of the label is left exactly as
    the workbook spells it, so the parameter names on the site do not shift.
    """
    name = re.sub(r"^\s*(upper|middle|lower)\s*[-–]?\s*", "", sheet_name, flags=re.I)
    return " ".join(name.split())


def read_sheet(worksheet):
    """Return (years, stations) or None when the sheet is not a year matrix."""
    rows = worksheet.iter_rows(values_only=True)
    try:
        header = [clean(c) for c in next(rows)]
    except StopIteration:
        return None

    year_cols = [(i, h) for i, h in enumerate(header) if h and YEAR_RE.match(h)]
    if not year_cols:
        return None

    try:
        name_col = next(i for i, h in enumerate(header) if h and h.lower() == "name")
    except StopIteration:
        return None
    code_col = next(
        (i for i, h in enumerate(header) if h and h.lower() == "new station code"), None
    )

    years = [h for _, h in year_cols]
    stations = []

    for row in rows:
        station = clean(row[name_col]) if name_col < len(row) else None
        if not station:
            continue

        values = {}
        for idx, year in year_cols:
            number = as_number(row[idx]) if idx < len(row) else None
            if number is not None:
                values[year] = round(number, ROUND_TO)

        if not values:
            continue  # station listed but never sampled for this parameter

        readings = list(values.values())
        stations.append(
            {
                "station": station,
                "code": clean(row[code_col]) if code_col is not None and code_col < len(row) else None,
                "avg": round(sum(readings) / len(readings), ROUND_TO),
                "min": round(min(readings), ROUND_TO),
                "max": round(max(readings), ROUND_TO),
                "values": values,
            }
        )

    if not stations:
        return None
    return years, stations


def yearly_summary(years, stations):
    """Across-station average / minimum / maximum for each year."""
    summary = {}
    for year in years:
        readings = [s["values"][year] for s in stations if year in s["values"]]
        if not readings:
            continue
        summary[year] = {
            "avg": round(sum(readings) / len(readings), ROUND_TO),
            "min": round(min(readings), ROUND_TO),
            "max": round(max(readings), ROUND_TO),
            "n": len(readings),
        }
    return summary


def build_zone(path):
    workbook = load_workbook(path, data_only=True, read_only=True)
    zone = {}
    for sheet_name in workbook.sheetnames:
        parsed = read_sheet(workbook[sheet_name])
        if parsed is None:
            continue  # raw sample sheets and scratch sheets are skipped
        years, stations = parsed
        present = [y for y in years if any(y in s["values"] for s in stations)]
        zone[parameter_name(sheet_name)] = {
            "years": present,
            "yearly": yearly_summary(present, stations),
            "stations": stations,
        }
    workbook.close()
    return zone


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: build_ground_water.py <Upper_GW.xlsx> <Middle_GW.xlsx>")

    output = {
        "upper": build_zone(sys.argv[1]),
        "middle": build_zone(sys.argv[2]),
    }

    destination = Path("app/static/data/ground_water.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))

    for zone_name, zone in output.items():
        print(f"{zone_name}: {len(zone)} parameters")
        for param, block in zone.items():
            print(
                f"   {param:<12} {len(block['stations']):>4} stations"
                f"  {len(block['years']):>2} years"
                f"  {block['years'][0]}-{block['years'][-1]}"
            )
    print(f"\nwrote {destination} ({destination.stat().st_size / 1048576:.2f} MB)")


if __name__ == "__main__":
    main()
