import argparse
import json
import sys
from pathlib import Path

from app.answer_eval import evaluate_answer_quality, load_answer_eval_cases
from app.batch_ingest import ingest_dataset
from app.capabilities import EvidenceRetriever
from app.config import settings
from app.demo import seed_demo
from app.document_service import DocumentIngestionService
from app.evaluation import (
    ExtractionEvalCase,
    evaluate_extraction,
    evaluate_retrieval,
    evaluate_retrieval_ablation,
    load_evaluation_cases,
)
from app.store import Store
from app.workflow import ESGAnalysisPipeline

DEFAULT_EVALUATION = Path("data/evaluation/retrieval_cases.json")
DEFAULT_ANSWER_EVAL = Path("data/evaluation/answer_eval_cases.json")


def main() -> None:
    """Command-line adapter for ingestion, evaluation, and ESG analysis."""
    _enable_utf8_output()
    args = _build_parser().parse_args()
    store = Store(args.database)

    if args.command == "ingest":
        report = ingest_dataset(
            args.metadata,
            args.reports_dir,
            DocumentIngestionService(store),
            limit=args.limit,
            force=args.force,
        )
        print(report.model_dump_json(indent=2))
        return

    if args.command == "evaluate":
        seed_demo(store)
        cases = load_evaluation_cases(args.cases)
        report = evaluate_retrieval(
            EvidenceRetriever(store, mode=args.mode),
            cases,
            args.top_k,
        )
        print(report.model_dump_json(indent=2))
        if report.recall_at_k < args.min_recall or report.mrr < args.min_mrr:
            raise SystemExit(1)
        return

    if args.command == "benchmark":
        seed_demo(store)
        cases = load_evaluation_cases(args.cases)
        ablation = evaluate_retrieval_ablation(store, cases, top_k=args.top_k)
        print("\n" + ablation.to_markdown_table() + "\n")
        print(ablation.model_dump_json(indent=2))
        return

    pipeline = ESGAnalysisPipeline(store)

    if args.command == "evaluate-answer":
        seed_demo(store)
        cases = load_answer_eval_cases(args.cases)
        report = evaluate_answer_quality(pipeline, cases, top_k=args.top_k)
        print("\n=== ANSWER QUALITY EVALUATION ===")
        print(f"Cases: {report.cases}")
        print(f"Faithfulness: {report.faithfulness * 100:.1f}%")
        print(f"Citation correctness: {report.citation_correctness * 100:.1f}%")
        print(f"Completeness: {report.completeness * 100:.1f}%")
        print(f"Unsupported claim rate: {report.unsupported_claim_rate * 100:.1f}%\n")
        print(report.model_dump_json(indent=2))
        if report.faithfulness < args.min_faithfulness:
            raise SystemExit(1)
        return

    if args.command == "evaluate-extraction":
        seed_demo(store)
        extraction_cases = [
            ExtractionEvalCase(
                id="boeing_suppliers_extracted",
                question="How many suppliers were rated using social criteria?",
                query_scope=["boeing-demo"],
                expected_metric="supplier_assessment",
                expected_value=724,
                expected_unit="suppliers",
                expected_year=2024,
            ),
            ExtractionEvalCase(
                id="nextera_renewables_mw",
                question="What is NextEra's total wind and solar generation capacity?",
                query_scope=["nextera-demo"],
                expected_metric="renewable_energy",
                expected_value=34000,
                expected_unit="megawatt",
                expected_year=2024,
            ),
            ExtractionEvalCase(
                id="alcoa_trir_safety",
                question="What is Alcoa's Total Recordable Incident Rate?",
                query_scope=["alcoa-demo"],
                expected_metric="work_safety",
                expected_value=1.12,
                expected_unit=None,
                expected_year=2024,
            ),
        ]
        report = evaluate_extraction(pipeline, extraction_cases, top_k=args.top_k)
        print("\n=== STRUCTURED EXTRACTION EVALUATION ===")
        print(f"Exact match: {report.exact_match * 100:.1f}%")
        print(f"Numeric tolerance accuracy: {report.numeric_tolerance_acc * 100:.1f}%")
        print(f"Unit accuracy: {report.unit_acc * 100:.1f}%")
        print(f"Year accuracy: {report.year_acc * 100:.1f}%\n")
        print(report.model_dump_json(indent=2))
        return

    if args.command == "audit":
        seed_demo(store)
        doc_ids = [args.document_id] if args.document_id else None
        result = pipeline.run(
            question=(
                "Comprehensive ESG disclosure audit covering emissions, targets, "
                "workforce safety, governance, and assurance."
            ),
            top_k=args.top_k,
            document_ids=doc_ids,
            mode="audit",
            agent_mode=args.agent_mode,
        )
        print("\n=== ESG DISCLOSURE EVIDENCE MATRIX ===")
        print("| Criterion | Pillar | Status | Value | Year | Page |")
        print("|---|---|---|---|---|---|")
        for row in result.evidence_matrix:
            page = f"p.{row.citation.page}" if row.citation else "—"
            value = f"{row.value} {row.unit or ''}".strip() if row.value else "—"
            print(
                f"| {row.criterion_name} | {row.pillar} | {row.status} | "
                f"{value} | {row.reporting_year or '—'} | {page} |"
            )
        if result.screening_result:
            print(f"\nScreening priority: {result.screening_result.screening_priority}")
            print("Screening output is heuristic and requires analyst review.")
        return

    if args.command == "compare":
        seed_demo(store)
        companies = [item.strip() for item in args.companies.split(",") if item.strip()]
        comparison = pipeline.audit.run_comparison(companies, store)
        print(f"\n=== CROSS-COMPANY DISCLOSURE COMPARISON ({', '.join(companies)}) ===")
        for finding in comparison.findings:
            print(f"• {finding}")
        return

    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-grounded ESG report analysis CLI")
    parser.add_argument("--database", type=Path, default=settings.database_path)
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Ingest a PDF dataset from metadata CSV")
    ingest.add_argument("--metadata", type=Path, required=True)
    ingest.add_argument("--reports-dir", type=Path, required=True)
    ingest.add_argument("--limit", type=int)
    ingest.add_argument("--force", action="store_true")

    evaluate = commands.add_parser("evaluate", help="Evaluate retrieval quality")
    evaluate.add_argument("--cases", type=Path, default=DEFAULT_EVALUATION)
    evaluate.add_argument("--top-k", type=int, default=5)
    evaluate.add_argument("--mode", type=str, default="hybrid_rerank")
    evaluate.add_argument("--min-recall", type=float, default=0)
    evaluate.add_argument("--min-mrr", type=float, default=0)

    benchmark = commands.add_parser("benchmark", help="Run retrieval ablation")
    benchmark.add_argument("--cases", type=Path, default=DEFAULT_EVALUATION)
    benchmark.add_argument("--top-k", type=int, default=5)

    answer_eval = commands.add_parser("evaluate-answer", help="Evaluate answer grounding")
    answer_eval.add_argument("--cases", type=Path, default=DEFAULT_ANSWER_EVAL)
    answer_eval.add_argument("--top-k", type=int, default=5)
    answer_eval.add_argument("--min-faithfulness", type=float, default=0.0)

    extraction_eval = commands.add_parser(
        "evaluate-extraction",
        help="Evaluate structured ESG fact extraction",
    )
    extraction_eval.add_argument("--top-k", type=int, default=6)

    audit = commands.add_parser("audit", help="Run ESG disclosure audit")
    audit.add_argument("--document-id", type=str)
    audit.add_argument("--top-k", type=int, default=12)
    audit.add_argument(
        "--agent-mode",
        choices=("agentic", "orchestrated", "deterministic"),
        default="agentic",
        help="Choose LLM-assisted planning, bounded orchestration, or deterministic execution",
    )

    compare = commands.add_parser("compare", help="Compare disclosure evidence")
    compare.add_argument("--companies", type=str, default="Boeing,NextEra Energy,Alcoa")

    commands.add_parser("stats", help="Show corpus statistics")
    return parser


def _enable_utf8_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
