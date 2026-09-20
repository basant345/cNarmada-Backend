"""
Build the Narmada Mitra knowledge base.

Narmada Mitra is the cNARMADA assistant. It answers from a curated knowledge
base rather than a language model, so it costs nothing to run and starts
instantly on a free Render dyno.

Every figure in the knowledge base is computed here from the datasets the
site actually serves. Nothing is copied from an older report or typed in by
hand, so if a dataset is rebuilt the answers move with it. Run this whenever
the underlying data changes:

    python scripts/build_chatbot_kb.py

Output: app/static/data/chatbot/knowledge.json

The file is validated before it is written, so a failure part-way through
cannot leave a half-built knowledge base on disk.
"""

import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "app", "static", "data")
OUT_DIR = os.path.join(DATA_DIR, "chatbot")
OUT_FILE = os.path.join(OUT_DIR, "knowledge.json")


def load(*parts):
    path = os.path.join(DATA_DIR, *parts)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def count_species(bio):
    """Total species entries across every zone/group/class in the tree."""
    if not bio:
        return 0
    total = 0
    for zone in (bio.get("zones") or []):
        for group in (zone.get("groups") or []):
            for klass in (group.get("classes") or []):
                total += len(klass.get("species") or [])
    return total


def gather_facts():
    """Read every published dataset and derive the numbers the answers use."""
    f = {}

    stations = load("stations.json") or []
    f["stations_total"] = len(stations)
    f["stations_mapped"] = sum(1 for s in stations if s.get("lat") and s.get("lon"))
    f["stations_flow"] = sum(1 for s in stations if s.get("has_streamflow"))
    f["stations_level"] = sum(1 for s in stations if s.get("has_waterlevel"))

    reports = load("reports_index.json") or []
    f["reports_total"] = len(reports)

    bio = load("biodiversity.json")
    f["species_total"] = count_species(bio)
    f["bio_zones"] = len((bio or {}).get("zones") or [])

    gw = load("ground_water.json") or {}
    f["gw_regions"] = len([k for k in gw.keys() if isinstance(gw.get(k), dict)])

    wq = load("water_quality.json") or {}
    f["wq_parameters"] = len(wq.get("parameters") or [])
    f["wq_locations"] = len(wq.get("locations") or [])

    gwq = load("gujarat_water_quality.json") or {}
    f["guj_stations"] = len(gwq.get("stations") or [])
    f["guj_parameters"] = len(gwq.get("parameters") or [])

    ind = load("industrial_profile.json") or {}
    f["industrial_parks"] = len(((ind.get("parks") or {}).get("items")) or [])
    monitoring = (ind.get("monitoring") or {}).get("stations") or []
    f["monitoring_stations"] = len(monitoring)
    f["monitoring_sectors"] = len((ind.get("monitoring") or {}).get("sectors") or [])

    atlas = load("river_atlas", "catalog.json") or {}
    layers = {l.get("id"): l for l in (atlas.get("layers") or [])}
    f["atlas_layers"] = len(layers)
    f["named_streams"] = (layers.get("named_streams") or {}).get("feature_count", 0)
    unnamed = layers.get("unnamed_streams") or {}
    f["unnamed_served"] = unnamed.get("feature_count", 0)
    coverage = unnamed.get("coverage") or {}
    f["unnamed_source"] = coverage.get("source_features", 0)
    f["unnamed_min_order"] = coverage.get("min_stream_order", 0)
    f["unnamed_km"] = coverage.get("served_length_km", 0)

    # Centre-line length, straight from the published geometry's own record.
    centre = load("river_atlas", "centre_line.geojson") or {}
    feats = centre.get("features") or []
    f["centreline_km"] = (feats[0].get("properties") or {}).get("Length") if feats else None

    return f


