import re
import time
from io import BytesIO
from typing import Any, BinaryIO, Literal

from app.chunking import HEADING, is_table_content
from app.config import settings
from app.evidence_extractor import EvidenceExtractionAgent
from app.llm import LLMClient
from app.models import (
    AgentTraceStep,
    AnalysisResponse,
    Citation,
    CompanyComparisonCriterion,
    CompanyComparisonResult,
    CriterionCitationRef,
    CriterionResult,
    ESGFact,
    EvidenceConflict,
    EvidenceMatrixRow,
    GreenwashingScreeningResult,
    LayoutBlock,
    PillarResult,
    RetrievalPlan,
    RubricCriterion,
    TemporalAnalysisResult,
    TemporalTrendPoint,
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


# ==============================================================================
# DOCUMENT INTELLIGENCE CAPABILITY
# ==============================================================================
class DocumentIntelligenceAgent:
    """Năng lực Document Intelligence & Thẩm định Cấu trúc Trang (Page Quality Gate).

    Nhiệm vụ:
    1. Tiếp nhận và giải mã cấu trúc tài liệu PDF đa tầng (Native Text, Table, Scanned, Mixed).
    2. Phân loại cấu trúc trang (Page Classification Router).
    3. Trích xuất văn bản theo từng khối LayoutBlock có tọa độ giả lập (bbox), block_type, section và chất lượng.
    4. Bảo toàn tuyệt đối số trang (Page Number) cho toàn bộ pipeline.
    """

    @staticmethod
    def classify_page(text: str, image_count: int = 0) -> str:
        """Phân loại hình thức của một trang PDF."""
        clean_text = " ".join(text.split())
        if len(clean_text) < 40:
            return "scanned_image"
        has_table = is_table_content(text)
        has_text_paragraphs = len(re.split(r"\n\s*\n", text.strip())) >= 2
        if has_table and has_text_paragraphs:
            return "mixed_page"
        if has_table:
            return "table"
        return "native_text"

    @classmethod
    def extract_pdf_blocks(
        cls, source: bytes | BinaryIO, document_id: str = "doc"
    ) -> list[LayoutBlock]:
        """Trích xuất PDF thành danh sách các khối LayoutBlock chi tiết."""
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        reader = PdfReader(stream)
        blocks: list[LayoutBlock] = []
        current_section = "General Information"

        for page_num, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            page_type = cls.classify_page(raw_text)

            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]
            for block_idx, p in enumerate(paragraphs, start=1):
                block_id = f"{document_id}_p{page_num}_b{block_idx}"

                if HEADING.match(p):
                    current_section = p[:100]
                    b_type = "heading"
                elif is_table_content(p):
                    b_type = "table"
                else:
                    b_type = "text"

                clean_words = p.split()
                quality = round(
                    min(1.0, sum(len(w) >= 2 for w in clean_words) / max(1, len(clean_words))), 2
                )
                top_y = min(900, block_idx * 150)
                bbox = [float(top_y), 50.0, float(min(1000, top_y + 120)), 950.0]

                blocks.append(
                    LayoutBlock(
                        document_id=document_id,
                        page=page_num,
                        block_id=block_id,
                        block_type=b_type,
                        section=current_section,
                        text=p,
                        bbox=bbox,
                        source_method="native" if page_type != "scanned_image" else "ocr_candidate",
                        quality_score=quality,
                    )
                )

        return blocks

    @staticmethod
    def extract_pdf(source: bytes | BinaryIO) -> list[tuple[int, str]]:
        """Đọc tệp PDF từ dữ liệu bytes hoặc file stream và trả danh sách (số_trang, nội_dung_văn_bản)."""
        from pypdf import PdfReader

        stream = BytesIO(source) if isinstance(source, bytes) else source
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(PdfReader(stream).pages, start=1)
        ]


DocumentAgent = DocumentIntelligenceAgent


