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
    f["unnamed_km"] = coverage.get("source_length_km", 0)
    f["unnamed_overview_order"] = coverage.get("overview_min_order", 0)
    bands = ((unnamed.get("tiles") or {}).get("bands")) or []
    f["unnamed_detail_zoom"] = min((b.get("min_zoom", 0) for b in bands), default=0)

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
            "gu": "નર્મદા દ્વીપકલ્પીય ભારતની સૌથી મોટી પશ્ચિમ-વાહિની નદી છે. તે મધ્ય "
                  "પ્રદેશમાં મૈકાલ પર્વતમાળાના અમરકંટકમાંથી નીકળે છે અને મધ્ય પ્રદેશ, "
                  "મહારાષ્ટ્ર તથા ગુજરાતમાંથી પસાર થઈને પશ્ચિમમાં અરબી સમુદ્રના ખંભાતના "
                  "અખાત સુધી વહે છે. નદી એટલસમાં પ્રકાશિત કેન્દ્રરેખાની લંબાઈ "
                  "{centreline_km:,.0f} કિમી છે.",
            "links": [{"label": "River Atlas", "to": "/river-atlas"}],
        },
        {
            "id": "tributaries",
            "tags": ["tributary", "tributaries", "stream", "streams", "network", "named", "unnamed",
                     "drainage", "how many rivers"],
            "en": "The River Atlas carries {named_streams:,} named tributaries and the complete "
                  "unnamed stream network: all {unnamed_served:,} reaches ({unnamed_km:,.0f} km), "
                  "with original geometry, drawn at every zoom level. Click any stream to see its "
                  "record. To click the smallest streams, zoom in to level "
                  "{unnamed_detail_zoom} or closer.",
            "hi": "नदी एटलस में {named_streams:,} नामित सहायक नदियाँ और पूरा अनाम धारा नेटवर्क शामिल है: "
                  "सभी {unnamed_served:,} खंड ({unnamed_km:,.0f} किमी), मूल ज्यामिति के साथ, हर ज़ूम "
                  "स्तर पर। किसी भी धारा पर क्लिक करके उसका विवरण देखें। सबसे छोटी धाराओं पर क्लिक "
                  "करने के लिए ज़ूम स्तर {unnamed_detail_zoom} या उससे अधिक पर जाएँ।",
            "gu": "નદી એટલસમાં {named_streams:,} નામિત સહાયક નદીઓ અને સંપૂર્ણ અનામી ધારા "
                  "નેટવર્ક છે: બધા {unnamed_served:,} ખંડ ({unnamed_km:,.0f} કિમી), મૂળ "
                  "ભૂમિતિ સાથે, દરેક ઝૂમ સ્તરે દોરેલા. કોઈપણ ધારા પર ક્લિક કરીને તેનો "
                  "રેકોર્ડ જુઓ. સૌથી નાની ધારાઓ પર ક્લિક કરવા માટે ઝૂમ સ્તર "
                  "{unnamed_detail_zoom} અથવા તેથી નજીક જાઓ.",
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
            "gu": "પોર્ટલ પર બેસિનને ત્રણ ઝોનમાં જોવામાં આવે છે: ઉપરનું, મધ્ય અને નીચેનું "
                  "નર્મદા. ભૂગર્ભ જળ ગુણવત્તા ઉપરના અને મધ્ય ઝોન માટે પ્રકાશિત છે, અને "
                  "જૈવવિવિધતા {bio_zones} બેસિન ઝોનમાં ગોઠવાયેલી છે.",
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
            "gu": "સી-નર્મદા એટલે નર્મદા નદી બેસિન વ્યવસ્થાપન અભ્યાસ કેન્દ્ર, જે જળ શક્તિ "
                  "મંત્રાલય હેઠળ IIT ઇન્દોર અને IIT ગાંધીનગરની સંયુક્ત પહેલ છે. તેનું "
                  "કાર્ય નર્મદા માટેની સ્થિતિ મૂલ્યાંકન અને વ્યવસ્થાપન યોજના (CAMP) છે, "
                  "જેનો હેતુ નદીના પારિસ્થિતિક સ્વાસ્થ્યની પુનઃસ્થાપના અને ટકાઉ જળ સંસાધન "
                  "વ્યવસ્થાપનને સમર્થન આપવાનો છે.",
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
            "gu": "ડેટાસેટ માટે નેવિગેશન બારમાં ડેટા મેનૂ ખોલો: સમય શ્રેણી, ભૂ-અવકાશી, "
                  "ભૂગર્ભ જળ ગુણવત્તા, કૃષિ, ઘન કચરો અને ઔદ્યોગિક પ્રોફાઇલ, બેસિન વસ્તી "
                  "વિષયક, જૈવવિવિધતા, API સૂચિ અને વપરાશકર્તા માર્ગદર્શિકા. નદી એટલસનું "
                  "પોતાનું ટેબ છે, અને અહેવાલો વિભાગમાં પ્રકાશિત દસ્તાવેજો છે.",
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
            "gu": "જોવું, ચાર્ટ બનાવવું અને નકશા પર જોવું બધા માટે ખુલ્લું છે. ડેટાસેટ "
                  "ડાઉનલોડ કરવા માટે સાઇન ઇન કરેલું @iiti.ac.in ખાતું જરૂરી છે, તેથી "
                  "એક્સપોર્ટ બટન દબાવવાથી એક વખતના પાસવર્ડનો પ્રોમ્પ્ટ ખૂલે છે. આ તપાસ "
                  "સર્વર પર થાય છે, બ્રાઉઝરમાં નહીં.",
            "links": [{"label": "Data", "to": "/data"}],
        },
        {
            "id": "languages",
            "tags": ["language", "hindi", "english", "gujarati", "translate", "भाषा", "ભાષા"],
            "en": "The whole portal is available in English, Hindi and Gujarati. Use the language "
                  "switcher in the header; your choice is remembered on this device.",
            "hi": "पूरा पोर्टल अंग्रेज़ी, हिंदी और गुजराती में उपलब्ध है। हेडर में भाषा स्विचर का उपयोग "
                  "करें; आपका चयन इस डिवाइस पर सहेजा जाता है।",
            "gu": "સંપૂર્ણ પોર્ટલ અંગ્રેજી, હિન્દી અને ગુજરાતીમાં ઉપલબ્ધ છે. હેડરમાં ભાષા "
                  "સ્વિચરનો ઉપયોગ કરો; તમારી પસંદગી આ ઉપકરણ પર યાદ રાખવામાં આવે છે.",
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
            "gu": "સમય શ્રેણીમાં {stations_total} દેખરેખ સ્ટેશન છે, જેમાંથી "
                  "{stations_mapped} ના કોઓર્ડિનેટ ઉપલબ્ધ છે. {stations_flow} માં "
                  "પ્રવાહના અને {stations_level} માં જળ સ્તરના રેકોર્ડ છે. શ્રેણીનો ચાર્ટ "
                  "જોવા એક સ્ટેશન પસંદ કરો.",
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
            "gu": "ભૂ-અવકાશી ડેટા મુખ્ય નકશો છે. તેમાં બેસિન સીમા, કેન્દ્રરેખા, નામિત "
                  "નેટવર્ક, દેખરેખ સ્ટેશનો, જિલ્લાઓ, બંધ, જળાશયો અને STP કવરેજના સ્તરો "
                  "છે, સાથે ઊંચાઈ, ભૂમિ ઉપયોગ, વરસાદ, સરેરાશ તાપમાન અને ભૂઆકૃતિશાસ્ત્રના "
                  "રાસ્ટર ઓવરલે પણ. વિશેષતાઓ જોવા કોઈપણ ફીચર પર ક્લિક કરો.",
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
            "gu": "સપાટી જળ ગુણવત્તા {wq_locations} સ્થળો માટે {wq_parameters} માપદંડો પર "
                  "પ્રકાશિત છે, સાથે દસ વર્ષનું તુલનાત્મક દૃશ્ય પણ છે.",
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
            "gu": "ભૂગર્ભ જળ ગુણવત્તા ઉપરના અને મધ્ય બેસિન માટે, માપદંડ અને સ્થળ અનુસાર "
                  "પ્રકાશિત છે, વર્ષ-વાર મૂલ્યો સાથે, જેથી કોઈ સ્ટેશનને સમય સાથે જોઈ "
                  "શકાય.",
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
            "gu": "જૈવવિવિધતામાં {species_total:,} પ્રજાતિ નોંધો વૃક્ષ સ્વરૂપે ગોઠવાયેલી "
                  "છે: બેસિન ઝોન, પછી જૂથ, પછી વર્ગ, પછી પ્રજાતિ. જૂથોમાં પાદપ પ્લવક, "
                  "પ્રાણી પ્લવક, મેક્રોબેન્થોસ, મેક્રોફાઇટ, માછલીઓ, પક્ષીઓ, સરીસૃપ અને "
                  "ઉભયજીવી સમાવિષ્ટ છે.",
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
            "gu": "કૃષિ વિભાગમાં સમગ્ર બેસિનમાં પાક અને સિંચિત ક્ષેત્રની સાથે ફળ બગીચા "
                  "અને બાગાયતના નકશા છે.",
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
            "gu": "ઘન કચરો અને ઔદ્યોગિક પ્રોફાઇલમાં જોખમી, બાયોમેડિકલ, પ્લાસ્ટિક, "
                  "ઇલેક્ટ્રોનિક અને બાંધકામ કચરા સહિતની શ્રેણીઓ આવરી લેવાઈ છે, સાથે "
                  "ઔદ્યોગિક પ્રોફાઇલ: લાલ/નારંગી/લીલું વર્ગીકરણ, {industrial_parks} "
                  "ઔદ્યોગિક પાર્ક અને {monitoring_stations} રીઅલ-ટાઇમ દેખરેખ સ્ટેશન.",
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
            "gu": "બેસિન વસ્તી વિષયકમાં જિલ્લા-વાર વસ્તી, લિંગ પ્રમાણ, સાક્ષરતા, કાર્યબળ "
                  "અને અનુસૂચિત જાતિ/જનજાતિ હિસ્સા કોરોપ્લેથ સ્તરો તરીકે દર્શાવાયા છે, "
                  "જેમને તમે બદલી શકો છો.",
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
            "gu": "ગુજરાત પ્રદેશના ડેટાસેટ પોતાના સ્પષ્ટ રીતે અલગ વિભાગોમાં પ્રકાશિત છે: "
                  "{guj_stations} સ્ટેશનોની {guj_parameters} માપદંડો પર પાણીની ગુણવત્તા, "
                  "DEP22 કચરા અહેવાલ, અને CWC કાંપ ડેટા.",
            "links": [{"label": "Time Series Data", "to": "/data/time-series"}],
        },
        {
            "id": "river_atlas",
            "tags": ["river atlas", "atlas", "centre line", "center line", "basin boundary",
                     "stream order", "strahler"],
            "en": "River Atlas draws {atlas_layers} layers: the district boundaries, the basin "
                  "boundary, the Narmada centre line, the named stream network and the unnamed "
                  "stream network. Pick a district to filter the layers to it, and click any "
                  "feature to see every attribute recorded for it.",
            "hi": "नदी एटलस में {atlas_layers} परतें हैं: जिला सीमाएँ, बेसिन सीमा, नर्मदा केंद्र रेखा, "
                  "नामित धारा नेटवर्क और अनाम धारा नेटवर्क। परतों को किसी जिले तक सीमित करने के लिए "
                  "जिला चुनें, और किसी भी फ़ीचर पर क्लिक करके उसकी सभी दर्ज विशेषताएँ देखें।",
            "gu": "નદી એટલસમાં {atlas_layers} સ્તરો દોરવામાં આવે છે: જિલ્લા સીમાઓ, બેસિન "
                  "સીમા, નર્મદા કેન્દ્રરેખા, નામિત ધારા નેટવર્ક અને અનામી ધારા નેટવર્ક. સ્તરોને "
                  "એક જિલ્લા સુધી સીમિત કરવા જિલ્લા પસંદ કરો, અને કોઈપણ ફીચર પર ક્લિક કરીને "
                  "તેના માટે નોંધાયેલી દરેક વિશેષતા જુઓ.",
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
            "gu": "અહેવાલો વિભાગમાં {reports_total} પ્રકાશિત દસ્તાવેજો PDF સ્વરૂપે છે, જે "
                  "બેસિનના સ્થિતિ મૂલ્યાંકન અને સહાયક અભ્યાસોને આવરી લે છે.",
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
            "gu": "કોઈપણ વ્યક્તિ નદીમાં પડતા ગટર આઉટફોલની જાણ કરી શકે છે. ફોર્મમાં સ્થળ "
                  "અને ફોટા લેવાય છે, અને રજૂઆતો મૂલ્યાંકનમાં વપરાતા આઉટફોલ રેકોર્ડમાં "
                  "જોડાય છે.",
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
            "gu": "ડેટાસેટ પ્રકાશિત બેસિન અહેવાલો અને તેમની પાછળની એજન્સીઓમાંથી આવે છે, "
                  "જેમાં કેન્દ્રીય જળ આયોગ, રાજ્ય પ્રદૂષણ નિયંત્રણ બોર્ડ, MPIDC અને MSME "
                  "રેકોર્ડ, વસ્તી ગણતરી ડેટા તથા સુદૂર સંવેદન ઉત્પાદનો સમાવિષ્ટ છે. દરેક "
                  "ડેટાસેટ પૃષ્ઠ પોતાનો સ્રોત દર્શાવે છે, અને દરેક અહેવાલ અહેવાલો "
                  "વિભાગમાં સૂચિબદ્ધ છે.",
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
            "gu": "પોર્ટલનો દરેક ડેટાસેટ એક સાર્વજનિક રીડ API દ્વારા ઉપલબ્ધ છે, અને API "
                  "સૂચિમાં દરેક એન્ડપોઇન્ટનું સંક્ષિપ્ત વર્ણન સૂચિબદ્ધ છે. નકશા સ્તરો "
                  "GeoJSON માં અને બાકીનો ડેટા JSON માં મળે છે.",
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
            "gu": "નકશા ફીચર પોતાનો સંપૂર્ણ વિશેષતા રેકોર્ડ રાખે છે: કોઈ એક પર ક્લિક કરો "
                  "અને પેનલ દરેક ક્ષેત્રને તેના લેબલ અને એકમ સાથે દર્શાવશે. ડેટાસેટ "
                  "પૃષ્ઠો મૂલ્યોની સાથે માપદંડ અને સ્થળના નામ દર્શાવે છે, અને API સૂચિ "
                  "જણાવે છે કે દરેક એન્ડપોઇન્ટ શું પરત કરે છે.",
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
            "gu": "મોટાભાગના ડેટાસેટ ચાર્ટ અને કોષ્ટક સાથે-સાથે આપે છે, તથા માપદંડ અને "
                  "સ્થળ પસંદ કરવા ડ્રોપડાઉન હોય છે. અવકાશી ડેટાસેટ ઇન્ટરેક્ટિવ નકશા પર "
                  "દોરવામાં આવે છે, જેમને તમે પેન, ઝૂમ અને ક્લિક કરી શકો છો.",
            "links": [{"label": "Data", "to": "/data"}],
        },
        {
            "id": "contact",
            "tags": ["contact", "email", "reach", "support", "query", "question", "help desk"],
            "en": "Use the Contact page to reach the cNARMADA team at IIT Indore.",
            "hi": "आईआईटी इंदौर की सी-नर्मदा टीम से संपर्क करने के लिए संपर्क पृष्ठ का उपयोग करें।",
            "gu": "IIT ઇન્દોરની સી-નર્મદા ટીમનો સંપર્ક કરવા સંપર્ક પૃષ્ઠનો ઉપયોગ કરો.",
            "links": [{"label": "Contact Us", "to": "/contact"}],
        },
    ]