# ── Knowledge entries ────────────────────────────────────────────────────
# Each entry: id, tags (matched against the question), a short answer in
# English and Hindi, and optional links into the site. {placeholders} are
# filled from the computed facts above.
def build_entries(f):
    return [
        # ── The basin ────────────────────────────────────────────────────
        {
            "id": "basin_overview",
            "tags": ["narmada", "basin", "river", "overview", "introduction", "amarkantak",
                     "origin", "source of the river", "length", "states"],
            "en": "The Narmada is the largest west-flowing river in peninsular India. It rises at "
                  "Amarkantak on the Maikal range in Madhya Pradesh and runs west to the Gulf of "
                  "Khambhat in the Arabian Sea, crossing Madhya Pradesh, Maharashtra and Gujarat. "
                  "The centre line published in the River Atlas measures {centreline_km:,.0f} km.",
            "hi": "नर्मदा प्रायद्वीपीय भारत की सबसे बड़ी पश्चिम-वाहिनी नदी है। इसका उद्गम मध्य प्रदेश में "
                  "मैकाल श्रेणी के अमरकंटक से होता है और यह मध्य प्रदेश, महाराष्ट्र तथा गुजरात से होकर "
                  "पश्चिम में खंभात की खाड़ी तक बहती है। नदी एटलस में प्रकाशित केंद्र रेखा की लंबाई "
                  "{centreline_km:,.0f} किमी है।",
            "links": [{"label": "River Atlas", "to": "/river-atlas"}],
        },
        {
            "id": "tributaries",
            "tags": ["tributary", "tributaries", "stream", "streams", "network", "named", "unnamed",
                     "drainage", "how many rivers"],
            "en": "The River Atlas carries {named_streams:,} named tributaries and the unnamed "
                  "stream network. The unnamed layer is published at Strahler order "
                  "{unnamed_min_order} and above, which is {unnamed_served:,} reaches "
                  "({unnamed_km:,.0f} km) out of {unnamed_source:,} in the source data. The full "
                  "set is far too large to draw in a browser.",
            "hi": "नदी एटलस में {named_streams:,} नामित सहायक नदियाँ तथा अनाम धारा नेटवर्क शामिल हैं। "
                  "अनाम परत स्ट्रालर क्रम {unnamed_min_order} और उससे ऊपर पर प्रकाशित है, अर्थात "
                  "स्रोत डेटा के {unnamed_source:,} खंडों में से {unnamed_served:,} खंड "
                  "({unnamed_km:,.0f} किमी)। पूरा सेट ब्राउज़र में बनाने के लिए बहुत बड़ा है।",
            "links": [{"label": "River Atlas", "to": "/river-atlas"}],
        },
        {
            "id": "sub_basins",
            "tags": ["upper", "middle", "lower", "sub-basin", "sub basin", "zone", "zones", "region"],
            "en": "The basin is treated in three zones across the portal: Upper, Middle and Lower "
                  "Narmada. Ground water quality is published for the upper and middle zones, and "
                  "biodiversity is organised across {bio_zones} basin zones.",
            "hi": "पोर्टल पर बेसिन को तीन क्षेत्रों में देखा जाता है: ऊपरी, मध्य और निचला नर्मदा। "
                  "भूजल गुणवत्ता ऊपरी और मध्य क्षेत्रों के लिए प्रकाशित है, और जैव विविधता "
                  "{bio_zones} बेसिन क्षेत्रों में व्यवस्थित है।",
            "links": [{"label": "Ground Water Quality", "to": "/data/ground-water-quality"},
                      {"label": "Biodiversity", "to": "/data/biodiversity"}],
        },

        # ── The project ──────────────────────────────────────────────────
        {
            "id": "what_is_cnarmada",
            "tags": ["cnarmada", "portal", "website", "project", "centre", "about us",
                     "iit", "indore", "gandhinagar", "camp", "jal shakti"],
            "en": "cNARMADA is the Centre for Narmada River Basin Management Studies, a joint "
                  "initiative of IIT Indore and IIT Gandhinagar under the Ministry of Jal Shakti. "
                  "Its work is the Condition Assessment and Management Plan (CAMP) for the Narmada, "
                  "aimed at restoring the river's ecological health and supporting sustainable water "
                  "resource management.",
            "hi": "सी-नर्मदा, नर्मदा नदी बेसिन प्रबंधन अध्ययन केंद्र है — जल शक्ति मंत्रालय के अंतर्गत "
                  "आईआईटी इंदौर और आईआईटी गांधीनगर की संयुक्त पहल। इसका कार्य नर्मदा के लिए स्थिति "
                  "आकलन एवं प्रबंधन योजना (CAMP) है, जिसका उद्देश्य नदी के पारिस्थितिक स्वास्थ्य की "
                  "बहाली और सतत जल संसाधन प्रबंधन है।",
            "links": [{"label": "About cNARMADA", "to": "/about"}],
        },
        {
            "id": "navigate_site",
            "tags": ["use", "navigate", "find", "menu", "section", "help", "start",
                     "get started", "how to use", "datasets", "dataset", "available",
                     "what datasets", "data section", "list of datasets"],
            "en": "Open the Data menu in the navigation bar for the datasets: Time Series, Geo "
                  "Spatial, Ground Water Quality, Agriculture, Solid Waste & Industrial Profile, "
                  "Basin Demography, Biodiversity, the API Catalog and the User Manual. River Atlas "
                  "is its own tab, and Reports holds the published documents.",
            "hi": "डेटासेट के लिए नेविगेशन बार में डेटा मेन्यू खोलें: समय श्रृंखला, भू-स्थानिक, भूजल "
                  "गुणवत्ता, कृषि, ठोस अपशिष्ट एवं औद्योगिक प्रोफ़ाइल, बेसिन जनसांख्यिकी, जैव विविधता, "
                  "API कैटलॉग और उपयोगकर्ता पुस्तिका। नदी एटलस का अपना टैब है, और रिपोर्ट अनुभाग में "
                  "प्रकाशित दस्तावेज़ हैं।",
            "links": [{"label": "Data", "to": "/data"}, {"label": "User Manual", "to": "/data/user-manual"}],
        },
        {
            "id": "download_login",
            "tags": ["download", "excel", "csv", "export", "login", "sign in", "otp", "access",
                     "why can't i download"],
            "en": "Viewing, charting and mapping are open to everyone. Downloading a dataset needs "
                  "a signed-in @iiti.ac.in account, so clicking an export button opens a one-time "
                  "password prompt. The check runs on the server, not in the browser.",
            "hi": "देखना, चार्ट बनाना और मानचित्रण सभी के लिए खुला है। डेटासेट डाउनलोड करने के लिए "
                  "@iiti.ac.in खाते से साइन इन आवश्यक है, इसलिए एक्सपोर्ट बटन दबाने पर OTP प्रॉम्प्ट "
                  "खुलता है। यह जाँच सर्वर पर होती है, ब्राउज़र में नहीं।",
            "links": [{"label": "Data", "to": "/data"}],
        },
        {
            "id": "languages",
            "tags": ["language", "hindi", "english", "translate", "भाषा"],
            "en": "The whole portal is available in English and Hindi. Use the language switcher in "
                  "the header; your choice is remembered on this device.",
            "hi": "पूरा पोर्टल अंग्रेज़ी और हिंदी में उपलब्ध है। हेडर में भाषा स्विचर का उपयोग करें; "
                  "आपका चयन इस डिवाइस पर सहेजा जाता है।",
            "links": [],
        },

        # ── Datasets ─────────────────────────────────────────────────────
        {
            "id": "time_series",
            "tags": ["time series", "streamflow", "discharge", "water level", "gauge", "station",
                     "stations", "hydrology", "flow"],
            "en": "Time Series covers {stations_total} monitoring stations, {stations_mapped} of "
                  "them with coordinates. {stations_flow} carry streamflow records and "
                  "{stations_level} carry water level. Pick a station to chart its series.",
            "hi": "समय श्रृंखला में {stations_total} निगरानी स्टेशन शामिल हैं, जिनमें {stations_mapped} "
                  "के निर्देशांक उपलब्ध हैं। {stations_flow} में प्रवाह और {stations_level} में जल स्तर "
                  "के अभिलेख हैं। श्रृंखला का चार्ट देखने के लिए स्टेशन चुनें।",
            "links": [{"label": "Time Series Data", "to": "/data/time-series"}],
        },
        {
            "id": "geospatial",
            "tags": ["geo", "spatial", "map", "gis", "layer", "layers", "raster", "lulc", "dem",
                     "elevation", "dam", "dams", "waterbodies", "stp", "geomorphology",
                     "precipitation", "temperature"],
            "en": "Geo Spatial Data is the main map. It layers the basin boundary, centre line, "
                  "named network, monitoring stations, districts, dams, waterbodies and STP "
                  "coverage, plus raster overlays for elevation, land use, precipitation, mean "
                  "temperature and geomorphology. Click a feature for its attributes.",
            "hi": "भू-स्थानिक डेटा मुख्य मानचित्र है। इसमें बेसिन सीमा, केंद्र रेखा, नामित नेटवर्क, "
                  "निगरानी स्टेशन, ज़िले, बाँध, जलाशय और STP कवरेज की परतें हैं, साथ ही ऊँचाई, "
                  "भू-उपयोग, वर्षा, औसत तापमान और भू-आकृति विज्ञान के रास्टर ओवरले भी। विशेषताएँ "
                  "देखने के लिए किसी फ़ीचर पर क्लिक करें।",
            "links": [{"label": "Geo Spatial Data", "to": "/data/geo-spatial"}],
        },
        {
            "id": "water_quality",
            "tags": ["water quality", "quality", "parameter", "ph", "do", "bod", "pollution",
                     "surface water"],
            "en": "Surface water quality is published for {wq_locations} locations across "
                  "{wq_parameters} parameters, with a ten-year comparative view alongside it.",
            "hi": "सतही जल गुणवत्ता {wq_locations} स्थानों के लिए {wq_parameters} मापदंडों पर "
                  "प्रकाशित है, साथ में दस वर्षीय तुलनात्मक दृश्य भी उपलब्ध है।",
            "links": [{"label": "Time Series Data", "to": "/data/time-series"}],
        },
        {
            "id": "ground_water",
            "tags": ["ground water", "groundwater", "ground water quality", "aquifer", "well",
                     "borewell", "no3", "nitrate", "fluoride"],
            "en": "Ground Water Quality is published for the upper and middle basin, by parameter "
                  "and by location, with year-wise values so you can follow a station over time.",
            "hi": "भूजल गुणवत्ता ऊपरी और मध्य बेसिन के लिए, मापदंड और स्थान के अनुसार प्रकाशित है, "
                  "वर्ष-वार मानों सहित, ताकि किसी स्टेशन को समय के साथ देखा जा सके।",
            "links": [{"label": "Ground Water Quality", "to": "/data/ground-water-quality"}],
        },
        {
            "id": "biodiversity",
            "tags": ["biodiversity", "species", "fish", "bird", "birds", "plankton", "phytoplankton",
                     "zooplankton", "macrobenthos", "macrophyte", "reptile", "amphibian", "flora",
                     "fauna", "ecology"],
            "en": "Biodiversity holds {species_total:,} species entries arranged as a tree: basin "
                  "zone, then group, then class, then species. Groups include phytoplankton, "
                  "zooplankton, macrobenthos, macrophytes, fish, birds, reptiles and amphibians.",
            "hi": "जैव विविधता में {species_total:,} प्रजाति प्रविष्टियाँ एक वृक्ष के रूप में हैं: "
                  "बेसिन क्षेत्र, फिर समूह, फिर वर्ग, फिर प्रजाति। समूहों में पादप प्लवक, प्राणी प्लवक, "
                  "मैक्रोबेंथोस, मैक्रोफाइट, मछलियाँ, पक्षी, सरीसृप और उभयचर शामिल हैं।",
            "links": [{"label": "Biodiversity", "to": "/data/biodiversity"}],
        },
        {
            "id": "agriculture",
            "tags": ["agriculture", "crop", "crops", "irrigation", "irrigated", "orchard",
                     "horticulture", "farming"],
            "en": "Agriculture maps crop and irrigated area alongside orchards and horticulture "
                  "across the basin.",
            "hi": "कृषि अनुभाग में बेसिन भर में फसल एवं सिंचित क्षेत्र के साथ बाग और बागवानी के "
                  "मानचित्र हैं।",
            "links": [{"label": "Agriculture", "to": "/data/agriculture"}],
        },
        {
            "id": "solid_waste",
            "tags": ["solid waste", "waste", "hazardous", "biomedical", "plastic", "electronic",
                     "e-waste", "c&d", "industrial", "industry", "industries", "mppcb", "mpidc",
                     "msme", "park", "parks", "red orange green"],
            "en": "Solid Waste & Industrial Profile covers waste categories including hazardous, "
                  "biomedical, plastic, electronic and construction waste, together with the "
                  "industrial profile: Red/Orange/Green categorisation, {industrial_parks} "
                  "industrial parks and {monitoring_stations} real-time monitoring stations.",
            "hi": "ठोस अपशिष्ट एवं औद्योगिक प्रोफ़ाइल में संकटमय, जैव-चिकित्सा, प्लास्टिक, इलेक्ट्रॉनिक "
                  "और निर्माण अपशिष्ट सहित श्रेणियाँ शामिल हैं, साथ ही औद्योगिक प्रोफ़ाइल: लाल/नारंगी/हरा "
                  "वर्गीकरण, {industrial_parks} औद्योगिक पार्क और {monitoring_stations} वास्तविक-समय "
                  "निगरानी स्टेशन।",
            "links": [{"label": "Solid Waste & Industrial Profile", "to": "/data/solid-waste"}],
        },
        {
            "id": "demography",
            "tags": ["demography", "population", "literacy", "sex ratio", "workforce", "census",
                     "district", "districts", "people"],
            "en": "Basin Demography maps district-wise population, sex ratio, literacy, workforce "
                  "and SC/ST shares as choropleth layers you can switch between.",
            "hi": "बेसिन जनसांख्यिकी में ज़िलेवार जनसंख्या, लिंगानुपात, साक्षरता, कार्यबल और अजा/अजजा "
                  "अनुपात कोरोप्लेथ परतों के रूप में दिखाए जाते हैं, जिन्हें आप बदल सकते हैं।",
            "links": [{"label": "Basin Demography", "to": "/data/basin-demography"}],
        },
        {
            "id": "gujarat",
            "tags": ["gujarat", "dep22", "sediment", "cwc", "bharuch", "garudeshwar"],
            "en": "Gujarat-region datasets are published in their own clearly separated sections: "
                  "water quality for {guj_stations} stations across {guj_parameters} parameters, "
                  "the DEP22 waste report, and CWC sediment data.",
            "hi": "गुजरात क्षेत्र के डेटासेट अलग, स्पष्ट रूप से चिह्नित अनुभागों में प्रकाशित हैं: "
                  "{guj_stations} स्टेशनों की {guj_parameters} मापदंडों पर जल गुणवत्ता, DEP22 अपशिष्ट "
                  "रिपोर्ट, और CWC तलछट डेटा।",
            "links": [{"label": "Time Series Data", "to": "/data/time-series"}],
        },
        {
            "id": "river_atlas",
            "tags": ["river atlas", "atlas", "centre line", "center line", "basin boundary",
                     "stream order", "strahler"],
            "en": "River Atlas draws {atlas_layers} layers: the basin boundary, the Narmada centre "
                  "line, the named stream network and the unnamed stream network. Click any "
                  "feature and the panel on the right lists every attribute recorded for it.",
            "hi": "नदी एटलस में {atlas_layers} परतें हैं: बेसिन सीमा, नर्मदा केंद्र रेखा, नामित धारा "
                  "नेटवर्क और अनाम धारा नेटवर्क। किसी भी फ़ीचर पर क्लिक करें और दाईं ओर का पैनल उसकी "
                  "सभी दर्ज विशेषताएँ दिखाएगा।",
            "links": [{"label": "River Atlas", "to": "/river-atlas"}],
        },
        {
            "id": "reports",
            "tags": ["report", "reports", "document", "documents", "pdf", "publication",
                     "publications", "study"],
            "en": "The Reports section holds {reports_total} published documents as PDFs, covering "
                  "the basin's condition assessment and supporting studies.",
            "hi": "रिपोर्ट अनुभाग में {reports_total} प्रकाशित दस्तावेज़ PDF रूप में हैं, जो बेसिन के "
                  "स्थिति आकलन और सहायक अध्ययनों को कवर करते हैं।",
            "links": [{"label": "Reports", "to": "/reports"}],
        },
        {
            "id": "sewer_outfall",
            "tags": ["sewer", "outfall", "drain", "report a problem", "complaint", "citizen",
                     "pollution report"],
            "en": "Anyone can report a sewer outfall into the river. The form takes a location and "
                  "photographs, and submissions feed the outfall record used in the assessment.",
            "hi": "कोई भी व्यक्ति नदी में गिरने वाले सीवर आउटफॉल की सूचना दे सकता है। फ़ॉर्म में स्थान "
                  "और फ़ोटो लिए जाते हैं, और प्रविष्टियाँ आकलन में प्रयुक्त आउटफॉल अभिलेख में जुड़ती हैं।",
            "links": [{"label": "Report Sewer Outfall", "to": "/report-sewer-outfall"}],
        },

        # ── Sources, metadata, access ────────────────────────────────────
        {
            "id": "data_sources",
            "tags": ["source", "sources", "origin", "provenance", "reliable", "citation",
                     "cite", "come from", "data come from", "who collected",
                     "where does the data", "collected"],
            "en": "The datasets come from the published basin reports and from the agencies behind "
                  "them, including the Central Water Commission, the state pollution control "
                  "boards, MPIDC and MSME records, census data and remote sensing products. Each "
                  "dataset page names its own source, and every report is listed in the Reports "
                  "section.",
            "hi": "डेटासेट प्रकाशित बेसिन रिपोर्टों और उनके पीछे की एजेंसियों से आते हैं, जिनमें केंद्रीय "
                  "जल आयोग, राज्य प्रदूषण नियंत्रण बोर्ड, MPIDC और MSME अभिलेख, जनगणना डेटा तथा "
                  "सुदूर संवेदन उत्पाद शामिल हैं। प्रत्येक डेटासेट पृष्ठ अपना स्रोत बताता है, और हर "
                  "रिपोर्ट, रिपोर्ट अनुभाग में सूचीबद्ध है।",
            "links": [{"label": "Reports", "to": "/reports"},
                      {"label": "API Catalog", "to": "/data/api-catalog"}],
        },
        {
            "id": "api",
            "tags": ["api", "endpoint", "json", "developer", "programmatic", "catalog", "rest",
                     "integrate"],
            "en": "Every dataset on the portal is served by a public read API, and the API Catalog "
                  "lists the endpoints with a short description of each. Map layers come back as "
                  "GeoJSON, the rest as JSON.",
            "hi": "पोर्टल का हर डेटासेट एक सार्वजनिक रीड API द्वारा उपलब्ध है, और API कैटलॉग में "
                  "प्रत्येक एंडपॉइंट का संक्षिप्त विवरण सूचीबद्ध है। मानचित्र परतें GeoJSON में और शेष "
                  "डेटा JSON में मिलता है।",
            "links": [{"label": "API Catalog", "to": "/data/api-catalog"}],
        },
        {
            "id": "metadata",
            "tags": ["metadata", "attribute", "attributes", "field", "fields", "unit", "units",
                     "column", "what does this mean"],
            "en": "Map features carry their full attribute record: click one and the panel lists "
                  "every field with its label and unit. Dataset pages show the parameter and "
                  "location names alongside the values, and the API Catalog documents the "
                  "structure each endpoint returns.",
            "hi": "मानचित्र फ़ीचर अपना पूरा विशेषता अभिलेख रखते हैं: किसी पर क्लिक करें और पैनल हर "
                  "फ़ील्ड को उसके लेबल और इकाई सहित दिखाएगा। डेटासेट पृष्ठ मानों के साथ मापदंड और "
                  "स्थान के नाम दिखाते हैं, और API कैटलॉग बताता है कि प्रत्येक एंडपॉइंट क्या लौटाता है।",
            "links": [{"label": "API Catalog", "to": "/data/api-catalog"}],
        },
        {
            "id": "visualisations",
            "tags": ["chart", "charts", "graph", "plot", "visualisation", "visualization", "table",
                     "compare", "trend"],
            "en": "Most datasets offer a chart and a table side by side, with dropdowns to pick a "
                  "parameter and a location. Spatial datasets are drawn on interactive maps you "
                  "can pan, zoom and click.",
            "hi": "अधिकांश डेटासेट चार्ट और तालिका साथ-साथ देते हैं, तथा मापदंड और स्थान चुनने के लिए "
                  "ड्रॉपडाउन होते हैं। स्थानिक डेटासेट इंटरैक्टिव मानचित्रों पर बनाए जाते हैं, जिन्हें आप "
                  "पैन, ज़ूम और क्लिक कर सकते हैं।",
            "links": [{"label": "Data", "to": "/data"}],
        },
        {
            "id": "contact",
            "tags": ["contact", "email", "reach", "support", "query", "question", "help desk"],
            "en": "Use the Contact page to reach the cNARMADA team at IIT Indore.",
            "hi": "आईआईटी इंदौर की सी-नर्मदा टीम से संपर्क करने के लिए संपर्क पृष्ठ का उपयोग करें।",
            "links": [{"label": "Contact Us", "to": "/contact"}],
        },
    ]



