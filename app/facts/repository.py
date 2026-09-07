"""Fact Store repository: single source of truth for structured ESG facts."""

from __future__ import annotations

import logging
from typing import Any

from app.extraction.fact_validator import detect_conflicts
from app.models import Citation, ESGFact, EvidenceConflict
from app.store import Store

logger = logging.getLogger(__name__)


class FactRepository:
    """Repository quản lý vòng đời và truy vấn Fact Store chuẩn kiểm toán."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_facts(self, facts: list[ESGFact]) -> int:
        """Ghi các fact đã được xác nhận vào canonical Fact Store.

        Candidate phải đi qua :meth:`save_candidates` và :meth:`promote`.
        """
        accepted = [
            fact.model_copy(
                update={
                    "status": "ACCEPTED",
                    "validation_status": "ACCEPTED",
                    "verification_status": "ACCEPTED",
                }
            )
            for fact in facts
        ]
        return self.store.save_facts(accepted)

    def save_candidates(self, facts: list[ESGFact]) -> int:
        """Persist extracted facts as unreviewed candidates."""
        candidates = []
        for fact in facts:
            conflict = fact.status in {"CONFLICT", "conflict"} or fact.validation_status in {
                "CONFLICT",
                "conflict",
            }
            status = "CONFLICT" if conflict else "CANDIDATE"
            candidates.append(
                fact.model_copy(
                    update={
                        "status": status,
                        "validation_status": status,
                        "verification_status": status,
                    }
                )
            )
        return self.store.save_fact_candidates(candidates)

    def promote(
        self,
        fact_ids: list[str],
        status: str = "ACCEPTED",
        reviewed_by: str | None = None,
    ) -> int:
        """Apply an explicit validator or human-review decision."""
        return self.store.promote_facts(fact_ids, status=status, reviewed_by=reviewed_by)

    def query_facts(
        self,
        company: str | None = None,
        metric: str | None = None,
        year: int | None = None,
        document_id: str | None = None,
        include_candidates: bool = False,
    ) -> list[ESGFact]:
        """Truy vấn các sự thật ESG từ Fact Store và chuyển đổi về đối tượng ESGFact."""
        rows = self.store.query_facts(
            company=company,
            metric=metric,
            year=year,
            document_id=document_id,
            include_candidates=include_candidates,
        )
        return [self._row_to_fact(r) for r in rows]

    def query_candidates(
        self,
        company: str | None = None,
        metric: str | None = None,
        year: int | None = None,
        document_id: str | None = None,
    ) -> list[ESGFact]:
        """Truy vấn lớp candidate riêng, không nhập lẫn vào fact accepted."""
        rows = self.store.query_fact_candidates(
            company=company,
            metric=metric,
            year=year,
            document_id=document_id,
        )
        return [self._row_to_fact(row) for row in rows]

    def get_temporal_series(self, company: str, metric: str) -> list[ESGFact]:
        """Truy xuất chuỗi thời gian đa năm của một chỉ số ESG cho một công ty cụ thể."""
        facts = self.query_facts(company=company, metric=metric)
        return sorted(facts, key=lambda f: f.reporting_year or f.year or 0)

    def get_cross_company_facts(self, companies: list[str], metric: str) -> list[ESGFact]:
        """Truy xuất các facts đồng chuẩn của cùng một chỉ tiêu cho nhiều công ty."""
        all_facts: list[ESGFact] = []
        for comp in companies:
            all_facts.extend(self.query_facts(company=comp, metric=metric))
        return all_facts

    def detect_conflicts_in_store(self, company: str | None = None) -> list[EvidenceConflict]:
        """Phát hiện mâu thuẫn số liệu công bố đa chiều trong Fact Store."""
        facts = self.query_facts(company=company)
        return detect_conflicts(facts)

    @staticmethod
    def _row_to_fact(row: dict[str, Any]) -> ESGFact:
        val_raw = row.get("raw_value")
        val: float | str | None = None
        if val_raw is not None:
            try:
                val = float(val_raw)
            except ValueError:
                val = val_raw

        cite = None
        if row.get("document_id") or row.get("page"):
            cite = Citation(
                document_id=row.get("document_id") or "unknown",
                document_name=row.get("name") or row.get("document_id") or "Report",
                company=row.get("company"),
                page=row.get("page") or 1,
                chunk_id=int(row["chunk_id"]) if str(row.get("chunk_id", "")).isdigit() else None,
                excerpt=(row.get("evidence_text") or f"Fact recorded from page {row.get('page')}")[
                    :700
                ],
                evidence_id=row.get("evidence_span_id"),
                stable_chunk_id=(
                    row.get("chunk_id") if not str(row.get("chunk_id", "")).isdigit() else None
                ),
            )

        return ESGFact(
            fact_id=row.get("fact_id", ""),
            company=row.get("company"),
            document_id=row.get("document_id"),
            metric=row["metric"],
            value=val,
            unit=row.get("raw_unit"),
            year=row.get("reporting_year"),
            reporting_year=row.get("reporting_year"),
            baseline_year=row.get("baseline_year"),
            target_year=row.get("target_year"),
            evidence_span_id=row.get("evidence_span_id"),
            source=cite,
            confidence=float(row.get("confidence") or 0.8),
            raw_value=val,
            raw_unit=row.get("raw_unit"),
            normalized_value=float(row["normalized_value"])
            if row.get("normalized_value") is not None
            else None,
            normalized_unit=row.get("normalized_unit"),
            methodology=row.get("methodology"),
            organizational_boundary=row.get("organizational_boundary"),
            verification_status=row.get("validation_status", "CANDIDATE"),
            validation_status=row.get("validation_status", "CANDIDATE"),
            status=row.get("validation_status", "CANDIDATE"),
            conflict_status=row.get("conflict_status", "none") or "none",
            extractor_version=row.get("extractor_version", "esg-extractor-v2"),
        )


class FactCandidateRepository(FactRepository):
    """Named repository used by the extraction workflow for candidate facts."""

    def save(self, candidates: list[ESGFact]) -> int:
        return self.save_candidates(candidates)
