# Production Pipeline

This document describes the runtime path that should be treated as the canonical system flow.

## 1. System boundary

The project is an **evidence-grounded ESG report analysis system**. It is not an autonomous auditor and it does not determine whether a company is legally greenwashing.

The production boundary is split into four layers:

1. **Adapters** — FastAPI, CLI, web UI.
2. **Application workflow** — `app/workflow.py`.
3. **Domain capabilities** — query planning, retrieval, verification, fact extraction, ESG disclosure scoring, screening, synthesis.
4. **Infrastructure** — SQLite/FTS store, embeddings/reranker integration, PDF ingestion, model clients.

The key rule is that adapters do not orchestrate domain logic themselves. They call one application pipeline.

## 2. Offline ingestion flow

```text
PDF upload / dataset file
        |
        v
DocumentIngestionService
        |
        +--> file validation
        +--> size/content checks
        +--> text extraction
        +--> OCR-required quality gate
        +--> page-preserving chunking
        |
        v
Store
        |
        +--> document metadata
        +--> chunks with document_id + page
        +--> sparse index (FTS5/BM25)
        +--> optional dense representations
```

Output contract: the online pipeline must receive chunks that preserve `document_id`, page number, and text. Any claim that requires exact geometric provenance must not rely on synthetic coordinates.

## 3. Online analysis flow

```text
HTTP / CLI request
      |
      v
ESGAnalysisPipeline
      |
      +--> 0. Validate request + document scope
      |
      +--> 1. QueryPlanningAgent
      |       output: RetrievalPlan
      |
      +--> 2. RetrievalAgent
      |       BM25 / dense / hybrid / optional rerank
      |       output: candidate citations
      |
      +--> 3. EvidenceVerificationAgent
      |       metadata/excerpt validation + deduplication
      |       output: validated citations
      |
      +--> 4. EvidenceExtractionAgent
      |       structured ESG facts + normalization + conflicts
      |
      +--> 5. EvidenceCompletenessGate
      |       required evidence -> satisfied / missing
      |
      +--> 6. ESGAuditAgent
      |       disclosure rubric matrix
      |       heuristic greenwashing screening
      |
      +--> 7. Specialized analysis (optional)
      |       temporal trend OR cross-company comparison
      |
      +--> 8. Claim verification
      |       extracted claims checked against retrieved evidence
      |
      +--> 9. ExplanationAgent
              evidence-grounded response / deterministic fallback
```

The pipeline returns one `AnalysisResponse`, including citations, extracted facts, conflicts, evidence completeness, evidence matrix, screening output, limitations, and a latency trace.

## 4. Why this design is more realistic

### One runtime path

Previously, orchestration lived inside a very large `agents.py` file and API/CLI entrypoints directly depended on that supervisor. The application workflow is now explicit, so the same business sequence can be reused by HTTP, CLI, evaluation, and tests.

### Agent means capability, not marketing label

Each agent is treated as a bounded capability with an input/output contract. The application pipeline decides order and data flow. Optional LLM behavior can exist inside capabilities, but it does not control the entire system lifecycle.

### Evidence completeness is first-class

A result may be technically retrievable but still incomplete for the requested ESG question. The pipeline therefore carries `required_evidence`, `satisfied`, and `missing` fields instead of silently producing a confident answer.

### Screening is not a verdict

The greenwashing module produces heuristic analyst-review signals. It must be described as screening, not fraud detection, legal judgment, or an independent audit conclusion.

## 5. Current limitations that must remain visible

- Citation verification validates provenance fields and retrieved text structure; it is not third-party verification of the disclosure itself.
- PDF extraction is text-centric. Scanned-image reports are rejected when OCR is required unless an OCR path is explicitly enabled later.
- Geometric page layout should only be claimed when coordinates come from the source parser; synthetic `bbox` values must not be presented as real layout coordinates.
- The rubric measures **disclosure coverage in indexed evidence**, not real-world ESG performance.
- Cross-company comparison is meaningful only when document/company scope is correctly resolved.
- Heuristic fact extraction and rule-based screening need benchmark coverage on a larger, independently annotated dataset before production compliance use.

## 6. Target module split

`app/agents.py` is still too large and should be decomposed incrementally without breaking public interfaces:

```text
app/
  agents/
    query_planner.py
    retrieval.py
    verification.py
    audit.py
    explanation.py
  domain/
    evidence.py
    rubric.py
    screening.py
  application/
    workflow.py
  infrastructure/
    store.py
    document_ingestion.py
    llm.py
```

The current `app/workflow.py` is the compatibility-safe first step toward this split.

## 7. Definition of done for a portfolio-grade project

A change should not be presented as production-ready unless the repository can demonstrate:

- deterministic end-to-end workflow tests;
- retrieval evaluation with fixed test cases;
- extraction evaluation against expected values/units/years;
- grounded-answer evaluation with unsupported-claim tracking;
- API health and error contracts;
- reproducible environment through `pyproject.toml` and Docker;
- CI that executes lint + tests;
- documented limitations and non-goals;
- benchmark reports that are regenerated from code rather than manually asserted.

This keeps the project credible for AI Engineer / LLM Systems / Applied AI portfolio review.