# Hindi keywords per entry. The site is bilingual, so the assistant needs
# Devanagari terms to match against; relying on the Hindi answer prose alone
# scores too low to clear the confidence floor.
GENERIC_WORDS = {
    "what", "how", "where", "who", "why", "when", "which", "is", "are", "the", "about",
    "क्या", "कैसे", "कहाँ", "कौन", "क्यों", "कब",
}

HI_TAGS = {
    "basin_overview": ["नर्मदा", "बेसिन", "नदी", "परिचय", "अमरकंटक", "उद्गम", "लंबाई"],
    "tributaries": ["सहायक", "नदियाँ", "धारा", "नेटवर्क", "नामित", "अनाम", "अपवाह"],
    "sub_basins": ["ऊपरी", "मध्य", "निचला", "क्षेत्र", "उपबेसिन"],
    "what_is_cnarmada": ["सीनर्मदा", "परियोजना", "केंद्र", "आईआईटी", "इंदौर", "गांधीनगर", "जल", "शक्ति"],
    "navigate_site": ["उपयोग", "खोजें", "मेन्यू", "अनुभाग", "सहायता", "शुरू", "कैसे उपयोग", "डेटासेट", "उपलब्ध"],
    "download_login": ["डाउनलोड", "एक्सपोर्ट", "लॉगिन", "साइन", "ओटीपी", "एक्सेल"],
    "languages": ["भाषा", "हिंदी", "अंग्रेज़ी", "अनुवाद"],
    "time_series": ["समय", "श्रृंखला", "प्रवाह", "जलस्तर", "स्टेशन", "जलविज्ञान"],
    "geospatial": ["भूस्थानिक", "मानचित्र", "परत", "परतें", "बाँध", "जलाशय", "भूउपयोग", "ऊँचाई"],
    "water_quality": ["जल", "गुणवत्ता", "मापदंड", "प्रदूषण", "सतही"],
    "ground_water": ["भूजल", "भूजल गुणवत्ता", "कुआँ", "जलभृत", "नाइट्रेट"],
    "biodiversity": ["जैव", "विविधता", "प्रजाति", "मछली", "पक्षी", "प्लवक", "वनस्पति"],
    "agriculture": ["कृषि", "फसल", "सिंचाई", "बागवानी", "खेती"],
    "solid_waste": ["ठोस", "अपशिष्ट", "कचरा", "औद्योगिक", "उद्योग", "प्लास्टिक"],
    "demography": ["जनसांख्यिकी", "जनसंख्या", "साक्षरता", "लिंगानुपात", "ज़िला", "जनगणना"],
    "gujarat": ["गुजरात", "तलछट", "भरूच"],
    "river_atlas": ["नदी", "एटलस", "केंद्र", "रेखा", "सीमा", "धाराक्रम"],
    "reports": ["रिपोर्ट", "दस्तावेज़", "प्रकाशन", "अध्ययन"],
    "sewer_outfall": ["सीवर", "आउटफॉल", "नाला", "शिकायत", "नागरिक"],
    "data_sources": ["स्रोत", "उत्पत्ति", "संदर्भ", "एजेंसी", "कहाँ से", "डेटा कहाँ"],
    "api": ["एपीआई", "एंडपॉइंट", "डेवलपर", "कैटलॉग"],
    "metadata": ["मेटाडेटा", "विशेषता", "फ़ील्ड", "इकाई", "स्तंभ"],
    "visualisations": ["चार्ट", "ग्राफ", "तालिका", "दृश्य", "तुलना", "रुझान"],
    "contact": ["संपर्क", "ईमेल", "सहायता", "पूछताछ"],
}

