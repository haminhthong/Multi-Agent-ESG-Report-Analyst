from typing import Any, Literal
from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Đoạn bằng chứng trích xuất từ tài liệu PDF, gắn liền với số trang cụ thể và provenance sâu.

    Đảm bảo nguyên tắc evidence-first: mọi nhận định phân tích đều phải dẫn chiếu
    về đúng tệp, đúng trang PDF nguồn, block id và vị trí section.
    """

    chunk_id: int | None = None
    document_id: str
    document_name: str
    page: int
    excerpt: str
    score: float = 0.0
    validated: bool = False
    section: str | None = None
    bbox: list[float] | None = None
    block_id: str | None = None
    block_type: Literal["text", "table", "heading", "figure"] = "text"
    char_offsets: tuple[int, int] | None = None
    retrieval_score: float = 0.0
    reranker_score: float | None = None
    validation_status: Literal["valid", "flagged", "rejected"] = "valid"


class LayoutBlock(BaseModel):
    """Cấu trúc biểu diễn một khối layout (văn bản hoặc bảng) trích xuất từ trang PDF."""

    document_id: str
    page: int
    block_id: str
    block_type: Literal["text", "table", "heading", "figure"] = "text"
    section: str | None = None
    text: str
    bbox: list[float] | None = None
    source_method: str = "native"
    quality_score: float = 1.0


class RubricCriterion(BaseModel):
    """Cấu trúc định nghĩa một tiêu chí kiểm tra ESG chuẩn mực."""

    id: str
    pillar: Literal["E", "S", "G"]
    name: str
    description: str
    framework_reference: str | None = None
    retrieval_keywords: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    metric_units: list[str] = Field(default_factory=list)
    mandatory: bool = False


class CriterionCitationRef(BaseModel):
    """Tham chiếu citation tới trang tài liệu chứa bằng chứng cho tiêu chí."""

    document: str
    page: int
    excerpt: str = ""
    section: str | None = None


class CriterionResult(BaseModel):
    """Kết quả đánh giá từng tiêu chí đơn lẻ theo độ đầy đủ dữ liệu (Completeness)."""

    criterion_id: str
    status: Literal["found", "partial", "not_found", "missing", "contradicts", "unclear"]
    value: str | None = None
    unit: str | None = None
    reporting_year: int | None = None
    citation: CriterionCitationRef | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    matched_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class PillarResult(BaseModel):
    """Kết quả phân tích chi tiết cho một trụ cột ESG (Environment - E, Social - S, Governance - G)."""

    pillar: str
    score: float = Field(ge=0.0, le=100.0, description="Tương đương disclosure_coverage (%)")
    disclosure_coverage: float = Field(ge=0.0, le=100.0)
    evidence_quality: float = Field(ge=0.0, le=100.0)
    data_completeness: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class RetrievalPlan(BaseModel):
    """Kế hoạch truy xuất có cấu trúc do Query Planning Agent sinh ra."""

    intent: Literal[
        "fact_lookup",
        "criterion_audit",
        "cross_document_compare",
        "greenwashing_screening",
        "temporal_trend",
    ] = "fact_lookup"
    subqueries: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    document_scope: list[str] | None = None
    temporal_scope: str | None = None


class ESGFact(BaseModel):
    """Bằng chứng số liệu ESG có cấu trúc đã chuẩn hóa đơn vị và năm."""

    metric: str
    value: float | str | None = None
    unit: str | None = None
    year: int | None = None
    baseline_year: int | None = None
    source: Citation | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    fact_id: str = ""
    target_year: int | None = None
    extraction_method: Literal["regex", "rule", "llm"] = "rule"
    verification_status: Literal["validated", "partial", "conflict", "valid", "unverified"] = "valid"
    validation_status: Literal["validated", "partial", "conflict", "valid", "unverified"] = "valid"

    # Lưu vết nguyên bản và chuẩn hóa (Dual Value/Unit Representation)
    raw_value: float | str | None = None
    raw_unit: str | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None
    methodology: str | None = None  # e.g. "market-based", "location-based", "gross", "net"
    organizational_boundary: str | None = None
    evidence_text: str | None = None


class EvidenceConflict(BaseModel):
    """Ghi nhận mâu thuẫn số liệu công bố giữa các trang hoặc tài liệu."""

    metric: str
    year: int | None = None
    disclosures: list[dict[str, Any]] = Field(default_factory=list)
    severity: Literal["high", "medium", "low"] = "medium"
    description: str = ""


class ScreeningSignal(BaseModel):
    """Tín hiệu sàng lọc rủi ro greenwashing có cấu trúc và có thể giải thích được."""

    code: str
    category: Literal["target_credibility", "evidence_quality", "narrative_risk"]
    severity: Literal["low", "medium", "high"]
    message: str
    evidence_ids: list[str] = Field(default_factory=list)
    rule: str = ""


class EvidenceRequirement(BaseModel):
    """Định nghĩa yêu cầu bằng chứng cấu trúc trong kiểm tra chất lượng (Quality Gate)."""

    name: str
    fact_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    requires_numeric_value: bool = False
    requires_year: bool = False
    requires_baseline: bool = False
    requires_unit: bool = False


class EvidenceRequirementResult(BaseModel):
    """Kết quả đánh giá từng yêu cầu bằng chứng."""

    requirement: str
    status: Literal["satisfied", "partial", "missing"] = "missing"
    matched_fact_ids: list[str] = Field(default_factory=list)
    matched_citation_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    missing_aspects: list[str] = Field(default_factory=list)


class EvidenceCompletenessResult(BaseModel):
    """Kết quả kiểm tra chất lượng bằng chứng (Evidence Completeness Gate)."""

    requirements: list[EvidenceRequirementResult] = Field(default_factory=list)
    satisfied_count: int = 0
    partial_count: int = 0
    missing_count: int = 0
    completeness_score: float = 0.0
    status: Literal["complete", "incomplete"] = "complete"
    required: list[str] = Field(default_factory=list)
    satisfied: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)

    def keys(self):
        return self.model_dump().keys()

    def values(self):
        return self.model_dump().values()

    def items(self):
        return self.model_dump().items()


class ExtractionQualityReport(BaseModel):
    """Báo cáo chất lượng trích xuất tài liệu (OCR / Text extraction quality)."""

    native_text_ratio: float = Field(ge=0.0, le=1.0, default=1.0)
    ocr_applied_ratio: float = Field(ge=0.0, le=1.0, default=0.0)
    table_count: int = 0
    empty_pages: list[int] = Field(default_factory=list)
    average_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    notes: list[str] = Field(default_factory=list)


class GreenwashingScreeningResult(BaseModel):
    """Kết quả sàng lọc rủi ro greenwashing đa tín hiệu."""

    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    signals: list[ScreeningSignal] = Field(default_factory=list)
    target_credibility_signals: list[str] = Field(default_factory=list)
    evidence_quality_signals: list[str] = Field(default_factory=list)
    narrative_risk_signals: list[str] = Field(default_factory=list)
    all_signals: list[str] = Field(default_factory=list)
    summary: str = ""


class TemporalTrendPoint(BaseModel):
    """Điểm dữ liệu theo chuỗi thời gian của một chỉ số ESG."""

    year: int
    value: float | str
    unit: str | None = None
    page: int | None = None
    document_id: str | None = None


class TemporalAnalysisResult(BaseModel):
    """Kết quả phân tích diễn biến ESG qua các năm của doanh nghiệp."""

    company: str
    metric: str
    timeline: list[TemporalTrendPoint] = Field(default_factory=list)
    yoy_changes: list[dict[str, Any]] = Field(default_factory=list)
    baseline_to_current_change: float | None = None
    reporting_consistency: str = "consistent"
    consistency_issues: list[str] = Field(default_factory=list)


class CompanyComparisonCriterion(BaseModel):
    """Đánh giá so sánh từng tiêu chí giữa các doanh nghiệp."""

    criterion_id: str
    criterion_name: str
    pillar: Literal["E", "S", "G"]
    values_by_company: dict[str, dict[str, Any]] = Field(default_factory=dict)


class CompanyComparisonResult(BaseModel):
    """Kết quả so sánh chất lượng công bố ESG giữa các doanh nghiệp."""

    companies: list[str]
    reporting_period: str | int = "latest"
    criteria_matrix: list[CompanyComparisonCriterion] = Field(default_factory=list)
    coverage_summary: dict[str, float] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)


class AgentTraceStep(BaseModel):
    """Bản ghi vết thực thi chi tiết của một Agent kèm độ trễ (latency)."""

    agent: str
    step: str
    latency_ms: float = 0.0
    retrieved_chunks: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceMatrixRow(BaseModel):
    """Hàng dữ liệu biểu diễn trực quan ma trận kiểm toán bằng chứng ESG."""

    criterion_id: str
    criterion_name: str
    pillar: Literal["E", "S", "G"]
    status: Literal["found", "partial", "missing", "not_found", "contradicts", "unclear"]
    value: str | None = None
    unit: str | None = None
    reporting_year: int | None = None
    citation: CriterionCitationRef | None = None
    confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)


class AnalysisRequest(BaseModel):
    """Schema dữ liệu đầu vào cho yêu cầu phân tích của người dùng."""

    question: str = Field(
        default="Assess this company's ESG disclosure coverage and evidence quality.",
        min_length=5,
        max_length=1000,
    )
    document_ids: list[str] | None = Field(default=None, max_length=20)
    top_k: int = Field(default=8, ge=1, le=25)
    mode: Literal["qa", "audit"] = Field(default="qa")
    focus_pillars: list[Literal["E", "S", "G"]] | None = None


class SearchRequest(BaseModel):
    """Schema truy vấn tìm kiếm bằng chứng trực tiếp (Retrieval search)."""

    query: str = Field(min_length=2, max_length=500)
    document_ids: list[str] | None = Field(default=None, max_length=20)
    top_k: int = Field(default=6, ge=1, le=25)


class ComparisonRequest(BaseModel):
    """Schema yêu cầu so sánh chất lượng công bố giữa các doanh nghiệp."""

    companies: list[str] = Field(min_length=2, max_length=10)
    top_k: int = Field(default=6, ge=1, le=20)
    criteria_ids: list[str] | None = None


class TemporalRequest(BaseModel):
    """Schema yêu cầu phân tích chuỗi thời gian của một doanh nghiệp."""

    company: str
    metric: str = "scope_1_emissions"
    document_ids: list[str] | None = None


class AuditRequest(BaseModel):
    """Schema yêu cầu kiểm toán ESG đầy đủ kèm ma trận bằng chứng."""

    document_ids: list[str] | None = None
    top_k: int = Field(default=12, ge=1, le=30)
    focus_pillars: list[Literal["E", "S", "G"]] | None = None


class DocumentIngestResponse(BaseModel):
    """Kết quả trả về sau khi hệ thống tiếp nhận và lập chỉ mục một tệp PDF."""

    id: str
    name: str
    pages: int
    text_pages: int
    extraction_quality: float = Field(ge=0, le=1)
    status: str
    extraction_report: ExtractionQualityReport | None = None


class AnalysisResponse(BaseModel):
    """Schema kết quả tổng hợp hoàn chỉnh do Supervisor Agent trả về."""

    mode: Literal["qa", "audit"] = "qa"
    agent_mode: Literal["llm_agentic", "deterministic_fallback", "agent_orchestrated"] = (
        "deterministic_fallback"
    )
    answer: str
    disclosure_coverage: float = Field(ge=0.0, le=100.0, default=0.0)
    evidence_quality: float = Field(ge=0.0, le=100.0, default=0.0)
    data_completeness: float = Field(ge=0.0, le=100.0, default=0.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    screening_signals: list[str] = Field(default_factory=list)
    pillars: list[PillarResult] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    verification_summary: dict[str, Any] = Field(default_factory=dict)
    trace: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    # Các trường nâng cấp cho Evidence-Grounded ESG Intelligence
    plan: RetrievalPlan | None = None
    evidence_matrix: list[EvidenceMatrixRow] = Field(default_factory=list)
    extracted_facts: list[ESGFact] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    screening_result: GreenwashingScreeningResult | None = None
    temporal_analysis: TemporalAnalysisResult | None = None
    comparison: CompanyComparisonResult | None = None
    evidence_completeness: EvidenceCompletenessResult | dict[str, Any] = Field(
        default_factory=EvidenceCompletenessResult
    )
    trace_steps: list[AgentTraceStep] = Field(default_factory=list)


class AnalysisState(BaseModel):
    """Trạng thái chia sẻ trung tâm được điều phối bởi Supervisor Agent."""

    request_id: str
    user_question: str
    mode: Literal["qa", "audit"] = "qa"
    document_ids: list[str] | None = None
    top_k: int = 8
    plan: RetrievalPlan | None = None
    raw_citations: list[Citation] = Field(default_factory=list)
    validated_citations: list[Citation] = Field(default_factory=list)
    extracted_facts: list[ESGFact] = Field(default_factory=list)
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    evidence_matrix: list[EvidenceMatrixRow] = Field(default_factory=list)
    screening_result: GreenwashingScreeningResult | None = None
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    temporal_analysis: TemporalAnalysisResult | None = None
    comparison: CompanyComparisonResult | None = None
    pillars: list[PillarResult] = Field(default_factory=list)
    overall_coverage: float = 0.0
    verification_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_completeness: EvidenceCompletenessResult | dict[str, Any] = Field(
        default_factory=EvidenceCompletenessResult
    )
    answer: str = ""
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    trace_steps: list[AgentTraceStep] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    """Định dạng chi tiết lỗi hệ thống."""

    code: str
    message: str
    request_id: str | None = None


class APIErrorResponse(BaseModel):
    """Response chứa thông tin lỗi chuẩn hóa."""

    error: ErrorDetail
