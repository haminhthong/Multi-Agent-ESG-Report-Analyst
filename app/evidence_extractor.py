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


class UnitNormalizer:
    """Bộ chuẩn hóa đơn vị đo lường và giá trị số học cho các chỉ số ESG."""

    # Hệ số quy đổi về tCO2e cho phát thải GHG
    GHG_CONVERSIONS: dict[str, float] = {
        "ktco2e": 1000.0,
        "thousand metric tons": 1000.0,
        "thousand metric tons co2e": 1000.0,
        "mtco2e": 1000000.0,
        "million metric tons": 1000000.0,
        "million metric tons co2e": 1000000.0,
        "million tons": 1000000.0,
        "mmt": 1000000.0,
        "tco2e": 1.0,
        "co2e": 1.0,
        "metric tons": 1.0,
        "metric tons co2e": 1.0,
        "tons": 1.0,
        "tonnes": 1.0,
        "tons co2e": 1.0,
    }

    # Hệ số quy đổi về MWh cho năng lượng
    ENERGY_CONVERSIONS: dict[str, float] = {
        "gwh": 1000.0,
        "mwh": 1.0,
        "kwh": 0.001,
        "tj": 277.778,
        "gj": 0.277778,
        "megawatts": 1.0,
        "mw": 1.0,
    }

    @classmethod
    def normalize(
        cls, metric: str, raw_value: float | str | None, raw_unit: str | None
    ) -> tuple[float | None, str | None]:
        """Chuẩn hóa giá trị định lượng và đơn vị đo lường về đơn vị chuẩn (Canonical Base Unit)."""
        if raw_value is None:
            return None, raw_unit

        try:
            val_float = float(raw_value) if isinstance(raw_value, (int, float, str)) else None
        except (ValueError, TypeError):
            return None, raw_unit

        if val_float is None:
            return None, raw_unit

        unit_str = raw_unit.lower().strip() if raw_unit else ""

        if "emission" in metric or "scope" in metric or "co2" in unit_str or "ton" in unit_str:
            if unit_str == "%":
                return val_float, "%"
            for pattern, factor in cls.GHG_CONVERSIONS.items():
                if pattern in unit_str:
                    return round(val_float * factor, 4), "tCO2e"
            return val_float, "tCO2e" if "emission" in metric else (raw_unit or "tCO2e")

        if (
            "renewable" in metric
            or "energy" in metric
            or any(u in unit_str for u in ["mwh", "gwh", "kwh", "tj", "gj", "mw"])
        ):
            if unit_str == "%":
                return val_float, "%"
            for pattern, factor in cls.ENERGY_CONVERSIONS.items():
                if pattern in unit_str:
                    canonical_u = "MW" if "mw" in pattern and "mwh" not in pattern else "MWh"
                    return round(val_float * factor, 4), canonical_u
            return val_float, raw_unit or "MWh"

        if "%" in unit_str or "diversity" in metric:
            return val_float, "%"

        return val_float, raw_unit


def extract_year_for_span(
    text: str, span_start: int, span_end: int, global_baseline: int | None = None
) -> tuple[int | None, int | None]:
    """Trích xuất năm báo cáo (reporting_year) và năm cơ sở (baseline_year) gắn với span cục bộ của metric.

    Ngăn chặn việc gán nhầm năm cơ sở (ví dụ '2019 baseline') làm năm báo cáo cho số liệu của năm 2024.
    """
    window_start = max(0, span_start - 120)
    window_end = min(len(text), span_end + 120)
    window = text[window_start:window_end]

    # Kiểm tra năm cơ sở cục bộ hoặc toàn cục
    baseline_match = re.search(
        r"\b(?:baseline|base year|from)\s*(20[12]\d)\b", window, re.IGNORECASE
    )
    baseline_year = int(baseline_match.group(1)) if baseline_match else global_baseline

    # Tìm tất cả năm 4 chữ số trong cửa sổ cục bộ
    all_years = [int(m.group(0)) for m in re.finditer(r"\b20[1234]\d\b", window)]

    # Loại bỏ năm cơ sở và các năm xa trong tương lai (> 2026 thường là target year)
    reporting_candidates = [y for y in all_years if y != baseline_year and y <= 2026]

    if reporting_candidates:
        metric_mid = (span_start + span_end) // 2
        # Chọn năm có vị trí gần span metric nhất
        best_year = min(
            reporting_candidates,
            key=lambda y: min(
                abs(m.start() + window_start - metric_mid) for m in re.finditer(str(y), window)
            ),
        )
        return best_year, baseline_year

    # Nếu trong window không có năm riêng, tìm trong toàn bộ text loại trừ baseline
    global_years = [
        int(m.group(0))
        for m in re.finditer(r"\b20[1234]\d\b", text)
        if int(m.group(0)) != baseline_year and int(m.group(0)) <= 2026
    ]
    reporting_year = global_years[0] if global_years else None
    return reporting_year, baseline_year


def extract_methodology(text: str, span_start: int, span_end: int) -> str | None:
    """Nhận diện phương pháp luận công bố (Market-based vs Location-based, Gross vs Net)."""
    window = text[max(0, span_start - 80) : min(len(text), span_end + 80)].lower()
    if "market-based" in window or "market based" in window:
        return "market-based"
    if "location-based" in window or "location based" in window:
        return "location-based"
    if "gross" in window:
        return "gross"
    if "net emissions" in window or "net-zero" in window:
        return "net"
    return None


