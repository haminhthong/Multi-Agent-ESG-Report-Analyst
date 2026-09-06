"""Backward compatibility facade for app.extraction."""

from app.extraction import (
    _MAX_REPORTING_YEAR,
    FACT_PATTERNS,
    EvidenceExtractionAgent,
    FactExtractor,
    UnitNormalizer,
    detect_conflicts,
    extract_methodology,
    extract_year_for_span,
    parse_numeric_value,
)

__all__ = [
    "EvidenceExtractionAgent",
    "FactExtractor",
    "UnitNormalizer",
    "detect_conflicts",
    "extract_year_for_span",
    "extract_methodology",
    "parse_numeric_value",
    "FACT_PATTERNS",
    "_MAX_REPORTING_YEAR",
]
