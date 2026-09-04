import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    APIErrorResponse,
    Citation,
    DocumentIngestResponse,
    ErrorDetail,
    SearchRequest,
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
    """Khởi tạo dữ liệu demo Boeing khi server bắt đầu chạy."""
    seed_demo(store)
    yield


app = FastAPI(
    title="Multi-Agent ESG Report Analyst",
    description="Nền tảng phân tích báo cáo bền vững ESG dựa trên bằng chứng minh bạch (Evidence-First Multi-Agent Architecture)",
    version="1.0.0",
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
def health() -> dict:
    """Trả về trạng thái hoạt động của dịch vụ và thống kê nhanh quy mô dữ liệu corpus."""
    return {"status": "ok", **store.stats()}


@app.get("/api/documents", summary="Danh sách tài liệu báo cáo")
def documents() -> list[dict]:
    """Lấy danh sách toàn bộ các tài liệu báo cáo ESG đã được tiếp nhận và lập chỉ mục trong hệ thống."""
    return store.documents()


@app.get("/api/corpus/stats", summary="Thống kê dữ liệu Corpus")
def corpus_stats() -> dict:
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
    summary="Phân tích ESG bằng Multi-Agent Pipeline (Q&A hoặc Audit)",
)
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    """Khởi chạy quy trình phân tích Multi-Agent ở chế độ Evidence Q&A hoặc Full ESG Audit."""
    return supervisor.run(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode=request.mode,
    )