# Hindi and Gujarati keywords per entry. The site is trilingual, so the
# assistant needs Devanagari and Gujarati terms to match against; relying on
# the translated answer prose alone scores too low to clear the confidence
# floor.
GENERIC_WORDS = {
    "what", "how", "where", "who", "why", "when", "which", "is", "are", "the", "about",
    "क्या", "कैसे", "कहाँ", "कौन", "क्यों", "कब",
    "શું", "કેવી", "ક્યાં", "કોણ", "કેમ", "ક્યારે",
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

GU_TAGS = {
    "basin_overview": ["નર્મદા", "બેસિન", "નદી", "પરિચય", "અમરકંટક", "ઉદ્ગમ", "લંબાઈ"],
    "tributaries": ["સહાયક", "નદીઓ", "ધારા", "નેટવર્ક", "નામિત", "અનામી", "નિકાલ"],
    "sub_basins": ["ઉપરનું", "મધ્ય", "નીચેનું", "ઝોન", "ઉપબેસિન"],
    "what_is_cnarmada": ["સીનર્મદા", "પરિયોજના", "કેન્દ્ર", "આઈઆઈટી", "ઇન્દોર", "ગાંધીનગર", "જળ", "શક્તિ"],
    "navigate_site": ["ઉપયોગ", "શોધો", "મેનૂ", "વિભાગ", "સહાય", "શરૂ", "કેવી રીતે ઉપયોગ", "ડેટાસેટ", "ઉપલબ્ધ"],
    "download_login": ["ડાઉનલોડ", "એક્સપોર્ટ", "લૉગિન", "સાઇન", "ઓટીપી", "એક્સેલ"],
    "languages": ["ભાષા", "ગુજરાતી", "હિન્દી", "અંગ્રેજી", "અનુવાદ"],
    "time_series": ["સમય", "શ્રેણી", "પ્રવાહ", "જળસ્તર", "સ્ટેશન", "જળવિજ્ઞાન"],
    "geospatial": ["ભૂઅવકાશી", "નકશો", "નકશા", "સ્તર", "સ્તરો", "બંધ", "જળાશય", "ભૂઉપયોગ",
                   "ઊંચાઈ"],
    "water_quality": ["પાણી", "ગુણવત્તા", "માપદંડ", "પ્રદૂષણ", "સપાટી"],
    "ground_water": ["ભૂગર્ભ", "ભૂગર્ભ જળ", "કૂવો", "જલભૃત", "નાઇટ્રેટ"],
    "biodiversity": ["જૈવ", "વિવિધતા", "પ્રજાતિ", "માછલી", "પક્ષી", "પ્લવક", "વનસ્પતિ"],
    "agriculture": ["કૃષિ", "પાક", "સિંચાઈ", "બાગાયત", "ખેતી"],
    "solid_waste": ["ઘન", "કચરો", "અપશિષ્ટ", "ઔદ્યોગિક", "ઉદ્યોગ", "પ્લાસ્ટિક"],
    "demography": ["વસ્તી વિષયક", "વસ્તી", "સાક્ષરતા", "લિંગ પ્રમાણ", "જિલ્લા", "વસ્તી ગણતરી"],
    "gujarat": ["ગુજરાત", "કાંપ", "ભરૂચ"],
    "river_atlas": ["નદી", "એટલસ", "કેન્દ્ર", "રેખા", "સીમા", "ધારાક્રમ"],
    "reports": ["અહેવાલ", "દસ્તાવેજ", "પ્રકાશન", "અભ્યાસ"],
    "sewer_outfall": ["ગટર", "આઉટફોલ", "નાળું", "ફરિયાદ", "નાગરિક"],
    "data_sources": ["સ્રોત", "ઉત્પત્તિ", "સંદર્ભ", "એજન્સી", "ક્યાંથી", "ડેટા ક્યાંથી"],
    "api": ["એપીઆઈ", "એન્ડપોઇન્ટ", "ડેવલપર", "સૂચિ"],
    "metadata": ["મેટાડેટા", "વિશેષતા", "ક્ષેત્ર", "એકમ", "સ્તંભ"],
    "visualisations": ["ચાર્ટ", "ગ્રાફ", "કોષ્ટક", "દૃશ્ય", "તુલના", "વલણ"],
    "contact": ["સંપર્ક", "ઈમેલ", "સહાય", "પૂછપરછ"],
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
    "gu": [
        "નર્મદા બેસિન શું છે?",
        "કયા કયા ડેટાસેટ ઉપલબ્ધ છે?",
        "ડેટા કેવી રીતે ડાઉનલોડ કરવો?",
        "ડેટા ક્યાંથી આવે છે?",
        "નદી એટલસમાં શું છે?",
    ],
}

GREETING = {
    "en": "Namaste, I am Narmada Mitra. Ask me about the Narmada basin, the datasets on this "
          "portal, where they come from, or how to find something.",
    "hi": "नमस्ते, मैं नर्मदा मित्र हूँ। नर्मदा बेसिन, इस पोर्टल के डेटासेट, उनके स्रोत, या कुछ ढूँढने "
          "के तरीके के बारे में मुझसे पूछें।",
    "gu": "નમસ્તે, હું નર્મદા મિત્ર છું. નર્મદા બેસિન, આ પોર્ટલના ડેટાસેટ, તેમના સ્રોત, અથવા કંઈક "
          "શોધવાની રીત વિશે મને પૂછો.",
}

FALLBACK = {
    "en": "I could not match that to anything I know. I can help with the Narmada basin, the "
          "datasets on this portal, where the data comes from, and how to use the site. Try "
          "rephrasing your question, or open the User Manual.",
    "hi": "मैं इसे अपनी जानकारी से नहीं जोड़ सका। मैं नर्मदा बेसिन, इस पोर्टल के डेटासेट, डेटा के "
          "स्रोत और साइट के उपयोग में सहायता कर सकता हूँ। प्रश्न को दूसरे शब्दों में पूछें, या "
          "उपयोगकर्ता पुस्तिका खोलें।",
    "gu": "હું તેને મારી જાણકારી સાથે જોડી શક્યો નથી. હું નર્મદા બેસિન, આ પોર્ટલના ડેટાસેટ, ડેટાના "
          "સ્રોત અને સાઇટના ઉપયોગમાં મદદ કરી શકું છું. પ્રશ્ન બીજા શબ્દોમાં પૂછો, અથવા વપરાશકર્તા "
          "માર્ગદર્શિકા ખોલો.",
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
            gu = entry["gu"].format(**facts)
        except (KeyError, ValueError) as exc:
            raise SystemExit(f"Entry {entry['id']!r} references an unknown figure: {exc}")
        entries.append({
            "id": entry["id"],
            "tags": entry["tags"],
            "tags_hi": HI_TAGS.get(entry["id"], []),
            "tags_gu": GU_TAGS.get(entry["id"], []),
            "answer": {"en": en, "hi": hi, "gu": gu},
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
        if not e["tags_gu"]:
            raise SystemExit(f"Entry {e['id']!r} has no Gujarati tags; add it to GU_TAGS.")
        bare = [t for t in e["tags"] + e["tags_hi"] + e["tags_gu"]
                if t.lower() in GENERIC_WORDS]
        if bare:
            raise SystemExit(
                f"Entry {e['id']!r} uses bare question words as tags {bare}; they match "
                "every question and produce confident wrong answers. Use a phrase instead."
            )
        for lang in ("en", "hi", "gu"):
            if "{" in e["answer"][lang]:
                raise SystemExit(f"Entry {e['id']!r} ({lang}) still has an unfilled placeholder.")

    kb = {
        "name": "Narmada Mitra",
        "name_hi": "नर्मदा मित्र",
        "name_gu": "નર્મદા મિત્ર",
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
