"""Rule engine sàng lọc tín hiệu cần chuyên gia kiểm tra thêm."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.models import Citation, ESGFact, GreenwashingScreeningResult, ScreeningSignal
from app.rubric import (
    ASSURANCE_PATTERN,
    BASELINE_PATTERN,
    METRIC_PATTERN,
    NEGATED_ASSURANCE_PATTERN,
    NEGATED_BASELINE_PATTERN,
    NEGATED_PERFORMANCE_PATTERN,
    TARGET_PATTERN,
    VAGUE_WORDS,
)

SCREENING_RULES: dict[str, dict[str, Any]] = {
    "TARGET_NO_BASELINE": {
        "weight": 2,
        "severity": "medium",
        "category": "target_credibility",
        "rule": "target_present AND baseline_absent",
        "message": "Có mục tiêu giảm phát thải nhưng thiếu năm cơ sở (Baseline year).",
    },
    "TARGET_NO_INTERIM": {
        "weight": 1,
        "severity": "low",
        "category": "target_credibility",
        "rule": "target_present AND interim_absent",
        "message": "Thiếu lộ trình mục tiêu trung gian ngắn/trung hạn trước 2050.",
    },
    "NO_QUANTITATIVE_METRICS": {
        "weight": 2,
        "severity": "medium",
        "category": "evidence_quality",
        "rule": "metrics_count == 0",
        "message": "Toàn bộ bằng chứng mới ở mức mô tả định tính, thiếu số liệu đo lường.",
    },
    "EXPLICIT_NO_ASSURANCE": {
        "weight": 2,
        "severity": "medium",
        "category": "evidence_quality",
        "rule": "assurance_negated",
        "message": "Báo cáo ghi nhận rõ KHÔNG ĐƯỢC kiểm toán hoặc bảo đảm độc lập.",
    },
    "NO_ASSURANCE_FOUND": {
        "weight": 1,
        "severity": "low",
        "category": "evidence_quality",
        "rule": "assurance_absent",
        "message": "Chưa tìm thấy phạm vi bảo đảm độc lập cho báo cáo.",
    },
    "TARGET_MISSED_OR_EMISSIONS_INCREASED": {
        "weight": 2,
        "severity": "medium",
        "category": "evidence_quality",
        "rule": "performance_negated",
        "message": "Ghi nhận mục tiêu không đạt hoặc phát thải tăng.",
    },
    "HIGH_VAGUE_NARRATIVE_RATIO": {
        "weight": 2,
        "severity": "medium",
        "category": "narrative_risk",
        "rule": "vague_count > metrics * 1.5",
        "message": "Mật độ ngôn ngữ tham vọng vượt trội so với số liệu chứng minh.",
    },
}


class GreenwashingScreeningService:
    """Tạo tín hiệu sàng lọc có rule, mức độ và evidence riêng cho từng tín hiệu."""

    def __init__(self, rules: dict[str, dict[str, Any]] | None = None):
        self.rules = rules or SCREENING_RULES

    def screen(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> GreenwashingScreeningResult:
        text = " ".join(item.excerpt.lower() for item in citations)
        metrics = max(
            len(METRIC_PATTERN.findall(text)),
            sum(1 for fact in facts if fact.value is not None),
        )
        all_ids = [_citation_key(citation) for citation in citations]
        target_ids = [
            _citation_key(citation)
            for citation in citations
            if TARGET_PATTERN.search(citation.excerpt)
            or re.search(
                r"\b(?:net[ -]?zero|baseline|pathway|goal)\b",
                citation.excerpt,
                re.IGNORECASE,
            )
        ]
        metric_ids = [
            _citation_key(citation)
            for citation in citations
            if METRIC_PATTERN.search(citation.excerpt)
        ]
        assurance_ids = [
            _citation_key(citation)
            for citation in citations
            if ASSURANCE_PATTERN.search(citation.excerpt)
            or NEGATED_ASSURANCE_PATTERN.search(citation.excerpt)
        ]

        signals: list[ScreeningSignal] = []
        target_signals: list[str] = []
        evidence_signals: list[str] = []
        narrative_signals: list[str] = []

        has_target = bool(TARGET_PATTERN.search(text)) or any(
            "target" in fact.metric.lower() for fact in facts
        )
        has_baseline = (
            bool(BASELINE_PATTERN.search(text)) and not bool(NEGATED_BASELINE_PATTERN.search(text))
        ) or any(fact.baseline_year is not None for fact in facts)
        has_interim = any(
            fact.target_year is not None and fact.target_year < 2050 for fact in facts
        ) or any(
            re.search(
                r"\b(?:interim|milestone|near[- ]term|short[- ]term|medium[- ]term)\b"
                r".{0,80}\b20[2-5]\d\b",
                citation.excerpt,
                re.IGNORECASE,
            )
            for citation in citations
        )

        if has_target:
            target_signals.append("✓ Có tuyên bố mục tiêu giảm phát thải/Net-Zero.")
            if has_baseline:
                target_signals.append("✓ Có công bố năm cơ sở (Baseline Year).")
            else:
                self._add_signal(
                    signals,
                    "TARGET_NO_BASELINE",
                    target_ids,
                    missing_requirement="baseline_year",
                )
                target_signals.append("⚠ " + self.rules["TARGET_NO_BASELINE"]["message"])
            if has_interim:
                target_signals.append("✓ Có lộ trình mục tiêu trung hạn.")
            else:
                self._add_signal(
                    signals,
                    "TARGET_NO_INTERIM",
                    target_ids,
                    missing_requirement="interim_target_or_milestone",
                )
                target_signals.append("⚠ " + self.rules["TARGET_NO_INTERIM"]["message"])
        else:
            target_signals.append("ℹ Chưa phát hiện cam kết Net-Zero trong evidence đã truy xuất.")

        if metrics > 0:
            evidence_signals.append(f"✓ Ghi nhận {metrics} số liệu định lượng.")
            if any("scope" in fact.metric.lower() for fact in facts):
                evidence_signals.append("✓ Có fact Scope phát thải có cấu trúc.")
        else:
            self._add_signal(
                signals,
                "NO_QUANTITATIVE_METRICS",
                metric_ids,
                missing_requirement="quantitative_metric",
            )
            evidence_signals.append("⚠ " + self.rules["NO_QUANTITATIVE_METRICS"]["message"])

        has_assurance = bool(ASSURANCE_PATTERN.search(text))
        negated_assurance = bool(NEGATED_ASSURANCE_PATTERN.search(text))
        if has_assurance and not negated_assurance:
            evidence_signals.append("✓ Có tuyên bố External Assurance độc lập từ bên thứ ba.")
        elif negated_assurance:
            self._add_signal(
                signals,
                "EXPLICIT_NO_ASSURANCE",
                assurance_ids,
                missing_requirement="external_assurance",
            )
            evidence_signals.append("⚠ " + self.rules["EXPLICIT_NO_ASSURANCE"]["message"])
        else:
            self._add_signal(
                signals,
                "NO_ASSURANCE_FOUND",
                [],
                missing_requirement="external_assurance",
            )
            evidence_signals.append("⚠ " + self.rules["NO_ASSURANCE_FOUND"]["message"])

        performance_ids = [
            _citation_key(citation)
            for citation in citations
            if NEGATED_PERFORMANCE_PATTERN.search(citation.excerpt)
        ]
        if performance_ids:
            self._add_signal(
                signals,
                "TARGET_MISSED_OR_EMISSIONS_INCREASED",
                performance_ids,
            )
            evidence_signals.append(
                "⚠ " + self.rules["TARGET_MISSED_OR_EMISSIONS_INCREASED"]["message"]
            )

        vague_count = sum(text.count(word) for word in VAGUE_WORDS)
        if metrics > 0 and vague_count > metrics * 1.5:
            self._add_signal(
                signals,
                "HIGH_VAGUE_NARRATIVE_RATIO",
                all_ids,
                message=(
                    f"Mật độ ngôn ngữ tham vọng ({vague_count}) vượt số liệu chứng minh ({metrics})."
                ),
            )
            narrative_signals.append(
                f"⚠ Mật độ ngôn ngữ tham vọng ({vague_count}) vượt số liệu chứng minh ({metrics})."
            )
        elif vague_count > 0:
            narrative_signals.append(f"ℹ Ghi nhận {vague_count} từ ngữ tham vọng.")

        score = sum(self.rules.get(signal.code, {}).get("weight", 1) for signal in signals)
        risk_level: Literal["LOW", "MEDIUM", "HIGH"] = (
            "HIGH" if score >= 5 else "MEDIUM" if score >= 2 else "LOW"
        )
        priority: Literal["LOW_SIGNAL", "MEDIUM_SIGNAL", "HIGH_SIGNAL"] = {
            "LOW": "LOW_SIGNAL",
            "MEDIUM": "MEDIUM_SIGNAL",
            "HIGH": "HIGH_SIGNAL",
        }[risk_level]
        summary = (
            f"Mức ưu tiên sàng lọc: {priority}. "
            "Đây là tín hiệu heuristic để chuyên gia đối soát, không phải xác suất hay kết luận pháp lý."
        )
        return GreenwashingScreeningResult(
            risk_level=risk_level,
            screening_priority=priority,
            signals=signals,
            target_credibility_signals=target_signals,
            evidence_quality_signals=evidence_signals,
            narrative_risk_signals=narrative_signals,
            all_signals=target_signals + evidence_signals + narrative_signals,
            summary=summary,
        )

    def _add_signal(
        self,
        signals: list[ScreeningSignal],
        code: str,
        evidence_ids: list[str],
        missing_requirement: str | None = None,
        message: str | None = None,
    ) -> None:
        rule = self.rules[code]
        signals.append(
            ScreeningSignal(
                code=code,
                category=rule["category"],
                severity=rule["severity"],
                message=message or rule["message"],
                evidence_ids=evidence_ids,
                rule=rule["rule"],
                missing_requirement=missing_requirement,
            )
        )


def _citation_key(citation: Citation) -> str:
    """Định danh evidence ổn định, không dùng numeric chunk id làm provenance."""
    return (
        citation.evidence_id
        or citation.stable_chunk_id
        or (
            f"{citation.document_id}:p{citation.page}:{citation.block_id or citation.chunk_id or 'text'}"
        )
    )
