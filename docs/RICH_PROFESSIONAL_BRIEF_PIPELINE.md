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

Empty sections are preferable to invented facts.

## Field Sources (BRIEF-001, BRIEF-002)

The model's output schema (`ProfessionalLegalBrief`) is frozen and has no
parties, chronology or evidence fields, so the response layer
(`backend/app/services/professional_brief.py`) fills them from the local
document map, which is extractive and cannot invent content:

- **Parties & Roles:** labelled parties ("Complainant: ...", "Accused No. 1:
  ...", "Respondent No. 2: ...") and the "X vs Y" title, whose first party
  takes the document's own label (appellant, petitioner or applicant).
- **Chronology:** every date mention in its sentence, with the event named in
  the clause around the date (FIR registered, arrest, bail, judgment
  delivered ...). Dates are parsed day-first and sorted; unparseable dates are
  left out.
- **Procedural Considerations:** sentences that state a procedural stage, by
  cue. This is a different source from the chronology, followed by the
  model's procedural posture.
- **Evidence Identified:** sentences that name evidence, with their categories:
  witnesses, documents, medical/forensic, electronic, recoveries/seizures.
  The material facts are never copied here.

Model-proposed parties would be accepted only with a P# reference whose text
contains the name (`validated_llm_parties`). The frozen schema cannot carry
them today. Precedents are built from the retrieved E# evidence, not from
model text; see `docs/API_CONTRACTS.md`.

Fixtures for every document type, with expected outputs, are in
`backend/scripts/tests/fixtures/briefs/`. The pipeline tests run them through
the real parser, chunker and document map, with a mocked model. Short documents may produce short briefs; substantial documents should produce a fuller case-file digest within the configured context budget.

## Budget And Privacy

The local map is capped by per-field limits, excerpt length limits, global multi-intent retrieval budget, and the product private-PDF input budget. If the map cannot fit after trusted evidence and prompt overhead, the request fails locally instead of relying on provider 413 errors.

The pipeline does not mutate global Chroma, BM25, ingestion state, benchmark files, or persisted raw PDF data. Observability logs contain counts and token estimates only, never document text.