# ==============================================================================
# QUERY PLANNING CAPABILITY
# ==============================================================================
class QueryPlanningAgent:
    """Năng lực Phân tích Ý định & Lập Kế hoạch Truy xuất (Query Planning & Intent Classifier).

    Nhiệm vụ:
    Phân rã câu hỏi tự nhiên phức tạp của người dùng thành RetrievalPlan gồm:
    - `intent`: Mục tiêu nghiệp vụ (fact_lookup, criterion_audit, cross_document_compare, greenwashing_screening, temporal_trend)
    - `subqueries`: Danh sách các truy vấn con đa góc nhìn (target, baseline, scope 1/2/3, assurance, metrics)
    - `required_evidence`: Danh mục bằng chứng bắt buộc cần tìm làm Quality Gate
    """

    def plan(
        self,
        question: str,
        mode: str = "qa",
        document_ids: list[str] | None = None,
    ) -> RetrievalPlan:
        lowered = question.lower()

        # 1. Nhận diện intent
        if any(w in lowered for w in ("compare", "versus", "vs", "so sánh", "đối chiếu")):
            intent = "cross_document_compare"
            subqueries = [
                f"{question} Scope 1 Scope 2 greenhouse gas emissions",
                f"{question} net zero target baseline year",
                f"{question} external assurance independent auditor",
            ]
            req = ["scope_1_2", "targets", "assurance"]

        elif any(
            w in lowered
            for w in (
                "trend",
                "trajectory",
                "yoy",
                "qua các năm",
                "lịch sử",
                "tiến trình",
                "timeline",
            )
        ):
            intent = "temporal_trend"
            subqueries = [
                f"{question} emissions 2021 2022 2023 2024 2025",
                f"{question} baseline year reduction progress",
                f"{question} year over year historical metrics",
            ]
            req = ["yearly_metrics", "baseline", "progress"]

        elif any(
            w in lowered
            for w in ("greenwash", "credible", "đáng tin", "tẩy xanh", "minh bạch", "ảo tưởng")
        ):
            intent = "greenwashing_screening"
            subqueries = [
                f"{question} target year baseline year",
                f"{question} Scope 1 Scope 2 Scope 3 metrics tCO2e",
                f"{question} independent external assurance report",
                f"{question} interim target reduction pathway 2030",
            ]
            req = ["target", "baseline", "metrics", "assurance"]

        elif mode == "audit" or any(
            w in lowered
            for w in ("audit", "kiểm toán", "đánh giá toàn diện", "coverage", "bao phủ")
        ):
            intent = "criterion_audit"
            subqueries = [
                f"{question} Scope 1 Scope 2 Scope 3 greenhouse gas emissions tCO2e",
                f"{question} net zero target year baseline year reduction",
                f"{question} employee safety injury trir training hours",
                f"{question} board oversight ethics anti-corruption compliance",
                f"{question} independent external limited assurance",
            ]
            req = ["emissions", "targets", "safety", "governance", "assurance"]

        else:
            intent = "fact_lookup"
            # Tìm các topic liên quan trong rubric
            matched_topics = [
                topic
                for rubric in RUBRICS.values()
                if _contains_any(lowered, rubric.topics)
                for topic in rubric.topics
            ]
            if not matched_topics:
                matched_topics = ["target", "baseline", "metrics", "assurance"]
            subqueries = [
                question,
                f"{question} {' '.join(matched_topics[:4])}",
            ]
            req = matched_topics[:4]

        return RetrievalPlan(
            intent=intent,
            subqueries=subqueries,
            required_evidence=req,
            document_scope=document_ids,
            temporal_scope="multi_year" if intent == "temporal_trend" else None,
        )


# ==============================================================================
# HYBRID RETRIEVAL & RERANKING CAPABILITY
# ==============================================================================
class RetrievalAgent:
    """Năng lực Truy xuất Bằng chứng Kết hợp & Tái xếp hạng (Hybrid Retrieval & Global Fusion).

    Nhiệm vụ:
    1. Thực thi truy xuất Hybrid (BM25 + Dense) kết hợp RRF Fusion và Cross-Encoder Reranker.
    2. Thực thi Global RRF Fusion qua các subqueries để triệt tiêu bias thứ tự truy vấn.
    3. Tự động khử trùng lặp và đa dạng hóa nguồn trích dẫn theo trang (Page Diversification).
    """

    def __init__(self, store: Store, mode: str | None = None):
        self.store = store
        self.mode = mode or settings.retrieval_mode

    def plan_query(self, question: str) -> str:
        """Bổ sung các thuật ngữ chủ đề liên quan của 3 trụ cột E/S/G vào câu hỏi ban đầu."""
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
        """Thực thi truy xuất đơn truy vấn."""
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
                section=row.get("section_title"),
                block_id=row.get("block_id"),
                block_type=row.get("block_type", "text"),
                retrieval_score=float(row.get("score") or 0.0),
                reranker_score=row.get("rerank_score"),
            )
            for row in raw_results
        ]
        return EvidenceVerificationAgent.validate(citations)

    def run_plan(self, plan: RetrievalPlan, top_k: int) -> list[Citation]:
        """Thực thi truy xuất đa truy vấn theo kế hoạch RetrievalPlan với Global RRF Fusion.

        Loại bỏ bias thứ tự truy vấn bằng cách tính Reciprocal Rank Fusion (RRF)
        toàn cục qua tất cả các subqueries trước khi lọc Top-K.
        """
        if not plan.subqueries:
            return []

        sub_limit = max(top_k, 6)
        rrf_k = 60.0

        rrf_scores: dict[tuple[str, int, str], float] = {}
        row_candidates: dict[tuple[str, int, str], dict] = {}
        rerank_scores: dict[tuple[str, int, str], float] = {}

        for sq in plan.subqueries:
            sub_results = self.store.search(
                query=sq,
                limit=sub_limit,
                document_ids=plan.document_scope,
                mode=self.mode,
            )
            for rank, row in enumerate(sub_results, start=1):
                sig = (row["document_id"], row["page"], row["text"][:60])
                sub_score = 1.0 / (rrf_k + rank)
                rrf_scores[sig] = rrf_scores.get(sig, 0.0) + sub_score
                if sig not in row_candidates:
                    row_candidates[sig] = row
                if row.get("rerank_score") is not None:
                    curr_rerank = rerank_scores.get(sig, -999.0)
                    rerank_scores[sig] = max(curr_rerank, float(row["rerank_score"]))

        scored_candidates: list[Citation] = []
        for sig, row in row_candidates.items():
            fused_score = rrf_scores[sig]
            if sig in rerank_scores and rerank_scores[sig] > -999.0:
                fused_score += rerank_scores[sig] * 0.1

            citation = Citation(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_name=row["name"],
                page=row["page"],
                excerpt=" ".join(row["text"].split())[:700],
                score=round(fused_score, 4),
                section=row.get("section_title"),
                block_id=row.get("block_id"),
                block_type=row.get("block_type", "text"),
                retrieval_score=float(row.get("score") or 0.0),
                reranker_score=rerank_scores.get(sig, row.get("rerank_score")),
            )
            scored_candidates.append(citation)

        # Sắp xếp toàn cục theo điểm RRF fusion
        scored_candidates.sort(key=lambda c: c.score, reverse=True)

        # Đa dạng hóa theo trang (Page Diversification)
        diversified: list[Citation] = []
        page_counts: dict[tuple[str, int], int] = {}
        for c in scored_candidates:
            pk = (c.document_id, c.page)
            if (
                page_counts.get(pk, 0) >= 2
                and len(diversified) + (len(scored_candidates) - len(diversified)) > top_k
            ):
                continue
            page_counts[pk] = page_counts.get(pk, 0) + 1
            diversified.append(c)

        if len(diversified) < top_k:
            for c in scored_candidates:
                if c not in diversified:
                    diversified.append(c)

        validated = EvidenceVerificationAgent.validate(diversified)
        return validated[:top_k]


