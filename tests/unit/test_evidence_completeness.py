from app.domain.evidence_completeness import EvidenceCompletenessGate
from app.models import Citation, ESGFact


def test_evidence_completeness_satisfied():
    gate = EvidenceCompletenessGate()
    facts = [
        ESGFact(
            metric="scope_1_emissions",
            value=125000.0,
            unit="tCO2e",
            year=2024,
            confidence=0.95,
        )
    ]
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=10,
            excerpt="Our Scope 1 greenhouse gas emissions were 125,000 tCO2e in 2024.",
        )
    ]

    res = gate.evaluate_requirement("scope_1", facts, citations)
    assert res.status == "satisfied"
    assert res.confidence >= 0.9
    assert len(res.matched_fact_ids) > 0


def test_evidence_completeness_partial_when_missing_year():
    gate = EvidenceCompletenessGate()
    facts = [
        ESGFact(
            metric="scope_1_emissions",
            value=125000.0,
            unit="tCO2e",
            year=None,  # Missing year!
            confidence=0.95,
        )
    ]
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=10,
            excerpt="Scope 1 greenhouse gas emissions reached 125,000 tCO2e without specifying reporting period.",
        )
    ]

    res = gate.evaluate_requirement("scope_1", facts, citations)
    assert res.status == "partial"
    assert "year" in res.missing_aspects


def test_evidence_completeness_baseline_requirement():
    gate = EvidenceCompletenessGate()
    facts = [
        ESGFact(
            metric="net_zero_target",
            value=2050.0,
            unit="year",
            year=2050,
            baseline_year=None,
        )
    ]
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=4,
            excerpt="We commit to achieve net-zero emissions by 2050.",
        )
    ]

    res = gate.evaluate_requirement("baseline", facts, citations)
    assert res.status in ("partial", "missing")
    assert "baseline" in res.missing_aspects or "not_found_in_evidence" in res.missing_aspects


def test_gate_check_batch():
    gate = EvidenceCompletenessGate()
    facts = [
        ESGFact(
            metric="scope_1_emissions",
            value=5000.0,
            unit="tCO2e",
            year=2024,
        ),
        ESGFact(
            metric="net_zero_target",
            value=2050.0,
            baseline_year=2019,
        ),
    ]
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=10,
            excerpt="Scope 1 emissions were 5000 tCO2e in 2024. Net-zero target by 2050 against 2019 baseline.",
        )
    ]

    summary = gate.check(["scope_1", "baseline"], facts, citations)
    assert "scope_1" in summary["satisfied"]
    assert "baseline" in summary["satisfied"]
    assert summary["status"] == "complete"
    assert len(summary["results"]) == 2
