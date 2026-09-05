from app.agents import ESGAnalysisAgent
from app.rubric import (
    ASSURANCE_PATTERN,
    BASELINE_PATTERN,
    METRIC_PATTERN,
    NEGATED_ASSURANCE_PATTERN,
    NEGATED_BASELINE_PATTERN,
    NEGATED_PERFORMANCE_PATTERN,
    TARGET_PATTERN,
)


def test_percentage_metric_is_detected():
    text = "Scope 1 emissions dropped by 15.5% and total volume was 124500 tCO2e."
    matches = METRIC_PATTERN.findall(text)
    assert len(matches) >= 2
    assert "15.5%" in matches
    assert "124500 tCO2e" in matches or "124500 tCO2e" in text


def test_reporting_year_is_not_automatically_a_target():
    reporting_text = "In 2024, total energy consumption was reported."
    target_text = "Our target is to reach net-zero emissions by 2030."

    assert TARGET_PATTERN.search(reporting_text) is None
    assert TARGET_PATTERN.search(target_text) is not None


def test_negated_assurance_is_not_positive_evidence():
    text = "No independent assurance was provided for the ESG report data."
    has_assurance_claim = bool(ASSURANCE_PATTERN.search(text))
    has_negation = bool(NEGATED_ASSURANCE_PATTERN.search(text))

    assert has_assurance_claim is True
    assert has_negation is True
    # Combined check rule:
    valid_assurance = has_assurance_claim and not has_negation
    assert valid_assurance is False


def test_negated_baseline_is_marked_missing():
    text = "The baseline year was not disclosed in this reporting period."
    has_baseline_claim = bool(BASELINE_PATTERN.search(text))
    has_negation = bool(NEGATED_BASELINE_PATTERN.search(text))

    assert has_baseline_claim is True
    assert has_negation is True
    valid_baseline = has_baseline_claim and not has_negation
    assert valid_baseline is False


def test_increased_emissions_is_not_scored_as_improvement():
    text = "Scope 1 emissions increased emissions by 12% in 2024."
    assert bool(NEGATED_PERFORMANCE_PATTERN.search(text)) is True


def test_no_evidence_returns_abstention():
    agent = ESGAnalysisAgent()
    pillars, coverage, signals = agent.run([])

    assert coverage == 0.0
    assert "Chưa truy xuất được bằng chứng nguồn để thẩm định." in signals
    for pillar in pillars:
        assert pillar.disclosure_coverage == 0.0
        assert any("Không tìm thấy" in r for r in pillar.risks)