# ==============================================================================
# EVIDENCE VERIFICATION & PROVENANCE CAPABILITY
# ==============================================================================
class EvidenceVerificationAgent:
    """Năng lực Thẩm định Bằng chứng & Kiểm chứng Khẳng định (Evidence Verification).

    Nhiệm vụ:
    1. Kiểm tra tính hợp lệ hình thức của citation (page >= 1, min words, deduplication).
    2. Thẩm định độc lập các khẳng định (Claim Verification) xem có mâu thuẫn hay không.
    3. Xác nhận tính đầy đủ nguồn gốc (Provenance Validation).
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
            citation.validation_status = "valid"
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

    @staticmethod
    def detect_conflicts(facts: list[ESGFact]) -> list[EvidenceConflict]:
        """Phát hiện mâu thuẫn số liệu công bố giữa các trang hoặc tài liệu."""
        return EvidenceExtractionAgent.detect_conflicts(facts)


EvidenceValidator = EvidenceVerificationAgent


# ==============================================================================
# AGENT 5: ESG AUDIT AGENT (EVIDENCE MATRIX, GREENWASHING, TEMPORAL, COMPARISON)
# ==============================================================================
class ESGAuditAgent:
    """Agent 5: Comprehensive ESG Audit & Analytical Intelligence Agent.

    Nhiệm vụ:
    1. Chấm điểm độ phủ tiêu chuẩn E/S/G (Disclosure Coverage).
    2. Xây dựng ma trận bằng chứng Evidence Matrix cho từng tiêu chí chuẩn mực.
    3. Sàng lọc rủi ro Greenwashing đa tín hiệu (Target Credibility, Evidence Quality, Narrative Risk).
    4. Phân tích chuỗi thời gian (Temporal ESG Analysis) và so sánh chéo (Cross-Company Comparison).
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client

    def run(self, citations: list[Citation]) -> tuple[list[PillarResult], float, list[str]]:
        """Phân tích các trụ cột E, S, G và sàng lọc các tín hiệu cần kiểm tra (Backward compatible)."""
        if not citations:
            pillars = [self._score_pillar(name, rubric, []) for name, rubric in RUBRICS.items()]
            return pillars, 0.0, ["Chưa truy xuất được bằng chứng nguồn để thẩm định."]
        pillars = [self._score_pillar(name, rubric, citations) for name, rubric in RUBRICS.items()]
        screening = self.screen_greenwashing_signals(citations, [])
        overall_coverage = (
            round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1) if pillars else 0.0
        )
        return pillars, overall_coverage, screening.all_signals

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
        partial_count = 0

        for criterion in pillar_criteria:
            res = self._evaluate_criterion(criterion, evidence)
            criteria_results.append(res)
            if res.status == "found":
                found_count += 1
            elif res.status == "partial":
                partial_count += 1

        total_criteria = len(pillar_criteria) if pillar_criteria else len(rubric.criteria)
        disclosure_coverage = (
            round(((found_count + 0.5 * partial_count) / total_criteria) * 100, 1)
            if total_criteria > 0
            else 0.0
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
            f"Hệ thống tìm thấy bằng chứng cho {found_count} tiêu chí đầy đủ và {partial_count} tiêu chí một phần trên {total_criteria} tiêu chí thuộc trụ cột {name}.",
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
        """Đánh giá trạng thái và chi tiết của 1 tiêu chí ESG dựa trên tập citation theo độ đầy đủ required_fields."""
        for cite in citations:
            text = cite.excerpt.lower()
            keywords = criterion.retrieval_keywords or criterion.required_evidence

            matched_keywords = [req for req in keywords if req in text] or [
                unit for unit in criterion.metric_units if unit.lower() in text
            ]

            if matched_keywords:
                # Nếu tiêu chí là External Assurance nhưng phát hiện mẫu câu phủ định
                if criterion.id == "G_EXTERNAL_ASSURANCE" and NEGATED_ASSURANCE_PATTERN.search(
                    text
                ):
                    return CriterionResult(
                        criterion_id=criterion.id,
                        status="contradicts",
                        citation=CriterionCitationRef(
                            document=cite.document_name,
                            page=cite.page,
                            excerpt=cite.excerpt[:200],
                            section=cite.section,
                        ),
                        confidence=0.85,
                        missing_fields=list(criterion.required_fields),
                    )

                if NEGATED_PERFORMANCE_PATTERN.search(text):
                    return CriterionResult(
                        criterion_id=criterion.id,
                        status="contradicts",
                        citation=CriterionCitationRef(
                            document=cite.document_name,
                            page=cite.page,
                            excerpt=cite.excerpt[:200],
                            section=cite.section,
                        ),
                        confidence=0.8,
                        missing_fields=list(criterion.required_fields),
                    )

                metric_match = METRIC_PATTERN.search(text)
                value = metric_match.group(0) if metric_match else None
                year_match = YEAR_PATTERN.search(text)
                year = int(year_match.group(0)) if year_match else None
                unit = criterion.metric_units[0] if criterion.metric_units else None

                # Đánh giá độ đầy đủ của required_fields
                matched_fields: list[str] = []
                missing_fields: list[str] = []

                for rf in criterion.required_fields:
                    rf_l = rf.lower()
                    if "year" in rf_l:
                        if year is not None:
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "unit" in rf_l:
                        if any(u.lower() in text for u in criterion.metric_units):
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "scope_1" in rf_l:
                        if "scope 1" in text and value is not None:
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "scope_2" in rf_l:
                        if "scope 2" in text and value is not None:
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "scope_3" in rf_l:
                        if "scope 3" in text and value is not None:
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif any(k in rf_l for k in ("value", "rate", "percentage", "count")):
                        if value is not None:
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "target" in rf_l:
                        if TARGET_PATTERN.search(text) or any(
                            t in text for t in ("net zero", "net-zero", "target", "goal")
                        ):
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "baseline" in rf_l:
                        if BASELINE_PATTERN.search(text) and not NEGATED_BASELINE_PATTERN.search(
                            text
                        ):
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    elif "assurance" in rf_l:
                        if ASSURANCE_PATTERN.search(text) and not NEGATED_ASSURANCE_PATTERN.search(
                            text
                        ):
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)
                    else:
                        if any(term in text for term in rf_l.split("_")):
                            matched_fields.append(rf)
                        else:
                            missing_fields.append(rf)

                # Xác định status theo độ đầy đủ required_fields
                if not missing_fields and matched_fields:
                    status: Literal[
                        "found", "partial", "not_found", "missing", "contradicts", "unclear"
                    ] = "found"
                    confidence = 0.95
                elif matched_fields:
                    status = "partial"
                    confidence = 0.75
                else:
                    status = "partial" if value or year else "unclear"
                    confidence = 0.50

                return CriterionResult(
                    criterion_id=criterion.id,
                    status=status,
                    value=value,
                    unit=unit,
                    reporting_year=year,
                    citation=CriterionCitationRef(
                        document=cite.document_name,
                        page=cite.page,
                        excerpt=cite.excerpt[:200],
                        section=cite.section,
                    ),
                    confidence=confidence,
                    matched_fields=matched_fields,
                    missing_fields=missing_fields,
                )

        return CriterionResult(
            criterion_id=criterion.id,
            status="missing",
            confidence=0.0,
            missing_fields=list(criterion.required_fields),
        )

    def build_evidence_matrix(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> list[EvidenceMatrixRow]:
        """Xây dựng ma trận kiểm toán bằng chứng đầy đủ cho toàn bộ tiêu chí chuẩn mực."""
        matrix: list[EvidenceMatrixRow] = []
        fact_by_metric = {f.metric: f for f in facts}

        for criterion in CRITERIA_DEFINITIONS:
            eval_res = self._evaluate_criterion(criterion, citations)
            status: Literal[
                "found", "partial", "missing", "not_found", "contradicts", "unclear"
            ] = "missing"
            if eval_res.status in ("found", "partial", "contradicts", "unclear"):
                status = eval_res.status  # type: ignore[assignment]

            # Tìm xem có fact tương ứng không để bổ sung giá trị số liệu chuẩn xác
            matched_fact = None
            if "scope_1" in criterion.id.lower():
                matched_fact = fact_by_metric.get("scope_1_emissions")
            elif "scope_3" in criterion.id.lower():
                matched_fact = fact_by_metric.get("scope_3_emissions")
            elif "target" in criterion.id.lower():
                matched_fact = fact_by_metric.get("net_zero_target")
            elif "safety" in criterion.id.lower():
                matched_fact = fact_by_metric.get("work_safety")

            display_val = eval_res.value
            display_unit = eval_res.unit
            display_year = eval_res.reporting_year

            if matched_fact:
                display_val = (
                    str(matched_fact.value) if matched_fact.value is not None else display_val
                )
                display_unit = matched_fact.unit or display_unit
                display_year = matched_fact.year or display_year

            matrix.append(
                EvidenceMatrixRow(
                    criterion_id=criterion.id,
                    criterion_name=criterion.name,
                    pillar=criterion.pillar,
                    status=status,
                    value=display_val,
                    unit=display_unit,
                    reporting_year=display_year,
                    citation=eval_res.citation,
                    confidence=eval_res.confidence,
                )
            )
        return matrix

    def screen_greenwashing_signals(
        self, citations: list[Citation], facts: list[ESGFact]
    ) -> GreenwashingScreeningResult:
        """Sàng lọc rủi ro Greenwashing đa chiều (Target Credibility, Evidence Quality, Narrative Risk)."""
        text = " ".join(item.excerpt.lower() for item in citations)
        metrics = len(METRIC_PATTERN.findall(text))

        target_signals: list[str] = []
        evidence_signals: list[str] = []
        narrative_signals: list[str] = []
        warning_score = 0

        # 1. Target Credibility
        has_target = bool(TARGET_PATTERN.search(text))
        has_baseline = bool(BASELINE_PATTERN.search(text)) and not bool(
            NEGATED_BASELINE_PATTERN.search(text)
        )
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
                target_signals.append(
                    "⚠ Có mục tiêu giảm phát thải nhưng thiếu năm cơ sở (Baseline year)."
                )
                warning_score += 2

            if has_interim:
                target_signals.append(
                    "✓ Có lộ trình mục tiêu trung hạn (Interim target / 2030 milestone)."
                )
            else:
                target_signals.append(
                    "⚠ Thiếu lộ trình mục tiêu trung gian ngắn/trung hạn trước 2050."
                )
                warning_score += 1
        else:
            target_signals.append("ℹ Chưa phát hiện cam kết Net-Zero trong các đoạn đã truy xuất.")

        # 2. Evidence Quality
        if metrics > 0:
            evidence_signals.append(
                f"✓ Ghi nhận {metrics} số liệu định lượng có kèm đơn vị đo lường cụ thể."
            )
        else:
            evidence_signals.append(
                "⚠ Toàn bộ báo cáo mới ở mức mô tả định tính, hoàn toàn thiếu số liệu đo lường."
            )
            warning_score += 2

        has_assurance = bool(ASSURANCE_PATTERN.search(text))
        negated_assurance = bool(NEGATED_ASSURANCE_PATTERN.search(text))
        if has_assurance and not negated_assurance:
            evidence_signals.append(
                "✓ Có tuyên bố bảo đảm độc lập từ bên thứ ba (External Assurance)."
            )
        elif negated_assurance:
            evidence_signals.append(
                "⚠ Báo cáo ghi nhận rõ KHÔNG ĐƯỢC kiểm toán hoặc bảo đảm độc lập."
            )
            warning_score += 2
        else:
            evidence_signals.append(
                "⚠ Chưa tìm thấy phạm vi bảo đảm độc lập (External Assurance) cho báo cáo."
            )
            warning_score += 1

        if NEGATED_PERFORMANCE_PATTERN.search(text):
            evidence_signals.append(
                "⚠ Ghi nhận thông tin không đạt mục tiêu giảm phát thải hoặc phát thải tăng."
            )
            warning_score += 2

        # 3. Narrative Risk
        vague_count = sum(text.count(w) for w in VAGUE_WORDS)
        if metrics > 0 and vague_count > metrics * 1.5:
            narrative_signals.append(
                f"⚠ Mật độ từ ngữ định hướng tham vọng ({vague_count}) vượt trội so với số liệu chứng minh ({metrics})."
            )
            warning_score += 2
        elif vague_count > 0:
            narrative_signals.append(
                f"ℹ Ghi nhận {vague_count} từ ngữ mang tính định hướng tham vọng."
            )

        # Xác định Risk Level
        if warning_score >= 5:
            risk_level = "HIGH"
        elif warning_score >= 2:
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
            target_credibility_signals=target_signals,
            evidence_quality_signals=evidence_signals,
            narrative_risk_signals=narrative_signals,
            all_signals=all_signals,
            summary=summary,
        )

    def run_temporal_analysis(
        self,
        company: str,
        store: Store,
        metric: str = "scope_1_emissions",
        document_ids: list[str] | None = None,
    ) -> TemporalAnalysisResult:
        """Phân tích diễn biến chuỗi thời gian của một chỉ số ESG qua các năm."""
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

        facts = EvidenceExtractionAgent.extract_facts(citations)
        timeline_points: list[TemporalTrendPoint] = []
        seen_years: set[int] = set()

        for f in facts:
            if f.year and f.year not in seen_years and f.value is not None:
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

    def run_comparison(
        self,
        companies: list[str],
        store: Store,
        criteria_ids: list[str] | None = None,
    ) -> CompanyComparisonResult:
        """Thực thi so sánh chất lượng công bố ESG giữa các doanh nghiệp theo cùng rubric."""
        target_criteria = [
            c for c in CRITERIA_DEFINITIONS if not criteria_ids or c.id in criteria_ids
        ]
        comp_rows: list[CompanyComparisonCriterion] = []
        coverage_summary: dict[str, float] = {}

        for company in companies:
            results = store.search(f"{company} ESG sustainability report", limit=12)
            cites = [
                Citation(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    document_name=r["name"],
                    page=r["page"],
                    excerpt=r["text"],
                )
                for r in results
            ]
            facts = EvidenceExtractionAgent.extract_facts(cites)
            matrix = self.build_evidence_matrix(cites, facts)
            found_count = sum(1 for m in matrix if m.status == "found")
            cov = round((found_count / max(1, len(matrix))) * 100, 1)
            coverage_summary[company] = cov

        for crit in target_criteria:
            row_dict: dict[str, Any] = {}
            for company in companies:
                results = store.search(f"{company} {crit.name}", limit=4)
                cites = [
                    Citation(
                        chunk_id=r["chunk_id"],
                        document_id=r["document_id"],
                        document_name=r["name"],
                        page=r["page"],
                        excerpt=r["text"],
                    )
                    for r in results
                ]
                eval_res = self._evaluate_criterion(crit, cites)
                row_dict[company] = {
                    "status": eval_res.status,
                    "value": eval_res.value,
                    "page": eval_res.citation.page if eval_res.citation else None,
                    "confidence": eval_res.confidence,
                }

            comp_rows.append(
                CompanyComparisonCriterion(
                    criterion_id=crit.id,
                    criterion_name=crit.name,
                    pillar=crit.pillar,
                    values_by_company=row_dict,
                )
            )

        findings = [
            f"So sánh {len(companies)} doanh nghiệp: "
            + ", ".join(f"{c}: {cov}% coverage" for c, cov in coverage_summary.items())
        ]
        return CompanyComparisonResult(
            companies=companies,
            criteria_matrix=comp_rows,
            coverage_summary=coverage_summary,
            findings=findings,
        )


