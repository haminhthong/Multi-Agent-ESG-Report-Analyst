from app.extraction.extractor import FactExtractor
from app.extraction.fact_validator import detect_conflicts
from app.extraction.unit_normalizer import UnitNormalizer
from app.extraction.value_parser import parse_numeric_value
from app.extraction.year_resolver import extract_methodology, extract_year_for_span
from app.models import Citation, ESGFact


def test_unit_normalizer():
    # GHG normalization
    val, unit = UnitNormalizer.normalize("scope_1_emissions", 120, "ktCO2e")
    assert val == 120000.0
    assert unit == "tCO2e"

    # Energy normalization
    val, unit = UnitNormalizer.normalize("renewable_energy", 5, "GWh")
    assert val == 5000.0
    assert unit == "MWh"

    # Percentage normalization
    val, unit = UnitNormalizer.normalize("diversity_percentage", "35.5", "%")
    assert val == 35.5
    assert unit == "%"


def test_year_resolver():
    text = "Against our 2019 baseline, Scope 1 emissions were 50,000 tCO2e in 2023."
    span_start = text.index("50,000")
    span_end = span_start + len("50,000")
    reporting_year, baseline_year = extract_year_for_span(text, span_start, span_end)

    assert reporting_year == 2023
    assert baseline_year == 2019


def test_methodology_resolver():
    text = "Scope 2 market-based emissions reached 25,000 tCO2e."
    meth = extract_methodology(text, 0, len(text))
    assert meth == "market-based"

    text2 = "Scope 2 location-based total."
    meth2 = extract_methodology(text2, 0, len(text2))
    assert meth2 == "location-based"


def test_value_parser():
    assert parse_numeric_value("1,250,000.50") == 1250000.5
    assert parse_numeric_value("invalid_val") == "invalid_val"


def test_fact_extractor_and_conflict():
    c1 = Citation(
        chunk_id=1,
        document_id="doc1",
        document_name="doc.pdf",
        page=1,
        excerpt="In 2023, Scope 1 direct emissions reached 100,000 tCO2e.",
    )
    c2 = Citation(
        chunk_id=2,
        document_id="doc1",
        document_name="doc.pdf",
        page=2,
        excerpt="In 2023, Scope 1 direct emissions reached 200,000 tCO2e.",
    )

    facts = FactExtractor.extract_facts([c1, c2])
    assert len(facts) >= 2
    assert all(isinstance(f, ESGFact) for f in facts)

    conflicts = detect_conflicts(facts)
    assert len(conflicts) == 1
    assert conflicts[0].metric == "scope_1_emissions"
    assert conflicts[0].severity == "high"
