"""Year and temporal context resolution for ESG metrics."""

import re
from datetime import datetime

# Năm báo cáo tối đa hợp lệ (cho phép trễ 1 năm so với lịch hiện tại; năm xa hơn thường là target).
_MAX_REPORTING_YEAR = datetime.now().year + 1


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

    # Loại bỏ năm cơ sở và các năm xa trong tương lai (thường là target year)
    reporting_candidates = [
        y for y in all_years if y != baseline_year and y <= _MAX_REPORTING_YEAR
    ]

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
