# Multi-Agent ESG Report Analyst

Evidence-grounded ESG report analysis with a clear ingestion pipeline, hybrid retrieval, structured fact extraction, disclosure-evidence scoring, greenwashing risk screening, and traceable responses.

> This project is an **analysis and screening system**, not an accounting audit, legal opinion, ESG rating, or fraud detector. Results are limited to the documents and evidence retrieved by the system.

## Why this project exists

Sustainability reports are long, inconsistent, and difficult to compare. A useful ESG assistant should do more than send PDF chunks to an LLM. It should preserve source identity, retrieve the right evidence, extract structured facts, expose missing evidence, and show how a conclusion was produced.

This repository implements that workflow as an application rather than a collection of independent agent demos.

## What the system does

Given one or more ESG / sustainability PDF reports, the system can:

- ingest and validate PDF files;
- preserve document and page provenance;
- create text chunks with section/block metadata;
- retrieve evidence using BM25, dense retrieval, hybrid fusion, and optional reranking;
- classify analytical intent and generate retrieval subqueries;
- extract ESG facts such as emissions, energy, targets, years, and safety metrics;
- normalize supported units such as `ktCO2e -> tCO2e` and `GWh -> MWh`;
- detect conflicting disclosures for compatible metric/year/methodology groups;
- build an E/S/G disclosure evidence matrix;
- identify missing required evidence;
- screen greenwashing-related disclosure risks using transparent heuristics;
- perform temporal and cross-company disclosure analysis;
- generate a grounded answer with citations and an execution trace.

## Canonical architecture

The project has two distinct flows.

### 1. Offline ingestion

```text
PDF report
   |
   v
File validation
   |-- PDF magic bytes / type / size
   |-- SHA-256 document identity
   v
Native text extraction
   |-- preserve page number
   |-- heuristic heading / text / table-like blocks
   |-- no fabricated PDF coordinates
   v
Quality gate
   |-- text-page ratio
   |-- reject OCR-required documents
   v
Chunking + metadata
   v
SQLite-backed search indexes
   |-- FTS5 / BM25
   |-- optional dense embeddings
```

### 2. Online analysis

```text
Question / audit request
        |
        v
[0] Validate document scope
        |
        v
[1] QueryPlanningAgent
        |-- intent
        |-- subqueries
        |-- required evidence
        v
[2] RetrievalAgent
        |-- BM25 / dense / hybrid
        |-- multi-query RRF fusion
        |-- optional reranker
        |-- page diversification
        v
[3] EvidenceVerificationAgent
        |-- page + document metadata checks
        |-- excerpt validation
        |-- deduplication
        v
[4] EvidenceExtractionAgent
        |-- ESGFact extraction
        |-- unit normalization
        |-- year association
        |-- conflict detection
        v
[5] Evidence Completeness Gate
        |-- satisfied requirements
        |-- missing requirements
        v
[6] ESGAuditAgent
        |-- disclosure evidence matrix
        |-- E / S / G coverage
        |-- heuristic greenwashing screening
        v
[7] Optional specialized analysis
        |-- temporal trend
        |-- company comparison
        v
[8] Claim-support check
        v
[9] ExplanationAgent
        |
        v
AnalysisResponse + citations + limitations + trace
```

The canonical orchestration lives in `app/workflow.py`. FastAPI and CLI use the same runtime path.

## Project structure

```text
Multi-Agent-ESG-Report-Analyst/
├── app/
│   ├── capabilities/
│   │   ├── planning.py          # Intent classification + RetrievalPlan
│   │   ├── retrieval.py         # Search, RRF fusion, diversification
│   │   ├── verification.py      # Citation + claim-support validation
│   │   └── explanation.py       # Grounded synthesis + fallback
│   ├── workflow.py              # Canonical application orchestration
│   ├── document_intelligence.py # PyPDF text extraction; no fake bbox
│   ├── document_service.py      # PDF validation, quality gate, indexing
│   ├── chunking.py              # Chunking and block metadata
│   ├── evidence_extractor.py    # ESGFact extraction + normalization
│   ├── rubric.py                # ESG disclosure criteria / patterns
│   ├── store.py                 # SQLite, FTS5, retrieval storage
│   ├── embeddings.py            # Optional dense embeddings
│   ├── reranker.py              # Optional cross-encoder reranking
│   ├── llm.py                   # Optional local LLM integration
│   ├── main.py                  # FastAPI adapter
│   ├── cli.py                   # CLI adapter
│   ├── models.py                # Pydantic contracts
│   └── agents.py                # Legacy compatibility during migration
├── data/
│   ├── demo/
│   └── evaluation/
├── docs/
├── reports/
├── tests/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

`app/agents.py` is intentionally retained for backward compatibility while large legacy capabilities are migrated incrementally. New orchestration should not be added there.

## Core data contracts

### RetrievalPlan

A query is converted into an explicit plan:

```json
{
  "intent": "greenwashing_screening",
  "subqueries": [
    "target year baseline year",
    "Scope 1 Scope 2 Scope 3 metrics",
    "external assurance"
  ],
  "required_evidence": ["target", "baseline", "emissions", "assurance"],
  "document_scope": ["document-id"]
}
```

### ESGFact

Extracted quantitative evidence is represented separately from generated prose:

```json
{
  "metric": "scope_1_emissions",
  "value": 12.5,
  "raw_unit": "ktCO2e",
  "normalized_value": 12500.0,
  "normalized_unit": "tCO2e",
  "year": 2024,
  "baseline_year": 2020,
  "confidence": 0.9
}
```

### AnalysisResponse

The response exposes not only an answer, but also:

- citations;
- extracted facts;
- evidence matrix;
- conflicts;
- evidence completeness;
- screening result;
- temporal/comparison outputs when applicable;
- limitations;
- per-stage trace and latency.

## Greenwashing screening: what it means

The system uses transparent signals such as:

- target disclosed but baseline missing;
- no interim milestone found;
- weak quantitative evidence;
- no external assurance evidence retrieved;
- negative performance wording;
- vague narrative language dominating quantitative evidence.

The resulting `LOW / MEDIUM / HIGH` value is a **screening priority**, not a statement that a company committed greenwashing.

## Evidence verification: what is actually verified

`EvidenceVerificationAgent` currently checks the retrieved evidence layer:

- valid page number;
- document identity fields;
- non-trivial excerpt content;
- duplicate citations;
- lightweight claim-to-retrieved-excerpt support.

It does **not** independently verify whether the company disclosure itself is true. Independent assurance would require external evidence and a different verification process.

## PDF provenance boundary

The current PDF implementation uses PyPDF native text extraction. It preserves page numbers and heuristic block types, but does **not** produce trustworthy physical bounding boxes.

Therefore `bbox=None` is deliberate. Exact coordinates should only be added when a coordinate-aware layout parser is integrated.

## Retrieval

The repository supports multiple retrieval modes depending on installed dependencies/configuration:

- BM25 / SQLite FTS5;
- dense semantic retrieval;
- hybrid retrieval;
- multi-query Reciprocal Rank Fusion (`k=60`);
- optional cross-encoder reranking;
- page diversification.

This makes retrieval behavior measurable independently from answer generation.

## Evaluation

Evaluation is treated as executable project code rather than a README claim.

Available evaluation paths include:

```bash
# Unit + integration tests
python -m pytest

