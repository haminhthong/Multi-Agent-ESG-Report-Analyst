from pathlib import Path

from app.extraction.extractor import FactExtractor
from app.extraction.fact_validator import detect_conflicts
from app.extraction.year_resolver import resolve_target_year
from app.facts.repository import FactRepository
from app.ingestion.layout_parser import LayoutBlock, LayoutParser
from app.models import Citation, ESGFact
from app.store import Store


def test_resolve_target_year_proximity_and_exclusion():
    """resolve_target_year phải tìm năm gần cụm target nhất và loại trừ reporting_year / baseline_year."""
    # Trường hợp 1: năm 2024 xác nhận lại mục tiêu cho năm 2050.
    text1 = "In 2024, the corporation proudly reaffirmed our net-zero target for 2050."
    target_idx1 = text1.index("target")
    resolved1 = resolve_target_year(
        text1, (target_idx1, target_idx1 + 6), reporting_year=2024, baseline_year=2018
    )
    assert resolved1 == 2050

    # Trường hợp 2: so với mốc cơ sở 2019, đạt net-zero vào năm 2040.
    text2 = "Against our 2019 baseline, we aim to achieve net-zero carbon emissions by 2040."
    target_idx2 = text2.index("net-zero")
    resolved2 = resolve_target_year(
        text2, (target_idx2, target_idx2 + 8), reporting_year=2023, baseline_year=2019
    )
    assert resolved2 == 2040

    # Trường hợp 3: không có năm mục tiêu trong tương lai.
    text3 = (
        "The company is committed to aggressive emissions reductions in our manufacturing plants."
    )
    target_idx3 = text3.index("reductions")
    resolved3 = resolve_target_year(text3, (target_idx3, target_idx3 + 10), reporting_year=2024)
    assert resolved3 is None


def test_cross_company_conflict_isolation():
    """Khác công ty thì không bao giờ bị coi là conflicting disclosures."""
    c_boeing = Citation(
        chunk_id=1,
        document_id="boeing-2024",
        company="Boeing",
        document_name="Boeing_2024.pdf",
        document_year=2024,
        page=10,
        excerpt="In 2024, Scope 1 direct emissions reached 450,000 tCO2e.",
    )
    c_alcoa = Citation(
        chunk_id=2,
        document_id="alcoa-2024",
        company="Alcoa",
        document_name="Alcoa_2024.pdf",
        document_year=2024,
        page=12,
        excerpt="In 2024, Scope 1 direct emissions reached 120,000 tCO2e.",
    )

    facts_boeing = FactExtractor.extract_facts([c_boeing])
    facts_alcoa = FactExtractor.extract_facts([c_alcoa])

    all_facts = facts_boeing + facts_alcoa
    conflicts = detect_conflicts(all_facts)

    # Do khác công ty ("Boeing" và "Alcoa"), không có conflict.
    assert len(conflicts) == 0


def test_fact_repository_and_store_integration(tmp_path: Path):
    """FactRepository quản lý bảng esg_facts, lưu trữ và truy vấn chuỗi thời gian, so sánh công ty."""
    db_path = tmp_path / "test_facts.db"
    store = Store(db_path)
    store.add_document("doc1", "Doc1.pdf", [(1, "Text")], company="EcoCorp", year=2024)

    repo = FactRepository(store)

    fact1 = ESGFact(
        metric="scope_1_emissions",
        raw_value="100,000",
        raw_unit="tCO2e",
        normalized_value=100000.0,
        normalized_unit="tCO2e",
        reporting_year=2023,
        methodology="direct",
        confidence=0.95,
        page=1,
        chunk_id="c1",
        company="EcoCorp",
        document_id="doc1",
    )
    fact2 = ESGFact(
        metric="scope_1_emissions",
        raw_value="90,000",
        raw_unit="tCO2e",
        normalized_value=90000.0,
        normalized_unit="tCO2e",
        reporting_year=2024,
        methodology="direct",
        confidence=0.96,
        page=2,
        chunk_id="c2",
        company="EcoCorp",
        document_id="doc1",
    )

    saved_count = repo.save_facts([fact1, fact2])
    assert saved_count == 2

    # Truy vấn chuỗi thời gian.
    series = repo.get_temporal_series("EcoCorp", "scope_1_emissions")
    assert len(series) == 2
    assert series[0].reporting_year == 2023
    assert series[1].reporting_year == 2024
    assert series[0].value == 100000.0
    assert series[0].raw_value == "100,000"
    assert series[0].normalized_value == 100000.0
    assert series[1].normalized_value == 90000.0

    # Truy vấn giữa nhiều công ty.
    comp_facts = repo.get_cross_company_facts(["EcoCorp"], "scope_1_emissions")
    assert len(comp_facts) == 2
    assert any(f.normalized_value == 90000.0 for f in comp_facts)


def test_layout_parser_structure():
    """Kiểm tra LayoutBlock và khả năng hoạt động của LayoutParser."""
    assert LayoutParser.is_pymupdf_available() is True

    # Tạo thử một LayoutBlock
    block = LayoutBlock(
        document_id="doc-test",
        page=1,
        block_id="p1_b1",
        block_type="heading",
        bbox=[50.0, 100.0, 400.0, 130.0],
        section="1. Overview",
        text="1. Overview of Sustainability",
        extraction_method="native_layout",
        quality_score=0.98,
    )
    assert block.bbox == [50.0, 100.0, 400.0, 130.0]
    assert block.block_type == "heading"
    assert block.extraction_method == "native_layout"
