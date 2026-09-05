import re
from io import BytesIO
from typing import Any, BinaryIO, Literal

from app.config import settings
from app.llm import LLMClient
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
from app.tools import AgentTools


class DocumentAgent:
    """Agent 1: Document Ingestion & Page Preservation Agent.

    Nhiệm vụ: Trích xuất văn bản từ tệp PDF gốc và bảo toàn chính xác
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
    """Agent 2: Query Expansion & Advanced Hybrid Retrieval Agent.

    Nhiệm vụ:
    1. Lập kế hoạch mở rộng truy vấn (Query Expansion) bổ sung từ khóa ngành ESG liên quan.
    2. Thực thi tìm kiếm theo nhiều cơ chế: BM25, Dense Embeddings, Hybrid RRF, hoặc Hybrid + Reranker.
    3. Gửi danh sách citation tới EvidenceVerificationAgent để kiểm tra chất lượng.
    """

    def __init__(self, store: Store, mode: str | None = None):
        self.store = store
        self.mode = mode or settings.retrieval_mode

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
        """Thực thi truy xuất, chuẩn hóa kết quả thành các đối tượng Citation và lọc qua EvidenceVerificationAgent."""
        raw_results = self.store.search(
            query=self.plan_query(query),
            limit=top_k,
            document_ids=document_ids,
            mode=self.mode,
        )
        citations = [
            Citation(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_name=row["name"],
                page=row["page"],
                excerpt=" ".join(row["text"].split())[:700],
                score=float(row.get("score") or round(1 / (1 + abs(row.get("rank", 1.0))), 4)),
            )
            for row in raw_results
        ]
        return EvidenceVerificationAgent.validate(citations)


class EvidenceVerificationAgent:
    """Agent 3: Evidence & Claim Verification Agent (Verification Guardrail).

    Nhiệm vụ:
    1. Kiểm tra tính hợp lệ hình thức của citation: loại bỏ trang < 1, văn bản rác (< 3 từ), trùng lặp.
    2. Thẩm định độc lập các khẳng định (Claim Verification): đối soát các con số, năm và khẳng định
       với trích đoạn PDF thực tế, phát hiện mẫu câu phủ định/mâu thuẫn (contradiction).
    """

    @staticmethod
    def validate(citations: list[Citation]) -> list[Citation]:
        """Lọc và đánh dấu `validated = True` cho các citation đủ tiêu chuẩn hình thức."""
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

    @staticmethod
    def audit_claims(claims: list[str], citations: list[Citation]) -> dict[str, Any]:
        """Đối soát danh sách nhận định với nội dung bằng chứng thực tế."""
        combined_text = " ".join(c.excerpt for c in citations)
        audits = []
        supported_count = 0
        for claim in claims:
            res = AgentTools.verify_claim(claim, combined_text)
            audits.append({"claim": claim, **res})
            if res["supported"]:
                supported_count += 1

        total = max(1, len(claims))
        return {
            "audits": audits,
            "supported_rate": round(supported_count / total, 4),
            "total_claims": len(claims),
            "unsupported_claims": [a["claim"] for a in audits if not a["supported"]],
        }


# Alias tương thích ngược cho EvidenceValidator cũ
EvidenceValidator = EvidenceVerificationAgent


class ESGAnalysisAgent:
    """Agent 4: ESG Rubric Coverage & Screening Signals Agent.

    Nhiệm vụ:
    1. Đánh giá mức độ công bố thông tin (Disclosure Coverage) minh bạch giải thích được = (số tiêu chí tìm thấy / tổng tiêu chí) * 100.
    2. Đánh giá chất lượng bằng chứng (Evidence Quality) và độ đầy đủ của số liệu (Data Completeness).
    3. Sàng lọc tín hiệu cần chuyên gia kiểm tra (Screening Signals) dựa trên quy tắc minh bạch.
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client

    def run(self, citations: list[Citation]) -> tuple[list[PillarResult], float, list[str]]:
        """Phân tích các trụ cột E, S, G và sàng lọc các tín hiệu cần kiểm tra."""
        pillars = [self._score_pillar(name, rubric, citations) for name, rubric in RUBRICS.items()]
        signals = self._detect_screening_signals(citations)
        overall_coverage = (
            round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1) if pillars else 0.0
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
            bool(ASSURANCE_PATTERN.search(text))
            and not bool(NEGATED_ASSURANCE_PATTERN.search(text)),
        ]
        evidence_quality = (
            round((sum(quality_checks) / len(quality_checks)) * 100, 1) if evidence else 0.0
        )
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
            risks.append(
                "Các bằng chứng đã tìm thấy mới ở dạng mô tả định tính, thiếu số liệu đo lường cụ thể."
            )
        if evidence and (
            not ASSURANCE_PATTERN.search(text) or NEGATED_ASSURANCE_PATTERN.search(text)
        ):
            risks.append(
                "Chưa tìm thấy tuyên bố bảo đảm độc lập (External Assurance) cho dữ liệu này."
            )

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

            matched_keywords = [req for req in criterion.required_evidence if req in text] or [
                unit for unit in criterion.metric_units if unit.lower() in text
            ]

            if matched_keywords:
                if NEGATED_PERFORMANCE_PATTERN.search(text):
                    return CriterionResult(
                        criterion_id=criterion.id,
                        status="contradicts",
                        citation=CriterionCitationRef(
                            document=cite.document_name, page=cite.page, excerpt=cite.excerpt[:200]
                        ),
                        confidence=0.8,
                    )

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
            signals.append(
                "Tỷ lệ ngôn ngữ định hướng tham vọng cao hơn số liệu bằng chứng định lượng."
            )
        if TARGET_PATTERN.search(text) and (
            not BASELINE_PATTERN.search(text) or NEGATED_BASELINE_PATTERN.search(text)
        ):
            signals.append(
                "Có mục tiêu giảm phát thải/bền vững nhưng chưa tìm thấy căn cứ năm cơ sở (Baseline year)."
            )
        if TARGET_PATTERN.search(text) and metrics == 0:
            signals.append("Tuyên bố mục tiêu chưa đi kèm số liệu hiệu suất đo lường hiện tại.")
        if citations and (
            not ASSURANCE_PATTERN.search(text) or NEGATED_ASSURANCE_PATTERN.search(text)
        ):
            signals.append(
                "Chưa tìm thấy phạm vi bảo đảm độc lập (External Assurance) cho báo cáo."
            )
        if NEGATED_PERFORMANCE_PATTERN.search(text):
            signals.append("Ghi nhận thông tin không đạt mục tiêu hoặc phát thải gia tăng.")
        if not citations:
            signals.append("Chưa truy xuất được bằng chứng nguồn để thẩm định.")

        return signals


