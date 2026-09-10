import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.demo import seed_demo
from app.document_service import (
    DocumentExtractionError,
    DocumentIngestError,
    DocumentIngestionService,
    DocumentTooLargeError,
    DocumentTooManyPagesError,
    OcrRequiredError,
    UnsupportedDocumentError,
)
from app.facts.repository import FactRepository
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
    FactReviewRequest,
    SearchRequest,
    TemporalAnalysisResult,
    TemporalRequest,
)
from app.pipeline import ESGPipeline
from app.store import Store

store = Store(settings.database_path)
pipeline = ESGPipeline(store)
document_service = DocumentIngestionService(store)
fact_repository = FactRepository(store)

INGEST_ERROR_STATUS = {
    UnsupportedDocumentError: (415, "PDF_INVALID"),
    DocumentTooLargeError: (413, "PDF_TOO_LARGE"),
    DocumentTooManyPagesError: (413, "PDF_TOO_MANY_PAGES"),
    DocumentExtractionError: (422, "PDF_EXTRACTION_ERROR"),
    OcrRequiredError: (422, "OCR_REQUIRED"),
}


async def read_limited_file(file: UploadFile, max_bytes: int = settings.max_file_size) -> bytes:
    """Read uploads in bounded chunks instead of trusting client-reported size."""
    chunks: list[bytes] = []
    total = 0
    while block := await file.read(1024 * 1024):
        total += len(block)
        if total > max_bytes:
            raise DocumentTooLargeError(
                f"File exceeds the maximum size ({max_bytes // (1024 * 1024)}MB)"
            )
        chunks.append(block)
    return b"".join(chunks)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.seed_demo_data:
        seed_demo(store)
    yield


app = FastAPI(
    title="Evidence-Grounded ESG Report Analyst",
    description=(
        "Evidence-grounded ESG report analysis with an explicit application pipeline, "
        "hybrid retrieval, structured fact extraction, disclosure auditing, and "
        "heuristic greenwashing screening."
    ),
    version="2.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = str(uuid.uuid4())[:8]
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = exc.detail["code"]
        message = exc.detail.get("message", str(exc.detail))
    else:
        code = "REQUEST_ERROR"
        message = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=APIErrorResponse(
            error=ErrorDetail(code=code, message=message, request_id=request_id)
        ).model_dump(),
    )


@app.get("/", summary="Web dashboard")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/health", summary="Health check")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "system": "Evidence-Grounded ESG Report Analyst",
        "pipeline": "extract-retrieve-validate-analyze-answer",
        **store.stats(),
    }


@app.get("/api/documents", summary="List indexed reports")
def documents() -> list[dict[str, Any]]:
    return store.documents()


@app.get("/api/corpus/stats", summary="Corpus statistics")
def corpus_stats() -> dict[str, Any]:
    return store.stats()


@app.post("/api/search", response_model=list[Citation], summary="Search evidence")
def search(request: SearchRequest) -> list[Citation]:
    return pipeline.retrieval.run(request.query, request.top_k, request.document_ids)


@app.post(
    "/api/documents",
    response_model=DocumentIngestResponse,
    status_code=201,
    summary="Upload and index a PDF report",
)
async def upload_document(
    file: UploadFile = File(...),
    company: str | None = Form(None),
    sector: str | None = Form(None),
    year: int | None = Form(None),
) -> DocumentIngestResponse:
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


@app.post("/api/analyze", response_model=AnalysisResponse, summary="Run ESG analysis pipeline")
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    return pipeline.run(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode=request.mode,
        focus_pillars=request.focus_pillars,
    )


@app.post("/api/query", response_model=AnalysisResponse, summary="Evidence-grounded Q&A")
def query_endpoint(request: AnalysisRequest) -> AnalysisResponse:
    return pipeline.run(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode="qa",
        focus_pillars=request.focus_pillars,
    )


@app.post("/api/audit", response_model=AnalysisResponse, summary="Run ESG disclosure audit")
def audit_endpoint(request: AuditRequest) -> AnalysisResponse:
    return pipeline.run(
        question=(
            "Comprehensive ESG disclosure audit covering emissions, targets, workforce safety, "
            "governance, and assurance."
        ),
        top_k=request.top_k,
        document_ids=request.document_ids,
        mode="audit",
        focus_pillars=request.focus_pillars,
    )


@app.post("/api/compare", response_model=CompanyComparisonResult, summary="Compare companies")
def compare_endpoint(request: ComparisonRequest) -> CompanyComparisonResult:
    return pipeline.audit.run_comparison(
        companies=request.companies,
        store=pipeline.store,
        criteria_ids=request.criteria_ids,
    )


@app.post("/api/temporal", response_model=TemporalAnalysisResult, summary="Analyze ESG trend")
def temporal_endpoint(request: TemporalRequest) -> TemporalAnalysisResult:
    return pipeline.audit.run_temporal_analysis(
        company=request.company,
        store=pipeline.store,
        metric=request.metric,
        document_ids=request.document_ids,
    )


@app.get(
    "/api/documents/{document_id}/metrics",
    response_model=list[ESGFact],
    summary="Extract structured metrics for one report",
)
def document_metrics(document_id: str) -> list[ESGFact]:
    if not store.get_document(document_id):
        raise HTTPException(status_code=404, detail=f"Unknown document id '{document_id}'")
    return fact_repository.query_candidates(document_id=document_id)


@app.patch(
    "/api/v1/facts/{fact_id}",
    summary="Accept, reject, or flag an extracted fact candidate",
)
def review_fact(fact_id: str, request: FactReviewRequest) -> dict[str, Any]:
    updated = fact_repository.promote(
        [fact_id],
        status=request.status,
        reviewed_by=request.reviewed_by,
    )
    if updated == 0:
        raise HTTPException(status_code=404, detail=f"Unknown fact candidate '{fact_id}'")
    return {
        "fact_id": fact_id,
        "status": request.status,
        "reviewed_by": request.reviewed_by,
    }


@app.get(
    "/api/documents/{document_id}/audit",
    response_model=list[EvidenceMatrixRow],
    summary="Build evidence matrix for one report",
)
def document_audit_matrix(document_id: str) -> list[EvidenceMatrixRow]:
    if not store.get_document(document_id):
        raise HTTPException(status_code=404, detail=f"Unknown document id '{document_id}'")
    response = pipeline.run(
        question="Audit ESG disclosure for this document.",
        top_k=15,
        document_ids=[document_id],
        mode="audit",
    )
    return response.evidence_matrix


@app.get("/api/analysis/recent/trace", summary="Inspect the most recent pipeline trace")
def recent_trace() -> dict[str, Any]:
    last = pipeline.last_response
    if last is None:
        return {
            "status": "empty",
            "message": "No analysis has been executed in this process.",
            "retrieval_mode": settings.retrieval_mode,
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.reranker_model,
        }
    return {
        "status": "ok",
        "request_id": last.request_id,
        "analysis_status": last.status,
        "mode": last.mode,
        "intent": last.plan.intent if last.plan else None,
        "trace": last.trace,
        "evidence_completeness": last.evidence_completeness,
        "disclosure_coverage": last.disclosure_coverage,
        "retrieval_mode": settings.retrieval_mode,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
    }
