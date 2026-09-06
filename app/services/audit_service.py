from app.domain.company_comparison import CompanyComparisonService
from app.domain.rubric_evaluator import (
    EvidenceMatrixBuilder,
    PillarEvaluator,
    RubricEvaluator,
)
from app.domain.screening import GreenwashingScreeningService
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


class ESGAuditService:
    """Service điều phối toàn diện hoạt động kiểm toán ESG và thẩm định bằng chứng.

    Điều phối 5 domain components chuyên biệt:
    1. RubricEvaluator: Chấm điểm tiêu chí độc lập.
    2. PillarEvaluator: Chấm điểm trụ cột E, S, G.
    3. EvidenceMatrixBuilder: Dựng ma trận đối soát số liệu.
    4. GreenwashingScreeningService: Sàng lọc rủi ro tẩy xanh bằng Rule Engine.
    5. TemporalAnalyzer & CompanyComparisonService: Phân tích chuỗi thời gian và so sánh doanh nghiệp.
    """

    def __init__(
        self,
        rubric_evaluator: RubricEvaluator | None = None,
        pillar_evaluator: PillarEvaluator | None = None,
        screening_service: GreenwashingScreeningService | None = None,
        temporal_analyzer: TemporalAnalyzer | None = None,
        comparison_service: CompanyComparisonService | None = None,
        matrix_builder: EvidenceMatrixBuilder | None = None,
        llm_client: LLMClient | None = None,
    ):
        self.rubric_evaluator = rubric_evaluator or RubricEvaluator()
        self.pillar_evaluator = pillar_evaluator or PillarEvaluator(self.rubric_evaluator)
        self.matrix_builder = matrix_builder or EvidenceMatrixBuilder(self.rubric_evaluator)
        self.screening_service = screening_service or GreenwashingScreeningService()
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

    def _score_pillar(
        self, name: str, rubric: PillarRubric, citations: list[Citation]
    ) -> PillarResult:
        """Thực thi đánh giá chi tiết cho một trụ cột (E/S/G)."""
        return self.pillar_evaluator.evaluate_pillar(name, rubric, citations)

    def _evaluate_criterion(
        self, criterion: RubricCriterion, citations: list[Citation]
    ) -> CriterionResult:
        """Đánh giá 1 tiêu chí bằng cách gộp bằng chứng từ nhiều citation."""
        return self.rubric_evaluator.evaluate_criterion(criterion, citations)

    def build_evidence_matrix(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> list[EvidenceMatrixRow]:
        """Xây dựng ma trận kiểm toán bằng chứng đầy đủ cho toàn bộ tiêu chí chuẩn mực."""
        return self.matrix_builder.build_evidence_matrix(citations, facts)

    def screen_greenwashing_signals(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> GreenwashingScreeningResult:
        """Sàng lọc rủi ro Greenwashing đa chiều (Target Credibility, Evidence Quality, Narrative Risk)."""
        return self.screening_service.screen(citations, facts)

    def run_temporal_analysis(
        self,
        company: str,
        store: Store,
        metric: str = "scope_1_emissions",
        document_ids: list[str] | None = None,
    ) -> TemporalAnalysisResult:
        """Phân tích diễn biến chuỗi thời gian của một chỉ số ESG qua các năm."""
        return self.temporal_analyzer.run_temporal_analysis(
            company=company, store=store, metric=metric, document_ids=document_ids
        )

    def run_comparison(
        self,
        companies: list[str],
        store: Store,
        criteria_ids: list[str] | None = None,
    ) -> CompanyComparisonResult:
        """Thực thi so sánh chất lượng công bố ESG giữa các doanh nghiệp theo cùng rubric."""
        return self.comparison_service.run_comparison(
            companies=companies, store=store, criteria_ids=criteria_ids
        )


ESGAuditAgent = ESGAuditService
ESGAnalysisAgent = ESGAuditService
