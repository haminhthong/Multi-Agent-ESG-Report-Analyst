import atexit
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.answer_eval import evaluate_answer_quality, load_answer_eval_cases
from app.demo import seed_demo
from app.embeddings import embedding_engine
from app.evaluation import (
    ExtractionEvalCase,
    evaluate_extraction,
    evaluate_retrieval_ablation,
    load_evaluation_cases,
)
from app.pipeline import ESGPipeline
from app.reranker import reranker
from app.store import Store


def compute_file_hash(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()[:16]


def get_git_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main():
    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    db_path = REPO_ROOT / "scratch" / "benchmark_run.db"
    if db_path.exists():
        db_path.unlink()
    atexit.register(db_path.unlink, missing_ok=True)
    store = Store(db_path)
    seed_demo(store)

    cases_path = REPO_ROOT / "data" / "evaluation" / "retrieval_cases.json"
    ans_cases_path = REPO_ROOT / "data" / "evaluation" / "answer_eval_cases.json"
    demo_files = list((REPO_ROOT / "data" / "demo").glob("*.txt"))

    dataset_hashes = {f.name: compute_file_hash(f) for f in demo_files}
    dataset_hashes["retrieval_cases.json"] = compute_file_hash(cases_path)
    dataset_hashes["answer_eval_cases.json"] = compute_file_hash(ans_cases_path)

    cases = load_evaluation_cases(cases_path)
    ans_cases = load_answer_eval_cases(ans_cases_path)

    print("1. Running Retrieval Ablation Benchmark...")
    ablation = evaluate_retrieval_ablation(store, cases, top_k=5)
    ablation_json = ablation.model_dump_json(indent=2)
    (reports_dir / "retrieval_ablation.json").write_text(ablation_json, encoding="utf-8")
    print("   -> Saved reports/retrieval_ablation.json")

    print("2. Running Structured Fact Extraction Benchmark...")
    pipeline = ESGPipeline(store)
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
        ExtractionEvalCase(
            id="alcoa_female_diversity",
            question="What is female representation in professional roles at Alcoa?",
            query_scope=["alcoa-demo"],
            expected_metric="diversity_percentage",
            expected_value=28.5,
            expected_unit="%",
            expected_year=2024,
        ),
    ]
    ext_report = evaluate_extraction(pipeline, extraction_cases)
    ext_json = ext_report.model_dump_json(indent=2)
    (reports_dir / "extraction_eval.json").write_text(ext_json, encoding="utf-8")
    print("   -> Saved reports/extraction_eval.json")

    print("3. Running Answer Quality & Faithfulness Benchmark...")
    ans_report = evaluate_answer_quality(pipeline, ans_cases, top_k=6)
    ans_json = ans_report.model_dump_json(indent=2)
    (reports_dir / "answer_eval.json").write_text(ans_json, encoding="utf-8")
    print("   -> Saved reports/answer_eval.json")

    # Backend status check
    _ = embedding_engine._get_model()
    _ = reranker._get_model()
    emb_backend = (
        f"SentenceTransformer ({embedding_engine.model_name})"
        if not embedding_engine._is_fallback
        else "Feature Hashing 384-dim (Offline Fallback)"
    )
    rerank_backend = (
        f"CrossEncoder ({reranker.model_name})"
        if not reranker._is_fallback
        else "Lexical Proximity & Entity Overlap (Offline Fallback)"
    )

    manifest = {
        "manifest_version": "1.0.0",
        "platform": "Evidence-Grounded ESG Intelligence & Audit Platform",
        "git_commit": get_git_sha(),
        "generated_at": datetime.now(UTC).isoformat(),
        "execution_backend": {
            "embedding_engine": emb_backend,
            "embedding_fallback_active": embedding_engine._is_fallback,
            "reranker_engine": rerank_backend,
            "reranker_fallback_active": reranker._is_fallback,
            "storage_backend": "SQLite FTS5 + JSON Embeddings",
            "llm_engine": "Deterministic Engine (Heuristic Grounding Fallback)",
        },
        "dataset_scope": {
            "benchmark_corpus_type": "Curated multi-company ESG excerpts benchmark",
            "companies": ["The Boeing Company", "NextEra Energy", "Alcoa Corporation"],
            "files_sha256": dataset_hashes,
        },
        "summary_metrics": {
            "retrieval": {
                "cases_count": ablation.cases,
                "top_k": ablation.top_k,
                "systems": [s.model_dump() for s in ablation.systems],
            },
            "extraction": {
                "cases_count": ext_report.cases,
                "precision": ext_report.precision,
                "recall": ext_report.recall,
                "f1_score": ext_report.f1_score,
            },
            "answer_faithfulness": {
                "cases_count": ans_report.cases,
                "faithfulness": ans_report.faithfulness,
                "citation_correctness": ans_report.citation_correctness,
                "unsupported_claim_rate": ans_report.unsupported_claim_rate,
            },
        },
    }

    (reports_dir / "benchmark_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("4. -> Saved reports/benchmark_manifest.json")
    print("DONE!")


if __name__ == "__main__":
    main()
