import csv
from pathlib import Path

from pydantic import BaseModel, Field

from app.document_service import (
    DocumentIngestError,
    DocumentIngestionService,
    OcrRequiredError,
)


class BatchFailure(BaseModel):
    """Thông tin chi tiết về một báo cáo không thể hoàn tất quy trình ingestion."""

    pdf_file: str
    category: str
    reason: str


class BatchIngestReport(BaseModel):
    """Báo cáo tổng hợp số liệu chi tiết của lần nạp dữ liệu hàng loạt (Batch Ingestion).

    Bao gồm tổng số tệp, số lượng thành công, bỏ qua (đã có), cần OCR, thất bại, v.v.
    """

    total: int = 0
    indexed: int = 0
    skipped: int = 0
    ocr_required: int = 0
    missing: int = 0
    failed: int = 0
    failures: list[BatchFailure] = Field(default_factory=list)


def ingest_dataset(
    metadata_path: Path,
    reports_dir: Path,
    service: DocumentIngestionService,
    *,
    limit: int | None = None,
    force: bool = False,
) -> BatchIngestReport:
    """Thực thi nạp dữ liệu hàng loạt các tệp PDF được khai báo trong tệp CSV metadata.

    Bảo vệ an toàn đường dẫn: Kiểm tra ngăn chặn lỗi Path Traversal (`pdf_path.is_relative_to(root)`).
    """

    root = reports_dir.resolve()
    report = BatchIngestReport()
    for row in _read_metadata(metadata_path, limit):
        report.total += 1
        relative_path = row.get("pdf_file", "").strip()
        pdf_path = (root / relative_path).resolve()

        # Kiểm tra tính tồn tại và bảo mật đường dẫn
        if not relative_path or not pdf_path.is_relative_to(root) or not pdf_path.is_file():
            report.missing += 1
            report.failures.append(
                BatchFailure(
                    pdf_file=relative_path,
                    category="missing",
                    reason="Không tìm thấy PDF trong thư mục dataset",
                )
            )
            continue

        try:
            result = service.ingest(
                pdf_path.read_bytes(),
                relative_path,
                "application/pdf",
                row.get("company_name") or None,
                row.get("sector_gics") or None,
                _parse_year(row.get("report_year")),
                force=force,
            )
            if result.status == "already_indexed":
                report.skipped += 1
            else:
                report.indexed += 1
        except OcrRequiredError as exc:
            report.ocr_required += 1
            report.failures.append(
                BatchFailure(pdf_file=relative_path, category="ocr_required", reason=str(exc))
            )
        except (DocumentIngestError, OSError) as exc:
            report.failed += 1
            report.failures.append(
                BatchFailure(pdf_file=relative_path, category="failed", reason=str(exc))
            )
    return report


def _read_metadata(metadata_path: Path, limit: int | None) -> list[dict[str, str]]:
    """Hàm phụ trợ đọc tệp CSV UTF-8 (hỗ trợ BOM) và trả về danh sách dict."""

    with metadata_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "pdf_file" not in reader.fieldnames:
            raise ValueError("Metadata CSV phải có cột pdf_file")
        rows = list(reader)
    return rows[:limit] if limit is not None else rows


def _parse_year(value: str | None) -> int | None:
    """Hàm phụ trợ chuyển đổi giá trị chuỗi năm báo cáo sang số nguyên."""

    try:
        return int(value) if value else None
    except ValueError:
        return None
