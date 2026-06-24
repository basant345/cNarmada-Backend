"""
Curated district-level dataset for the Home page "Districts Along the Narmada"
section. Every fact here is drawn directly from the cNARMADA report PDFs
already served under /static/data/reports — nothing is invented or estimated.

Source reports (short_id -> filename):
  demography  -> Demography-of-NRB.pdf
  agriculture -> Agricultural-Profile-of-Narmada-River-Basin_20250924.pdf
  water       -> Water-Demand-and-Supply-in-NRB.pdf
  flood       -> Flood-Hazard-Model-of-narmada-River-Basin.pdf
  pollution   -> pollution-load-report_20251023.pdf

Each district entry has 4 tabs: overview, land_use, water_resources,
insights_alerts. Each fact carries a `source` key naming the report it came
from, so the frontend can show "Source: <report>" next to the content.
"""
import json
import os

SOURCES = {
    "demography": "Demography of NRB",
    "agriculture": "Agricultural Profile of Narmada River Basin",
    "water": "Water Demand and Supply in NRB",
    "flood": "Flood Hazard Model of Narmada River Basin",
    "pollution": "Pollution Load Report",
}

DISTRICTS = [
    {
        "slug": "jabalpur",
        "name": "Jabalpur",
        "state": "Madhya Pradesh",
        "basin_zone": "Upper Narmada Basin",
        "lat": 23.1815, "lon": 79.9864,
        "basin_area_sq_km": 4675.56,
        "overview": {
            "summary": "Jabalpur is the most populous district in the Upper Narmada Basin and one of its central administrative and urban hubs, with 94.97% of its total area lying within the basin.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "2,425,715", "source": "demography"},
                {"label": "Projected population (2031)", "value": "3,141,469", "source": "water"},
                {"label": "Basin area", "value": "4,675.56 sq km (94.97% of district)", "source": "demography"},
                {"label": "Sub-districts (tehsils)", "value": "7", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "Jabalpur is among the basin's agriculturally intensive districts, with rising cropping intensity since the 1990s driven by expanded irrigation.",
            "facts": [
                {"label": "Land use trend", "value": "One of the central districts (with Hoshangabad, Sehore, Raisen) showing rising cropping intensity after 1990 due to expanded irrigation", "source": "agriculture"},
                {"label": "Landholding pattern", "value": "More than 60% of landholdings are marginal, alongside Mandla district", "source": "agriculture"},
                {"label": "Net cropped area trend", "value": "Among districts with consistent growth in net cropped area from the 1970s through the 2010s", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Jabalpur has the highest projected water demand of any district in the basin, tracking its large and growing urban population.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~170 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~220 MLD", "source": "water"},
                {"label": "Population growth driving demand", "value": "2.42 million (2011) → 3.14 million (2031)", "source": "water"},
                {"label": "Domestic sewage generation", "value": "143.68 MLD — the largest in the basin", "source": "pollution"},
            ],
        },
        "insights_alerts": {
            "summary": "Jabalpur hosts the basin's largest sewage treatment infrastructure, but still discharges significant untreated sewage; CPCB has flagged the Jabalpur river stretch itself as critically polluted.",
            "alerts": [
                {"severity": "critical", "text": "CPCB has marked the Jabalpur river stretch as critically polluted, per the NGT case Kirtikumar Sadashiv Bhatt vs Narmada Water Resources.", "source": "pollution"},
                {"severity": "warning", "text": "Of 143.68 MLD domestic sewage generated, only 83.43 MLD receives partial treatment across 8 operational STPs; roughly 60 MLD of sewage remains untreated.", "source": "pollution"},
                {"severity": "info", "text": "Jabalpur has the highest sewage treatment coverage in the basin, with 11 operational STPs.", "source": "pollution"},
            ],
        },
    },
    {
        "slug": "mandla",
        "name": "Mandla",
        "state": "Madhya Pradesh",
        "basin_zone": "Upper Narmada Basin",
        "lat": 22.6, "lon": 80.37,
        "basin_area_sq_km": 6722.82,
        "overview": {
            "summary": "Mandla is the largest district by area in the Upper Narmada Basin, with 88.39% of its territory inside the basin.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "914,427", "source": "demography"},
                {"label": "Projected population (2031)", "value": "1,184,246", "source": "water"},
                {"label": "Basin area", "value": "6,722.82 sq km — the largest of any Upper Basin district", "source": "demography"},
                {"label": "Population density", "value": "Lower density (156.86/sq km) indicating less demographic pressure than urban districts", "source": "water"},
            ],
        },
        "land_use": {
            "summary": "A tribal and upland district with relatively low and stagnant cropping intensity due to terrain constraints and limited irrigation.",
            "facts": [
                {"label": "Cropping intensity", "value": "Often below 110%, constrained by terrain and fragmented landholdings", "source": "agriculture"},
                {"label": "Landholding pattern", "value": "More than 60% of landholdings are marginal, alongside Jabalpur district", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Water demand is moderate and rising in line with population growth, with sewage infrastructure still under construction.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~64 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~83 MLD", "source": "water"},
                {"label": "Domestic sewage generation", "value": "10.25 MLD", "source": "pollution"},
            ],
        },
        "insights_alerts": {
            "summary": "CPCB has flagged the Mandla–Bhedaghat river stretch as highly polluted, and sewage treatment infrastructure remains incomplete.",
            "alerts": [
                {"severity": "critical", "text": "CPCB declared the Mandla–Bhedaghat stretch as highly polluted, per the NGT case Kirtikumar Sadashiv Bhatt vs Narmada Water Resources.", "source": "pollution"},
                {"severity": "warning", "text": "No operational STP for the district's 10.25 MLD of sewage; 2 STPs (2 MLD & 7.75 MLD) are under construction and 1 small STP (0.5 MLD) is not working — sewage is currently discharged largely untreated.", "source": "pollution"},
            ],
        },
    },
    {
        "slug": "dindori",
        "name": "Dindori",
        "state": "Madhya Pradesh",
        "basin_zone": "Upper Narmada Basin",
        "lat": 22.94, "lon": 81.07,
        "basin_area_sq_km": 4706.49,
        "overview": {
            "summary": "Dindori is a predominantly tribal upland district with 83.06% of its area inside the Upper Narmada Basin.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "601,517", "source": "demography"},
                {"label": "Projected population (2031)", "value": "779,006", "source": "water"},
                {"label": "Basin area", "value": "4,706.49 sq km (83.06% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "Among the tribal and upland districts with relatively low, stagnant cropping intensity.",
            "facts": [
                {"label": "Cropping intensity", "value": "Relatively low and stagnant — often below 110% — due to terrain constraints, fragmented landholdings, and limited irrigation", "source": "agriculture"},
                {"label": "Net cropped area", "value": "Among districts that recorded consistently low net cropped area, particularly in earlier decades", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "One of the lowest sewage-generating districts in the basin, reflecting its rural and tribal population base.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~42 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~55 MLD", "source": "water"},
                {"label": "Domestic sewage generation", "value": "3.49 MLD — among the lowest in the basin", "source": "pollution"},
            ],
        },
        "insights_alerts": {
            "summary": "Like neighbouring Amarkantak and Mandla, Dindori currently has no functioning sewage treatment plant.",
            "alerts": [
                {"severity": "warning", "text": "No operational STP; a 3.8 MLD STP is under construction while untreated sewage is currently discharged.", "source": "pollution"},
            ],
        },
    },
    {
        "slug": "hoshangabad",
        "name": "Hoshangabad (Narmadapuram)",
        "state": "Madhya Pradesh",
        "basin_zone": "Upper / Middle Narmada Basin",
        "lat": 22.75, "lon": 77.73,
        "basin_area_sq_km": 4631.52,
        "overview": {
            "summary": "Hoshangabad straddles both the Upper and Middle Narmada Basins and is part of the basin's agricultural core.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "1,260,086", "source": "demography"},
                {"label": "Projected population (2031)", "value": "1,631,899", "source": "water"},
                {"label": "Basin area (Upper Basin)", "value": "4,631.52 sq km (69.37% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "Part of the basin's agricultural core, with net cropped area consistently exceeding 700,000 hectares and cropping intensity well above 150%.",
            "facts": [
                {"label": "Agricultural core district", "value": "Cropping intensity well above 150%, supported by canal irrigation and groundwater extraction for soybean–wheat and paddy–wheat cropping", "source": "agriculture"},
                {"label": "Fertilizer use", "value": "Tops nitrogen fertilizer usage in the basin, alongside Khargone", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Among the districts with the sharpest projected rise in water demand, and currently discharges its entire sewage load untreated.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~88 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~114 MLD", "source": "water"},
                {"label": "Domestic sewage generation (Narmadapuram)", "value": "12 MLD", "source": "pollution"},
            ],
        },
        "insights_alerts": {
            "summary": "Nitrate contamination has breached WHO safety thresholds, and the district has no operational sewage treatment plant despite high sewage generation.",
            "alerts": [
                {"severity": "critical", "text": "Nitrate levels in Omkareshwar and Hoshangabad have breached 60 mg/L, exceeding WHO safety thresholds, linked to fertilizer residues.", "source": "agriculture"},
                {"severity": "warning", "text": "No STP currently operational for Narmadapuram's 12 MLD sewage load; a 21 MLD STP has been proposed but the entire load is presently discharged untreated.", "source": "pollution"},
                {"severity": "warning", "text": "Was among the worst-hit districts (with Vidisha and Dewas) in a major flood disaster, with over 100 villages inundated and 24,000 homes destroyed across at least 12 affected districts.", "source": "flood"},
                {"severity": "info", "text": "In the August 2020 flood, Hoshangabad recorded over 400 mm of rain in 24 hours, pushing the Narmada 2.1 metres above its danger mark — close to the historic 1972 flood levels.", "source": "flood"},
            ],
        },
    },
    {
        "slug": "khargone",
        "name": "Khargone (West Nimar)",
        "state": "Madhya Pradesh",
        "basin_zone": "Middle Narmada Basin",
        "lat": 21.82, "lon": 75.61,
        "basin_area_sq_km": 7722.99,
        "overview": {
            "summary": "Khargone is the most densely populated district in the Middle Narmada Basin and has the largest basin area share (93.68%) among Middle Basin districts.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "1,834,133 — the largest in the Middle Basin", "source": "demography"},
                {"label": "Projected population (2031)", "value": "2,375,329", "source": "water"},
                {"label": "Basin area", "value": "7,722.99 sq km (93.68% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "A leading adopter of micro-irrigation, achieving both significant water savings and yield gains.",
            "facts": [
                {"label": "Micro-irrigation adoption", "value": "Among the leading districts (with Bharuch, Dhar, Narsinghpur) for drip irrigation, enabling 30–50% water savings and 15–25% yield gains in cotton, vegetables and banana", "source": "agriculture"},
                {"label": "Fertilizer use", "value": "Tops nitrogen fertilizer usage in the basin, alongside Hoshangabad", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Khargone has the highest projected water demand of any district in the basin, driven by its large and fast-growing population.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~128 MLD — the highest in the basin", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~166 MLD", "source": "water"},
                {"label": "Population growth driving demand", "value": "1.83 million (2011) → 2.38 million (2031)", "source": "water"},
            ],
        },
        "insights_alerts": {
            "summary": "Ranks among the more flood-vulnerable Middle Basin districts in the Flood Vulnerability Index assessment.",
            "alerts": [
                {"severity": "warning", "text": "Ranked 19th of 21 districts assessed in the Madhya Pradesh Flood Vulnerability Index (normalised FVI 0.82) — among the more vulnerable districts in the basin.", "source": "flood"},
            ],
        },
    },
    {
        "slug": "dhar",
        "name": "Dhar",
        "state": "Madhya Pradesh",
        "basin_zone": "Middle Narmada Basin",
        "lat": 22.6, "lon": 75.3,
        "basin_area_sq_km": 4955.33,
        "overview": {
            "summary": "Dhar has 60.83% of its total area within the Middle Narmada Basin, with 7 sub-districts (tehsils) inside the basin.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "1,440,006", "source": "demography"},
                {"label": "Projected population (2031)", "value": "1,864,908", "source": "water"},
                {"label": "Basin area", "value": "4,955.33 sq km (60.83% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "A leading adopter of micro-irrigation alongside Bharuch, Khargone and Narsinghpur.",
            "facts": [
                {"label": "Micro-irrigation adoption", "value": "Among the leading districts for drip irrigation adoption, with 30–50% water savings and 15–25% yield gains in cotton, vegetables and banana", "source": "agriculture"},
                {"label": "Industrial wastewater", "value": "Produces only around 18 MLD of industrial wastewater — comparatively low among basin districts", "source": "pollution"},
            ],
        },
        "water_resources": {
            "summary": "Water demand from Dhar is among the higher figures in the Middle Basin, tracking strong population growth.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~101 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~131 MLD", "source": "water"},
            ],
        },
        "insights_alerts": {
            "summary": "Localized flooding has affected upstream villages in Dhar district during recent dam-related release events.",
            "alerts": [
                {"severity": "warning", "text": "Flooding in upstream villages such as Ekalbara in Dhar district has been recorded in relation to reservoir operations.", "source": "flood"},
                {"severity": "warning", "text": "Ranked 10th of 21 districts in the Madhya Pradesh Flood Vulnerability Index (normalised FVI 0.63).", "source": "flood"},
            ],
        },
    },
    {
        "slug": "barwani",
        "name": "Barwani",
        "state": "Madhya Pradesh",
        "basin_zone": "Middle Narmada Basin",
        "lat": 22.03, "lon": 74.9,
        "basin_area_sq_km": 3909.05,
        "overview": {
            "summary": "Barwani has 75.53% of its area within the Middle Narmada Basin and is the second most populous district in the Middle Basin.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "1,103,143", "source": "demography"},
                {"label": "Projected population (2031)", "value": "1,428,647", "source": "water"},
                {"label": "Basin area", "value": "3,909.05 sq km (75.53% of district)", "source": "demography"},
                {"label": "Sub-districts (tehsils)", "value": "9 — tied with Khargone for the most in the Middle Basin", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "Reported among districts with alarming sediment concentrations of chromium and nickel, linked to fertilizer residues.",
            "facts": [
                {"label": "Sediment contamination", "value": "Sediment samples show concentrations of chromium and nickel linked to fertilizer residues, alongside Sehore district", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "One of the steepest projected rises in water demand of any district in the basin.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~77 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~100 MLD — one of the steepest jumps in the basin", "source": "water"},
            ],
        },
        "insights_alerts": {
            "summary": "Ranked the most flood-vulnerable district in the entire Madhya Pradesh portion of the basin.",
            "alerts": [
                {"severity": "critical", "text": "Ranked 21st of 21 districts — the most flood-vulnerable in the Madhya Pradesh Flood Vulnerability Index (normalised FVI 1.00, exposure index 1.0).", "source": "flood"},
            ],
        },
    },
    {
        "slug": "indore",
        "name": "Indore",
        "state": "Madhya Pradesh",
        "basin_zone": "Middle Narmada Basin",
        "lat": 22.72, "lon": 75.86,
        "basin_area_sq_km": 1009.18,
        "overview": {
            "summary": "Indore's basin-area population is smaller than Khargone or Jabalpur, but its economic weight makes it significant for basin water planning.",
            "facts": [
                {"label": "Population (2011 Census, basin area)", "value": "204,201", "source": "demography"},
                {"label": "Projected population (2031, basin area)", "value": "264,454", "source": "water"},
                {"label": "Basin area", "value": "1,009.18 sq km (26.61% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "Cropping intensity in Indore rose markedly after 1990 alongside Hoshangabad, Sehore and Raisen, driven by expanded irrigation.",
            "facts": [
                {"label": "Cropping intensity trend", "value": "Among central districts showing higher cropping intensity values after 1990 due to expanded irrigation and improved practices", "source": "agriculture"},
                {"label": "Net cropped area trend", "value": "Net cropped area rose markedly, reaching 10–25 thousand hectares by 2017, alongside Bhopal and Jabalpur", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Indore's water demand is rising steadily, reflecting both population growth and its economic importance for urban water planning.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~14 MLD (basin area)", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~18.5 MLD (basin area)", "source": "water"},
                {"label": "Industrial wastewater", "value": "7.3 MLD from 385 industries", "source": "pollution"},
            ],
        },
        "insights_alerts": {
            "summary": "Despite being a major urban centre, a large share of Indore's sewage still reaches the river without treatment.",
            "alerts": [
                {"severity": "warning", "text": "Even in large cities like Indore and Jabalpur, most sewage still goes into the river without adequate treatment, per the basin-wide sewage assessment.", "source": "pollution"},
                {"severity": "info", "text": "One of three group field-visit locations (with Bhopal, Jhabua, Alirajpur, Dewas) where the report team met MPPCB and municipal officials to verify pollution data on the ground.", "source": "pollution"},
            ],
        },
    },
    {
        "slug": "vadodara",
        "name": "Vadodara",
        "state": "Gujarat",
        "basin_zone": "Lower Narmada Basin",
        "lat": 22.31, "lon": 73.18,
        "basin_area_sq_km": 3914.3,
        "overview": {
            "summary": "Vadodara has the largest basin-area share of any Lower Basin district in Gujarat, at 51.9% of its total area.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "1,155,469", "source": "demography"},
                {"label": "Projected population (2031)", "value": "1,489,855", "source": "water"},
                {"label": "Basin area", "value": "3,914.3 sq km (51.9% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "Identified as one of the basin's most prominent agricultural land-use zones, alongside Jalgaon, Bharuch, Indore and Hoshangabad.",
            "facts": [
                {"label": "Agricultural zone status", "value": "One of the most prominent land-use zones in the basin by net cropped area", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Vadodara has the second-highest water demand of any district in the Lower Basin.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~81 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~104 MLD", "source": "water"},
            ],
        },
        "insights_alerts": {
            "summary": "Low-lying villages in Vadodara district were flooded during the major dam-release flood events of 2013 and 2020.",
            "alerts": [
                {"severity": "critical", "text": "The 2013 flood saw the Orsang river (a Narmada tributary) cause extensive destruction to riverside villages in Vadodara district.", "source": "flood"},
                {"severity": "warning", "text": "In the August–September 2020 flood, low-lying villages in Bharuch, Narmada and Vadodara districts were flooded, forcing evacuation of over 9,700 people from 49 villages.", "source": "flood"},
            ],
        },
    },
    {
        "slug": "bharuch",
        "name": "Bharuch",
        "state": "Gujarat",
        "basin_zone": "Lower Narmada Basin",
        "lat": 21.7, "lon": 72.97,
        "basin_area_sq_km": 1651.0,
        "overview": {
            "summary": "Bharuch sits at the Narmada's mouth and is one of the most heavily industrialized districts in the entire basin.",
            "facts": [
                {"label": "Population (2011 Census)", "value": "897,495", "source": "demography"},
                {"label": "Projected population (2031)", "value": "1,157,225", "source": "water"},
                {"label": "Basin area", "value": "1,651 sq km (31.7% of district)", "source": "demography"},
            ],
        },
        "land_use": {
            "summary": "A leading adopter of micro-irrigation and a major industrial land-use zone, hosting chemicals, petrochemicals, pharmaceuticals, textiles and agro-processing.",
            "facts": [
                {"label": "Industrial profile", "value": "Heavily industrialized with chemicals & petrochemicals, pharmaceuticals, textiles, engineering, dairy and agro-processing (incl. peanut processing); also hosts lignite, silica sand and agate mineral resources", "source": "pollution"},
                {"label": "Ankleshwar chemical estate", "value": "Contributes over 5% of India's chemical output, specializing in dyes, pharmaceuticals and industrial chemicals", "source": "pollution"},
                {"label": "Micro-irrigation adoption", "value": "Among the leading districts for drip irrigation, with 30–50% water savings and 15–25% yield gains", "source": "agriculture"},
            ],
        },
        "water_resources": {
            "summary": "Bharuch's water demand is rising sharply, and the district bears the brunt of operational releases from the Sardar Sarovar Dam.",
            "facts": [
                {"label": "Water demand (2011)", "value": "~63 MLD", "source": "water"},
                {"label": "Projected water demand (2031)", "value": "~81 MLD", "source": "water"},
                {"label": "Domestic sewage generation", "value": "~35.5 MLD", "source": "pollution"},
            ],
        },
        "insights_alerts": {
            "summary": "Bharuch experiences the most severe downstream flood impacts in the basin from Sardar Sarovar Dam releases, and hosts the basin's largest industrial pollution load.",
            "alerts": [
                {"severity": "critical", "text": "In the 2013 flood, the Narmada at the Golden Bridge in Bharuch surged to 32–33.5 feet, far exceeding the 24-foot danger mark; the event was termed a \"man-made calamity\" due to sudden upstream dam releases.", "source": "flood"},
                {"severity": "critical", "text": "Bharuch and Narmada districts bear the brunt of operational releases from the Sardar Sarovar Dam, per historical flood vulnerability analysis.", "source": "flood"},
                {"severity": "warning", "text": "Five Common Effluent Treatment Plants (CETPs) operate in the Bharuch–Ankleshwar belt, which remains the main source of industrial wastewater in the Lower Basin.", "source": "pollution"},
                {"severity": "info", "text": "Hazardous waste from large industries, especially in Bharuch, adds to land and water pollution across the Lower Basin.", "source": "pollution"},
            ],
        },
    },
]


def build():
    return {
        "sources": SOURCES,
        "districts": DISTRICTS,
    }


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "app", "static", "data")
    out_path = os.path.join(out_dir, "districts.json")
    with open(out_path, "w") as f:
        json.dump(build(), f, indent=2)
    print(f"Wrote {len(DISTRICTS)} districts to {out_path}")
