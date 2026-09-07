"""Canonical application workflow for evidence-grounded ESG analysis.

HTTP and CLI adapters should call this module instead of assembling agents on
their own. Orchestration is deterministic and observable; optional LLM usage is
contained inside bounded capabilities.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Literal

from app.agent_runtime import AgentGraphSupervisor, AgentNode
from app.capabilities import (
    AnswerReviewAgent,
    EvidenceVerificationAgent,
    ExplanationAgent,
    QueryPlanningAgent,
    RetrievalAgent,
)
from app.config import settings
from app.domain.evidence_completeness import EvidenceCompletenessGate
from app.evidence_extractor import EvidenceExtractionAgent
from app.facts.repository import FactCandidateRepository
from app.llm import LLMClient
from app.models import (
    AgentExecutionMode,
    AgentTraceStep,
    AnalysisResponse,
    AnalysisState,
    Citation,
    ESGFact,
    PillarResult,
    RetrievalPlan,
)
from app.services.audit_service import ESGAuditService
from app.store import Store
from app.tools import AgentTools

AUDIT_SUBQUERIES = [
    "Scope 1 Scope 2 direct indirect greenhouse gas emissions tCO2e",
    "Scope 3 value chain supply chain indirect emissions",
    "net zero reduction target goal baseline year 2030 2050",
    "renewable electricity wind solar capacity MWh GWh",
    "worker safety TRIR total recordable incident rate fatalities",
    "female women gender diversity workforce representation",
    "supplier social environmental assessment evaluation",
    "board climate oversight ethics compliance external assurance independent auditor",
]

_EVIDENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "scope_1_2": ("scope_1_emissions", "scope_2_emissions", "scope 1", "scope 2"),
    "scope_1": ("scope_1_emissions", "scope 1", "scope1"),
    "scope_2": ("scope_2_emissions", "scope 2", "scope2"),
    "scope_3": ("scope_3_emissions", "scope 3", "scope3"),
    "target": ("net zero", "net-zero", "target", "reduction goal"),
    "targets": ("net zero", "net-zero", "target", "reduction goal"),
    "net_zero_target": ("net zero", "net-zero", "target", "carbon neutral"),
    "baseline": ("baseline", "base year", "baseline year"),
    "progress": ("reduction", "progress", "historical", "trajectory"),
    "assurance": ("assurance", "assured", "independent auditor", "verified"),
    "emissions": (
        "scope_1_emissions",
        "scope_2_emissions",
        "scope_3_emissions",
        "emission",
        "tco2e",
    ),
    "metrics": ("scope_1_emissions", "scope_2_emissions", "tco2e", "mwh", "trir", "%"),
    "safety": ("work_safety", "trir", "injury", "safety", "fatalit"),
    "governance": ("board", "ethics", "compliance", "governance", "oversight"),
}


class ESGAnalysisPipeline:
    """One runtime path for API, CLI, and evaluation adapters.

    Stages:
    request validation -> query planning -> retrieval -> citation validation ->
    structured extraction -> evidence completeness -> ESG rubric/screening ->
    optional specialized analysis -> claim support check -> grounded synthesis.
    """

    def __init__(
        self,
        store: Store,
        llm_client: LLMClient | None = None,
        retrieval_mode: str | None = None,
        audit_service: ESGAuditService | None = None,
    ) -> None:
        self.store = store
        self.llm = llm_client or LLMClient()
        self.tools = AgentTools(store)
        self.planner = QueryPlanningAgent()
        self.retrieval = RetrievalAgent(store, mode=retrieval_mode)
        self.verifier = EvidenceVerificationAgent()
        self.answer_reviewer = AnswerReviewAgent()
        self.extractor = EvidenceExtractionAgent()
        self.audit = audit_service or ESGAuditService(llm_client=self.llm)
        self.analysis = self.audit
        self.explanation = ExplanationAgent(llm_client=self.llm)
        self.completeness_gate = EvidenceCompletenessGate()
        self.fact_candidates = FactCandidateRepository(store)
        self.agent_supervisor = AgentGraphSupervisor(max_steps=16)
        self.retrieval_mode = retrieval_mode or settings.retrieval_mode
        self.last_response: AnalysisResponse | None = None

    def _execute_llm_plan_steps(
        self,
        llm_plan: list[dict[str, Any]],
        question: str,
        document_ids: list[str] | None,
        top_k: int,
    ) -> tuple[list[Citation], list[str], int]:
        """Execute subset of tools proposed by LLM plan."""
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
                                    evidence_id=(
                                        f"{row['document_id']}:p{row['page']}:{row.get('stable_id') or row.get('block_id') or row['chunk_id']}"
                                    ),
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
            except Exception as exc:  # noqa: BLE001 - bounded optional tool boundary
                logs.append(f"Tool {tool} failed: {exc}")

        return extra_citations, logs, executed

    def run(
        self,
        question: str,
        top_k: int = 5,
        document_ids: list[str] | None = None,
        mode: Literal["qa", "audit"] = "qa",
        focus_pillars: list[Literal["E", "S", "G"]] | None = None,
        agent_mode: AgentExecutionMode = "orchestrated",
    ) -> AnalysisResponse:
        requested_agent_mode: AgentExecutionMode = (
            agent_mode
            if agent_mode in {"agentic", "orchestrated", "deterministic"}
            else "orchestrated"
        )
        is_llm_active = requested_agent_mode != "deterministic" and self.llm.is_available()
        resolved_agent_mode: Literal["llm_agentic", "deterministic_fallback", "agent_orchestrated"]
        if requested_agent_mode == "deterministic":
            resolved_agent_mode = "deterministic_fallback"
        elif requested_agent_mode == "agentic" and is_llm_active:
            resolved_agent_mode = "llm_agentic"
        elif is_llm_active:
            resolved_agent_mode = "agent_orchestrated"
        else:
            resolved_agent_mode = "deterministic_fallback"

        state = AnalysisState(
            request_id=str(uuid.uuid4()),
            user_question=question,
            mode=mode,
            document_ids=document_ids,
            top_k=top_k,
            agent_mode=requested_agent_mode,
        )
        state.trace.append(
            f"workflow.start request_id={state.request_id} mode={mode} retrieval={self.retrieval_mode}"
        )

        plan_extra_citations: list[Citation] = []
        if requested_agent_mode == "deterministic" or not is_llm_active:
            state.trace.append(
                "Supervisor: Chạy chế độ Deterministic Heuristic Engine ($0 API Cost Fallback)"
            )
        else:
            state.trace.append(
                "Supervisor: LLM Structured Planning — sinh và thực thi tool plan (nếu có)"
            )
            llm_plan = self.llm.generate_plan(question, mode=mode)
            if llm_plan:
                extra_cites, tool_logs, _ = self._execute_llm_plan_steps(
                    llm_plan, question, document_ids, top_k
                )
                plan_extra_citations.extend(extra_cites)
                state.trace.extend(tool_logs)

        route_result = self.agent_supervisor.execute(
            state,
            self._build_agent_nodes(state, focus_pillars, plan_extra_citations),
            start="ScopeAgent",
        )
        state.agent_stop_reason = route_result.stop_reason

        evidence_quality, data_completeness, confidence = _aggregate_pillar_metrics(state.pillars)
        response = AnalysisResponse(
            mode=state.mode,
            agent_mode=resolved_agent_mode,
            requested_agent_mode=requested_agent_mode,
            agent_route=state.agent_route,
            agent_stop_reason=state.agent_stop_reason,
            answer=state.answer,
            disclosure_coverage=state.overall_coverage,
            evidence_quality=evidence_quality,
            data_completeness=data_completeness,
            confidence=confidence,
            screening_signals=(
                state.screening_result.all_signals if state.screening_result else []
            ),
            pillars=state.pillars,
            citations=state.validated_citations,
            verification_summary=state.verification_summary,
            trace=state.trace,
            limitations=state.limitations,
            plan=state.plan,
            evidence_matrix=state.evidence_matrix,
            extracted_facts=state.extracted_facts,
            conflicts=state.conflicts,
            screening_result=state.screening_result,
            temporal_analysis=state.temporal_analysis,
            comparison=state.comparison,
            evidence_completeness=state.evidence_completeness,
            trace_steps=state.trace_steps,
        )
        self.last_response = response
        return response

    def _build_agent_nodes(
        self,
        state: AnalysisState,
        focus_pillars: list[Literal["E", "S", "G"]] | None,
        plan_extra_citations: list[Citation],
    ) -> dict[str, AgentNode]:
        """Build the explicit supervisor graph for one request.

        The graph is intentionally request-scoped so closures cannot leak data
        between concurrent API requests.
        """

        def retrieve() -> None:
            self._retrieve(state)
            if plan_extra_citations:
                state.raw_citations = self._merge_citations(
                    state.raw_citations,
                    plan_extra_citations,
                    limit=max(state.top_k, 12),
                )

        def after_retrieval(current: AnalysisState) -> str:
            return (
                "EvidenceVerificationAgent" if current.raw_citations else "EvidenceCompletenessGate"
            )

        def after_verification(current: AnalysisState) -> str:
            return (
                "EvidenceExtractionAgent"
                if current.validated_citations
                else "EvidenceCompletenessGate"
            )

        def after_completeness(current: AnalysisState) -> str:
            if current.evidence_completeness.get("status") == "incomplete":
                current.trace.append(
                    "Supervisor decision: continue with explicit evidence limitations"
                )
            return "ESGAuditAgent"

        def after_audit(current: AnalysisState) -> str:
            if current.plan and current.plan.intent in {
                "temporal_trend",
                "cross_document_compare",
            }:
                return "SpecializedAnalysisAgent"
            return "ClaimVerificationAgent"

        return {
            "ScopeAgent": AgentNode(
                name="ScopeAgent",
                run=lambda: self._validate_scope(state),
                next_agent=lambda _: "QueryPlanningAgent",
            ),
            "QueryPlanningAgent": AgentNode(
                name="QueryPlanningAgent",
                run=lambda: self._plan(state),
                next_agent=lambda _: "RetrievalAgent",
            ),
            "RetrievalAgent": AgentNode(
                name="RetrievalAgent",
                run=retrieve,
                next_agent=after_retrieval,
            ),
            "EvidenceVerificationAgent": AgentNode(
                name="EvidenceVerificationAgent",
                run=lambda: self._verify(state),
                next_agent=after_verification,
            ),
            "EvidenceExtractionAgent": AgentNode(
                name="EvidenceExtractionAgent",
                run=lambda: self._extract(state),
                next_agent=lambda _: "EvidenceCompletenessGate",
            ),
            "EvidenceCompletenessGate": AgentNode(
                name="EvidenceCompletenessGate",
                run=lambda: self._check_completeness(state),
                next_agent=after_completeness,
            ),
            "ESGAuditAgent": AgentNode(
                name="ESGAuditAgent",
                run=lambda: self._audit(state, focus_pillars),
                next_agent=after_audit,
            ),
            "SpecializedAnalysisAgent": AgentNode(
                name="SpecializedAnalysisAgent",
                run=lambda: self._run_specialized_analysis(state),
                next_agent=lambda _: "ClaimVerificationAgent",
            ),
            "ClaimVerificationAgent": AgentNode(
                name="ClaimVerificationAgent",
                run=lambda: self._verify_claims(state),
                next_agent=lambda _: "ExplanationAgent",
            ),
            "ExplanationAgent": AgentNode(
                name="ExplanationAgent",
                run=lambda: self._synthesize(state),
                next_agent=lambda _: "AnswerReviewAgent",
            ),
            "AnswerReviewAgent": AgentNode(
                name="AnswerReviewAgent",
                run=lambda: self._review_answer(state),
                next_agent=lambda _: "LimitationsAgent",
            ),
            "LimitationsAgent": AgentNode(
                name="LimitationsAgent",
                run=lambda: self._build_limitations(state),
                next_agent=lambda _: None,
            ),
        }

    @staticmethod
    def _merge_citations(
        primary: list[Citation], extra: list[Citation], limit: int
    ) -> list[Citation]:
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

    def _validate_scope(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        if state.document_ids:
            existing = {doc["id"] for doc in self.store.documents()}
            unknown = [doc_id for doc_id in state.document_ids if doc_id not in existing]
            if unknown:
                state.warnings.append("Unknown document ids: " + ", ".join(unknown))
                state.document_ids = [doc_id for doc_id in state.document_ids if doc_id in existing]
        self._trace(
            state,
            "Workflow",
            "Validate request and document scope",
            started,
            details={"document_scope": state.document_ids or [], "warnings": state.warnings},
        )

    def _plan(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.plan = self.planner.plan(
            state.user_question,
            mode=state.mode,
            document_ids=state.document_ids,
        )
        state.plan.original_question = state.user_question
        state.plan.canonical_query = state.user_question
        self._trace(
            state,
            "QueryPlanningAgent",
            "Build retrieval plan",
            started,
            details={
                "intent": state.plan.intent,
                "subqueries": len(state.plan.subqueries),
                "required_evidence": state.plan.required_evidence,
            },
        )

    def _retrieve(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        if state.mode == "audit":
            from app.rubric import CRITERIA_DEFINITIONS

            # Criterion-level audit retrieval: đảm bảo mọi tiêu chí chuẩn mực đều được truy xuất bằng chứng chuyên biệt
            criterion_cites: list[Citation] = []
            for crit in CRITERIA_DEFINITIONS:
                crit_query = f"{crit.name} {' '.join(crit.retrieval_keywords[:3])}"
                sub_cites = self.retrieval.run(crit_query, top_k=3, document_ids=state.document_ids)
                criterion_cites.extend(sub_cites)

            plan = RetrievalPlan(
                intent="criterion_audit",
                original_question=state.user_question,
                canonical_query=state.user_question,
                subqueries=AUDIT_SUBQUERIES,
                required_evidence=state.plan.required_evidence,
                document_scope=state.document_ids,
            )
            core_cites = self.retrieval.run_plan(plan, top_k=max(state.top_k, 12))
            state.raw_citations = self._merge_citations(
                core_cites, criterion_cites, limit=max(state.top_k * 4, 30)
            )
        else:
            state.raw_citations = self.retrieval.run_plan(state.plan, top_k=state.top_k)
        self._trace(
            state,
            "RetrievalAgent",
            "Retrieve hybrid evidence candidates (criterion-level audit)"
            if state.mode == "audit"
            else "Retrieve hybrid evidence candidates",
            started,
            retrieved_chunks=len(state.raw_citations),
            details={"mode": self.retrieval_mode, "top_k": len(state.raw_citations)},
        )

    def _verify(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.validated_citations = self.verifier.validate(state.raw_citations)
        self._trace(
            state,
            "EvidenceVerificationAgent",
            "Validate citation metadata and excerpt shape",
            started,
            retrieved_chunks=len(state.validated_citations),
            details={
                "accepted": len(state.validated_citations),
                "rejected": len(state.raw_citations) - len(state.validated_citations),
                "scope": "retrieved-evidence validation",
            },
        )

    def _extract(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.extracted_facts = self.extractor.extract_facts(state.validated_citations)
        state.conflicts = self.extractor.detect_conflicts(state.extracted_facts)

        # Extraction is not validation. Persist candidates for review, never as
        # accepted source-of-truth facts.
        if state.extracted_facts:
            self.fact_candidates.save(state.extracted_facts)

        self._trace(
            state,
            "EvidenceExtractionAgent",
            "Extract structured ESG facts and detect conflicts",
            started,
            retrieved_chunks=len(state.extracted_facts),
            details={"facts": len(state.extracted_facts), "conflicts": len(state.conflicts)},
        )

    def _targeted_retrieval_retry(self, state: AnalysisState) -> None:
        """Kích hoạt targeted retrieval retry cho các khía cạnh bằng chứng còn thiếu."""
        if not state.evidence_completeness:
            return

        missing_reqs = list(state.evidence_completeness.missing) + list(
            state.evidence_completeness.partial
        )
        if not missing_reqs:
            return

        retry_queries: list[str] = []
        for req in missing_reqs[:3]:
            aliases = _EVIDENCE_ALIASES.get(req, (req.replace("_", " "),))
            retry_queries.append(" ".join(aliases[:3]))

        if not retry_queries:
            return

        started = time.perf_counter()
        retry_plan = RetrievalPlan(
            intent=state.plan.intent if state.plan else "fact_lookup",
            original_question=state.user_question,
            canonical_query=" ".join(retry_queries),
            subqueries=retry_queries,
            document_scope=state.document_ids,
        )
        retry_citations = self.retrieval.run_plan(retry_plan, top_k=4)
        validated_retry = self.verifier.validate(retry_citations)

        new_cites = [
            c
            for c in validated_retry
            if not any(
                c.document_id == ex.document_id
                and c.page == ex.page
                and c.excerpt[:80] == ex.excerpt[:80]
                for ex in state.validated_citations
            )
        ]
        if new_cites:
            state.validated_citations.extend(new_cites)
            new_facts = self.extractor.extract_facts(new_cites)
            if new_facts:
                state.extracted_facts.extend(new_facts)
                self.fact_candidates.save(new_facts)
                state.conflicts = self.extractor.detect_conflicts(state.extracted_facts)

            # Thẩm định lại completeness sau khi thu hồi thêm bằng chứng
            state.evidence_completeness = self.completeness_gate.check(
                state.plan.required_evidence if state.plan else [],
                state.extracted_facts,
                state.validated_citations,
            )

        self._trace(
            state,
            "EvidenceCompletenessGate",
            "Targeted retrieval retry for missing evidence",
            started,
            retrieved_chunks=len(new_cites),
            details={
                "missing_targeted": missing_reqs,
                "new_citations": len(new_cites),
                "recheck_status": state.evidence_completeness.status,
            },
        )

    def _check_completeness(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        state.evidence_completeness = self.completeness_gate.check(
            state.plan.required_evidence,
            state.extracted_facts,
            state.validated_citations,
        )

        # Active Completeness Gate: Tự động chạy targeted retry nếu thiếu bằng chứng
        if state.evidence_completeness.status == "incomplete" and (
            state.evidence_completeness.missing or state.evidence_completeness.partial
        ):
            self._targeted_retrieval_retry(state)

        self._trace(
            state,
            "EvidenceCompletenessGate",
            "Check required evidence",
            started,
            details=state.evidence_completeness.model_dump()
            if hasattr(state.evidence_completeness, "model_dump")
            else state.evidence_completeness,
        )

    def _audit(
        self,
        state: AnalysisState,
        focus_pillars: list[Literal["E", "S", "G"]] | None,
    ) -> None:
        started = time.perf_counter()
        pillars, overall_coverage, _ = self.audit.run(
            state.validated_citations, facts=state.extracted_facts
        )
        matrix = self.audit.build_evidence_matrix(
            state.validated_citations,
            state.extracted_facts,
        )
        screening = self.audit.screen_greenwashing_signals(
            state.validated_citations,
            state.extracted_facts,
        )

        if focus_pillars:
            selected = set(focus_pillars)
            pillars = [pillar for pillar in pillars if pillar.pillar in selected]
            matrix = [row for row in matrix if row.pillar in selected]
            overall_coverage = (
                round(sum(p.disclosure_coverage for p in pillars) / len(pillars), 1)
                if pillars
                else 0.0
            )

        state.pillars = pillars
        state.evidence_matrix = matrix
        state.screening_result = screening
        state.overall_coverage = overall_coverage
        self._trace(
            state,
            "ESGAuditAgent",
            "Evaluate rubric and screen greenwashing risk",
            started,
            retrieved_chunks=len(matrix),
            details={
                "coverage": overall_coverage,
                "risk_level": screening.risk_level if screening else "UNKNOWN",
                "evidence_matrix_rows": len(matrix),
            },
        )

    def _run_specialized_analysis(self, state: AnalysisState) -> None:
        assert state.plan is not None
        started = time.perf_counter()
        details: dict[str, Any] = {"executed": False, "analysis": state.plan.intent}

        if state.plan.intent == "temporal_trend":
            company = self._resolve_primary_company(state)
            state.temporal_analysis = self.audit.run_temporal_analysis(
                company,
                self.store,
                document_ids=state.document_ids,
            )
            details.update({"executed": True, "company": company, "analysis": "temporal"})
        elif state.plan.intent == "cross_document_compare":
            companies = self._resolve_companies(state.user_question, state.document_ids)
            if len(companies) >= 2:
                state.comparison = self.audit.run_comparison(companies, self.store)
                details.update({"executed": True, "companies": companies, "analysis": "comparison"})
            else:
                state.warnings.append(
                    "Comparison intent detected but fewer than two companies could be resolved."
                )

        self._trace(
            state,
            "SpecializedAnalysis",
            "Run intent-specific analysis when required",
            started,
            details=details,
        )

    def _verify_claims(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        claims = _build_audit_claims(state.extracted_facts, state.pillars)
        state.verification_summary = self.verifier.audit_claims(
            claims,
            state.validated_citations,
        )
        self._trace(
            state,
            "EvidenceVerificationAgent",
            "Check extracted claim support in retrieved excerpts",
            started,
            details={
                "claims": len(claims),
                "supported_rate": state.verification_summary.get("supported_rate", 0.0),
            },
        )

    def _synthesize(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        state.answer = self.explanation.run(
            state.mode,
            state.pillars,
            state.overall_coverage,
            state.validated_citations,
            state.user_question,
            screening_result=state.screening_result,
        )
        self._trace(
            state,
            "ExplanationAgent",
            "Synthesize evidence-grounded response",
            started,
            details={
                "citations_available": len(state.validated_citations),
                "llm_available": self.llm.is_available(),
            },
        )

    def _review_answer(self, state: AnalysisState) -> None:
        started = time.perf_counter()
        review = self.answer_reviewer.review(state.answer, state.validated_citations)
        if not review["passed"]:
            state.warnings.append(
                "[ANSWER_REVIEW] Answer was regenerated because it was not fully grounded: "
                + ", ".join(review["issues"])
            )
            state.answer = self.explanation._deterministic_answer(
                state.mode,
                state.pillars,
                state.overall_coverage,
                state.validated_citations,
                state.user_question,
                state.screening_result,
            )
            review = self.answer_reviewer.review(state.answer, state.validated_citations)
            if not review["passed"]:
                state.answer = (
                    "The retrieved evidence was insufficient to produce a fully grounded answer. "
                    "No ESG conclusion is made."
                )
                review = self.answer_reviewer.review(state.answer, state.validated_citations)

        state.verification_summary["answer_review"] = review
        self._trace(
            state,
            "AnswerReviewAgent",
            "Review final answer references and grounding contract",
            started,
            details=review,
        )

    def _build_limitations(self, state: AnalysisState) -> None:
        state.limitations = [
            "Analysis is limited to indexed documents and retrieved evidence chunks.",
            "Citation validation checks metadata and retrieved excerpts; it is not independent third-party verification of the issuer's ESG disclosure.",
            "Greenwashing output is a heuristic screening signal for analyst review, not a legal or fraud determination.",
        ]
        if state.evidence_completeness.get("status") == "incomplete":
            state.limitations.append(
                "[MISSING_EVIDENCE] Missing required evidence: "
                + ", ".join(state.evidence_completeness.get("missing", []))
            )
        if state.mode == "audit":
            state.limitations.append(
                "Disclosure coverage measures evidence presence in the indexed corpus, not corporate ESG performance."
            )
        state.limitations.extend(state.warnings)

    def _resolve_primary_company(self, state: AnalysisState) -> str:
        if state.document_ids:
            for document_id in state.document_ids:
                doc = self.store.get_document(document_id)
                if doc and doc.get("company"):
                    return str(doc["company"])
        for citation in state.validated_citations:
            doc = self.store.get_document(citation.document_id)
            if doc and doc.get("company"):
                return str(doc["company"])
        return "Company"

    def _resolve_companies(
        self,
        question: str,
        document_ids: list[str] | None,
    ) -> list[str]:
        companies: list[str] = []
        seen: set[str] = set()

        def add(name: str | None) -> None:
            if not name:
                return
            clean = name.strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                companies.append(clean)

        if document_ids:
            for document_id in document_ids:
                doc = self.store.get_document(document_id)
                if doc:
                    add(doc.get("company"))

        for doc in self.store.documents():
            company = doc.get("company")
            if company and company.lower() in question.lower():
                add(company)

        match = re.search(
            r"(.+?)\s+(?:vs\.?|versus|so sánh với|đối chiếu với)\s+(.+)",
            question,
            re.IGNORECASE,
        )
        if match:
            for raw in match.groups():
                token = re.sub(
                    r"\b(?:compare|so sánh|đối chiếu|emissions?|esg|report)\b",
                    "",
                    raw,
                    flags=re.IGNORECASE,
                ).strip(" ,.")
                if token and len(token.split()) <= 4:
                    add(token)
        return companies[:10]

    @staticmethod
    def _trace(
        state: AnalysisState,
        agent: str,
        step: str,
        started: float,
        retrieved_chunks: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        state.trace_steps.append(
            AgentTraceStep(
                agent=agent,
                step=step,
                latency_ms=latency_ms,
                retrieved_chunks=retrieved_chunks,
                details=details or {},
            )
        )
        state.trace.append(f"{agent}: {step} ({latency_ms} ms)")


SupervisorWorkflow = ESGAnalysisPipeline
SupervisorAgent = ESGAnalysisPipeline
AnalysisWorkflow = ESGAnalysisPipeline


def _requirement_satisfied(
    requirement: str,
    facts: list[ESGFact],
    citations: list[Citation],
) -> bool:
    requirement = requirement.lower().strip()
    tokens = (requirement, *_EVIDENCE_ALIASES.get(requirement, ()))
    for token in dict.fromkeys(tokens):
        lowered = token.lower()
        for fact in facts:
            metric = fact.metric.lower()
            unit = (fact.unit or "").lower()
            if lowered in metric or metric in lowered or (unit and lowered in unit):
                return True
            if lowered in ("year", "reporting_year") and fact.year is not None:
                return True
            if lowered == "baseline_year" and fact.baseline_year is not None:
                return True
        if any(lowered in citation.excerpt.lower() for citation in citations):
            return True
    return False


def _build_audit_claims(facts: list[ESGFact], pillars: list[PillarResult]) -> list[str]:
    claims: list[str] = []
    for fact in facts:
        if fact.value is None:
            continue
        unit = f" {fact.unit}" if fact.unit else ""
        year = f" in {fact.year}" if fact.year else ""
        claims.append(f"{fact.metric}: {fact.value}{unit}{year}")
        if len(claims) >= 8:
            return claims

    for pillar in pillars:
        for criterion in pillar.criteria_results:
            if criterion.status in ("found", "partial") and criterion.value:
                claims.append(f"{criterion.criterion_id}: {criterion.value}")
            if len(claims) >= 8:
                return claims
    return claims


def _aggregate_pillar_metrics(pillars: list[PillarResult]) -> tuple[float, float, float]:
    if not pillars:
        return 0.0, 0.0, 0.0
    evidence_quality = round(sum(p.evidence_quality for p in pillars) / len(pillars), 1)
    completeness = round(sum(p.data_completeness for p in pillars) / len(pillars), 1)
    confidence = round(sum(p.confidence for p in pillars) / len(pillars), 2)
    return evidence_quality, completeness, confidence
