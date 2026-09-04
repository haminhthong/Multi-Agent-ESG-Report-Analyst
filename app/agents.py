import re
from io import BytesIO
from typing import BinaryIO, Literal

from app.models import (
    AnalysisResponse,
    Citation,
    CriterionCitationRef,
    CriterionResult,
    PillarResult,
    RubricCriterion,
)
from app.rubric import (
    ASSURANCE_PATTERN,
    BASELINE_PATTERN,
    CRITERIA_DEFINITIONS,
    METRIC_PATTERN,
    NEGATED_ASSURANCE_PATTERN,
    NEGATED_BASELINE_PATTERN,
    NEGATED_PERFORMANCE_PATTERN,
    RUBRICS,
    TARGET_PATTERN,
    VAGUE_WORDS,
    YEAR_PATTERN,
    PillarRubric,
)
from app.store import Store


class DocumentAgent:
    """Agent 1: Document Ingestion & Page Preservation Agent.

    Nhiệm vụ: Trích xuất văn bản từ tệp PDF gốc và đảm bảo bảo toàn chính xác
    chỉ số trang (page number) cho từng trang dữ liệu, làm cơ sở truy xuất citation.
    """

    @staticmethod
    def extract_pdf(source: bytes | BinaryIO) -> list[tuple[int, str]]:
        """Đọc tệp PDF từ dữ liệu bytes hoặc file stream và trả danh sách (số_trang, nội_dung_văn_bản)."""

        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(PdfReader(stream).pages, start=1)
        ]


class RetrievalAgent:
    """Agent 2: Query Expansion & Page Evidence Retrieval Agent.

    Nhiệm vụ:
    1. Lập kế hoạch mở rộng truy vấn (Query Expansion) bằng cách bổ sung các từ khóa ngành ESG liên quan.
    2. Thực thi tìm kiếm full-text bằng BM25 trên SQLite FTS5 để lấy các đoạn văn bản bằng chứng.
    3. Gửi danh sách citation tới EvidenceValidator để lọc nhiễu.
    """

    def __init__(self, store: Store):
        self.store = store

    def plan_query(self, question: str) -> str:
        """Bổ sung các thuật ngữ chủ đề liên quan của 3 trụ cột E/S/G vào câu hỏi ban đầu để tối ưu hóa Retrieval."""

        lowered = question.lower()
        topics = [
            topic
            for rubric in RUBRICS.values()
            if _contains_any(lowered, rubric.topics)
            for topic in rubric.topics
        ]
        if not topics:
            topics = [topic for rubric in RUBRICS.values() for topic in rubric.topics]
        return " ".join((question, *topics, "target baseline performance assurance metrics"))

    def run(self, query: str, top_k: int, document_ids: list[str] | None = None) -> list[Citation]:
        """Thực thi truy xuất, chuẩn hóa kết quả thành các đối tượng Citation và xác thực qua EvidenceValidator."""

        citations = [
            Citation(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_name=row["name"],
                page=row["page"],
                excerpt=" ".join(row["text"].split())[:700],
                score=round(1 / (1 + abs(row["rank"])), 4),
            )
            for row in self.store.search(self.plan_query(query), top_k, document_ids)
        ]
        return EvidenceValidator.validate(citations)


class EvidenceValidator:
    """Component Thẩm định Bằng chứng (Evidence Citation Validator).

    Nhiệm vụ: Kiểm tra độc lập chất lượng của danh sách citation:
    - Loại bỏ citation sai số trang (< 1).
    - Loại bỏ các đoạn văn bản rác hoặc quá ngắn (< 3 từ).
    - Loại bỏ các đoạn trùng lặp nội dung dựa trên chữ ký (document_id, page, normalized_text_prefix).
    """

    @staticmethod
    def validate(citations: list[Citation]) -> list[Citation]:
        """Thực thi lọc và đánh dấu `validated = True` cho các citation đủ tiêu chuẩn."""
        valid: list[Citation] = []
        seen: set[tuple[str, int, str]] = set()
        for citation in citations:
            normalized = re.sub(r"\W+", " ", citation.excerpt.lower()).strip()
            signature = (citation.document_id, citation.page, normalized[:160])
            if citation.page < 1 or len(normalized.split()) < 3 or signature in seen:
                continue
            seen.add(signature)
            citation.validated = True
            valid.append(citation)
        return valid


