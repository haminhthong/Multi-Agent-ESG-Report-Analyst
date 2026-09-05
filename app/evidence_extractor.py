import re

from app.models import Citation, ESGFact, EvidenceConflict
from app.rubric import (
    TARGET_PATTERN,
    YEAR_PATTERN,
    normalize_number,
)

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


class EvidenceExtractionAgent:
    """Agent 4: Structured ESG Fact & Provenance Extraction Agent.

    Nhiệm vụ:
    1. Quét các đoạn trích dẫn (Citations) được truy xuất để trích xuất số liệu ESG có cấu trúc.
    2. Chuẩn hóa đơn vị đo lường (tCO2e, %, MWh, etc.) và định dạng số.
    3. Xác định năm báo cáo (Reporting Year) và năm cơ sở (Baseline Year).
    4. Gắn citation nguồn (Provenance) và tính độ tin cậy trích xuất (Confidence Score).
    """

    @classmethod
    def extract_facts(cls, citations: list[Citation]) -> list[ESGFact]:
        """Trích xuất danh sách các đối tượng ESGFact từ tập citation."""
        facts: list[ESGFact] = []

        for cite in citations:
            text = cite.excerpt
            year_match = YEAR_PATTERN.search(text)
            doc_year = int(year_match.group(0)) if year_match else None

            # 1. Tìm năm cơ sở (Baseline year)
            baseline_match = re.search(
                r"\b(?:baseline|base year|from)\s*(20[12]\d)\b", text, re.IGNORECASE
            )
            baseline_year = int(baseline_match.group(1)) if baseline_match else None

            # 2. Quét các mẫu metric định lượng
            for metric_key, pattern in FACT_PATTERNS.items():
                match = pattern.search(text)
                if match:
                    groups = [g for g in match.groups() if g is not None]
                    raw_val = groups[0] if groups else None
                    raw_unit = groups[1] if len(groups) > 1 else None
                    if not raw_val:
                        continue
                    if metric_key == "supplier_assessment" and not raw_unit:
                        raw_unit = "suppliers"
                    val_str = normalize_number(raw_val)

                    # Chuyển đổi giá trị số
                    try:
                        numeric_val = float(val_str.replace(",", ""))
                    except (ValueError, AttributeError):
                        numeric_val = val_str

                    # Đánh giá độ tin cậy
                    has_unit = bool(raw_unit)
                    has_year = bool(doc_year)
                    confidence = 0.70 + (0.15 if has_unit else 0.0) + (0.15 if has_year else 0.0)

                    facts.append(
                        ESGFact(
                            metric=metric_key,
                            value=numeric_val,
                            unit=raw_unit.strip()
                            if raw_unit
                            else (
                                "%" if "target" in metric_key or "diversity" in metric_key else None
                            ),
                            year=doc_year,
                            baseline_year=baseline_year,
                            source=cite,
                            confidence=round(confidence, 2),
                        )
                    )

            # 3. Quét thêm cam kết Target / Net-zero nếu chưa được trích xuất
            if TARGET_PATTERN.search(text) and not any(
                f.metric == "net_zero_target" and f.source == cite for f in facts
            ):
                target_year_m = re.search(r"\b20[2-5]\d\b", text)
                target_year = int(target_year_m.group(0)) if target_year_m else 2030
                facts.append(
                    ESGFact(
                        metric="net_zero_target",
                        value=target_year,
                        unit="year",
                        year=doc_year,
                        baseline_year=baseline_year,
                        source=cite,
                        confidence=0.88 if baseline_year else 0.75,
                    )
                )

        return facts

    @classmethod
    def detect_conflicts(cls, facts: list[ESGFact]) -> list[EvidenceConflict]:
        """Phát hiện mâu thuẫn số liệu (Conflicting Disclosures) giữa các trang hoặc tài liệu:

        Nếu cùng một chỉ tiêu (metric) và cùng năm báo cáo (year), nhưng giá trị công bố
        khác nhau quá 1%, hệ thống kích hoạt cảnh báo mâu thuẫn cho kiểm toán viên.
        """
        conflicts: list[EvidenceConflict] = []
        groups: dict[tuple[str, int | None], list[ESGFact]] = {}

        for fact in facts:
            if fact.value is None or not isinstance(fact.value, (int, float)):
                continue
            key = (fact.metric, fact.year)
            groups.setdefault(key, []).append(fact)

        for (metric, year), fact_list in groups.items():
            if len(fact_list) < 2:
                continue

            values = [f.value for f in fact_list if isinstance(f.value, (int, float))]
            if not values:
                continue

            min_val, max_val = min(values), max(values)
            # Nếu chênh lệch tương đối lớn hơn 1%
            if min_val > 0 and (max_val - min_val) / min_val > 0.01:
                severity = "high" if (max_val - min_val) / min_val > 0.10 else "medium"
                disclosures = [
                    {
                        "document": f.source.document_name if f.source else "unknown",
                        "page": f.source.page if f.source else 0,
                        "value": f.value,
                        "unit": f.unit,
                        "excerpt": f.source.excerpt[:150] if f.source else "",
                    }
                    for f in fact_list
                ]
                desc = (
                    f"Mâu thuẫn số liệu công bố cho chỉ tiêu '{metric}' (năm {year or 'không xác định'}): "
                    + " so với ".join(
                        f"trang {d['page']} ({d['value']} {d.get('unit') or ''})"
                        for d in disclosures
                    )
                )
                conflicts.append(
                    EvidenceConflict(
                        metric=metric,
                        year=year,
                        disclosures=disclosures,
                        severity=severity,
                        description=desc,
                    )
                )
                # Đánh dấu trạng thái conflict cho các fact
                for f in fact_list:
                    f.validation_status = "conflict"

        return conflicts