SUGGESTIONS = {
    "en": [
        "What is the Narmada basin?",
        "What datasets are available?",
        "How do I download data?",
        "Where does the data come from?",
        "What is in the River Atlas?",
    ],
    "hi": [
        "नर्मदा बेसिन क्या है?",
        "कौन-कौन से डेटासेट उपलब्ध हैं?",
        "डेटा कैसे डाउनलोड करें?",
        "डेटा कहाँ से आता है?",
        "नदी एटलस में क्या है?",
    ],
}

GREETING = {
    "en": "Namaste, I am Narmada Mitra. Ask me about the Narmada basin, the datasets on this "
          "portal, where they come from, or how to find something.",
    "hi": "नमस्ते, मैं नर्मदा मित्र हूँ। नर्मदा बेसिन, इस पोर्टल के डेटासेट, उनके स्रोत, या कुछ ढूँढने "
          "के तरीके के बारे में मुझसे पूछें।",
}

FALLBACK = {
    "en": "I could not match that to anything I know. I can help with the Narmada basin, the "
          "datasets on this portal, where the data comes from, and how to use the site. Try "
          "rephrasing your question, or open the User Manual.",
    "hi": "मैं इसे अपनी जानकारी से नहीं जोड़ सका। मैं नर्मदा बेसिन, इस पोर्टल के डेटासेट, डेटा के "
          "स्रोत और साइट के उपयोग में सहायता कर सकता हूँ। प्रश्न को दूसरे शब्दों में पूछें, या "
          "उपयोगकर्ता पुस्तिका खोलें।",
}


