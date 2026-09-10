"""Pipeline con để trích xuất fact ESG có cấu trúc."""

from app.extraction.extractor import FactExtractor
from app.extraction.fact_validator import detect_conflicts
from app.extraction.metric_detector import FACT_PATTERNS
from app.extraction.unit_normalizer import UnitDefinition, UnitNormalizer
from app.extraction.value_parser import parse_numeric_value
from app.extraction.year_resolver import (
    _MAX_REPORTING_YEAR,
    extract_methodology,
    extract_year_for_span,
)

__all__ = [
    "FACT_PATTERNS",
    "_MAX_REPORTING_YEAR",
    "FactExtractor",
    "UnitDefinition",
    "UnitNormalizer",
    "detect_conflicts",
    "extract_methodology",
    "extract_year_for_span",
    "parse_numeric_value",
]
