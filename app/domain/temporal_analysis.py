"""Temporal analysis service: tracks multi-year ESG metric trajectories from structured facts."""

from __future__ import annotations

from typing import Any

from app.evidence_extractor import EvidenceExtractionAgent
from app.models import Citation, ESGFact, TemporalAnalysisResult, TemporalTrendPoint
from app.store import Store


class TemporalAnalyzer:
    """Analyze multi-year historical trajectories of ESG metrics using structured facts."""

    def analyze(
        self,
        company: str,
        facts: list[ESGFact],
        metric: str = "scope_1_emissions",
    ) -> TemporalAnalysisResult:
        """Compute multi-year timeline and YoY trends directly from extracted ESGFact records."""
        timeline_points: list[TemporalTrendPoint] = []
        seen_years: set[int] = set()

        # Filter facts matching the requested metric or related aliases
        metric_tokens = (metric.lower(), "scope 1" if "scope_1" in metric else metric.lower())
        relevant_facts = [
            f
            for f in facts
            if any(t in f.metric.lower() for t in metric_tokens)
            and f.year is not None
            and f.value is not None
        ]

        for f in relevant_facts:
            if f.year not in seen_years:
                seen_years.add(f.year)
                timeline_points.append(
                    TemporalTrendPoint(
                        year=f.year,
                        value=f.value,
                        unit=f.unit,
                        page=f.source.page if f.source else None,
                        document_id=f.source.document_id if f.source else None,
                    )
                )

        timeline_points.sort(key=lambda p: p.year)
        yoy_changes: list[dict[str, Any]] = []
        baseline_delta = None

        for i in range(1, len(timeline_points)):
            prev = timeline_points[i - 1]
            curr = timeline_points[i]
            if (
                isinstance(prev.value, (int, float))
                and isinstance(curr.value, (int, float))
                and prev.value > 0
            ):
                diff = curr.value - prev.value
                pct = round((diff / prev.value) * 100, 2)
                yoy_changes.append(
                    {"from_year": prev.year, "to_year": curr.year, "change_pct": pct}
                )

        if len(timeline_points) >= 2:
            first = timeline_points[0]
            last = timeline_points[-1]
            if (
                isinstance(first.value, (int, float))
                and isinstance(last.value, (int, float))
                and first.value > 0
            ):
                baseline_delta = round(((last.value - first.value) / first.value) * 100, 2)

        return TemporalAnalysisResult(
            company=company,
            metric=metric,
            timeline=timeline_points,
            yoy_changes=yoy_changes,
            baseline_to_current_change=baseline_delta,
            reporting_consistency="consistent" if len(yoy_changes) > 0 else "limited_data",
            consistency_issues=["Thiếu dữ liệu đa năm liên tục"]
            if len(timeline_points) < 2
            else [],
        )

    def run_temporal_analysis(
        self,
        company: str,
        store: Store | None = None,
        metric: str = "scope_1_emissions",
        document_ids: list[str] | None = None,
        facts: list[ESGFact] | None = None,
    ) -> TemporalAnalysisResult:
        """Backward-compatible entry point: uses facts if provided, otherwise retrieves from store."""
        if facts:
            return self.analyze(company=company, facts=facts, metric=metric)

        if store is None:
            return TemporalAnalysisResult(
                company=company,
                metric=metric,
                timeline=[],
                yoy_changes=[],
                baseline_to_current_change=None,
                reporting_consistency="limited_data",
                consistency_issues=["No facts or store available"],
            )

        query = f"{company} {metric} Scope 1 greenhouse gas emissions"
        results = store.search(query, limit=12, document_ids=document_ids)
        citations = [
            Citation(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                document_name=r["name"],
                page=r["page"],
                excerpt=r["text"],
                score=float(r.get("score") or 0.5),
            )
            for r in results
        ]

        extracted_facts = EvidenceExtractionAgent.extract_facts(citations)
        return self.analyze(company=company, facts=extracted_facts, metric=metric)
