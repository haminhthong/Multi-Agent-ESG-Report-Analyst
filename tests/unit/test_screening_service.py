from app.domain.screening import (
    SCREENING_RULES,
    GreenwashingScreeningService,
)
from app.models import Citation, ESGFact


def test_target_without_baseline_signal():
    service = GreenwashingScreeningService()
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=2,
            excerpt="We aim to achieve net zero greenhouse gas emissions by 2050.",
        )
    ]
    facts = []

    res = service.screen(citations, facts)
    assert res.risk_level in ("MEDIUM", "HIGH")
    assert any(s.code == "TARGET_NO_BASELINE" for s in res.signals)
    target_signal = next(s for s in res.signals if s.code == "TARGET_NO_BASELINE")
    assert target_signal.category == "target_credibility"
    assert target_signal.severity == "medium"
    assert "target_present AND baseline_absent" in target_signal.rule
    assert any("Baseline year" in s for s in res.target_credibility_signals)


def test_qualitative_only_and_explicit_no_assurance():
    service = GreenwashingScreeningService()
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=5,
            excerpt="Our environmental leadership is passionate and world-class. Note: this report has not been independently assured or audited.",
        )
    ]
    facts = []

    res = service.screen(citations, facts)
    assert any(s.code == "NO_QUANTITATIVE_METRICS" for s in res.signals)
    assert any(s.code == "EXPLICIT_NO_ASSURANCE" for s in res.signals)
    assert res.risk_level in ("MEDIUM", "HIGH")


def test_verified_targets_and_metrics_low_risk():
    service = GreenwashingScreeningService()
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=10,
            excerpt=(
                "In 2024, Scope 1 emissions were 15,000 tCO2e. "
                "Target is net-zero by 2050 compared against 2019 baseline year, with an interim milestone in 2030. "
                "The report received independent external assurance from KPMG."
            ),
        )
    ]
    facts = [
        ESGFact(
            metric="scope_1_emissions",
            value=15000.0,
            unit="tCO2e",
            year=2024,
            baseline_year=2019,
        )
    ]

    res = service.screen(citations, facts)
    assert res.risk_level == "LOW"
    assert not any(s.code == "TARGET_NO_BASELINE" for s in res.signals)
    assert not any(s.code == "NO_QUANTITATIVE_METRICS" for s in res.signals)
    assert any("External Assurance" in s for s in res.evidence_quality_signals)
