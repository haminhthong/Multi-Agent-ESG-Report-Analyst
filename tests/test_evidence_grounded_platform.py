from pathlib import Path

from app.domain.rubric_evaluator import RubricEvaluator
from app.extraction.extractor import FactExtractor
from app.extraction.fact_validator import detect_conflicts
from app.extraction.unit_normalizer import UnitNormalizer
from app.extraction.year_resolver import extract_year_for_span
from app.models import Citation, RubricCriterion
from app.pipeline import ESGPipeline
from app.store import Store


def test_target_without_year_is_none_not_2030():
    """P0: Khi tài liệu chỉ cam kết Net-Zero mà không có năm đích, target_year phải là None (hoặc 'disclosed'), KHÔNG được bịa 2030."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Vague_Target.pdf",
        page=5,
        excerpt="The corporation commits to achieving net-zero carbon emissions across our global footprint.",
    )
    facts = FactExtractor.extract_facts([cite])
    nz_fact = next((f for f in facts if f.metric == "net_zero_target"), None)
    assert nz_fact is not None
    # Giá trị không bao giờ là 2030 khi 2030 không xuất hiện trong text!
    assert nz_fact.value != 2030
    assert nz_fact.normalized_value is None or nz_fact.value == "disclosed"


def test_target_with_explicit_year_preserves_year():
    """Khi tài liệu công bố rõ năm 2030 hoặc 2050, hệ thống trích xuất đúng năm đó."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Explicit_Target.pdf",
        page=6,
        excerpt="We aim to achieve net-zero carbon emissions by 2045.",
    )
    facts = FactExtractor.extract_facts([cite])
    nz_fact = next((f for f in facts if f.metric == "net_zero_target"), None)
    assert nz_fact is not None
    assert nz_fact.value == 2045


def test_unit_normalizer_ghg_conversions():
    """P1: UnitNormalizer chuẩn hóa đúng các bậc đơn vị phát thải GHG về tCO2e."""
    # ktCO2e -> nhân 1.000 tCO2e.
    norm_val, norm_unit = UnitNormalizer.normalize("scope_1_emissions", 12.5, "ktCO2e")
    assert norm_val == 12500.0
    assert norm_unit == "tCO2e"

    # MtCO2e -> nhân 1.000.000 tCO2e.
    norm_val, norm_unit = UnitNormalizer.normalize("scope_2_emissions", 1.2, "MtCO2e")
    assert norm_val == 1200000.0
    assert norm_unit == "tCO2e"

    # tCO2e chuẩn -> giữ nguyên giá trị.
    norm_val, norm_unit = UnitNormalizer.normalize("scope_3_emissions", 500000.0, "tCO2e")
    assert norm_val == 500000.0
    assert norm_unit == "tCO2e"


def test_unit_normalizer_energy_conversions():
    """P1: UnitNormalizer chuẩn hóa năng lượng về MWh."""
    # GWh -> nhân 1.000 MWh.
    norm_val, norm_unit = UnitNormalizer.normalize("renewable_energy", 34.0, "GWh")
    assert norm_val == 34000.0
    assert norm_unit == "MWh"

    # MWh -> giữ nguyên
    norm_val, norm_unit = UnitNormalizer.normalize("renewable_energy", 5000.0, "MWh")
    assert norm_val == 5000.0
    assert norm_unit == "MWh"


def test_metric_span_year_association():
    """P1: Phân định rạch ròi giữa năm cơ sở (2019 baseline) và năm báo cáo (2024 reporting year)."""
    text = "Compared with our 2019 baseline, Scope 1 greenhouse gas emissions in 2024 were 800,000 tCO2e."
    reporting_yr, baseline_yr = extract_year_for_span(text, 35, 90, global_baseline=2019)
    assert reporting_yr == 2024
    assert baseline_yr == 2019


def test_multidimensional_conflict_detection():
    """P1: Scope 2 Market-based và Location-based không bị báo động conflict giả."""
    cite_mkt = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Report.pdf",
        page=20,
        excerpt="In 2023, market-based Scope 2 emissions were 400,000 tCO2e.",
    )
    cite_loc = Citation(
        chunk_id=2,
        document_id="d1",
        document_name="Report.pdf",
        page=21,
        excerpt="In 2023, location-based Scope 2 emissions were 850,000 tCO2e.",
    )
    facts = FactExtractor.extract_facts([cite_mkt, cite_loc])
    conflicts = detect_conflicts(facts)

    # Khác phương pháp luận nên không được coi là conflict.
    assert len(conflicts) == 0


