# Legal Grounded Answer Foundation

## Purpose

Phase 0 Step 0.9A defines the answer-generation boundary that sits after
`LegalQueryUnderstanding` and `LegalRetrievalResult`. It prepares citation-grounded
answer contracts, prompt construction, model adapter contracts, and deterministic
validation. It does not run formal LLM evaluation or create production answers.

## Architecture

Flow:

1. Raw query is analyzed by the existing query-understanding service.
2. Frozen retrieval returns `LegalRetrievalResult`.
3. `GroundedEvidencePacket` selects bounded prompt inputs.
4. `build_legal_answer_prompt` constructs mode-specific structured instructions.
5. A `LegalAnswerModelAdapter` may later produce structured JSON.
6. Citation validation checks evidence IDs and metadata against retrieval results.
7. Structural grounding validation marks claims as grounded, partially grounded,
   ungrounded, or insufficiently supported.

## Input Contracts

The answer layer consumes:

- `LegalQueryUnderstanding`
- `LegalRetrievalResult`

It does not modify retrieval, query understanding, NER, legal section prediction, or
ranking configuration.

## Evidence Packet

`GroundedEvidencePacket` includes the original query, normalized legal signals,
explicit user sections, supplementary predicted sections, regime, procedural posture,
offence families, and exact retrieved chunk text.

Evidence IDs are preserved as response-local IDs such as `E1` through `E5`. Retrieved
text is inserted exactly as stored. There is no hidden summarization stage.

## Public Schema

`PublicLegalAnswer` supports:

- `summary`
- `what_this_may_mean`
- `possible_legal_provisions`
- `possible_next_steps`
- `important_cautions`
- structured `citations`

Public mode avoids internal retrieval scores and uses plain, uncertainty-preserving
language.

## Professional Schema

`ProfessionalLegalBrief` supports future professional UI sections:

- issue summary
- material facts from query
- explicit legal provisions
- potential additional provisions
- procedural posture
- legal regime
- retrieved authorities
- legal issues
- applicable principles
- analysis
- counterpoints
- uncertainties
- recommended research questions
- structured citations

Professional mode preserves richer citation metadata without fabricating missing fields.

## Prompt Construction

The prompt builder emits strong structured blocks:

- `<SYSTEM_RULES>`
- `<ANSWER_MODE>`
- `<MODE_REQUIREMENTS>`
- `<QUERY_CONTEXT>`
- `<EVIDENCE_SET>`
- `<EVIDENCE id="...">`
- `<METADATA>`
- `<TEXT>`
- `<CITATION_POLICY>`

The structured citation objects are authoritative. Prose markers such as `[E1]` are not
enough by themselves.

## Prompt Injection Defense

Prompt instructions explicitly state that retrieved judgments and user documents are
data, not instructions. Evidence content cannot override system rules, and instructions
inside judgments must be ignored.

## Citation Rules

Citations may only reference evidence IDs present in `LegalRetrievalResult.evidence`.
Unknown IDs such as `E6`, invented case names, unsupported URLs, and mismatched
metadata fail validation.

## Claim Grounding Rules

Legal rules, procedural guidance, case-law claims, statutory-reference explanations,
and factual summaries require at least one valid evidence citation. General cautions may
remain uncited if clearly non-case-specific.

Grounding statuses:

- `STRUCTURALLY_GROUNDED`
- `PARTIALLY_GROUNDED`
- `UNGROUNDED`
- `INSUFFICIENT_RETRIEVED_AUTHORITY`

This is structural validation only. It does not claim semantic entailment is proven.

## Uncertainty

Supported uncertainty and warning codes include:

- `INSUFFICIENT_RETRIEVED_AUTHORITY`
- `AMBIGUOUS_LEGAL_REGIME`
- `INSUFFICIENT_FACTS`
- `CONFLICTING_AUTHORITIES`
- `PREDICTED_SECTION_UNCERTAIN`
- `CITATION_VALIDATION_FAILED`
- `MODEL_UNAVAILABLE`
- `MODEL_OUTPUT_VALIDATION_FAILED`

## Insufficient Retrieval Behavior

If retrieved evidence is empty, the service returns
`INSUFFICIENT_RETRIEVED_AUTHORITY` and does not call the model adapter. It may support
limited general information later, but it must not invent supporting cases.

## Gemini Adapter Contract

`GeminiAnswerAdapter` reads provider configuration from `Settings`. API keys come from
environment settings only. Model IDs are configuration values such as `GEMINI_MODEL`;
runtime code does not hardcode a Gemini version.

Example environment configuration:

```bash
LEGALAI_LLM_PROVIDER=gemini
GEMINI_MODEL=<configured Gemini model>
GEMINI_API_KEY=<set in local environment>
```

## Ollama Fallback Contract

Local fallback is explicit and transparent. If used later, `model_metadata` must expose
the primary provider, fallback provider, fallback reason, and `fallback_used=true`.
Ollama endpoint and model names are configurable through settings.

## Structured Output

The adapter contract returns raw response text, parsed response data, model metadata,
timings, and errors. Structured Pydantic schemas are the contract; arbitrary Markdown is
not authoritative.

Any future repair behavior is limited to one bounded schema/format repair attempt and
must not add facts or citations.

## Validation

`legal_citation_validation` verifies citation IDs, claim linkage, duplicate malformed
citations, and metadata consistency with current retrieval evidence.

`validate_claim_grounding` assigns a structural grounding status based on whether
claims requiring citations actually cite current evidence.

## Dry-Run Workflow

Use:

```bash
.venv/bin/python backend/scripts/build_grounded_legal_answer.py "Section 302 IPC murder bail before Sessions Court"
```

Dry run performs query understanding, retrieval, evidence packet construction, and
prompt construction. It reports evidence IDs, citation metadata, answer schema, citation
policy, and prompt character estimate. It does not call a live LLM.

## No-LLM Boundary For Tests

Unit tests use mocked adapters and fabricated evidence fixtures only. Gemini and Ollama
availability is not required.

## Limitations

This foundation validates structure, not answer quality. It does not score legal
accuracy, compare LLMs, tune prompts, persist answer history, expose API routes, or
build frontend behavior.

## Future Evaluation

Later phases can add controlled live LLM integration, answer-quality review sets,
grounding evaluation, citation correctness metrics, and prompt tuning after this
contract is frozen.
