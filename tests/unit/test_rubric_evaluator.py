from app.domain.rubric_evaluator import (
    EvidenceMatrixBuilder,
    PillarEvaluator,
    RubricEvaluator,
)
from app.models import Citation, ESGFact, RubricCriterion
from app.rubric import CLIMATE_RUBRIC_PATH, CRITERIA_DEFINITIONS, RUBRICS


def test_versioned_rubric_is_resolvable():
    assert CLIMATE_RUBRIC_PATH.name == "climate_disclosure_v1.yaml"
    assert CLIMATE_RUBRIC_PATH.is_file()


def test_rubric_evaluator_criterion_found():
    evaluator = RubricEvaluator()
    criterion = RubricCriterion(
        id="E_SCOPE_1",
        pillar="E",
        name="Scope 1 Emissions",
        description="Direct greenhouse gas emissions under operational control",
        required_fields=["scope_1", "unit", "year"],
        metric_units=["tCO2e", "mtco2e"],
        retrieval_keywords=["scope 1", "direct emissions"],
    )
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=12,
            excerpt="In 2024, our direct Scope 1 greenhouse gas emissions were 125,000 tCO2e across all facilities.",
        )
    ]

    result = evaluator.evaluate_criterion(criterion, citations)
    assert result.status == "found"
    assert result.criterion_id == "E_SCOPE_1"
    assert result.reporting_year == 2024
    assert result.confidence >= 0.9
    assert result.citation is not None
    assert result.citation.page == 12


def test_rubric_evaluator_criterion_partial_when_missing_year():
    evaluator = RubricEvaluator()
    criterion = RubricCriterion(
        id="E_SCOPE_1",
        pillar="E",
        name="Scope 1 Emissions",
        description="Direct greenhouse gas emissions under operational control",
        required_fields=["scope_1", "unit", "year"],
        metric_units=["tCO2e"],
        retrieval_keywords=["scope 1"],
    )
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=15,
            excerpt="The company reported Scope 1 emissions of 85,000 tCO2e without specifying the reporting year.",
        )
    ]

    result = evaluator.evaluate_criterion(criterion, citations)
    assert result.status == "partial"
    assert "year" in result.missing_fields


def test_rubric_evaluator_criterion_missing():
    evaluator = RubricEvaluator()
    criterion = RubricCriterion(
        id="E_SCOPE_1",
        pillar="E",
        name="Scope 1 Emissions",
        description="Direct greenhouse gas emissions under operational control",
        required_fields=["scope_1", "unit", "year"],
        metric_units=["tCO2e"],
        retrieval_keywords=["scope 1"],
    )
    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=5,
            excerpt="Our board consists of 12 directors who oversee executive compensation.",
        )
    ]

    result = evaluator.evaluate_criterion(criterion, citations)
    assert result.status == "missing"
    assert result.confidence == 0.0


def test_pillar_evaluator_and_matrix_builder():
    evaluator = RubricEvaluator()
    pillar_eval = PillarEvaluator(evaluator)
    matrix_builder = EvidenceMatrixBuilder(evaluator)

    citations = [
        Citation(
            chunk_id=1,
            document_id="doc1",
            document_name="Report.pdf",
            page=10,
            excerpt="In 2023, Scope 1 emissions were 50,000 tCO2e and Scope 2 was 20,000 tCO2e. Net-zero target set for 2050 against 2018 baseline.",
        )
    ]
    facts = [
        ESGFact(
            metric="scope_1_emissions",
            value=50000.0,
            unit="tCO2e",
            year=2023,
            confidence=0.95,
            document_id="doc1",
            page=10,
            evidence_text="Scope 1 emissions were 50,000 tCO2e",
        )
    ]

    pillar_res = pillar_eval.evaluate_pillar("E", RUBRICS["E"], citations)
    assert pillar_res.pillar == "E"
    assert pillar_res.disclosure_coverage > 0.0

    matrix = matrix_builder.build_evidence_matrix(citations, facts)
    assert len(matrix) == len(CRITERIA_DEFINITIONS)
    scope1_rows = [r for r in matrix if "scope_1" in r.criterion_id.lower()]
    assert len(scope1_rows) > 0
    assert scope1_rows[0].status == "found"
    assert scope1_rows[0].value == "50000.0"
