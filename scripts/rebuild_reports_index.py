"""
Rebuild reports_index.json from the reports folder itself.

The catalogue and the folder had drifted apart: entries pointing at files
that were gone, files that no entry mentioned. This script removes the
drift by construction. It lists the folder and writes one entry per file,
so the number of reports on the site is always the number of PDFs on disk.

Titles are never invented. For each file the title comes from, in order:

  1. the title already in reports_index.json for that same filename
  2. the title that was in reports_index.json for the file this one
     replaced (RENAMES below), used only when the old file is gone
  3. KNOWN_TITLES, for a report that has never been catalogued
  4. the filename itself, with separators turned into spaces

Anything that falls through to 4 is printed under NEW TITLE so you can
reword it. Entries are sorted by title, which is how this catalogue has
always been ordered.

    cd backend
    python scripts/rebuild_reports_index.py
    python scripts/rebuild_reports_index.py --write

Nothing is written without --write. Running it twice changes nothing.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "app", "static", "data"))
INDEX = os.path.join(DATA, "reports_index.json")
REPORTS = os.path.join(DATA, "reports")

LISTABLE = (".pdf", ".docx", ".xlsx", ".csv")

# new filename -> the filename it replaced. The old entry's title is carried
# over, but only while the old file is no longer in the folder: if both are
# present they are two separate reports and each keeps its own title.
RENAMES = {
    "Infrastructure_and_Planing_Report.pdf":
        "Narmada-Basin-Infrastructure-and-Planning-Report.pdf",
    "Quarter_8_Threats_and_challenges_of_the_Narmada_River_.pdf":
        "Threats-and-Challenges-of-the-Narmada-River-27-March-2026.pdf",
    "Quarter-8-Identification-of-the-Major-Threats-and-Challenges-for-the-Narmada-River.pdf":
        "Threats-and-Challenges-of-the-Narmada-River-27-March-2026.pdf",
    "Pollution-Source-Mapping-for-Narmada-River-Basin.pdf":
        "Pollution-Source-Mapping-Report_20260314.pdf",
    "Management-Plan-for-Domestic-Wastewater.pdf":
        "Domestic-Wastewater-Management-Plan-28.7.26.pdf",
    "Management-Plan-for-Industrial-Wastewater.pdf":
        "Industrial-Wastewater-Management-Plan-28.7.26.pdf",
    "Physico-Chemical-and-Biological-Profile-Upper-and-Middle-Basin.pdf":
        "Physio-chemical-and-biological-Profile-final-report_20260314.pdf",
    "Narmada-Nutrient-Sediment-and-Load-Management.pdf":
        "Nutrient-Sediment-Load-Report-final_20260314.pdf",
    "Mapping-of-Best-Practices-in-Solid-Liquid-Waste-Management-International-and-National.pdf":
        "Mapping-of-Best-Practices-in-Solid-Liquid-Waste-Management-National-and-International-30-03-2026.pdf",
    "Industrial-Profile-of-Narmada-River-Basin.pdf":
        "Industrial-Profile-Report_Final_cnarmada_20260313.pdf",
}

# Reports that have never had a catalogue entry, titled from their cover page.
KNOWN_TITLES = {
    "Quarter_9_IITI_Biodiversity_report_.pdf":
        "Identification of Major Threats to Biodiversity, Management and Conservation (Quarter 9)",
    "Quarter-9-Identification-of-Major-Threats-to-Biodiversity-Management-and-Conservation.pdf":
        "Identification of Major Threats to Biodiversity, Management and Conservation (Quarter 9)",
    # Used only while the report each of these replaced is still in the
    # folder; otherwise the older entry's title carries over through RENAMES.
    "Quarter-8-Identification-of-the-Major-Threats-and-Challenges-for-the-Narmada-River.pdf":
        "Identification of the Major Threats and Challenges for the Narmada River (Quarter 8)",
    "Mapping-of-Best-Practices-in-Solid-Liquid-Waste-Management-International-and-National.pdf":
        "Mapping of Best Practices in Solid-Liquid Waste Management (International and National)",
}


def from_filename(name):
    """A readable title out of the filename, inventing nothing."""
    stem = os.path.splitext(name)[0]
    return re.sub(r"\s+", " ", stem.replace("_", " ").replace("-", " ")).strip()


def size_mb(name):
    return round(os.path.getsize(os.path.join(REPORTS, name)) / (1024 * 1024), 2)


def main():
    write = "--write" in sys.argv

    if not os.path.isdir(REPORTS):
        sys.exit(f"Not found: {REPORTS}")

    old_titles = {}
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as fh:
            for entry in json.load(fh):
                old_titles[entry["filename"]] = entry["title"]

    files = sorted(f for f in os.listdir(REPORTS) if f.lower().endswith(LISTABLE))

    index, derived, carried = [], [], []
    for name in files:
        if name in old_titles:
            title = old_titles[name]
        elif name in RENAMES and RENAMES[name] not in files and RENAMES[name] in old_titles:
            title = old_titles[RENAMES[name]]
            carried.append((name, RENAMES[name], title))
        elif name in KNOWN_TITLES:
            title = KNOWN_TITLES[name]
            derived.append((name, title, "cover page"))
        else:
            title = from_filename(name)
            derived.append((name, title, "filename"))
        index.append({"title": title, "filename": name, "size_mb": size_mb(name)})

    index.sort(key=lambda entry: entry["title"].lower())

    dropped = sorted(set(old_titles) - set(files))
    # a replaced report whose old file is still in the folder: two versions
    # of the same document, both listed
    both = [(new, old) for new, old in RENAMES.items() if new in files and old in files]

    print(f"{len(files)} files in the folder -> {len(index)} catalogue entries\n")
    for entry in index:
        print(f"  {entry['size_mb']:>6} MB  {entry['title']}")
        print(f"             {entry['filename']}")

    if carried:
        print("\nTITLE CARRIED OVER from the report each of these replaced:")
        for new, old, title in carried:
            print(f"  {new}\n      kept: {title}   (was {old})")
    if derived:
        print("\nNEW TITLE, check the wording:")
        for name, title, how in derived:
            print(f"  {name}\n      {title}   (from the {how})")
    if dropped:
        print("\nENTRIES DROPPED, their file is not in the folder:")
        for name in dropped:
            print(f"  {name}   was: {old_titles[name]}")
    if both:
        print("\nTWO VERSIONS OF THE SAME REPORT, both listed:")
        for new, old in both:
            print(f"  {old}\n  {new}")
        print("  Delete the older file and re-run if you only want one of each.")

    if not write:
        print("\nNothing written. Re-run with --write to apply.")
        return

    with open(INDEX, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\nWrote {INDEX}  ({len(index)} entries)")


if __name__ == "__main__":
    main()
