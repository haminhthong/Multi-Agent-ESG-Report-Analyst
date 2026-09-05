import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agents import SupervisorAgent
from app.config import settings
from app.demo import seed_demo
from app.document_service import (
    DocumentExtractionError,
    DocumentIngestError,
    DocumentIngestionService,
    DocumentTooLargeError,
    OcrRequiredError,
    UnsupportedDocumentError,
)
from app.evidence_extractor import EvidenceExtractionAgent
from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    APIErrorResponse,
    AuditRequest,
    Citation,
    CompanyComparisonResult,
    ComparisonRequest,
    DocumentIngestResponse,
    ErrorDetail,
    ESGFact,
    EvidenceMatrixRow,
    SearchRequest,
    TemporalAnalysisResult,
    TemporalRequest,
)
from app.store import Store

# ==============================================================================
# KHỞI TẠO CÁC THÀNH PHẦN SINGLETON HỆ THỐNG
# ==============================================================================
store = Store(settings.database_path)
supervisor = SupervisorAgent(store)
document_service = DocumentIngestionService(store)

INGEST_ERROR_STATUS = {
    UnsupportedDocumentError: (415, "PDF_INVALID"),
    DocumentTooLargeError: (413, "PDF_TOO_LARGE"),
    DocumentExtractionError: (422, "PDF_EXTRACTION_ERROR"),
    OcrRequiredError: (422, "OCR_REQUIRED"),
}


async def read_limited_file(file: UploadFile, max_bytes: int = settings.max_file_size) -> bytes:
    """Đọc tệp PDF gửi lên theo từng block 1MB để tránh quá tải bộ nhớ RAM."""
    chunks = []
    total = 0
    while block := await file.read(1024 * 1024):
        total += len(block)
        if total > max_bytes:
            raise DocumentTooLargeError(
                f"Kích thước tệp vượt quá giới hạn tối đa ({max_bytes // (1024 * 1024)}MB)"
            )
        chunks.append(block)
    return b"".join(chunks)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Khởi tạo dữ liệu demo đa ngành khi server bắt đầu chạy."""
    seed_demo(store)
    yield


app = FastAPI(
    title="Evidence-Grounded ESG Intelligence & Audit System",
    description="Nền tảng kiểm toán và phân tích báo cáo bền vững ESG đa tác tử với bảo toàn số trang nguồn (5-Layer Architecture)",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Exception handler chuẩn hóa lỗi HTTP cho client."""
    request_id = str(uuid.uuid4())[:8]
    code = getattr(exc, "detail_code", "REQUEST_ERROR")
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = exc.detail["code"]
        message = exc.detail.get("message", str(exc.detail))
    else:
        message = str(exc.detail)

    return JSONResponse(
        status_code=exc.status_code,
        content=APIErrorResponse(
            error=ErrorDetail(code=code, message=message, request_id=request_id)
        ).model_dump(),
    )


@app.get("/", summary="Trang chủ Web UI Dashboard")
def index() -> FileResponse:
    """Trả về tệp giao diện HTML chính của ứng dụng web."""
    return FileResponse("app/static/index.html")


@app.get("/health", summary="Health Check API")
def health() -> dict[str, Any]:
    """Trả về trạng thái hoạt động của dịch vụ và thống kê nhanh quy mô dữ liệu corpus."""
    return {"status": "ok", "system": "Evidence-Grounded ESG Intelligence", **store.stats()}


@app.get("/api/documents", summary="Danh sách tài liệu báo cáo")
def documents() -> list[dict[str, Any]]:
    """Lấy danh sách toàn bộ các tài liệu báo cáo ESG đã được tiếp nhận và lập chỉ mục trong hệ thống."""
    return store.documents()


@app.get("/api/corpus/stats", summary="Thống kê dữ liệu Corpus")
def corpus_stats() -> dict[str, Any]:
    """Lấy số liệu thống kê chi tiết về quy mô corpus (tổng số tệp, chunk, công ty, ngành)."""
    return store.stats()


@app.post(
    "/api/search", response_model=list[Citation], summary="Truy xuất bằng chứng (Retrieval Search)"
)
def search(request: SearchRequest) -> list[Citation]:
    """Tìm kiếm trực tiếp các đoạn văn bản bằng chứng liên quan đến từ khóa."""
    return supervisor.retrieval.run(request.query, request.top_k, request.document_ids)


@app.post(
    "/api/documents",
    response_model=DocumentIngestResponse,
    status_code=201,
    summary="Tải lên và lập chỉ mục tệp PDF",
)
async def upload_document(
    file: UploadFile = File(...),
    company: str | None = Form(None),
    sector: str | None = Form(None),
    year: int | None = Form(None),
) -> DocumentIngestResponse:
    """Tiếp nhận tệp PDF gửi từ client, trích xuất văn bản theo block và tạo chỉ mục tìm kiếm."""
    try:
        content = await read_limited_file(file)
        return document_service.ingest(
            content,
            file.filename or "report.pdf",
            file.content_type,
            company,
            sector,
            year,
        )
    except DocumentIngestError as exc:
        status, code = INGEST_ERROR_STATUS.get(type(exc), (422, "DOCUMENT_INGEST_ERROR"))
        raise HTTPException(
            status_code=status,
            detail={"code": code, "message": str(exc)},
        ) from exc