class ESGAnalysisAgent:
    """Agent 3: ESG Coverage Evaluation & Screening Signals Agent.

    Nhiệm vụ:
    1. Đánh giá mức độ công bố thông tin (Disclosure Coverage) minh bạch giải thích được = (số tiêu chí tìm thấy / tổng tiêu chí) * 100.
    2. Đánh giá chất lượng bằng chứng (Evidence Quality) và độ đầy đủ của số liệu (Data Completeness).
    3. Sàng lọc tín hiệu cần chuyên gia kiểm tra (Screening Signals) dựa trên các quy tắc minh bạch.
    """

    def run(self, citations: list[Citation]) -> tuple[list[PillarResult], float, list[str]]:
        """Phân tích các trụ cột E, S, G và sàng lọc các tín hiệu cần kiểm tra."""

        pillars = [self._score_pillar(name, rubric, citations) for name, rubric in RUBRICS.items()]
        signals = self._detect_screening_signals(citations)
        overall_coverage = (
            round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1)
            if pillars
            else 0.0
        )
        return pillars, overall_coverage, signals

    def _score_pillar(
        self, name: str, rubric: PillarRubric, citations: list[Citation]
    ) -> PillarResult:
        """Thực thi đánh giá chi tiết cho một trụ cột (E/S/G)."""

        evidence = [
            item for item in citations if _contains_any(item.excerpt.lower(), rubric.topics)
        ]
        text = " ".join(item.excerpt.lower() for item in evidence)

        # Đánh giá theo cấu trúc CRITERIA_DEFINITIONS
        pillar_criteria = [c for c in CRITERIA_DEFINITIONS if c.pillar == name]
        criteria_results: list[CriterionResult] = []
        found_count = 0

        for criterion in pillar_criteria:
            res = self._evaluate_criterion(criterion, evidence)
            criteria_results.append(res)
            if res.status == "found":
                found_count += 1

        total_criteria = len(pillar_criteria) if pillar_criteria else len(rubric.criteria)
        disclosure_coverage = (
            round((found_count / total_criteria) * 100, 1) if total_criteria > 0 else 0.0
        )

        metrics = len(METRIC_PATTERN.findall(text))
        data_completeness = round(min(100.0, (metrics / max(1, total_criteria)) * 50.0), 1)

        quality_checks = [
            bool(METRIC_PATTERN.search(text)),
            bool(YEAR_PATTERN.search(text)),
            bool(BASELINE_PATTERN.search(text)) and not bool(NEGATED_BASELINE_PATTERN.search(text)),
            bool(ASSURANCE_PATTERN.search(text)) and not bool(NEGATED_ASSURANCE_PATTERN.search(text)),
        ]
        evidence_quality = round((sum(quality_checks) / len(quality_checks)) * 100, 1) if evidence else 0.0
        confidence = round(min(1.0, len(evidence) / 4) * (evidence_quality / 100.0), 2)

        findings = [
            f"Hệ thống tìm thấy bằng chứng cho {found_count}/{total_criteria} tiêu chí thuộc trụ cột {name}.",
            f"Ghi nhận {metrics} số liệu định lượng có đơn vị đo lường.",
        ]

        risks = []
        if not evidence:
            risks.append(
                f"Không tìm thấy đoạn văn bản bằng chứng liên quan đến trụ cột {name} trong các đoạn đã truy xuất."
            )
        elif metrics == 0:
            risks.append("Các bằng chứng đã tìm thấy mới ở dạng mô tả định tính, thiếu số liệu đo lường cụ thể.")
        if evidence and (not ASSURANCE_PATTERN.search(text) or NEGATED_ASSURANCE_PATTERN.search(text)):
            risks.append("Chưa tìm thấy tuyên bố bảo đảm độc lập (External Assurance) cho dữ liệu này.")

        return PillarResult(
            pillar=name,
            score=disclosure_coverage,
            disclosure_coverage=disclosure_coverage,
            evidence_quality=evidence_quality,
            data_completeness=data_completeness,
            confidence=confidence,
            criteria_results=criteria_results,
            findings=findings,
            risks=risks,
            citations=evidence[:4],
        )

    def _evaluate_criterion(
        self, criterion: RubricCriterion, citations: list[Citation]
    ) -> CriterionResult:
        """Đánh giá trạng thái và chi tiết của 1 tiêu chí ESG dựa trên tập citation."""

        for cite in citations:
            text = cite.excerpt.lower()

            # Kiểm tra từ khóa tiêu chí
            matched_keywords = [
                req for req in criterion.required_evidence if req in text
            ] or [unit for unit in criterion.metric_units if unit.lower() in text]

            if matched_keywords:
                # Kiểm tra xem có phủ định hay không
                if NEGATED_PERFORMANCE_PATTERN.search(text):
                    return CriterionResult(
                        criterion_id=criterion.id,
                        status="contradicts",
                        citation=CriterionCitationRef(
                            document=cite.document_name, page=cite.page, excerpt=cite.excerpt[:200]
                        ),
                        confidence=0.8,
                    )

                # Tìm số liệu kèm đơn vị
                metric_match = METRIC_PATTERN.search(text)
                value = metric_match.group(0) if metric_match else None
                year_match = YEAR_PATTERN.search(text)
                year = int(year_match.group(0)) if year_match else None

                return CriterionResult(
                    criterion_id=criterion.id,
                    status="found",
                    value=value,
                    unit=criterion.metric_units[0] if criterion.metric_units else None,
                    reporting_year=year,
                    citation=CriterionCitationRef(
                        document=cite.document_name, page=cite.page, excerpt=cite.excerpt[:200]
                    ),
                    confidence=0.9,
                )

        return CriterionResult(
            criterion_id=criterion.id,
            status="not_found",
            confidence=0.0,
        )

    def _detect_screening_signals(self, citations: list[Citation]) -> list[str]:
        """Sàng lọc các tín hiệu nghi vấn cần chuyên gia kiểm tra (Screening Signals)."""

        text = " ".join(item.excerpt.lower() for item in citations)
        metrics = len(METRIC_PATTERN.findall(text))
        signals: list[str] = []

        if sum(text.count(w) for w in VAGUE_WORDS) > metrics:
            signals.append("Tỷ lệ ngôn ngữ định hướng tham vọng cao hơn số liệu bằng chứng định lượng.")
        if TARGET_PATTERN.search(text) and (
            not BASELINE_PATTERN.search(text) or NEGATED_BASELINE_PATTERN.search(text)
        ):
            signals.append("Có mục tiêu giảm phát thải/bền vững nhưng chưa tìm thấy căn cứ năm cơ sở (Baseline year).")
        if TARGET_PATTERN.search(text) and metrics == 0:
            signals.append("Tuyên bố mục tiêu chưa đi kèm số liệu hiệu suất đo lường hiện tại.")
        if citations and (not ASSURANCE_PATTERN.search(text) or NEGATED_ASSURANCE_PATTERN.search(text)):
            signals.append("Chưa tìm thấy phạm vi bảo đảm độc lập (External Assurance) cho báo cáo.")
        if NEGATED_PERFORMANCE_PATTERN.search(text):
            signals.append("Ghi nhận thông tin không đạt mục tiêu hoặc phát thải gia tăng.")
        if not citations:
            signals.append("Chưa truy xuất được bằng chứng nguồn để thẩm định.")

        return signals


