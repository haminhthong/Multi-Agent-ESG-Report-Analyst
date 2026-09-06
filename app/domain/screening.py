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

# Cấu hình tường minh các quy tắc sàng lọc greenwashing kèm trọng số và độ nghiêm trọng
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
        "message": "Toàn bộ báo cáo mới ở mức mô tả định tính, hoàn toàn thiếu số liệu đo lường.",
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
        "message": "Chưa tìm thấy phạm vi bảo đảm độc lập (External Assurance) cho báo cáo.",
    },
    "TARGET_MISSED_OR_EMISSIONS_INCREASED": {
        "weight": 2,
        "severity": "medium",
        "category": "evidence_quality",
        "rule": "performance_negated",
        "message": "Ghi nhận thông tin không đạt mục tiêu giảm phát thải hoặc phát thải tăng.",
    },
    "HIGH_VAGUE_NARRATIVE_RATIO": {
        "weight": 2,
        "severity": "medium",
        "category": "narrative_risk",
        "rule": "vague_count > metrics * 1.5",
        "message": "Mật độ từ ngữ định hướng tham vọng vượt trội so với số liệu chứng minh.",
    },
}


class GreenwashingScreeningService:
    """Dịch vụ chuyên biệt sàng lọc rủi ro Greenwashing có cấu trúc và giải thích được.

    Đặc điểm:
    - Tách biệt hoàn toàn khỏi rubric audit và so sánh đa công ty.
    - Sử dụng Rule Engine cấu hình hóa (config-driven weights & severity).
    - Tạo các đối tượng ScreeningSignal rõ ràng (code, rule, category, severity, message).
    - Tương thích ngược tuyệt đối với các chuỗi thông báo truyền thống.
    """

    def __init__(self, rules: dict[str, dict[str, Any]] | None = None):
        self.rules = rules or SCREENING_RULES

    def screen(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> GreenwashingScreeningResult:
        """Sàng lọc rủi ro Greenwashing đa chiều (Target Credibility, Evidence Quality, Narrative Risk)."""
        text = " ".join(item.excerpt.lower() for item in citations)
        metrics = len(METRIC_PATTERN.findall(text))
        fact_metric_count = sum(1 for f in facts if f.value is not None)
        metrics = max(metrics, fact_metric_count)

        signals: list[ScreeningSignal] = []
        target_signals: list[str] = []
        evidence_signals: list[str] = []
        narrative_signals: list[str] = []

        citation_ids = [str(c.chunk_id) for c in citations if c.chunk_id is not None]

        # 1. Target Credibility
        has_target = bool(TARGET_PATTERN.search(text)) or any(
            "target" in f.metric.lower() for f in facts
        )
        has_baseline = (
            bool(BASELINE_PATTERN.search(text)) and not bool(NEGATED_BASELINE_PATTERN.search(text))
        ) or any(f.baseline_year is not None for f in facts)
        has_interim = bool(re.search(r"\b(?:2025|2030|interim|milestone)\b", text))

        if has_target:
            target_signals.append(
                "✓ Doanh nghiệp có tuyên bố cam kết mục tiêu giảm phát thải/Net-Zero."
            )
            if has_baseline:
                target_signals.append(
                    "✓ Công bố năm cơ sở (Baseline Year) làm mốc đối sánh rõ ràng."
                )
            else:
                rule_info = self.rules["TARGET_NO_BASELINE"]
                signals.append(
                    ScreeningSignal(
                        code="TARGET_NO_BASELINE",
                        category=rule_info["category"],
                        severity=rule_info["severity"],
                        message=rule_info["message"],
                        evidence_ids=citation_ids,
                        rule=rule_info["rule"],
                    )
                )
                target_signals.append("⚠ " + rule_info["message"])

            if has_interim:
                target_signals.append(
                    "✓ Có lộ trình mục tiêu trung hạn (Interim target / 2030 milestone)."
                )
            else:
                rule_info = self.rules["TARGET_NO_INTERIM"]
                signals.append(
                    ScreeningSignal(
                        code="TARGET_NO_INTERIM",
                        category=rule_info["category"],
                        severity=rule_info["severity"],
                        message=rule_info["message"],
                        evidence_ids=citation_ids,
                        rule=rule_info["rule"],
                    )
                )
                target_signals.append("⚠ " + rule_info["message"])
        else:
            target_signals.append("ℹ Chưa phát hiện cam kết Net-Zero trong các đoạn đã truy xuất.")

        # 2. Evidence Quality
        if metrics > 0:
            evidence_signals.append(
                f"✓ Ghi nhận {metrics} số liệu định lượng có kèm đơn vị đo lường cụ thể."
            )
            if any("scope" in f.metric.lower() for f in facts):
                evidence_signals.append(
                    "✓ Trích xuất được số liệu Scope phát thải có cấu trúc từ bằng chứng."
                )
        else:
            rule_info = self.rules["NO_QUANTITATIVE_METRICS"]
            signals.append(
                ScreeningSignal(
                    code="NO_QUANTITATIVE_METRICS",
                    category=rule_info["category"],
                    severity=rule_info["severity"],
                    message=rule_info["message"],
                    evidence_ids=citation_ids,
                    rule=rule_info["rule"],
                )
            )
            evidence_signals.append("⚠ " + rule_info["message"])

        has_assurance = bool(ASSURANCE_PATTERN.search(text))
        negated_assurance = bool(NEGATED_ASSURANCE_PATTERN.search(text))
        if has_assurance and not negated_assurance:
            evidence_signals.append(
                "✓ Có tuyên bố bảo đảm độc lập từ bên thứ ba (External Assurance)."
            )
        elif negated_assurance:
            rule_info = self.rules["EXPLICIT_NO_ASSURANCE"]
            signals.append(
                ScreeningSignal(
                    code="EXPLICIT_NO_ASSURANCE",
                    category=rule_info["category"],
                    severity=rule_info["severity"],
                    message=rule_info["message"],
                    evidence_ids=citation_ids,
                    rule=rule_info["rule"],
                )
            )
            evidence_signals.append("⚠ " + rule_info["message"])
        else:
            rule_info = self.rules["NO_ASSURANCE_FOUND"]
            signals.append(
                ScreeningSignal(
                    code="NO_ASSURANCE_FOUND",
                    category=rule_info["category"],
                    severity=rule_info["severity"],
                    message=rule_info["message"],
                    evidence_ids=citation_ids,
                    rule=rule_info["rule"],
                )
            )
            evidence_signals.append("⚠ " + rule_info["message"])

        if NEGATED_PERFORMANCE_PATTERN.search(text):
            rule_info = self.rules["TARGET_MISSED_OR_EMISSIONS_INCREASED"]
            signals.append(
                ScreeningSignal(
                    code="TARGET_MISSED_OR_EMISSIONS_INCREASED",
                    category=rule_info["category"],
                    severity=rule_info["severity"],
                    message=rule_info["message"],
                    evidence_ids=citation_ids,
                    rule=rule_info["rule"],
                )
            )
            evidence_signals.append("⚠ " + rule_info["message"])

        # 3. Narrative Risk
        vague_count = sum(text.count(w) for w in VAGUE_WORDS)
        if metrics > 0 and vague_count > metrics * 1.5:
            rule_info = self.rules["HIGH_VAGUE_NARRATIVE_RATIO"]
            signals.append(
                ScreeningSignal(
                    code="HIGH_VAGUE_NARRATIVE_RATIO",
                    category=rule_info["category"],
                    severity=rule_info["severity"],
                    message=f"Mật độ từ ngữ định hướng tham vọng ({vague_count}) vượt trội so với số liệu chứng minh ({metrics}).",
                    evidence_ids=citation_ids,
                    rule=rule_info["rule"],
                )
            )
            narrative_signals.append(
                f"⚠ Mật độ từ ngữ định hướng tham vọng ({vague_count}) vượt trội so với số liệu chứng minh ({metrics})."
            )
        elif vague_count > 0:
            narrative_signals.append(
                f"ℹ Ghi nhận {vague_count} từ ngữ mang tính định hướng tham vọng."
            )

        # Tính tổng điểm cảnh báo từ trọng số cấu hình
        total_warning_score = sum(self.rules.get(s.code, {}).get("weight", 1) for s in signals)

        # Phân loại Risk Level
        risk_level: Literal["LOW", "MEDIUM", "HIGH"]
        if total_warning_score >= 5:
            risk_level = "HIGH"
        elif total_warning_score >= 2:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        summary = (
            f"Sàng lọc rủi ro Greenwashing ở mức: {risk_level}. "
            "Lưu ý: Đây là chỉ số đánh giá rủi ro công bố (screening risk) nhằm khuyến nghị chuyên gia đối soát, "
            "không phải kết luận pháp lý hay khẳng định doanh nghiệp gian lận."
        )

        all_signals = target_signals + evidence_signals + narrative_signals
        return GreenwashingScreeningResult(
            risk_level=risk_level,
            signals=signals,
            target_credibility_signals=target_signals,
            evidence_quality_signals=evidence_signals,
            narrative_risk_signals=narrative_signals,
            all_signals=all_signals,
            summary=summary,
        )