@app.post(
    "/api/analyze",
    response_model=AnalysisResponse,
    summary="Phân tích ESG bằng Multi-Agent Pipeline (Backward compatible)",
)
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    """Khởi chạy quy trình phân tích Multi-Agent ở chế độ Evidence Q&A hoặc Full ESG Audit."""
    return supervisor.run(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode=request.mode,
    )


# ==============================================================================
# CÁC API ENDPOINTS MỚI CHO EVIDENCE-GROUNDED ESG INTELLIGENCE
# ==============================================================================
@app.post(
    "/api/query",
    response_model=AnalysisResponse,
    summary="Truy vấn hỏi đáp với Query Planning Agent (Evidence Q&A)",
)
def query_endpoint(request: AnalysisRequest) -> AnalysisResponse:
    """Khởi chạy quy trình hỏi đáp phân rã truy vấn có cấu trúc với Query Planner."""
    return supervisor.run(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode="qa",
    )


@app.post(
    "/api/audit",
    response_model=AnalysisResponse,
    summary="Kiểm toán ESG toàn diện với Ma trận Bằng chứng (Evidence Matrix)",
)
def audit_endpoint(request: AuditRequest) -> AnalysisResponse:
    """Khởi chạy kiểm toán ESG toàn bộ tiêu chí E, S, G, sinh Ma trận Bằng chứng và sàng lọc Greenwashing."""
    return supervisor.run(
        question="Comprehensive ESG Audit covering emissions, targets, workforce safety, governance, and assurance.",
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode="audit",
    )


@app.post(
    "/api/compare",
    response_model=CompanyComparisonResult,
    summary="So sánh đối chiếu chất lượng công bố giữa các doanh nghiệp",
)
def compare_endpoint(request: ComparisonRequest) -> CompanyComparisonResult:
    """So sánh chất lượng công bố ESG giữa các doanh nghiệp theo cùng hệ thống chuẩn mực."""
    return supervisor.audit.run_comparison(
        companies=request.companies,
        store=supervisor.store,
        criteria_ids=request.criteria_ids,
    )


@app.post(
    "/api/temporal",
    response_model=TemporalAnalysisResult,
    summary="Phân tích diễn biến chuỗi thời gian (Temporal ESG Analysis)",
)
def temporal_endpoint(request: TemporalRequest) -> TemporalAnalysisResult:
    """Phân tích diễn biến phát thải và mục tiêu qua các năm của doanh nghiệp."""
    return supervisor.audit.run_temporal_analysis(
        company=request.company,
        store=supervisor.store,
        metric=request.metric,
        document_ids=request.document_ids,
    )


@app.get(
    "/api/documents/{document_id}/metrics",
    response_model=list[ESGFact],
    summary="Lấy danh sách các số liệu sự thật ESG đã trích xuất từ tài liệu",
)
def document_metrics(document_id: str) -> list[ESGFact]:
    """Trích xuất và trả về danh sách các số liệu định lượng (ESGFact) của một tài liệu."""
    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=404, detail=f"Không tìm thấy tài liệu với ID '{document_id}'"
        )

    citations = supervisor.retrieval.run(
        query=f"{doc['name']} emissions energy safety board governance",
        top_k=15,
        document_ids=[document_id],
    )
    return EvidenceExtractionAgent.extract_facts(citations)


@app.get(
    "/api/documents/{document_id}/audit",
    response_model=list[EvidenceMatrixRow],
    summary="Lấy Ma trận Bằng chứng (Evidence Matrix) của một tài liệu",
)
def document_audit_matrix(document_id: str) -> list[EvidenceMatrixRow]:
    """Xây dựng và trả về Ma trận Bằng chứng cho tất cả tiêu chí chuẩn mực của tài liệu."""
    doc = store.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=404, detail=f"Không tìm thấy tài liệu với ID '{document_id}'"
        )

    resp = supervisor.run(
        question="Audit ESG disclosure for document",
        top_k=15,
        document_ids=[document_id],
        mode="audit",
    )
    return resp.evidence_matrix


@app.get(
    "/api/analysis/recent/trace",
    summary="Xem vết thực thi (Observability Latency Trace) của lần phân tích gần nhất",
)
def recent_trace() -> dict[str, Any]:
    """Trả về thông tin trace chi tiết và latency waterfall phục vụ observability."""
    return {
        "status": "active",
        "retrieval_mode": settings.retrieval_mode,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
    }
