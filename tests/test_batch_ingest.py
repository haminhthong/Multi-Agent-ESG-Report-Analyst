from pathlib import Path

from app.agents import DocumentAgent
from app.batch_ingest import ingest_dataset
from app.document_service import DocumentIngestionService
from app.store import Store


def test_batch_ingest_reports_indexed_missing_and_skipped(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    pdf = reports / "Energy" / "ACME.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-demo")
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "pdf_file,company_name,sector_gics,report_year\n"
        "Energy/ACME.pdf,ACME,Energy,2024\n"
        "Energy/Missing.pdf,Missing,Energy,2024\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        DocumentAgent,
        "extract_pdf",
        staticmethod(lambda _: [(1, "carbon emissions decreased 12% in 2024" * 3)]),
    )
    service = DocumentIngestionService(Store(tmp_path / "test.db"))

    first = ingest_dataset(metadata, reports, service)
    second = ingest_dataset(metadata, reports, service)

    assert (first.total, first.indexed, first.missing) == (2, 1, 1)
    assert second.skipped == 1
    assert second.missing == 1


def test_batch_ingest_blocks_path_outside_dataset(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    metadata = tmp_path / "metadata.csv"
    metadata.write_text("pdf_file\n../secret.pdf\n", encoding="utf-8")

    report = ingest_dataset(
        metadata,
        reports,
        DocumentIngestionService(Store(tmp_path / "test.db")),
    )

    assert report.missing == 1
