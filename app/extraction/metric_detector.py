"""Bộ nhận diện metric bằng regex cho dữ liệu ESG."""

import re

# Các mẫu bóc tách số liệu chuyên sâu theo từng chỉ tiêu ESG
FACT_PATTERNS = {
    "scope_1_emissions": re.compile(
        r"(?:scope\s*1\b[^0-9]{0,60}?)(\d+(?:[,.]\d+)*)\s*(%|tco2e|co2e|ktco2e|mtco2e|metric\s*tons?(?:\s*co2e)?|tons?|tonnes?)?",
        re.IGNORECASE,
    ),
    "scope_2_emissions": re.compile(
        r"(?:scope\s*2\b[^0-9]{0,60}?)(\d+(?:[,.]\d+)*)\s*(%|tco2e|co2e|ktco2e|mtco2e|metric\s*tons?(?:\s*co2e)?|tons?|tonnes?)?",
        re.IGNORECASE,
    ),
    "scope_3_emissions": re.compile(
        r"(?:scope\s*3\b[^0-9]{0,60}?)(\d+(?:[,.]\d+)*)\s*(%|tco2e|co2e|ktco2e|mtco2e|metric\s*tons?(?:\s*co2e)?|tons?|tonnes?)?",
        re.IGNORECASE,
    ),
    "net_zero_target": re.compile(
        r"\b(?:net[ -]?zero|carbon[ -]?neutral|zero\s*emissions)\b.{0,60}?\b(20[2-5]\d)\b",
        re.IGNORECASE,
    ),
    "renewable_energy": re.compile(
        r"(?:operated\s*(?:over\s*)?|capacity\s*of\s*|renewable\s*(?:generation|energy|electricity)?|wind\s*and\s*solar|clean\s*energy)[^0-9$]{0,50}?"
        r"(\d+(?:[,.]\d+)*)\s*(%|megawatts?|mw|mwh|gwh|gj|tj)\b",
        re.IGNORECASE,
    ),
    "work_safety": re.compile(
        r"(?:total\s*recordable\s*incident\s*rate|trir|safety\s*training|injury\s*rate|fatalit(?:y|ies)|incidents?)[^0-9]{0,60}?"
        r"(\d+(?:[,.]\d+)*)\s*(hours?|employees?|fatalities|incidents?|%)?",
        re.IGNORECASE,
    ),
    "workforce_size": re.compile(
        r"(?:covered|workforce|total\s*employees?|headcount)[^0-9]{0,30}?(\d+(?:[,.]\d+)*)\s*(employees?)?",
        re.IGNORECASE,
    ),
    "diversity_percentage": re.compile(
        r"(?:female|women|gender\s*diversity|minorities)[^0-9]{0,30}?(\d+(?:[,.]\d+)*)\s*%",
        re.IGNORECASE,
    ),
    "supplier_assessment": re.compile(
        r"(?:(\d+(?:[,.]\d+)*)\s*(?:of\s*major\s*)?suppliers?\s*(?:were\s*)?(?:rated|evaluated|assessed)|"
        r"(?:suppliers?\s*(?:were\s*)?(?:rated|evaluated|assessed)|supplier\s*assessments?)[^0-9]{0,40}?(\d+(?:[,.]\d+)*))\s*(suppliers?|%)?",
        re.IGNORECASE,
    ),
}