ESGAnalysisAgent = ESGAuditAgent


# ==============================================================================
# EXPLANATION SYNTHESIS CAPABILITY
# ==============================================================================
class ExplanationAgent:
    """Năng lực Tổng hợp Giải trình & Thẩm định Trích dẫn (Explanation Synthesis & Grounding).

    Nhiệm vụ:
    - Tổng hợp câu trả lời dựa trên trích đoạn bằng chứng đã qua xác thực.
    - Post-Generation Citation Grounding: Thẩm định nghiêm ngặt rằng mọi trích dẫn (Document, Page)
      trong câu trả lời do LLM sinh ra đều thuộc tập hợp bằng chứng đã truy xuất hợp lệ.
    - Deterministic Fallback: Tự động chuyển đổi sang bộ tổng hợp xác định khi offline ($0 cost).
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
        screening_result: GreenwashingScreeningResult | None = None,
    ) -> str:
        """Tạo chuỗi giải thích rõ ràng kèm danh sách nguồn tài liệu và số trang tương ứng."""
        if self.llm and self.llm.is_available() and citations:
            rubric_summary = f"Coverage {overall_coverage}%. " + ", ".join(
                f"{p.pillar}: {p.disclosure_coverage}%" for p in pillars
            )
            # Chuẩn bị citation kèm citation IDs [C1], [C2]
            citation_payload = []
            for idx, c in enumerate(citations[:6], start=1):
                cd = c.model_dump()
                cd["cid"] = f"[C{idx}]"
                citation_payload.append(cd)

            llm_answer = self.llm.synthesize_answer(
                question=question,
                citations=citation_payload,
                rubric_summary=rubric_summary,
            )
            if llm_answer and len(llm_answer.strip()) > 20:
                # Post-Generation Citation Validation
                valid_pages = {c.page for c in citations}
                cited_pages = [
                    int(m.group(1))
                    for m in re.finditer(r"(?:trang|page)\s*(\d+)", llm_answer, re.IGNORECASE)
                ]
                hallucinated_pages = [p for p in cited_pages if p not in valid_pages]
                if not hallucinated_pages:
                    return llm_answer

        sources = (
            ", ".join(f"[{item.document_name}, trang {item.page}]" for item in citations[:6])
            or "không có citation"
        )

        risk_snippet = (
            f" [Screening Risk: {screening_result.risk_level}]" if screening_result else ""
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
                f"Trả lời dựa trên bằng chứng truy xuất cho câu hỏi '{question}'{risk_snippet}: "
                f"Tìm thấy {len(citations)} đoạn văn bản nguồn tại {sources}.{metric_snippet}{excerpt_snippet}"
            )
        else:
            scores_str = ", ".join(
                f"{item.pillar}: coverage {item.disclosure_coverage}% (quality {item.evidence_quality}%)"
                for item in pillars
            )
            return (
                f"Hệ thống tìm thấy bằng chứng công bố cho {overall_coverage}% tổng số tiêu chí E/S/G kiểm tra{risk_snippet}. "
                f"Chi tiết từng trụ cột: {scores_str}. Nguồn trích dẫn: {sources}. "
                "Lưu ý: Kết quả phản ánh mức độ công bố thông tin trong các đoạn đã truy xuất, không phản ánh hiệu suất ESG tổng thể của doanh nghiệp."
            )


# ==============================================================================
# WORKFLOW ORCHESTRATION LAYER
# ==============================================================================
class SupervisorAgent:
    """Agent-Orchestrated ESG Audit Workflow & Observability Orchestrator.

    Nhiệm vụ:
    - Điều phối luồng phân tích xác định (Deterministic DAG Workflow):
      `QueryPlanning` -> `HybridRetrieval` -> `EvidenceVerification` ->
      `FactExtraction` -> `ESGAudit` -> `ExplanationSynthesis`.
    - Thẩm định cổng chất lượng bằng chứng (Evidence Completeness Gate).
    - Đo lường độ trễ chi tiết (latency waterfall ms) cho từng bước phục vụ Observability.
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
        self.planner = QueryPlanningAgent()
        self.verifier = EvidenceVerificationAgent()
        self.retrieval = RetrievalAgent(store, mode=retrieval_mode)
        self.extractor = EvidenceExtractionAgent()
        self.audit = ESGAuditAgent(llm_client=self.llm)
        self.analysis = self.audit
        self.explanation = ExplanationAgent(llm_client=self.llm)
        self.retrieval_mode = retrieval_mode or settings.retrieval_mode

    def run(
        self,
        question: str,
        top_k: int = 6,
        document_ids: list[str] | None = None,
        mode: Literal["qa", "audit"] = "qa",
    ) -> AnalysisResponse:
        """Thực thi luồng phân tích toàn diện có căn cứ bằng chứng kèm đo lường vết thực thi (Tracing)."""
        is_llm_active = self.llm.is_available()
        agent_mode: Literal["llm_agentic", "deterministic_fallback"] = (
            "llm_agentic" if is_llm_active else "deterministic_fallback"
        )

        trace_steps: list[AgentTraceStep] = []
        trace_logs: list[str] = [
            f"Supervisor: Khởi tạo phân tích ở chế độ '{mode.upper()}' | Engine: {agent_mode.upper()}"
        ]
        if is_llm_active:
            trace_logs.append("Supervisor: Gọi LLM Structured Planning để lập kế hoạch tool calls")
            llm_plan = self.llm.generate_plan(question, mode=mode)
            if llm_plan:
                trace_logs.append(
                    f"Supervisor: LLM đã sinh kế hoạch gồm {len(llm_plan)} bước hành động"
                )
        else:
            trace_logs.append(
                "Supervisor: Chạy chế độ Deterministic Heuristic Engine ($0 API Cost Fallback)"
            )

        # Step 1: Query Planning
        t0 = time.perf_counter()
        plan = self.planner.plan(question, mode=mode, document_ids=document_ids)
        plan_lat = round((time.perf_counter() - t0) * 1000, 2)
        trace_steps.append(
            AgentTraceStep(
                agent="QueryPlanningAgent",
                step="Generate Retrieval Plan",
                latency_ms=plan_lat,
                retrieved_chunks=0,
                details={"intent": plan.intent, "subqueries_count": len(plan.subqueries)},
            )
        )
        trace_logs.append(
            f"Query Planning Agent: Intent '{plan.intent}' với {len(plan.subqueries)} subqueries ({plan_lat} ms)"
        )

        # Step 2: Hybrid Retrieval (QA vs Targeted Audit Retrieval)
        t0 = time.perf_counter()
        if mode == "audit":
            audit_subqueries = [
                "Scope 1 Scope 2 direct indirect greenhouse gas emissions tCO2e",
                "Scope 3 value chain supply chain indirect emissions",
                "net zero reduction target goal baseline year 2030 2050",
                "renewable electricity wind solar capacity MWh GWh",
                "worker safety TRIR total recordable incident rate fatalities",
                "female women gender diversity workforce representation",
                "supplier social environmental assessment evaluation",
                "board climate oversight ethics compliance external assurance independent auditor",
            ]
            audit_plan = RetrievalPlan(
                intent="criterion_audit",
                subqueries=audit_subqueries,
                required_evidence=plan.required_evidence,
                document_scope=document_ids,
            )
            raw_citations = self.retrieval.run_plan(audit_plan, top_k=max(top_k, 12))
        else:
            raw_citations = self.retrieval.run_plan(plan, top_k=top_k)
        retrieval_lat = round((time.perf_counter() - t0) * 1000, 2)
        trace_steps.append(
            AgentTraceStep(
                agent="RetrievalAgent",
                step="Hybrid Dense+BM25 + Cross-Encoder Rerank",
                latency_ms=retrieval_lat,
                retrieved_chunks=len(raw_citations),
                details={"mode": self.retrieval_mode, "top_k": top_k},
            )
        )
        trace_logs.append(
            f"Retrieval Agent: Đã tìm thấy {len(raw_citations)} đoạn ứng viên qua {self.retrieval_mode} ({retrieval_lat} ms)"
        )

        # Step 3: Evidence Verification
        t0 = time.perf_counter()
        validated_citations = self.verifier.validate(raw_citations)
        verify_lat = round((time.perf_counter() - t0) * 1000, 2)
        trace_steps.append(
            AgentTraceStep(
                agent="EvidenceVerificationAgent",
                step="Validate Page Boundaries & Provenance",
                latency_ms=verify_lat,
                retrieved_chunks=len(validated_citations),
                details={
                    "valid": len(validated_citations),
                    "rejected": len(raw_citations) - len(validated_citations),
                },
            )
        )
        trace_logs.append(
            f"Evidence Verification Agent: Thẩm định {len(validated_citations)} citation hợp lệ ({verify_lat} ms)"
        )

        # Step 4: Structured ESG Fact Extraction
        t0 = time.perf_counter()
        facts = self.extractor.extract_facts(validated_citations)
        conflicts = self.extractor.detect_conflicts(facts)
        extract_lat = round((time.perf_counter() - t0) * 1000, 2)
        trace_steps.append(
            AgentTraceStep(
                agent="EvidenceExtractionAgent",
                step="Extract ESG Facts & Conflict Detection",
                latency_ms=extract_lat,
                retrieved_chunks=len(facts),
                details={"facts": len(facts), "conflicts": len(conflicts)},
            )
        )
        trace_logs.append(
            f"Evidence Extraction Agent: Trích xuất {len(facts)} facts, phát hiện {len(conflicts)} mâu thuẫn ({extract_lat} ms)"
        )

        # Step 5: ESG Audit & Rubric Scoring
        t0 = time.perf_counter()
        pillars, overall_coverage, _ = self.audit.run(validated_citations)
        evidence_matrix = self.audit.build_evidence_matrix(validated_citations, facts)
        screening_res = self.audit.screen_greenwashing_signals(validated_citations, facts)
        audit_lat = round((time.perf_counter() - t0) * 1000, 2)
        trace_steps.append(
            AgentTraceStep(
                agent="ESGAuditAgent",
                step="Evaluate Rubric & Greenwashing Screening",
                latency_ms=audit_lat,
                retrieved_chunks=len(evidence_matrix),
                details={
                    "coverage": overall_coverage,
                    "risk_level": screening_res.risk_level,
                    "matrix_rows": len(evidence_matrix),
                },
            )
        )
        trace_logs.append(
            f"ESG Audit Agent: Coverage {overall_coverage}%, Greenwashing Risk: {screening_res.risk_level} ({audit_lat} ms)"
        )

        # Step 5b: Evidence Completeness Gate
        completeness_details: dict[str, Any] = {
            "required": plan.required_evidence,
            "satisfied": [],
            "missing": [],
            "status": "complete",
        }
        for req in plan.required_evidence:
            req_l = req.lower()
            has_fact = any(
                req_l in f.metric.lower()
                or (f.unit and req_l in f.unit.lower())
                or (req_l == "year" and f.year is not None)
                or (req_l == "baseline_year" and f.baseline_year is not None)
                or (req_l == "target" and "target" in f.metric.lower())
                for f in facts
            )
            has_cite = any(req_l in c.excerpt.lower() for c in validated_citations)
            if has_fact or has_cite:
                completeness_details["satisfied"].append(req)
            else:
                completeness_details["missing"].append(req)

        if completeness_details["missing"]:
            completeness_details["status"] = "incomplete"

        # Step 6: Temporal / Comparison Analysis nếu cần
        temporal_analysis = None
        comparison_res = None
        if plan.intent == "temporal_trend":
            company_hint = "Company"
            if validated_citations:
                first_doc_id = validated_citations[0].document_id
                doc_meta = self.store.get_document(first_doc_id)
                if doc_meta and doc_meta.get("company"):
                    company_hint = doc_meta["company"]
                elif validated_citations[0].document_name:
                    raw_name = validated_citations[0].document_name
                    clean_name = re.sub(r"^\b20\d\d\b\s*", "", raw_name)
                    clean_name = re.sub(r"\.pdf$", "", clean_name, flags=re.IGNORECASE)
                    tokens = [
                        t
                        for t in clean_name.split()
                        if not t.isdigit()
                        and t.lower() not in ("sustainability", "report", "esg", "annual")
                    ]
                    company_hint = tokens[0] if tokens else clean_name.split()[0]
            temporal_analysis = self.audit.run_temporal_analysis(
                company_hint, self.store, document_ids=document_ids
            )

        # Step 7: Claim Auditing
        claims_to_audit = [f for p in pillars for f in p.findings[:2]]
        verification_summary = self.verifier.audit_claims(claims_to_audit, validated_citations)

        # Step 8: Explanation Synthesis
        t0 = time.perf_counter()
        answer = self.explanation.run(
            mode,
            pillars,
            overall_coverage,
            validated_citations,
            question,
            screening_result=screening_res,
        )
        synth_lat = round((time.perf_counter() - t0) * 1000, 2)
        trace_steps.append(
            AgentTraceStep(
                agent="ExplanationAgent",
                step="Synthesize Evidence-Grounded Answer",
                latency_ms=synth_lat,
                retrieved_chunks=0,
                details={"citations_used": min(6, len(validated_citations))},
            )
        )
        trace_logs.append(f"Explanation Agent: Hoàn tất tổng hợp câu trả lời ({synth_lat} ms)")

        limitations = [
            "Câu trả lời được tổng hợp duy nhất từ các đoạn bằng chứng đã truy xuất.",
            "Nếu thông tin nằm ngoài phạm vi Top-K đoạn được tìm kiếm, hệ thống sẽ không thể đưa vào kết luận.",
        ]
        if completeness_details["status"] == "incomplete":
            limitations.append(
                "[MISSING_EVIDENCE] Tài liệu chưa cung cấp đủ bằng chứng đối chứng cho các trường yêu cầu: "
                + ", ".join(completeness_details["missing"])
            )
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
            screening_signals=screening_res.all_signals,
            pillars=pillars,
            citations=validated_citations,
            verification_summary=verification_summary,
            trace=trace_logs,
            limitations=limitations,
            plan=plan,
            evidence_matrix=evidence_matrix,
            extracted_facts=facts,
            conflicts=conflicts,
            screening_result=screening_res,
            temporal_analysis=temporal_analysis,
            comparison=comparison_res,
            evidence_completeness=completeness_details,
            trace_steps=trace_steps,
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