# Retrieval quality gate
python -m app.cli --database data/eval.db evaluate \
  --top-k 5 \
  --min-recall 0.8 \
  --min-mrr 0.8

# Retrieval ablation
python -m app.cli --database data/eval.db benchmark --top-k 5

# Structured ESG extraction
python -m app.cli --database data/eval.db evaluate-extraction

# Answer grounding
python -m app.cli --database data/eval.db evaluate-answer
```

Snapshot benchmark files under `reports/` are reproducibility artifacts, not production certification. When code, datasets, or retrieval models change, rerun the evaluation before quoting metrics.

## Quick start

### Requirements

- Python 3.11+
- SQLite with FTS5 support
- optional: `sentence-transformers` / PyTorch for dense retrieval and reranking
- optional: Ollama for local LLM synthesis

### Install

```bash
git clone https://github.com/haminhthong/Multi-Agent-ESG-Report-Analyst.git
cd Multi-Agent-ESG-Report-Analyst

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

For optional ML retrieval dependencies:

```bash
pip install -e ".[ml]"
```

### Run API

```bash
uvicorn app.main:app --reload
```

Useful endpoints:

```text
GET  /health
GET  /api/documents
POST /api/documents
POST /api/search
POST /api/query
POST /api/audit
POST /api/compare
POST /api/temporal
GET  /api/analysis/recent/trace
```

FastAPI interactive documentation is available at `/docs` while the server is running.

### Run an audit from CLI

```bash
python -m app.cli audit --document-id <document-id> --top-k 12
```

### Docker

```bash
docker compose up --build
```

## Testing strategy

The test suite covers multiple levels:

- unit normalization;
- year / baseline association;
- retrieval behavior;
- document filtering;
- PDF ingestion quality gates;
- no-fabricated-bbox provenance behavior;
- evidence extraction conflicts;
- greenwashing counter-examples;
- API behavior;
- canonical workflow end-to-end trace.

GitHub Actions runs formatting, linting, tests, a retrieval quality gate, and Docker build.

## Current limitations

1. **Native-text PDFs first** — scanned reports are rejected when OCR is required.
2. **No exact PDF coordinates** — page provenance exists; physical bbox provenance does not yet.
3. **Heuristic ESG rubric** — disclosure criteria are useful for engineering evaluation but are not a substitute for professional assurance standards interpretation.
4. **Heuristic greenwashing screening** — designed for triage, not accusation.
5. **Evaluation set size** — demo/evaluation corpora are still small relative to a production ESG intelligence platform.
6. **Legacy module remains** — `app/agents.py` is being decomposed incrementally to preserve compatibility.
7. **Local storage** — SQLite is suitable for a portfolio/single-node deployment; large-scale production would require a different persistence and vector-search strategy.

## Roadmap

Priority improvements:

- migrate remaining `ESGAuditAgent` logic out of `app/agents.py`;
- integrate coordinate-aware PDF layout extraction before enabling bbox provenance;
- add OCR as an explicit ingestion worker rather than silently processing scans;
- add document/version lineage and ingestion job status;
- expand independently annotated retrieval and extraction evaluation sets;
- add stronger claim-level entailment evaluation;
- version ESG rubric definitions;
- persist analysis runs and traces instead of keeping only the latest in memory;
- add structured logging / request correlation IDs across services;
- add production persistence/vector backends behind interfaces.

## Portfolio summary

**Multi-Agent ESG Report Analyst** demonstrates practical AI engineering across document ingestion, hybrid RAG, structured information extraction, agent orchestration, evaluation, API design, testing, Docker, and evidence-grounded AI safety boundaries.

A concise CV description:

> Built an evidence-grounded ESG report analysis system with a canonical multi-stage workflow for query planning, hybrid retrieval/RRF fusion, structured ESG fact extraction, disclosure-evidence scoring, heuristic risk screening, citation validation, evaluation, FastAPI, Docker, and automated tests; designed outputs to expose missing evidence and system limitations rather than hiding uncertainty.

## License

MIT License. See `LICENSE`.
