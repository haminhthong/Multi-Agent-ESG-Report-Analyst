"""Company comparison service: evaluates cross-company ESG performance using scoped evidence."""

from __future__ import annotations

from typing import Any

from app.domain.evidence_matrix import EvidenceMatrixBuilder
from app.domain.rubric_evaluator import RubricEvaluator
from app.evidence_extractor import EvidenceExtractionAgent
from app.models import Citation, CompanyComparisonCriterion, CompanyComparisonResult, ESGFact
from app.rubric import CRITERIA_DEFINITIONS, RubricCriterion
from app.store import Store


class CompanyComparisonService:
    """Evaluate and compare ESG disclosure quality across companies using standardized rubrics."""

    def __init__(
        self,
        rubric_evaluator: RubricEvaluator | None = None,
        evidence_matrix_builder: EvidenceMatrixBuilder | None = None,
    ) -> None:
        self.rubric_evaluator = rubric_evaluator or RubricEvaluator()
        self.evidence_matrix_builder = evidence_matrix_builder or EvidenceMatrixBuilder(
            self.rubric_evaluator
        )

    def compare(
        self,
        companies: list[str],
        store: Store | None = None,
        company_documents: dict[str, list[str]] | None = None,
        criteria_ids: list[str] | None = None,
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> CompanyComparisonResult:
        """Company-scoped cross-comparison avoiding global fuzzy keyword confusion."""
        defs = criteria_definitions or CRITERIA_DEFINITIONS
        target_criteria = [c for c in defs if not criteria_ids or c.id in criteria_ids]
        comp_rows: list[CompanyComparisonCriterion] = []
        coverage_summary: dict[str, float] = {}

        for company in companies:
            scoped_doc_ids = company_documents.get(company) if company_documents else None
            if store:
                results = store.search(
                    f"{company} ESG sustainability report",
                    limit=12,
                    document_ids=scoped_doc_ids,
                )
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
            else:
                cites = []

            facts = EvidenceExtractionAgent.extract_facts(cites)
            matrix = self.evidence_matrix_builder.build(cites, facts, defs)
            found_count = sum(1 for m in matrix if m.status == "found")
            cov = round((found_count / max(1, len(matrix))) * 100, 1)
            coverage_summary[company] = cov

        for crit in target_criteria:
            row_dict: dict[str, Any] = {}
            for company in companies:
                scoped_doc_ids = company_documents.get(company) if company_documents else None
                if store:
                    results = store.search(
                        f"{company} {crit.name}",
                        limit=4,
                        document_ids=scoped_doc_ids,
                    )
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
                else:
                    cites = []

                eval_res = self.rubric_evaluator.evaluate_criterion(crit, cites)
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

    def run_comparison(
        self,
        companies: list[str],
        store: Store,
        criteria_ids: list[str] | None = None,
        criteria_definitions: list[RubricCriterion] | None = None,
    ) -> CompanyComparisonResult:
        """Backward-compatible entry point delegating to compare()."""
        return self.compare(
            companies=companies,
            store=store,
            criteria_ids=criteria_ids,
            criteria_definitions=criteria_definitions,
        )


CompanyComparator = CompanyComparisonService
