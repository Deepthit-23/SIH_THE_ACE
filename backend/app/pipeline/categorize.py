"""Keyword-derived project categorisation.

The source `Category` field is ~97% "Normal/Others" and carries no signal, so we
derive a working category from the free-text work description. Keyword lists were
tuned against the actual token frequencies in the 2026-09-05 exports (e.g.
"light"/"mast"/"solar" is the single largest theme, then road, school, water,
community hall, drainage).

Rules are evaluated in order; first match wins. Order matters -- more specific /
higher-cost-driver themes are checked before generic ones.
"""

import re

# (category, [substrings]) -- matched against a lowercased description.
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    (
        "street_lighting",
        [
            "street light", "streetlight", "high mast", "highmast", " mast ",
            "mast light", "solar light", "solar street", "led light", "solar panel",
            "light pole", "lighting", "flood light", "focus light",
        ],
    ),
    (
        "water_supply",
        [
            "hand pump", "handpump", "hand-pump", "borewell", "bore well", "tubewell",
            "tube well", "water tank", "overhead tank", "water supply", "pipeline",
            "pipe line", "water tanker", "ro plant", "water purifier", "drinking water",
            "submersible", "water pump",
        ],
    ),
    (
        "drainage",
        ["drain", "drainage", "nala", "naala", "nali", "sewer", "sewerage", "soak pit"],
    ),
    (
        "road_paving",
        [
            "road", "cc road", "rcc road", "pcc road", "interlocking", "paver",
            "paver block", "paving", "footpath", "foot path", "pathway", "culvert",
            "pulia", "sadak", "khadanja", "cement concrete road", "black top", "bitumen",
        ],
    ),
    (
        "boundary_wall",
        [
            "boundary wall", "compound wall", "protection wall", "retaining wall",
            "chardiwari", "chaar diwari", "fencing", "railing",
        ],
    ),
    (
        "sanitation_toilet",
        ["toilet", "urinal", "sulabh", "sauchalay", "shauchalay", "bathroom"],
    ),
    (
        "sports_recreation",
        [
            "open gym", "open air gym", "gymnasium", "playground", "play ground",
            "stadium", "sports", "khel maidan", "park ", "children park",
        ],
    ),
    (
        "school_education",
        [
            "school", "college", "class room", "classroom", "library", "anganwadi",
            "aanganwadi", "hostel", "vidyalaya", "education", "smart class",
            "university", "iti ", "study",
        ],
    ),
    (
        "health_facility",
        [
            "hospital", "health centre", "health center", "phc", "chc", "dispensary",
            "sub centre", "sub center", "ambulance", "clinic",
            # "Ayushman Arogya Mandir" / "Aarogya Mandir" are health & wellness
            # centres -- must be matched here (before "mandir" below), see audit.
            "aarogya", "arogya", "ayushman", "aayushman", "wellness centre",
            "wellness center", "health and wellness", "hwc",
        ],
    ),
    (
        "religious_cremation",
        [
            "mandir", "temple", "masjid", "mosque", "church", "gurudwara", "gurdwara",
            "crematorium", "cremation", "shamshan", "samshan", "kabristan", "graveyard",
            "burial", "antim sanskar",
        ],
    ),
    (
        "community_hall",
        [
            "community hall", "community centre", "community center", "community building",
            "barat ghar", "baraat ghar", "marriage hall", "milan kendra", "bhawan",
            "bhavan", "panchayat ghar", "panchayat bhawan", "chaupal", "chabutra",
            "shed", "platform", "hall",
        ],
    ),
]

DEFAULT_CATEGORY = "other"
_ALLOWED = {c for c, _ in CATEGORY_RULES} | {DEFAULT_CATEGORY}

_ws_re = re.compile(r"\s+")


def _normalise(text: str) -> str:
    # Pad with spaces so " mast " / "park " style keywords with boundaries match.
    return " " + _ws_re.sub(" ", text.lower().strip()) + " "


def derive_category(description: str | None) -> str:
    """Map a free-text work description to a working category bucket."""
    if not description or not str(description).strip():
        return DEFAULT_CATEGORY
    text = _normalise(str(description))
    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in text:
                return category
    return DEFAULT_CATEGORY


def all_categories() -> list[str]:
    return [c for c, _ in CATEGORY_RULES] + [DEFAULT_CATEGORY]