class ExplanationAgent:
    """Agent 4: Evidence-Grounded Explanation Synthesis Agent.

    Nhiệm vụ: Tổng hợp câu giải thích chính văn KHÔNG hallucination,
    chỉ căn cứ duy nhất trên kết quả chấm điểm và các citation đã qua xác thực.
    """

    @staticmethod
    def run(
        mode: Literal["qa", "audit"],
        pillars: list[PillarResult],
        overall_coverage: float,
        citations: list[Citation],
        question: str,
    ) -> str:
        """Tạo chuỗi giải thích ngắn gọn, chuyên nghiệp kèm danh sách nguồn tài liệu và trang tương ứng."""

        sources = (
            ", ".join(f"[{item.document_name}, trang {item.page}]" for item in citations[:6])
            or "không có citation"
        )

        if mode == "qa":
            if not citations:
                return (
                    f"Hệ thống không tìm thấy bằng chứng hợp lệ trong tài liệu để trả lời cho câu hỏi: '{question}'. "
                    "Kết quả này phản ánh khoảng trống thông tin trong các trang đã truy xuất."
                )
            return (
                f"Trả lời dựa trên bằng chứng truy xuất cho câu hỏi '{question}': "
                f"Tìm thấy {len(citations)} đoạn văn bản nguồn tại {sources}. "
                "Thông tin phản ánh mức độ công bố thực tế trong tệp PDF gốc."
            )
        else:
            scores_str = ", ".join(
                f"{item.pillar}: coverage {item.disclosure_coverage}% (quality {item.evidence_quality}%)"
                for item in pillars
            )
            return (
                f"Hệ thống tìm thấy bằng chứng công bố cho {overall_coverage}% tổng số tiêu chí E/S/G kiểm tra. "
                f"Chi tiết từng trụ cột: {scores_str}. Nguồn trích dẫn: {sources}. "
                "Lưu ý: Kết quả phản ánh mức độ công bố thông tin trong các đoạn đã truy xuất, không phản ánh hiệu suất ESG tổng thể của doanh nghiệp."
            )