class EvidenceExtractionAgent:
    """Năng lực Trích xuất Sự thật ESG có Cấu trúc (Structured ESG Fact Extraction).

    Nhiệm vụ:
    1. Quét các đoạn trích dẫn (Citations) được truy xuất để trích xuất số liệu ESG có cấu trúc.
    2. Chuẩn hóa đơn vị đo lường (tCO2e, %, MWh, etc.) và lưu vết song song raw và normalized.
    3. Xác định năm báo cáo cục bộ theo metric span (tránh nhầm năm cơ sở).
    4. Gắn citation nguồn (Provenance) và tính độ tin cậy trích xuất (Confidence Score).
    5. Phát hiện mâu thuẫn số liệu đa chiều (Multidimensional Conflict Detection).
    """

    @classmethod
    def extract_facts(cls, citations: list[Citation]) -> list[ESGFact]:
        """Trích xuất danh sách các đối tượng ESGFact từ tập citation."""
        facts: list[ESGFact] = []

        for cite in citations:
            text = cite.excerpt
            year_match = YEAR_PATTERN.search(text)
            doc_year = int(year_match.group(0)) if year_match else None

            # 1. Tìm năm cơ sở toàn văn bản
            baseline_match = re.search(
                r"\b(?:baseline|base year|from)\s*(20[12]\d)\b", text, re.IGNORECASE
            )
            global_baseline = int(baseline_match.group(1)) if baseline_match else None

            # 2. Quét các mẫu metric định lượng
            for metric_key, pattern in FACT_PATTERNS.items():
                for match in pattern.finditer(text):
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

                    # Xác định năm gắn cục bộ với span của metric
                    m_start, m_end = match.span()
                    local_year, baseline_year = extract_year_for_span(
                        text, m_start, m_end, global_baseline=global_baseline
                    )
                    methodology = extract_methodology(text, m_start, m_end)

                    # Chuẩn hóa đơn vị qua UnitNormalizer
                    norm_val, norm_unit = UnitNormalizer.normalize(
                        metric_key, numeric_val, raw_unit
                    )

                    has_unit = bool(raw_unit or norm_unit)
                    has_year = bool(local_year or doc_year)
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
                            year=local_year or doc_year,
                            baseline_year=baseline_year,
                            source=cite,
                            confidence=round(confidence, 2),
                            raw_value=numeric_val,
                            raw_unit=raw_unit.strip() if raw_unit else None,
                            normalized_value=norm_val,
                            normalized_unit=norm_unit,
                            methodology=methodology,
                        )
                    )

            # 3. Quét thêm cam kết Target / Net-zero nếu chưa được trích xuất
            # P0: Không bao giờ gán mặc định target_year = 2030 khi tài liệu không công bố!
            has_net_zero = bool(
                re.search(
                    r"\b(?:net[ -]?zero|carbon[ -]?neutral|zero\s*emissions)\b",
                    text,
                    re.IGNORECASE,
                )
            )
            if (TARGET_PATTERN.search(text) or has_net_zero) and not any(
                f.metric == "net_zero_target" and f.source == cite for f in facts
            ):
                target_year_m = re.search(r"\b20[2-5]\d\b", text)
                target_year = int(target_year_m.group(0)) if target_year_m else None
                facts.append(
                    ESGFact(
                        metric="net_zero_target",
                        value=target_year if target_year is not None else "disclosed",
                        unit="year" if target_year is not None else "commitment",
                        year=doc_year,
                        baseline_year=global_baseline,
                        source=cite,
                        confidence=0.88 if global_baseline else 0.75,
                        raw_value=target_year if target_year is not None else "disclosed",
                        raw_unit="year" if target_year is not None else "commitment",
                        normalized_value=float(target_year) if target_year is not None else None,
                        normalized_unit="year" if target_year is not None else "commitment",
                    )
                )

        return facts

    @classmethod
    def detect_conflicts(cls, facts: list[ESGFact]) -> list[EvidenceConflict]:
        """Phát hiện mâu thuẫn số liệu công bố đa chiều (Multidimensional Conflict Detection):

        Khóa phân nhóm đa chiều: (metric, methodology, year).
        Tránh báo động mâu thuẫn giả giữa Scope 2 location-based vs market-based hoặc Gross vs Net.
        So sánh trên normalized_value theo normalized_unit chuẩn.
        """
        conflicts: list[EvidenceConflict] = []
        groups: dict[tuple[str, str | None, int | None], list[ESGFact]] = {}

        for fact in facts:
            val = fact.normalized_value if fact.normalized_value is not None else fact.value
            if val is None or not isinstance(val, (int, float)):
                continue
            key = (fact.metric, fact.methodology, fact.year)
            groups.setdefault(key, []).append(fact)

        for (metric, methodology, year), fact_list in groups.items():
            if len(fact_list) < 2:
                continue

            values = [
                float(f.normalized_value if f.normalized_value is not None else f.value)  # type: ignore[arg-type]
                for f in fact_list
                if isinstance(
                    f.normalized_value if f.normalized_value is not None else f.value,
                    (int, float),
                )
            ]
            if not values:
                continue

            min_val, max_val = min(values), max(values)
            # Nếu chênh lệch tương đối lớn hơn 1%
            if min_val > 0 and (max_val - min_val) / min_val > 0.01:
                severity = "high" if (max_val - min_val) / min_val > 0.10 else "medium"
                meth_desc = f" [{methodology}]" if methodology else ""
                disclosures = [
                    {
                        "document": f.source.document_name if f.source else "unknown",
                        "page": f.source.page if f.source else 0,
                        "value": f.value,
                        "unit": f.unit,
                        "normalized_value": f.normalized_value,
                        "normalized_unit": f.normalized_unit,
                        "methodology": f.methodology,
                        "excerpt": f.source.excerpt[:150] if f.source else "",
                    }
                    for f in fact_list
                ]
                desc = (
                    f"Mâu thuẫn số liệu công bố cho chỉ tiêu '{metric}'{meth_desc} (năm {year or 'không xác định'}): "
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
