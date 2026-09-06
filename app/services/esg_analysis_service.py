"""ESG analysis service: orchestrates domain evaluators under clean dependency injection."""

from __future__ import annotations

from app.domain.company_comparison import CompanyComparator, CompanyComparisonService
from app.domain.evidence_matrix import EvidenceMatrixBuilder
from app.domain.rubric_evaluator import PillarEvaluator, RubricEvaluator
from app.domain.screening import GreenwashingScreeningService, ScreeningService
from app.domain.temporal_analysis import TemporalAnalyzer
from app.llm import LLMClient
from app.models import (
    Citation,
    CompanyComparisonResult,
    CriterionResult,
    ESGFact,
    EvidenceMatrixRow,
    GreenwashingScreeningResult,
    PillarResult,
    RubricCriterion,
    TemporalAnalysisResult,
)
from app.rubric import PillarRubric
from app.store import Store


class ESGAnalysisService:
    """Orchestrate domain evaluators (Rubric, Matrix, Screening, Temporal, Comparison)."""

    def __init__(
        self,
        rubric_evaluator: RubricEvaluator | None = None,
        pillar_evaluator: PillarEvaluator | None = None,
        screening_service: GreenwashingScreeningService | None = None,
        matrix_builder: EvidenceMatrixBuilder | None = None,
        temporal_analyzer: TemporalAnalyzer | None = None,
        comparison_service: CompanyComparisonService | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.rubric_evaluator = rubric_evaluator or RubricEvaluator()
        self.pillar_evaluator = pillar_evaluator or PillarEvaluator(self.rubric_evaluator)
        self.screening_service = screening_service or GreenwashingScreeningService()
        self.matrix_builder = matrix_builder or EvidenceMatrixBuilder(self.rubric_evaluator)
        self.temporal_analyzer = temporal_analyzer or TemporalAnalyzer()
        self.comparison_service = comparison_service or CompanyComparisonService(
            self.rubric_evaluator, self.matrix_builder
        )
        self.llm = llm_client

    def run(self, citations: list[Citation]) -> tuple[list[PillarResult], float, list[str]]:
        """Phân tích các trụ cột E, S, G và sàng lọc các tín hiệu cần kiểm tra."""
        pillars, overall_coverage = self.pillar_evaluator.evaluate_all(citations)
        if not citations:
            return pillars, 0.0, ["Chưa truy xuất được bằng chứng nguồn để thẩm định."]
        screening = self.screening_service.screen(citations, [])
        return pillars, overall_coverage, screening.all_signals

    def evaluate_criterion(
        self, criterion: RubricCriterion, citations: list[Citation]
    ) -> CriterionResult:
        return self.rubric_evaluator.evaluate_criterion(criterion, citations)

    _evaluate_criterion = evaluate_criterion

    def evaluate_pillar(
        self, pillar: str, rubric: PillarRubric, citations: list[Citation]
    ) -> PillarResult:
        return self.pillar_evaluator.evaluate_pillar(pillar, rubric, citations)

    _score_pillar = evaluate_pillar

    def build_evidence_matrix(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> list[EvidenceMatrixRow]:
        return self.matrix_builder.build(citations, facts)

    def screen_greenwashing_signals(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> GreenwashingScreeningResult:
        return self.screening_service.screen(citations, facts)

    def run_temporal_analysis(
        self,
        company: str,
        store: Store | None = None,
        metric: str = "scope_1_emissions",
        document_ids: list[str] | None = None,
        facts: list[ESGFact] | None = None,
    ) -> TemporalAnalysisResult:
        return self.temporal_analyzer.run_temporal_analysis(
            company=company,
            store=store,
            metric=metric,
            document_ids=document_ids,
            facts=facts,
        )

    def run_comparison(
        self,
        companies: list[str],
        store: Store | None = None,
        criteria_ids: list[str] | None = None,
        company_documents: dict[str, list[str]] | None = None,
    ) -> CompanyComparisonResult:
        return self.comparison_service.compare(
            companies=companies,
            store=store,
            company_documents=company_documents,
            criteria_ids=criteria_ids,
        )


# Backward compatibility aliases
ESGAuditService = ESGAnalysisService
ESGAuditAgent = ESGAnalysisService
ESGAnalysisAgent = ESGAnalysisService