class SupervisorAgent:
    """Agent 5: Pipeline Supervisor & Dual-Mode Orchestrator.

    Nhiệm vụ:
    - Điều phối 2 chế độ độc lập: Evidence Q&A và Full ESG Audit.
    - Ghi vết thực thi (Execution Trace).
    - Cung cấp cảnh báo giới hạn (Limitations).
    """

    def __init__(self, store: Store):
        self.retrieval = RetrievalAgent(store)
        self.analysis = ESGAnalysisAgent()
        self.explanation = ExplanationAgent()

    def run(
        self,
        question: str,
        top_k: int = 6,
        document_ids: list[str] | None = None,
        mode: Literal["qa", "audit"] = "qa",
    ) -> AnalysisResponse:
        """Thực thi luồng làm việc theo chế độ được chọn."""

        trace = [
            f"Supervisor: Khởi tạo luồng làm việc ở chế độ '{mode.upper()}'",
            "Retrieval Agent: Thực thi truy xuất bằng chứng",
        ]

        if mode == "qa":
            citations = self.retrieval.run(question, top_k, document_ids)
            trace.append(f"Evidence Validator: Xác thực {len(citations)} citation phù hợp")

            pillars, overall_coverage, signals = self.analysis.run(citations)
            answer = self.explanation.run("qa", pillars, overall_coverage, citations, question)
            trace.append("Explanation Agent: Tổng hợp câu trả lời kèm citation")

            limitations = [
                "Câu trả lời được tổng hợp duy nhất từ các đoạn bằng chứng đã truy xuất.",
                "Nếu thông tin nằm ngoài phạm vi Top-K đoạn được tìm kiếm, hệ thống sẽ không thể đưa vào câu trả lời.",
            ]

            avg_quality, avg_completeness, avg_conf = _aggregate_pillar_metrics(pillars)

            return AnalysisResponse(
                mode="qa",
                answer=answer,
                disclosure_coverage=overall_coverage,
                evidence_quality=avg_quality,
                data_completeness=avg_completeness,
                confidence=avg_conf,
                screening_signals=signals,
                pillars=pillars,
                citations=citations,
                trace=trace,
                limitations=limitations,
            )

        else:
            # Full ESG Audit mode: chạy truy xuất theo từng bộ từ khóa tiêu chí E/S/G
            trace.append("Audit Engine: Thực thi kiểm tra theo bộ tiêu chí chuẩn E/S/G")

            audit_query = f"{question} scope emissions target baseline energy safety board governance assurance"
            citations = self.retrieval.run(audit_query, max(top_k, 12), document_ids)
            trace.append(f"Evidence Validator: Lọc và xác thực {len(citations)} đoạn bằng chứng cho Audit")

            pillars, overall_coverage, signals = self.analysis.run(citations)
            trace.append("ESG Analysis Agent: Đã hoàn tất đánh giá coverage và tín hiệu screening")

            answer = self.explanation.run("audit", pillars, overall_coverage, citations, question)
            trace.append("Explanation Agent: Hoàn tất lập báo cáo Audit với limitation")

            limitations = [
                "Báo cáo chỉ phản ánh mức độ công bố thông tin (disclosure coverage) trong các tài liệu đã lập chỉ mục.",
                "Kết quả không đại diện cho điểm hiệu suất hoạt động ESG thực tế của doanh nghiệp.",
                "Các tín hiệu cảnh báo (screening signals) cần được chuyên gia thẩm định trực tiếp trước khi kết luận.",
            ]

            avg_quality, avg_completeness, avg_conf = _aggregate_pillar_metrics(pillars)

            return AnalysisResponse(
                mode="audit",
                answer=answer,
                disclosure_coverage=overall_coverage,
                evidence_quality=avg_quality,
                data_completeness=avg_completeness,
                confidence=avg_conf,
                screening_signals=signals,
                pillars=pillars,
                citations=citations,
                trace=trace,
                limitations=limitations,
            )


def _aggregate_pillar_metrics(pillars: list[PillarResult]) -> tuple[float, float, float]:
    """Hàm phụ trợ tính trung bình chất lượng bằng chứng, độ đầy đủ số liệu và độ tin cậy giữa các trụ cột."""
    if not pillars:
        return 0.0, 0.0, 0.0
    avg_quality = round(sum(p.evidence_quality for p in pillars) / len(pillars), 1)
    avg_completeness = round(sum(p.data_completeness for p in pillars) / len(pillars), 1)
    avg_conf = round(sum(p.confidence for p in pillars) / len(pillars), 2)
    return avg_quality, avg_completeness, avg_conf



def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Hàm phụ trợ kiểm tra xem đoạn văn bản có chứa ít nhất một từ khóa trong danh sách hay không."""
    return any(keyword in text for keyword in keywords)