def test_genuine_conflict_detected():
    """Mâu thuẫn cùng metric, cùng methodology, cùng năm nhưng khác số liệu thì phải cảnh báo."""
    cite1 = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Report.pdf",
        page=10,
        excerpt="In 2023, Scope 1 direct emissions reached 100,000 tCO2e.",
    )
    cite2 = Citation(
        chunk_id=2,
        document_id="d1",
        document_name="Report.pdf",
        page=50,
        excerpt="In 2023, Scope 1 direct emissions reached 190,000 tCO2e.",
    )
    facts = FactExtractor.extract_facts([cite1, cite2])
    conflicts = detect_conflicts(facts)

    assert len(conflicts) > 0
    assert conflicts[0].metric == "scope_1_emissions"


def test_criterion_required_fields_completeness():
    """P0: Tiêu chí chỉ có keyword mà thiếu trường định lượng bắt buộc chỉ được đánh PARTIAL chứ không phải FOUND."""
    # Tiêu chí Scope 1+2 yêu cầu: scope_1_value, scope_2_value, unit, reporting_year
    crit = RubricCriterion(
        id="E_GHG_SCOPE_1_2",
        pillar="E",
        name="Scope 1 & 2",
        description="Emissions",
        retrieval_keywords=["scope 1", "scope 2", "emissions"],
        required_fields=["scope_1_value", "scope_2_value", "unit", "reporting_year"],
        metric_units=["tCO2e"],
    )

    # Đoạn chỉ có Scope 1 mà thiếu Scope 2
    cite_partial = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Doc.pdf",
        page=4,
        excerpt="In 2023, Scope 1 emissions were 250,000 tCO2e.",
    )

    evaluator = RubricEvaluator()
    res = evaluator.evaluate_criterion(crit, [cite_partial])

    # Phải là partial vì thiếu scope_2_value
    assert res.status == "partial"
    assert "scope_2_value" in res.missing_fields
    assert "scope_1_value" in res.matched_fields


def test_criterion_aggregates_across_citations():
    """Scope 1 và Scope 2 ở hai trang khác nhau phải gộp thành found (không dừng ở citation đầu)."""
    crit = RubricCriterion(
        id="E_GHG_SCOPE_1_2",
        pillar="E",
        name="Scope 1 & 2",
        description="Emissions",
        retrieval_keywords=["scope 1", "scope 2", "emissions"],
        required_fields=["scope_1_value", "scope_2_value", "unit", "reporting_year"],
        metric_units=["tCO2e"],
    )
    cite_s1 = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Doc.pdf",
        page=4,
        excerpt="In 2023, Scope 1 emissions were 250,000 tCO2e.",
    )
    cite_s2 = Citation(
        chunk_id=2,
        document_id="d1",
        document_name="Doc.pdf",
        page=5,
        excerpt="In 2023, Scope 2 emissions were 180,000 tCO2e.",
    )
    evaluator = RubricEvaluator()
    res = evaluator.evaluate_criterion(crit, [cite_s1, cite_s2])
    assert res.status == "found"
    assert not res.missing_fields
    assert "scope_1_value" in res.matched_fields
    assert "scope_2_value" in res.matched_fields


def test_evidence_completeness_gate(tmp_path: Path):
    """P1: Evidence Completeness Gate ghi nhận các trường thiếu vào limitations."""
    store = Store(tmp_path / "test_gate.db")
    store.add_document(
        "d1",
        "Doc.pdf",
        [(1, "Our company reduced emissions by 10% compared to baseline.")],
    )
    pipeline = ESGPipeline(store)
    # Truy vấn hỏi về target và assurance (nhưng doc không có assurance)
    result = pipeline.run("Review climate target and external assurance", mode="qa")
    assert result.evidence_completeness is not None
    # Nếu thiếu bằng chứng, limitations phải chứa thông báo rõ ràng.
    if result.evidence_completeness.get("status") == "incomplete":
        assert any("MISSING_EVIDENCE" in lim for lim in result.limitations)
