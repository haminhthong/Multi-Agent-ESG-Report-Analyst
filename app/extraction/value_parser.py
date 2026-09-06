"""Value parsing and conversion helpers for ESG metrics."""

from app.rubric import normalize_number


def parse_numeric_value(raw_val: str) -> float | str:
    """Chuyển đổi chuỗi số có dấu phẩy hoặc chấm thành float hoặc giữ nguyên dạng chuỗi."""
    val_str = normalize_number(raw_val)
    try:
        return float(val_str.replace(",", ""))
    except (ValueError, AttributeError):
        return val_str
