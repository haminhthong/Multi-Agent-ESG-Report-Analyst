import re
import time
from typing import Any, Literal

from app.capabilities.explanation import ExplanationAgent
from app.capabilities.planning import QueryPlanningAgent
from app.capabilities.retrieval import RetrievalAgent
from app.capabilities.verification import EvidenceVerificationAgent
from app.config import settings
from app.domain.evidence_completeness import EvidenceCompletenessGate
from app.evidence_extractor import EvidenceExtractionAgent
from app.llm import LLMClient
from app.models import (
    AgentTraceStep,
    AnalysisResponse,
    Citation,
    ESGFact,
    PillarResult,
    RetrievalPlan,
)
from app.services.audit_service import ESGAuditService
from app.store import Store
from app.tools import AgentTools


def _aggregate_pillar_metrics(pillars: list[PillarResult]) -> tuple[float, float, float]:
    """Hàm phụ trợ tính trung bình chất lượng bằng chứng, độ đầy đủ số liệu và độ tin cậy."""
    if not pillars:
        return 0.0, 0.0, 0.0
    avg_quality = round(sum(p.evidence_quality for p in pillars) / len(pillars), 1)
    avg_completeness = round(sum(p.data_completeness for p in pillars) / len(pillars), 1)
    avg_conf = round(sum(p.confidence for p in pillars) / len(pillars), 2)
    return avg_quality, avg_completeness, avg_conf


