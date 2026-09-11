"""Phân tích chuỗi thời gian từ các fact ESG đã được chấp nhận."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any, ClassVar

from app.facts.repository import FactRepository
from app.models import ESGFact, TemporalAnalysisResult, TemporalTrendPoint
from app.store import Store


class TemporalAnalyzer:
    """Tính xu hướng nhiều năm từ dữ liệu có cấu trúc và có provenance."""

    _METRIC_ALIASES: ClassVar[dict[str, str]] = {
        "scope_1": "scope_1_emissions",
        "scope1": "scope_1_emissions",
        "scope_1_ghg": "scope_1_emissions",
        "scope_1_ghg_emissions": "scope_1_emissions",
        "scope_1_emission": "scope_1_emissions",
        "scope_1_emissions": "scope_1_emissions",
        "scope_2": "scope_2_emissions",
        "scope2": "scope_2_emissions",
        "scope_2_ghg": "scope_2_emissions",
        "scope_2_ghg_emissions": "scope_2_emissions",
        "scope_2_emission": "scope_2_emissions",
        "scope_2_emissions": "scope_2_emissions",
        "scope_3": "scope_3_emissions",
        "scope3": "scope_3_emissions",
        "scope_3_ghg": "scope_3_emissions",
        "scope_3_ghg_emissions": "scope_3_emissions",
        "scope_3_emission": "scope_3_emissions",
        "scope_3_emissions": "scope_3_emissions",
        "renewable": "renewable_energy",
        "renewable_energy": "renewable_energy",
    }

    @classmethod
    def _normalise_metric(cls, metric: str) -> str:
        """Chuẩn hóa metric nhập từ API về dạng snake_case ổn định."""
        normalized = re.sub(r"[^a-z0-9]+", "_", metric.casefold()).strip("_")
        return cls._METRIC_ALIASES.get(normalized, normalized)

    @classmethod
    def _metric_aliases(cls, metric: str) -> tuple[str, ...]:
        """Sinh các tên tương đương để truy vấn cùng một loại metric."""
        normalized = re.sub(r"[^a-z0-9]+", "_", metric.casefold()).strip("_")
        canonical = cls._normalise_metric(metric)
        aliases = [metric.strip(), normalized, canonical]
        if canonical == "scope_1_emissions":
            aliases.extend(("scope 1", "scope1", "scope_1"))
        elif canonical == "scope_2_emissions":
            aliases.extend(("scope 2", "scope2", "scope_2"))
        elif canonical == "scope_3_emissions":
            aliases.extend(("scope 3", "scope3", "scope_3"))
        elif canonical == "renewable_energy":
            aliases.append("renewable")
        return tuple(dict.fromkeys(alias for alias in aliases if alias))

    @classmethod
    def _matches_metric(cls, fact_metric: str, requested_metric: str) -> bool:
        """So khớp metric canonical, tránh substring gây lẫn chỉ số."""
        return cls._normalise_metric(fact_metric) == cls._normalise_metric(requested_metric)

    @staticmethod
    def _fact_year(fact: ESGFact) -> int | None:
        """Ưu tiên reporting_year, fallback về year của dữ liệu cũ."""
        return fact.reporting_year or fact.year

    @staticmethod
    def _is_numeric(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def analyze(
        self,
        company: str,
        facts: list[ESGFact],
        metric: str = "scope_1_emissions",
    ) -> TemporalAnalysisResult:
        """Tính timeline và thay đổi YoY từ các fact ESG đã được truyền vào."""
        best_by_year: dict[int, ESGFact] = {}

        # Mỗi năm chỉ chọn một fact tốt nhất để không tính YoY trên dữ liệu trùng.
        for fact in facts:
            year = self._fact_year(fact)
            if not self._matches_metric(fact.metric, metric) or year is None or fact.value is None:
                continue
            current = best_by_year.get(year)
            if current is None or fact.confidence > current.confidence:
                best_by_year[year] = fact

        timeline_points: list[TemporalTrendPoint] = []
        for year, fact in sorted(best_by_year.items()):
            source = fact.source
            timeline_points.append(
                TemporalTrendPoint(
                    year=year,
                    value=fact.value,
                    unit=fact.unit,
                    page=source.page if source else fact.page,
                    document_id=source.document_id if source else fact.document_id,
                )
            )

        yoy_changes: list[dict[str, Any]] = []
        for previous, current in pairwise(timeline_points):
            if (
                self._is_numeric(previous.value)
                and self._is_numeric(current.value)
                and previous.value > 0
            ):
                difference = current.value - previous.value
                change_pct = round((difference / previous.value) * 100, 2)
                yoy_changes.append(
                    {
                        "from_year": previous.year,
                        "to_year": current.year,
                        "change_pct": change_pct,
                    }
                )

        baseline_delta = None
        if len(timeline_points) >= 2:
            first = timeline_points[0]
            last = timeline_points[-1]
            if self._is_numeric(first.value) and self._is_numeric(last.value) and first.value > 0:
                baseline_delta = round(((last.value - first.value) / first.value) * 100, 2)

        missing_years = [
            year
            for previous, current in pairwise(timeline_points)
            for year in range(previous.year + 1, current.year)
        ]
        consistency_issues: list[str] = []
        if len(timeline_points) < 2:
            consistency_issues.append("Thiếu dữ liệu đa năm liên tục")
        elif missing_years:
            consistency_issues.append(
                "Thiếu dữ liệu cho các năm: " + ", ".join(map(str, missing_years))
            )

        return TemporalAnalysisResult(
            company=company,
            metric=metric,
            timeline=timeline_points,
            yoy_changes=yoy_changes,
            baseline_to_current_change=baseline_delta,
            reporting_consistency=(
                "limited_data"
                if len(timeline_points) < 2
                else "gaps_detected"
                if missing_years
                else "consistent"
            ),
            consistency_issues=consistency_issues,
        )

    def run_temporal_analysis(
        self,
        company: str,
        store: Store | None = None,
        metric: str = "scope_1_emissions",
        document_ids: list[str] | None = None,
        facts: list[ESGFact] | None = None,
    ) -> TemporalAnalysisResult:
        """Chạy trên fact accepted; không trích xuất hoặc suy luận từ chunk online."""
        if facts is not None:
            return self.analyze(company=company, facts=facts, metric=metric)

        if store is None:
            return TemporalAnalysisResult(
                company=company,
                metric=metric,
                timeline=[],
                yoy_changes=[],
                baseline_to_current_change=None,
                reporting_consistency="limited_data",
                consistency_issues=["Chưa có fact accepted hoặc kho dữ liệu"],
            )

        repository = FactRepository(store)
        accepted_facts = self._query_metric_aliases(
            repository=repository,
            company=company,
            metric=metric,
            document_ids=document_ids,
        )
        return self.analyze(company=company, facts=accepted_facts, metric=metric)

    def _query_metric_aliases(
        self,
        repository: FactRepository,
        company: str,
        metric: str,
        document_ids: list[str] | None = None,
    ) -> list[ESGFact]:
        """Đọc accepted facts theo alias và loại trùng trước khi phân tích."""
        facts_by_id: dict[str, ESGFact] = {}
        aliases = self._metric_aliases(metric)
        scoped_documents = document_ids or [None]
        for alias in aliases:
            for document_id in scoped_documents:
                facts = repository.query_facts(
                    company=company,
                    metric=alias,
                    document_id=document_id,
                )
                for fact in facts:
                    key = fact.fact_id or (
                        f"{fact.document_id}:{fact.metric}:{self._fact_year(fact)}"
                    )
                    facts_by_id[key] = fact
        return list(facts_by_id.values())
