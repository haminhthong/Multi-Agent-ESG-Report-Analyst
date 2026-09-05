from pathlib import Path

from app.agents import SupervisorAgent
from app.store import Store


def test_analysis_has_page_citations(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "Example.pdf",
        [
            (
                7,
                "Scope 1 emissions fell 12% in 2024. Board audit and worker safety training covered 500 employees.",
            )
        ],
    )
    result = SupervisorAgent(store).run(
        "Assess climate emissions safety employee governance audit", 5, mode="audit"
    )
    assert result.citations[0].page == 7
    assert result.citations[0].validated is True
    assert {p.pillar for p in result.pillars} == {"E", "S", "G"}
    assert result.disclosure_coverage >= 0.0
    assert all(0.0 <= p.disclosure_coverage <= 100.0 for p in result.pillars)
    assert all(0.0 <= p.evidence_quality <= 100.0 for p in result.pillars)
    assert result.limitations


def test_document_filter(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document("a", "A.pdf", [(1, "carbon emissions were reduced")])
    store.add_document("b", "B.pdf", [(2, "carbon emissions increased")])
    result = SupervisorAgent(store).run("carbon emissions", 5, ["b"], mode="qa")
    assert result.citations and all(c.document_id == "b" for c in result.citations)


def test_greenwashing_target_without_baseline(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1", "Claims.pdf", [(3, "We aspire to achieve net-zero emissions by 2030.")]
    )
    result = SupervisorAgent(store).run("Review climate target and greenwashing", 5, mode="audit")
    assert any("năm cơ sở" in signal for signal in result.screening_signals)
