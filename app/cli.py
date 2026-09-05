import argparse
import json
import sys
from pathlib import Path

from app.agents import RetrievalAgent, SupervisorAgent
from app.answer_eval import evaluate_answer_quality, load_answer_eval_cases
from app.batch_ingest import ingest_dataset
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

DEFAULT_EVALUATION = Path("data/evaluation/retrieval_cases.json")
DEFAULT_ANSWER_EVAL = Path("data/evaluation/answer_eval_cases.json")


def main() -> None:
    """Điểm vào chính (CLI Entrypoint) quản trị hệ thống Evidence-Grounded ESG Intelligence.

    Hỗ trợ các lệnh:
    1. `ingest`: Nạp dữ liệu dataset hàng loạt từ tệp CSV metadata.
    2. `evaluate`: Chạy bộ đánh giá retrieval (Recall@K, MRR, nDCG) và Quality Gate CI/CD.
    3. `benchmark`: Chạy thực nghiệm bóc tách Ablation Study so sánh 4 cấu hình Retrieval.
    4. `evaluate-answer`: Đánh giá chất lượng câu trả lời & RAG Triad Guardrails.
    5. `evaluate-extraction`: Đánh giá trích xuất sự thật ESG có cấu trúc (Tier 2 Evaluation).
    6. `audit`: Khởi chạy kiểm toán ESG toàn diện sinh Evidence Matrix.
    7. `compare`: So sánh đối chiếu chất lượng công bố giữa các doanh nghiệp.
    8. `stats`: Xuất báo cáo thống kê quy mô corpus.
    """
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

    elif args.command == "evaluate":
        seed_demo(store)
        cases = load_evaluation_cases(args.cases)
        mode = getattr(args, "mode", "hybrid_rerank")
        report = evaluate_retrieval(RetrievalAgent(store, mode=mode), cases, args.top_k)
        print(report.model_dump_json(indent=2))

        # Quality Gate Check trong CI/CD
        if report.recall_at_k < args.min_recall or report.mrr < args.min_mrr:
            raise SystemExit(1)

    elif args.command == "benchmark":
        seed_demo(store)
        cases = load_evaluation_cases(args.cases)
        print("Đang thực hiện Ablation Study trên 4 cấu hình Retrieval...")
        ablation = evaluate_retrieval_ablation(store, cases, top_k=args.top_k)
        print("\n" + ablation.to_markdown_table() + "\n")
        print(ablation.model_dump_json(indent=2))

    elif args.command == "evaluate-answer":
        seed_demo(store)
        cases = load_answer_eval_cases(args.cases)
        print("Đang đánh giá chất lượng câu trả lời & RAG Triad Guardrails...")
        supervisor = SupervisorAgent(store)
        report = evaluate_answer_quality(supervisor, cases, top_k=args.top_k)
        print("\n=== KẾT QUẢ ANSWER QUALITY EVALUATION ===")
        print(f"Số trường hợp kiểm thử: {report.cases}")
        print(f"• Answer Faithfulness (Groundedness): {report.faithfulness * 100:.1f}%")
        print(f"• Citation Correctness: {report.citation_correctness * 100:.1f}%")
        print(f"• Answer Completeness: {report.completeness * 100:.1f}%")
        print(
            f"• Unsupported Claim Rate (Hallucination): {report.unsupported_claim_rate * 100:.1f}%\n"
        )
        print(report.model_dump_json(indent=2))

        if report.faithfulness < args.min_faithfulness:
            raise SystemExit(1)

    elif args.command == "evaluate-extraction":
        seed_demo(store)
        supervisor = SupervisorAgent(store)
        # Bộ test trích xuất mẫu dựa trên dữ liệu demo
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
        rep = evaluate_extraction(supervisor, extraction_cases, top_k=args.top_k)
        print("\n=== KẾT QUẢ STRUCTURED EXTRACTION EVALUATION ===")
        print(f"• Exact Match: {rep.exact_match * 100:.1f}%")
        print(f"• Numeric Tolerance Accuracy (5%): {rep.numeric_tolerance_acc * 100:.1f}%")
        print(f"• Unit Accuracy: {rep.unit_acc * 100:.1f}%")
        print(f"• Year Accuracy: {rep.year_acc * 100:.1f}%\n")
        print(rep.model_dump_json(indent=2))

    elif args.command == "audit":
        seed_demo(store)
        supervisor = SupervisorAgent(store)
        doc_ids = [args.document_id] if getattr(args, "document_id", None) else None
        res = supervisor.run(
            question="Comprehensive ESG Audit covering emissions, targets, workforce safety, governance, and assurance.",
            top_k=args.top_k,
            document_ids=doc_ids,
            mode="audit",
        )
        print("\n=== ESG AUDIT EVIDENCE MATRIX ===")
        print("| Criterion | Pillar | Status | Value | Year | Page |")
        print("|---|---|---|---|---|---|")
        for row in res.evidence_matrix:
            page_str = f"p.{row.citation.page}" if row.citation else "—"
            val_str = f"{row.value} {row.unit or ''}".strip() if row.value else "—"
            print(
                f"| {row.criterion_name} | {row.pillar} | {row.status} | {val_str} | {row.reporting_year or '—'} | {page_str} |"
            )
        if res.screening_result:
            print(f"\nGreenwashing Screening Risk: {res.screening_result.risk_level}")
            for sig in res.screening_result.all_signals:
                print(f"  {sig}")

    elif args.command == "compare":
        seed_demo(store)
        supervisor = SupervisorAgent(store)
        companies = args.companies.split(",")
        comp = supervisor.audit.run_comparison(companies, store)
        print(f"\n=== CROSS-COMPANY COMPARISON ({', '.join(companies)}) ===")
        for f in comp.findings:
            print(f"• {f}")

    else:
        print(json.dumps(store.stats(), ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    """Khai báo cấu trúc tham số lệnh CLI và các subcommands rõ ràng."""
    parser = argparse.ArgumentParser(
        description="Công cụ quản trị dòng lệnh ESG Intelligence & Audit CLI"
    )
    parser.add_argument("--database", type=Path, default=settings.database_path)
    commands = parser.add_subparsers(dest="command", required=True)

    # Subcommand: ingest
    ingest = commands.add_parser("ingest", help="Ingest dataset từ metadata CSV")
    ingest.add_argument("--metadata", type=Path, required=True)
    ingest.add_argument("--reports-dir", type=Path, required=True)
    ingest.add_argument("--limit", type=int)
    ingest.add_argument("--force", action="store_true")

    # Subcommand: evaluate
    evaluate = commands.add_parser(
        "evaluate", help="Đánh giá chất lượng truy xuất (Retrieval Evaluation: Recall, MRR, nDCG)"
    )
    evaluate.add_argument("--cases", type=Path, default=DEFAULT_EVALUATION)
    evaluate.add_argument("--top-k", type=int, default=5)
    evaluate.add_argument("--mode", type=str, default="hybrid_rerank")
    evaluate.add_argument("--min-recall", type=float, default=0)
    evaluate.add_argument("--min-mrr", type=float, default=0)

    # Subcommand: benchmark
    benchmark = commands.add_parser(
        "benchmark", help="Chạy thực nghiệm bóc tách (Ablation Study) 4 cấu hình Retrieval"
    )
    benchmark.add_argument("--cases", type=Path, default=DEFAULT_EVALUATION)
    benchmark.add_argument("--top-k", type=int, default=5)

    # Subcommand: evaluate-answer
    ans_eval = commands.add_parser(
        "evaluate-answer", help="Đánh giá chất lượng câu trả lời và tỷ lệ ảo giác"
    )
    ans_eval.add_argument("--cases", type=Path, default=DEFAULT_ANSWER_EVAL)
    ans_eval.add_argument("--top-k", type=int, default=5)
    ans_eval.add_argument("--min-faithfulness", type=float, default=0.0)

    # Subcommand: evaluate-extraction
    ext_eval = commands.add_parser(
        "evaluate-extraction", help="Đánh giá độ chính xác trích xuất số liệu ESG có cấu trúc"
    )
    ext_eval.add_argument("--top-k", type=int, default=6)

    # Subcommand: audit
    audit = commands.add_parser("audit", help="Chạy kiểm toán ESG và xuất Evidence Matrix")
    audit.add_argument("--document-id", type=str)
    audit.add_argument("--top-k", type=int, default=12)

    # Subcommand: compare
    compare = commands.add_parser(
        "compare", help="So sánh đối chiếu chất lượng công bố giữa các doanh nghiệp"
    )
    compare.add_argument("--companies", type=str, default="Boeing,NextEra Energy,Alcoa")

    # Subcommand: stats
    commands.add_parser("stats", help="Hiển thị thống kê tổng quan corpus")
    return parser


def _enable_utf8_output() -> None:
    """Đảm bảo Standard Output ghi đè chuẩn mã hóa UTF-8 để không bị lỗi ký tự trên Windows Console."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