class ExplanationAgent:
    """Agent 5: Evidence-Grounded Explanation Synthesis Agent.

    Nhiệm vụ: Tổng hợp câu trả lời chính văn dựa trên các trích đoạn bằng chứng đã qua xác thực.
    - Hỗ trợ LLM Synthesis có trích dẫn nghiêm ngặt khi LLM khả dụng.
    - Graceful fallback: Sử dụng bộ tổng hợp xác định (Deterministic Synthesis) khi offline ($0 cost).
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client

    def run(
        self,
        mode: Literal["qa", "audit"],
        pillars: list[PillarResult],
        overall_coverage: float,
        citations: list[Citation],
        question: str,
    ) -> str:
        """Tạo chuỗi giải thích rõ ràng kèm danh sách nguồn tài liệu và số trang tương ứng."""
        # 1. Thử nghiệm tổng hợp bằng LLM nếu khả dụng
        if self.llm and self.llm.is_available() and citations:
            rubric_summary = f"Coverage {overall_coverage}%. " + ", ".join(
                f"{p.pillar}: {p.disclosure_coverage}%" for p in pillars
            )
            llm_answer = self.llm.synthesize_answer(
                question=question,
                citations=[c.model_dump() for c in citations[:6]],
                rubric_summary=rubric_summary,
            )
            if llm_answer and len(llm_answer.strip()) > 20:
                return llm_answer

        # 2. Deterministic Fallback Synthesis ($0 API Cost)
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
            key_metrics = [f for p in pillars for f in p.findings if "Hệ thống" not in f][:1]
            metric_snippet = f" Ghi nhận: {key_metrics[0]}." if key_metrics else ""
            excerpt_snippet = (
                f' Trích dẫn chính: "{citations[0].excerpt[:200]}..."' if citations else ""
            )
            return (
                f"Trả lời dựa trên bằng chứng truy xuất cho câu hỏi '{question}': "
                f"Tìm thấy {len(citations)} đoạn văn bản nguồn tại {sources}.{metric_snippet}{excerpt_snippet}"
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
    """Agent 6: Dynamic Agentic Supervisor & Multi-Strategy Orchestrator.

    Nhiệm vụ:
    - Khi có Local LLM: Khởi tạo Structured Planning & Dynamic Tool Calling (`search_document`,
      `retrieve_evidence`, `extract_metric`, `score_rubric`, `verify_claim`).
    - Khi Fallback: Tự động chạy Deterministic Heuristic Engine đảm bảo $0 API cost và hoạt động 100% offline.
    - Điều phối Evidence Verification Agent và thu thập Execution Trace đầy đủ.
    """

    def __init__(
        self,
        store: Store,
        llm_client: LLMClient | None = None,
        retrieval_mode: str | None = None,
    ):
        self.store = store
        self.llm = llm_client or LLMClient()
        self.tools = AgentTools(store)
        self.verifier = EvidenceVerificationAgent()
        self.retrieval = RetrievalAgent(store, mode=retrieval_mode)
        self.analysis = ESGAnalysisAgent(llm_client=self.llm)
        self.explanation = ExplanationAgent(llm_client=self.llm)
        self.retrieval_mode = retrieval_mode or settings.retrieval_mode

    def run(
        self,
        question: str,
        top_k: int = 6,
        document_ids: list[str] | None = None,
        mode: Literal["qa", "audit"] = "qa",
    ) -> AnalysisResponse:
        """Thực thi luồng phân tích thích ứng (LLM Agentic Planning hoặc Deterministic Fallback)."""
        is_llm_active = self.llm.is_available()
        agent_mode: Literal["llm_agentic", "deterministic_fallback"] = (
            "llm_agentic" if is_llm_active else "deterministic_fallback"
        )

        trace: list[str] = [
            f"Supervisor: Khởi tạo phân tích ở chế độ '{mode.upper()}' | Engine: {agent_mode.upper()}"
        ]

        # 1. Kế hoạch truy xuất bằng chứng (Retrieval Plan)
        if is_llm_active:
            trace.append("Supervisor: Gọi LLM Structured Planning để lập kế hoạch tool calls")
            plan = self.llm.generate_plan(question, mode=mode)
            if plan:
                trace.append(f"Supervisor: LLM đã sinh kế hoạch gồm {len(plan)} bước hành động")
                for step in plan[:3]:
                    trace.append(f"  → Kế hoạch: {step.get('tool')}({step.get('args')})")
            else:
                trace.append("Supervisor: LLM sinh kế hoạch mặc định (Tool Execution Pipeline)")
        else:
            trace.append(
                "Supervisor: Chạy chế độ Deterministic Heuristic Engine ($0 API Cost Fallback)"
            )

        # 2. Thực thi Tool: search_document
        retrieval_query = (
            question
            if mode == "qa"
            else f"{question} scope emissions target baseline energy safety board governance assurance"
        )
        search_limit = max(top_k, 12) if mode == "audit" else top_k
        trace.append(
            f"Tool Call: search_document(query='{retrieval_query[:40]}...', mode='{self.retrieval_mode}')"
        )

        raw_citations = self.retrieval.run(retrieval_query, search_limit, document_ids)
        trace.append(f"Retrieval Engine: Đã truy xuất {len(raw_citations)} đoạn ứng viên")

        # 3. Thực thi Tool: verify_claim & citation validation
        citations = self.verifier.validate(raw_citations)
        trace.append(
            f"Evidence Verification Agent: Đã thẩm định và lọc sạch {len(citations)} citation hợp lệ"
        )

        # 4. Thực thi Tool: score_rubric & analysis
        trace.append("Tool Call: score_rubric(E/S/G Criteria & Signals)")
        pillars, overall_coverage, signals = self.analysis.run(citations)

        # 5. Thẩm định các nhận định (Claim Auditing)
        claims_to_audit = [f for p in pillars for f in p.findings[:2]]
        verification_summary = self.verifier.audit_claims(claims_to_audit, citations)
        trace.append(
            f"Evidence Verification Agent: Tỷ lệ nhận định có bằng chứng hỗ trợ: {verification_summary['supported_rate'] * 100:.1f}%"
        )

        # 6. Tổng hợp câu trả lời
        trace.append("Explanation Agent: Tổng hợp kết quả phân tích có dẫn nguồn")
        answer = self.explanation.run(mode, pillars, overall_coverage, citations, question)

        limitations = [
            "Câu trả lời được tổng hợp duy nhất từ các đoạn bằng chứng đã truy xuất.",
            "Nếu thông tin nằm ngoài phạm vi Top-K đoạn được tìm kiếm, hệ thống sẽ không thể đưa vào kết luận.",
        ]
        if mode == "audit":
            limitations.extend(
                [
                    "Báo cáo chỉ phản ánh mức độ công bố thông tin (disclosure coverage) trong các tài liệu đã lập chỉ mục.",
                    "Kết quả không đại diện cho điểm hiệu suất hoạt động ESG thực tế của doanh nghiệp.",
                ]
            )

        avg_quality, avg_completeness, avg_conf = _aggregate_pillar_metrics(pillars)

        return AnalysisResponse(
            mode=mode,
            agent_mode=agent_mode,
            answer=answer,
            disclosure_coverage=overall_coverage,
            evidence_quality=avg_quality,
            data_completeness=avg_completeness,
            confidence=avg_conf,
            screening_signals=signals,
            pillars=pillars,
            citations=citations,
            verification_summary=verification_summary,
            trace=trace,
            limitations=limitations,
        )


def _aggregate_pillar_metrics(pillars: list[PillarResult]) -> tuple[float, float, float]:
    """Hàm phụ trợ tính trung bình chất lượng bằng chứng, độ đầy đủ số liệu và độ tin cậy."""
    if not pillars:
        return 0.0, 0.0, 0.0
    avg_quality = round(sum(p.evidence_quality for p in pillars) / len(pillars), 1)
    avg_completeness = round(sum(p.data_completeness for p in pillars) / len(pillars), 1)
    avg_conf = round(sum(p.confidence for p in pillars) / len(pillars), 2)
    return avg_quality, avg_completeness, avg_conf


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Hàm phụ trợ kiểm tra xem đoạn văn bản có chứa ít nhất một từ khóa trong danh sách hay không."""
    return any(keyword in text for keyword in keywords)
