from pathlib import Path

from app.evaluation import ExpectedCitation, RetrievalEvalCase, evaluate_retrieval_ablation
from app.store import Store


def test_hybrid_and_rerank_retrieval(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "doc1",
        "Renewables.pdf",
        [
            (1, "NextEra Energy invested 18 billion in wind solar and battery storage capacity."),
            (
                2,
                "Scope 1 greenhouse gas emissions rate was reduced by 43 percent against 2005 baseline.",
            ),
            (3, "Worker health and safety protocols achieved zero serious injuries or fatalities."),
        ],
    )

    # BM25 có trong bộ cài đặt cơ bản.
    bm25_res = store.search("wind solar battery storage", limit=2, mode="bm25")
    assert len(bm25_res) > 0
    assert bm25_res[0]["page"] == 1

    # CI cơ bản không cài nhóm dependency sentence-transformers tùy chọn.
    # Truy vấn này kiểm tra luồng vector dense deterministic bằng fallback
    # feature hashing. Kiểm thử đồng nghĩa ở cấp mô hình thuộc profile tích hợp
    # ML có cài đầy đủ dependency tùy chọn.
    dense_res = store.search("energy wind solar investment", limit=2, mode="dense")
    assert len(dense_res) > 0
    assert dense_res[0]["page"] == 1

    # Truy xuất hybrid kết hợp danh sách ứng viên lexical và dense bằng RRF.
    hybrid_res = store.search("clean energy battery", limit=2, mode="hybrid")
    assert len(hybrid_res) > 0
    assert "hybrid_score" in hybrid_res[0]

    # Hybrid kèm reranker vẫn có fallback deterministic khi thiếu ML extra.
    rerank_res = store.search("wind and solar investment", limit=2, mode="hybrid_rerank")
    assert len(rerank_res) > 0
    assert "rerank_score" in rerank_res[0]


def test_retrieval_ablation_report(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "doc1",
        "Report.pdf",
        [
            (10, "Scope 1 emissions were 500000 tons in 2024."),
            (20, "Board members review climate risks annually."),
        ],
    )
    cases = [
        RetrievalEvalCase(
            id="q1",
            question="What are the Scope 1 emissions?",
            expected=[ExpectedCitation(document_id="doc1", page=10)],
        )
    ]
    report = evaluate_retrieval_ablation(store, cases, top_k=2)
    assert len(report.systems) == 4
    system_names = [system.system for system in report.systems]
    assert "BM25" in system_names
    assert "Dense" in system_names
    assert "Hybrid" in system_names
    assert "Hybrid + Reranker" in system_names

    md_table = report.to_markdown_table()
    assert "| System |" in md_table
    assert "BM25" in md_table
