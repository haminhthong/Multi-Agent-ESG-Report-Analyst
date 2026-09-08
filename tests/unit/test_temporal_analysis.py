from app.domain.temporal_analysis import TemporalAnalyzer
from app.facts.repository import FactRepository
from app.models import ESGFact
from app.store import Store


def test_temporal_alias_uses_highest_confidence_fact_and_reports_gaps():
    analyzer = TemporalAnalyzer()
    result = analyzer.analyze(
        company="Acme",
        metric="Scope 1",
        facts=[
            ESGFact(
                metric="scope_1_emissions",
                value=500.0,
                year=2020,
                confidence=0.95,
            ),
            ESGFact(
                metric="scope_1_emissions",
                value=999.0,
                year=2022,
                confidence=0.20,
            ),
            ESGFact(
                metric="scope 1",
                value=450.0,
                year=2022,
                confidence=0.90,
            ),
        ],
    )

    assert [point.year for point in result.timeline] == [2020, 2022]
    assert [point.value for point in result.timeline] == [500.0, 450.0]
    assert result.reporting_consistency == "gaps_detected"
    assert result.consistency_issues == ["Thiếu dữ liệu cho các năm: 2021"]
    assert result.baseline_to_current_change == -10.0


def test_temporal_store_query_accepts_metric_alias(tmp_path):
    store = Store(tmp_path / "temporal-alias.db")
    store.add_document(
        "doc_2023",
        "Acme_2023.pdf",
        [(1, "Acme Scope 1 emissions were 400 tCO2e in 2023.")],
        company="Acme",
        year=2023,
    )
    FactRepository(store).save_facts(
        [
            ESGFact(
                metric="scope_1_emissions",
                value=400.0,
                unit="tCO2e",
                year=2023,
                reporting_year=2023,
                company="Acme",
                document_id="doc_2023",
                confidence=0.9,
            )
        ]
    )

    result = TemporalAnalyzer().run_temporal_analysis("Acme", store, metric="Scope 1")

    assert len(result.timeline) == 1
    assert result.timeline[0].value == 400.0
    assert result.reporting_consistency == "limited_data"
