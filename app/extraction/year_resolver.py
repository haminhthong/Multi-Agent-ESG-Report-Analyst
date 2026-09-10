"""Xác định năm báo cáo và ngữ cảnh thời gian cho metric ESG."""

import re
from datetime import UTC, datetime

# Năm báo cáo tối đa hợp lệ (cho phép trễ 1 năm so với lịch hiện tại; năm xa hơn thường là target).
_MAX_REPORTING_YEAR = datetime.now(UTC).year + 1


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
        r"(?:\b(?:baseline|base year|from)\s*(20[12]\d)\b|\b(20[12]\d)\s*(?:baseline|base year)\b)",
        window,
        re.IGNORECASE,
    )
    baseline_year = (
        int(baseline_match.group(1) or baseline_match.group(2))
        if baseline_match
        else global_baseline
    )

    # Tìm tất cả năm 4 chữ số trong cửa sổ cục bộ
    all_years = [int(m.group(0)) for m in re.finditer(r"\b20[1234]\d\b", window)]

    # Loại bỏ năm cơ sở và các năm xa trong tương lai (thường là năm mục tiêu).
    reporting_candidates = [y for y in all_years if y != baseline_year and y <= _MAX_REPORTING_YEAR]

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

    # Nếu cửa sổ cục bộ không có năm riêng, tìm trong toàn văn bản và loại trừ năm cơ sở.
    global_years = [
        int(m.group(0))
        for m in re.finditer(r"\b20[1234]\d\b", text)
        if int(m.group(0)) != baseline_year and int(m.group(0)) <= _MAX_REPORTING_YEAR
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


def resolve_target_year(
    text: str,
    target_span: tuple[int, int] | None = None,
    reporting_year: int | None = None,
    baseline_year: int | None = None,
) -> int | None:
    """Xác định năm mục tiêu (target year) của cam kết Net-Zero / Climate Target.

    Ngăn chặn việc gán nhầm năm báo cáo (ví dụ 'In 2024, we reaffirmed our net-zero target for 2050')
    làm năm mục tiêu.
    """
    if target_span:
        span_start, span_end = target_span
        window_start = max(0, span_start - 120)
        window_end = min(len(text), span_end + 120)
        window = text[window_start:window_end]
        target_mid = (span_start + span_end) // 2
    else:
        window = text
        window_start = 0
        m = re.search(
            r"\b(?:target|net[ -]?zero|carbon[ -]?neutral|goal|commitment)\b", text, re.IGNORECASE
        )
        target_mid = (m.start() + m.end()) // 2 if m else len(text) // 2

    min_year = (reporting_year + 1) if reporting_year else 2025

    candidate_matches = list(re.finditer(r"\b20[2-5]\d\b", window))
    if not candidate_matches:
        candidate_matches = list(re.finditer(r"\b20[2-5]\d\b", text))
        window_start = 0

    valid_candidates = []
    for m in candidate_matches:
        year = int(m.group(0))
        if baseline_year and year == baseline_year:
            continue
        if year < min_year:
            continue
        distance = abs(m.start() + window_start - target_mid)
        valid_candidates.append((distance, year))

    if valid_candidates:
        valid_candidates.sort(key=lambda x: x[0])
        return valid_candidates[0][1]

    future_years = [
        int(m.group(0))
        for m in re.finditer(r"\b20[2-5]\d\b", text)
        if int(m.group(0)) >= min_year and int(m.group(0)) != baseline_year
    ]
    return future_years[0] if future_years else None
