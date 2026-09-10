from app.models import Citation, ESGFact
from app.services.esg_analysis_service import ESGAnalysisService


def test_analysis_service_delegates_to_domain_components():
    service = ESGAnalysisService()
    citations = [
        Citation(
            chunk_id=1,
            document_id="d1",
            document_name="Boeing_2023.pdf",
            page=15,
            excerpt="The company commits to reduce absolute Scope 1 emissions by 40% by 2030 compared to 2019 baseline year.",
        )
    ]
    facts = [
        ESGFact(
            metric="scope_1_emissions",
            value=40.0,
            unit="%",
            year=2030,
            baseline_year=2019,
        )
    ]

    # Kiểm tra luồng đánh giá chính.
    pillars, overall_cov, signals = service.run(citations)
    assert len(pillars) == 3
    assert overall_cov >= 0.0
    assert len(signals) > 0

    # Kiểm tra sàng lọc tín hiệu rủi ro công bố.
    res = service.screen_greenwashing_signals(citations, facts)
    assert any("Baseline Year" in s for s in res.target_credibility_signals)

    # Kiểm tra ma trận bằng chứng theo phạm vi mặc định.
    matrix = service.build_scoped_evidence_matrix(citations, facts, [])
    assert len(matrix) > 0
