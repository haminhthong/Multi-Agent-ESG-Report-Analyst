from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "documents" in data


def test_documents_and_corpus_stats():
    res1 = client.get("/api/documents")
    assert res1.status_code == 200
    assert isinstance(res1.json(), list)

    res2 = client.get("/api/corpus/stats")
    assert res2.status_code == 200
    assert "chunks" in res2.json()


def test_search_endpoint():
    response = client.post("/api/search", json={"query": "emissions", "top_k": 3})
    assert response.status_code == 200
    citations = response.json()
    assert isinstance(citations, list)


def test_analyze_qa_mode():
    payload = {
        "question": "What were Scope 1 and Scope 2 emissions?",
        "top_k": 5,
        "mode": "qa",
    }
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "qa"
    assert "answer" in data
    assert "disclosure_coverage" in data
    assert "screening_signals" in data
    assert "pillars" in data
    assert isinstance(data["citations"], list)


def test_analyze_audit_mode():
    payload = {
        "question": "Perform full ESG audit",
        "top_k": 6,
        "mode": "audit",
    }
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "audit"
    assert "pillars" in data
    assert len(data["pillars"]) == 3


def test_analyze_validation_errors():
    # Question too short
    response = client.post("/api/analyze", json={"question": "hi"})
    assert response.status_code == 422

    # top_k out of bounds
    response2 = client.post("/api/analyze", json={"question": "Valid question text", "top_k": 100})
    assert response2.status_code == 422