class SupervisorAgent:
    """Agent-Orchestrated ESG Audit Workflow & Observability Orchestrator.

    Nhiệm vụ:
    - Điều phối luồng phân tích xác định (Deterministic DAG Workflow):
      `QueryPlanning` -> `HybridRetrieval` -> `EvidenceVerification` ->
      `FactExtraction` -> `ESGAudit` -> `EvidenceCompletenessGate` ->
      `ClaimVerification` -> `ExplanationSynthesis`.
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
        self.audit = ESGAuditService(llm_client=self.llm)
        self.analysis = self.audit
        self.explanation = ExplanationAgent(llm_client=self.llm)
        self.completeness_gate = EvidenceCompletenessGate()
        self.retrieval_mode = retrieval_mode or settings.retrieval_mode
        self.last_response: AnalysisResponse | None = None

    def _execute_llm_plan_steps(
        self,
        llm_plan: list[dict[str, Any]],
        question: str,
        document_ids: list[str] | None,
        top_k: int,
    ) -> tuple[list[Citation], list[str], int]:
        """Thực thi subset an toàn các tool từ LLM plan; trả (citations phụ, logs, số bước đã chạy)."""
        extra_citations: list[Citation] = []
        logs: list[str] = []
        executed = 0

        for step in llm_plan[:6]:
            if not isinstance(step, dict):
                continue
            tool = step.get("tool")
            args = step.get("args") if isinstance(step.get("args"), dict) else {}
            try:
                if tool == "search_document":
                    query = str(args.get("query") or question)
                    limit = int(args.get("top_k") or args.get("limit") or top_k)
                    hits = self.tools.search_document(
                        query=query,
                        limit=max(1, min(limit, 15)),
                        document_ids=document_ids,
                    )
                    extra_citations.extend(hits)
                    executed += 1
                    logs.append(f"Tool search_document: {len(hits)} hits for '{query[:80]}'")
                elif tool == "retrieve_evidence":
                    chunk_ids = args.get("chunk_ids") or []
                    if isinstance(chunk_ids, list) and chunk_ids:
                        rows = self.tools.retrieve_evidence([int(x) for x in chunk_ids[:20]])
                        for row in rows:
                            extra_citations.append(
                                Citation(
                                    chunk_id=row["chunk_id"],
                                    document_id=row["document_id"],
                                    document_name=row.get("name") or row["document_id"],
                                    page=row["page"],
                                    excerpt=" ".join((row.get("text") or "").split())[:700],
                                    section=row.get("section_title"),
                                    block_id=row.get("block_id"),
                                    block_type=row.get("block_type", "text"),
                                )
                            )
                        executed += 1
                        logs.append(f"Tool retrieve_evidence: {len(rows)} chunks")
                elif tool == "extract_metric":
                    text = str(args.get("text") or "")
                    if text:
                        result = AgentTools.extract_metric(text)
                        executed += 1
                        logs.append(
                            f"Tool extract_metric: metrics={len(result.get('metrics', []))}, "
                            f"years={result.get('years')}"
                        )
                elif tool == "score_rubric":
                    pillar = str(args.get("pillar") or "E").upper()
                    if pillar not in ("E", "S", "G"):
                        pillar = "E"
                    texts = args.get("evidence_texts") or []
                    if not isinstance(texts, list):
                        texts = []
                    result = AgentTools.score_rubric(pillar, [str(t) for t in texts])
                    executed += 1
                    logs.append(
                        f"Tool score_rubric({pillar}): coverage={result.get('disclosure_coverage')}%"
                    )
                elif tool == "verify_claim":
                    claim = str(args.get("claim") or "")
                    excerpt = str(args.get("excerpt") or "")
                    if claim and excerpt:
                        result = AgentTools.verify_claim(claim, excerpt)
                        executed += 1
                        logs.append(
                            f"Tool verify_claim: supported={result.get('supported')} "
                            f"overlap={result.get('keyword_overlap')}"
                        )
                else:
                    logs.append(f"Tool skipped (unsupported): {tool}")
            except Exception as exc:
                logs.append(f"Tool {tool} failed: {exc}")

        return extra_citations, logs, executed

    @staticmethod
    def _merge_citations(
        primary: list[Citation], extra: list[Citation], limit: int
    ) -> list[Citation]:
        """Gộp citation từ DAG retrieval và tool plan, khử trùng theo (document_id, page, excerpt)."""
        merged: list[Citation] = []
        seen: set[tuple[str, int, str]] = set()
        for cite in primary + extra:
            sig = (cite.document_id, cite.page, " ".join(cite.excerpt.split())[:120].lower())
            if sig not in seen:
                seen.add(sig)
                merged.append(cite)
            if len(merged) >= limit:
                break
        return merged

    def _resolve_companies(
        self, question: str, document_ids: list[str] | None
    ) -> list[str]:
        """Suy ra danh sách công ty để so sánh từ document_ids, câu hỏi, hoặc metadata corpus."""
        companies: list[str] = []
        seen: set[str] = set()

        def add(name: str | None) -> None:
            if not name:
                return
            cleaned = name.strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                companies.append(cleaned)

        if document_ids:
            for did in document_ids:
                doc = self.store.get_document(did)
                if doc:
                    add(doc.get("company"))

        for doc in self.store.documents():
            company = doc.get("company")
            if company and company.lower() in question.lower():
                add(company)

        vs_match = re.search(
            r"(.+?)\s+(?:vs\.?|versus|so sánh với|đối chiếu với)\s+(.+)",
            question,
            re.IGNORECASE,
        )
        if vs_match:
            for part in (vs_match.group(1), vs_match.group(2)):
                token = re.sub(
                    r"\b(?:compare|so sánh|đối chiếu|emissions?|esg|report)\b",
                    "",
                    part,
                    flags=re.IGNORECASE,
                ).strip(" ,.")
                if token and len(token.split()) <= 4:
                    add(token)

        and_match = re.search(
            r"(?:compare|so sánh|đối chiếu)\s+(.+?)\s+(?:and|và|&)\s+(.+)",
            question,
            re.IGNORECASE,
        )
        if and_match:
            for part in (and_match.group(1), and_match.group(2)):
                token = part.strip(" ,.")
                if token and len(token.split()) <= 4:
                    add(token)

        return companies[:10]

    @staticmethod
    def _build_audit_claims(
        facts: list[ESGFact], pillars: list[PillarResult]
    ) -> list[str]:
        """Tạo claim có số liệu để đối soát (tránh meta-finding tiếng Việt vô nghĩa)."""
        claims: list[str] = []
        for fact in facts:
            if fact.value is None:
                continue
            unit = f" {fact.unit}" if fact.unit else ""
            year = f" in {fact.year}" if fact.year else ""
            claims.append(f"{fact.metric}: {fact.value}{unit}{year}")
            if len(claims) >= 8:
                break

        if len(claims) < 4:
            for pillar in pillars:
                for cr in pillar.criteria_results:
                    if cr.status in ("found", "partial") and cr.value:
                        claims.append(f"{cr.criterion_id}: {cr.value}")
                    if len(claims) >= 8:
                        break
                if len(claims) >= 8:
                    break

        return claims

    def run(
        self,
        question: str,
        top_k: int = 6,
        document_ids: list[str] | None = None,
        mode: Literal["qa", "audit"] = "qa",
        focus_pillars: list[Literal["E", "S", "G"]] | None = None,
    ) -> AnalysisResponse:
        """Thực thi luồng phân tích toàn diện có căn cứ bằng chứng kèm đo lường vết thực thi (Tracing)."""
        is_llm_active = self.llm.is_available()
        agent_mode: Literal["llm_agentic", "deterministic_fallback", "agent_orchestrated"] = (
            "deterministic_fallback"
        )

        trace_steps: list[AgentTraceStep] = []
        trace_logs: list[str] = [
            f"Supervisor: Khởi tạo phân tích ở chế độ '{mode.upper()}'"
        ]
        plan_extra_citations: list[Citation] = []
        llm_tools_executed = 0

        if is_llm_active:
            agent_mode = "llm_agentic"
            trace_logs.append(
                "Supervisor: LLM Structured Planning — sinh và thực thi tool plan (nếu có)"
            )
            llm_plan = self.llm.generate_plan(question, mode=mode)
            if llm_plan:
                plan_extra_citations, tool_logs, llm_tools_executed = self._execute_llm_plan_steps(
                    llm_plan, question, document_ids, top_k
                )
                trace_logs.append(
                    f"Supervisor: LLM đã sinh kế hoạch gồm {len(llm_plan)} bước hành động"
                )
                trace_logs.extend(tool_logs)
                if llm_tools_executed > 0:
                    agent_mode = "agent_orchestrated"
                    trace_logs.append(
                        f"Supervisor: Đã thực thi {llm_tools_executed} tool từ LLM plan"
                    )
                else:
                    trace_logs.append(
                        "Supervisor: LLM plan không có tool thực thi được; tiếp tục DAG deterministic"
                    )
            trace_logs[0] = (
                f"Supervisor: Khởi tạo phân tích ở chế độ '{mode.upper()}' | Engine: {agent_mode.upper()}"
            )
        else:
            trace_logs.append(
                "Supervisor: Chạy chế độ Deterministic Heuristic Engine ($0 API Cost Fallback)"
            )
            trace_logs[0] = (
                f"Supervisor: Khởi tạo phân tích ở chế độ '{mode.upper()}' | Engine: {agent_mode.upper()}"
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
            merge_limit = max(top_k, 12) + 6
        else:
            raw_citations = self.retrieval.run_plan(plan, top_k=top_k)
            merge_limit = top_k + 6

        if plan_extra_citations:
            raw_citations = self._merge_citations(
                raw_citations, plan_extra_citations, limit=merge_limit
            )
            trace_logs.append(
                f"Supervisor: Gộp {len(plan_extra_citations)} citation từ LLM tools vào retrieval"
            )

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

        if focus_pillars:
            focus_set = set(focus_pillars)
            pillars = [p for p in pillars if p.pillar in focus_set]
            evidence_matrix = [row for row in evidence_matrix if row.pillar in focus_set]
            overall_coverage = (
                round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1)
                if pillars
                else 0.0
            )

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
                    "focus_pillars": focus_pillars or ["E", "S", "G"],
                },
            )
        )
        trace_logs.append(
            f"ESG Audit Agent: Coverage {overall_coverage}%, Greenwashing Risk: {screening_res.risk_level} ({audit_lat} ms)"
        )

        # Step 5b: Evidence Completeness Gate (Deep Verification)
        completeness_details = self.completeness_gate.check(
            plan.required_evidence, facts, validated_citations
        )

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
        elif plan.intent == "cross_document_compare":
            companies = self._resolve_companies(question, document_ids)
            if len(companies) >= 2:
                comparison_res = self.audit.run_comparison(companies, self.store)
                trace_logs.append(
                    f"ESG Audit Agent: Cross-document comparison for {', '.join(companies)}"
                )
            else:
                trace_logs.append(
                    "ESG Audit Agent: Intent so sánh nhưng chưa đủ >=2 công ty "
                    "(cần document_ids/metadata company hoặc nêu tên trong câu hỏi)"
                )

        # Step 7: Claim Auditing — đối soát số liệu trích xuất
        claims_to_audit = self._build_audit_claims(facts, pillars)
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
        if comparison_res:
            answer = (
                f"{answer}\n\nSo sánh công bố giữa {', '.join(comparison_res.companies)}: "
                + "; ".join(
                    f"{c}: {cov}%" for c, cov in comparison_res.coverage_summary.items()
                )
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
            missing_items = completeness_details["missing"] + completeness_details.get(
                "partial", []
            )
            limitations.append(
                "[MISSING_EVIDENCE] Tài liệu chưa cung cấp đủ bằng chứng đối chứng cho các trường yêu cầu: "
                + ", ".join(missing_items)
            )
        if plan.intent == "cross_document_compare" and comparison_res is None:
            limitations.append(
                "[COMPARE_SKIPPED] Chưa đủ thông tin công ty để so sánh chéo "
                "(cần >=2 company trong metadata hoặc câu hỏi)."
            )
        if mode == "audit":
            limitations.extend(
                [
                    "Báo cáo chỉ phản ánh mức độ công bố thông tin (disclosure coverage) trong các tài liệu đã lập chỉ mục.",
                    "Kết quả không đại diện cho điểm hiệu suất hoạt động ESG thực tế của doanh nghiệp.",
                ]
            )

        avg_quality, avg_completeness, avg_conf = _aggregate_pillar_metrics(pillars)

        response = AnalysisResponse(
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
        self.last_response = response
        return response


AnalysisWorkflow = SupervisorAgent
