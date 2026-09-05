from typing import Literal
from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Đoạn bằng chứng trích xuất từ tài liệu PDF, gắn liền với số trang cụ thể.

    Đảm bảo nguyên tắc evidence-first: mọi nhận định phân tích đều phải dẫn chiếu
    về đúng tệp và đúng trang PDF nguồn.
    """

    chunk_id: int | None = None
    document_id: str
    document_name: str
    page: int
    excerpt: str
    score: float = 0
    validated: bool = False


class RubricCriterion(BaseModel):
    """Cấu trúc định nghĩa một tiêu chí kiểm tra ESG chuẩn mực."""

    id: str
    pillar: Literal["E", "S", "G"]
    name: str
    description: str
    framework_reference: str | None = None
    required_evidence: list[str] = Field(default_factory=list)
    metric_units: list[str] = Field(default_factory=list)
    mandatory: bool = False


class CriterionCitationRef(BaseModel):
    """Tham chiếu citation tới trang tài liệu chứa bằng chứng cho tiêu chí."""

    document: str
    page: int
    excerpt: str = ""


class CriterionResult(BaseModel):
    """Kết quả đánh giá từng tiêu chí đơn lẻ."""

    criterion_id: str
    status: Literal["found", "not_found", "contradicts", "unclear"]
    value: str | None = None
    unit: str | None = None
    reporting_year: int | None = None
    citation: CriterionCitationRef | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class PillarResult(BaseModel):
    """Kết quả phân tích chi tiết cho một trụ cột ESG (Environment - E, Social - S, Governance - G).

    Bao gồm:
    - disclosure_coverage: Tỷ lệ (%) tiêu chí tìm thấy bằng chứng hợp lệ.
    - evidence_quality: Chất lượng bằng chứng (0-100%).
    - data_completeness: Mức độ đầy đủ của dữ liệu định lượng (0-100%).
    - confidence: Độ tin cậy của quá trình truy xuất (0.0-1.0).
    - criteria_results: Danh sách kết quả từng tiêu chí.
    """

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


class SearchRequest(BaseModel):
    """Schema truy vấn tìm kiếm bằng chứng trực tiếp (Retrieval search)."""

    query: str = Field(min_length=2, max_length=500)
    document_ids: list[str] | None = Field(default=None, max_length=20)
    top_k: int = Field(default=6, ge=1, le=25)


class DocumentIngestResponse(BaseModel):
    """Kết quả trả về sau khi hệ thống tiếp nhận và lập chỉ mục một tệp PDF."""

    id: str
    name: str
    pages: int
    text_pages: int
    extraction_quality: float = Field(ge=0, le=1)
    status: str


class AnalysisResponse(BaseModel):
    """Schema kết quả tổng hợp hoàn chỉnh do Supervisor Agent trả về."""

    mode: Literal["qa", "audit"] = "qa"
    agent_mode: Literal["llm_agentic", "deterministic_fallback"] = "deterministic_fallback"
    answer: str
    disclosure_coverage: float = Field(ge=0.0, le=100.0, default=0.0)
    evidence_quality: float = Field(ge=0.0, le=100.0, default=0.0)
    data_completeness: float = Field(ge=0.0, le=100.0, default=0.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    screening_signals: list[str] = Field(default_factory=list)
    pillars: list[PillarResult] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    verification_summary: dict = Field(default_factory=dict)
    trace: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    """Định dạng chi tiết lỗi hệ thống."""

    code: str
    message: str
    request_id: str | None = None


class APIErrorResponse(BaseModel):
    """Response chứa thông tin lỗi chuẩn hóa."""

    error: ErrorDetail
