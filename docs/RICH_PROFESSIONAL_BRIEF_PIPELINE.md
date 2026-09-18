# Rich Professional Brief Pipeline

Professional Upload Brief mode keeps the single-call architecture:

FULL PDF -> local extractive legal analysis -> rich bounded document map -> bounded trusted authority -> one final LLM synthesis.

The uploaded PDF is parsed and chunked in memory. LegalAI then builds a request-local `LocalDocumentMap` with deterministic, non-generative extraction for document type, parties and roles, dates, chronology, explicit statutory provisions, evidence categories, procedural posture, findings, orders, and limitations. The map stores bounded P#-traceable excerpts rather than raw whole-document text.

The generative model is used only for the final synthesis. It does not repeatedly read every PDF chunk, and it does not create an intermediate summary through multiple provider calls.

## Evidence Boundaries

P# items are private uploaded-document evidence. They describe user-provided document content and are never legal authority or precedent citations.

E# items are trusted retrieved legal authorities from the product corpus. They remain the only source for precedent/legal-authority citations.

The final brief prompt keeps these categories separate and instructs the model to summarize what the uploaded document says before applying trusted legal analysis.

## Expected Brief Shape

When supported by the uploaded document and trusted authority, the professional brief should cover:

- Executive Summary
- Parties & Roles
- Material Facts
- Chronology / Procedural History
- Explicit Statutory Provisions
- Evidence Identified
- Key Legal Issues
- Precedent Analysis & Judicial Rationale
- Procedural Considerations
- Limitations / Missing Information

Empty sections are preferable to invented facts. Short documents may produce short briefs; substantial documents should produce a fuller case-file digest within the configured context budget.

## Budget And Privacy

The local map is capped by per-field limits, excerpt length limits, global multi-intent retrieval budget, and the product private-PDF input budget. If the map cannot fit after trusted evidence and prompt overhead, the request fails locally instead of relying on provider 413 errors.

The pipeline does not mutate global Chroma, BM25, ingestion state, benchmark files, or persisted raw PDF data. Observability logs contain counts and token estimates only, never document text.
