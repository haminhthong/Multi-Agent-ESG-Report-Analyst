# Canonical Runtime Pipeline

This document defines the runtime path that should be treated as authoritative for the project.

## System boundary

The repository is an **evidence-grounded ESG report analysis and screening system**. It is not an autonomous auditor, ESG rating agency, legal opinion, or greenwashing verdict engine.

The architecture is divided into four responsibilities:

1. **Adapters** — FastAPI, CLI, web UI.
2. **Application orchestration** — `app/workflow.py`.
3. **Bounded capabilities** — planning, retrieval, verification, extraction, disclosure analysis, screening, synthesis.
4. **Infrastructure** — PDF extraction, SQLite/FTS, embeddings, reranking, model clients.

Adapters must not create a second business workflow. They call `ESGAnalysisPipeline`.

## Offline ingestion

```text
PDF
 |
 v
DocumentIngestionService
 |-- validate PDF signature/type/size
 |-- SHA-256 document identity
 v
DocumentIntelligenceAgent
 |-- PyPDF native text extraction
 |-- page preservation
 |-- heuristic heading/text/table-like blocks
 |-- bbox=None (no synthetic coordinates)
 v
Text quality gate
 |-- reject OCR-required reports
 v
Chunking + metadata
 v
Store
 |-- document metadata
 |-- page-aware chunks
 |-- FTS5/BM25
 |-- optional dense representations
```

### Provenance contract

The current parser guarantees document identity, page number, extracted text, block id/type, and section metadata when available.

It does **not** guarantee geometric PDF coordinates. Exact bounding boxes must only be introduced with a parser that returns real source coordinates.

## Online analysis

```text
HTTP / CLI request
      |
      v
ESGAnalysisPipeline
      |
      +--> 0. Validate request/document scope
      |
      +--> 1. QueryPlanningAgent
      |       -> RetrievalPlan
      |
      +--> 2. RetrievalAgent
      |       -> BM25 / dense / hybrid
      |       -> multi-query RRF fusion
      |       -> optional reranking
      |       -> page diversification
      |
      +--> 3. EvidenceVerificationAgent
      |       -> citation metadata/excerpt checks
      |       -> deduplication
      |
      +--> 4. EvidenceExtractionAgent
      |       -> ESGFact
      |       -> normalization
      |       -> conflicts
      |
      +--> 5. Evidence Completeness Gate
      |       -> required / satisfied / missing
      |
      +--> 6. ESGAuditAgent
      |       -> disclosure evidence matrix
      |       -> E/S/G evidence coverage
      |       -> heuristic screening
      |
      +--> 7. Specialized analysis (optional)
      |       -> temporal trend or comparison
      |
      +--> 8. Claim-support check
      |       -> support against retrieved excerpts
      |
      +--> 9. ExplanationAgent
              -> grounded answer or deterministic fallback
```

The output is one `AnalysisResponse` containing the answer, citations, structured facts, evidence matrix, conflicts, completeness state, screening output, limitations, and per-stage trace.

## Current module ownership

```text
app/
  capabilities/
    planning.py
    retrieval.py
    verification.py
    explanation.py
  workflow.py
  document_intelligence.py
  document_service.py
  evidence_extractor.py
  rubric.py
  store.py
  embeddings.py
  reranker.py
  llm.py
  main.py
  cli.py
  agents.py          # legacy compatibility during migration
```

Planning, retrieval, verification, and explanation are now isolated from the legacy `agents.py` module. `ESGAuditAgent` remains in the legacy module temporarily because it still contains a large set of coupled rubric, temporal, comparison, and screening behaviors.

New orchestration logic must be added to `workflow.py`, not `agents.py`.

## Evidence verification semantics

The current verifier answers a narrow engineering question:

> Is this retrieved citation structurally usable, and does a candidate claim have lexical support in the retrieved excerpts?

It checks metadata, page values, excerpt content, duplicate signatures, and lightweight claim support.

It does not answer:

> Is the issuer's disclosure objectively true in the real world?

That would require independent external sources or assurance evidence.

## Greenwashing screening semantics

Screening uses transparent heuristic signals such as missing baselines, missing interim milestones, weak quantitative evidence, absent assurance evidence, negative performance language, and vague language density.

`LOW / MEDIUM / HIGH` means **review priority**, not innocence/guilt or legal classification.

## Quality gates

A portfolio-grade change should be backed by executable checks:

- deterministic workflow tests;
- retrieval evaluation on fixed cases;
- extraction evaluation for metric/value/unit/year;
- grounding/unsupported-claim evaluation;
- PDF ingestion and OCR-required tests;
- provenance test ensuring bbox is not fabricated;
- API tests;
- lint/format checks;
- Docker build;
- documented limitations.

Snapshot metrics in `reports/` are artifacts. They should be regenerated after material code, dataset, or model changes before being quoted externally.

## Remaining migration work

1. Move `ESGAuditAgent` out of `app/agents.py` into bounded domain/capability modules.
2. Separate ESG rubric evaluation from greenwashing screening.
3. Persist analysis runs/traces rather than retaining only the latest response in memory.
4. Add coordinate-aware PDF parsing before enabling bbox provenance.
5. Add OCR as an explicit worker/stage.
6. Expand independently annotated evaluation data.
7. Add stronger entailment-style claim verification.
8. Add versioned rubric definitions and analysis-run metadata.

This incremental migration keeps existing API behavior usable while moving the active runtime toward a maintainable application architecture.