def main():
    facts = gather_facts()

    missing = [k for k, v in facts.items() if v in (None, 0)]
    if missing:
        print("Warning: these figures came back empty, check the datasets are present:")
        for k in missing:
            print(f"  - {k}")

    entries = []
    for entry in build_entries(facts):
        try:
            en = entry["en"].format(**facts)
            hi = entry["hi"].format(**facts)
        except (KeyError, ValueError) as exc:
            raise SystemExit(f"Entry {entry['id']!r} references an unknown figure: {exc}")
        entries.append({
            "id": entry["id"],
            "tags": entry["tags"],
            "tags_hi": HI_TAGS.get(entry["id"], []),
            "answer": {"en": en, "hi": hi},
            "links": entry.get("links", []),
        })

    # Validate before writing anything.
    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate entry ids in the knowledge base.")
    for e in entries:
        if not e["tags"]:
            raise SystemExit(f"Entry {e['id']!r} has no tags and could never be matched.")
        if not e["tags_hi"]:
            raise SystemExit(f"Entry {e['id']!r} has no Hindi tags; add it to HI_TAGS.")
        bare = [t for t in e["tags"] + e["tags_hi"]
                if t.lower() in GENERIC_WORDS]
        if bare:
            raise SystemExit(
                f"Entry {e['id']!r} uses bare question words as tags {bare}; they match "
                "every question and produce confident wrong answers. Use a phrase instead."
            )
        for lang in ("en", "hi"):
            if "{" in e["answer"][lang]:
                raise SystemExit(f"Entry {e['id']!r} ({lang}) still has an unfilled placeholder.")

    kb = {
        "name": "Narmada Mitra",
        "name_hi": "नर्मदा मित्र",
        "generated_on": date.today().isoformat(),
        "greeting": GREETING,
        "fallback": FALLBACK,
        "suggestions": SUGGESTIONS,
        "facts": facts,
        "entries": entries,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(kb, fh, ensure_ascii=False, indent=2)

    size = os.path.getsize(OUT_FILE) / 1024
    print(f"Wrote {OUT_FILE} — {len(entries)} entries, {size:.1f} KB")
    print("Figures used:")
    for k, v in facts.items():
        print(f"  {k:<22} {v}")


if __name__ == "__main__":
    main()
