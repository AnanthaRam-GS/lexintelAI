# Legal NER Annotation Guidelines

These are HUMAN GOLD annotations. No automatic suggestion is treated as gold.

Use schema version `legalai-ner-schema-v1` only.

## Entity Taxonomy

Allowed types:

- `PERSON`
- `ORGANIZATION`
- `COURT`
- `LOCATION`
- `DATE`
- `STATUTE`
- `SECTION`
- `CASE_CITATION`
- `CASE_NAME`
- `LEGAL_PROCEDURE`
- `OFFENCE`
- `LEGAL_ROLE`
- `POLICE_STATION`
- `FIR_NUMBER`

Do not add new types. If a span does not fit this schema, leave it unannotated
and add a review note.

## Exact-Span Policy

Gold labels use exact character span plus canonical entity type. Prefer the
smallest complete legally meaningful span.

Store:

- `text`
- `entity_type`
- `start_char`
- `end_char`
- optional `notes`

Offsets index the original example text. `start_char` is inclusive and
`end_char` is exclusive. The stored `text` must exactly equal
`example_text[start_char:end_char]`.

## Overlap Policy

Avoid overlapping gold entities unless the canonical schema genuinely requires
them. For case-title spans, `CASE_NAME` takes precedence over nested `PERSON`
labels unless a later review policy explicitly changes this convention.

If an example contains a distinct case name and a formal citation, annotate
them separately where the spans do not overlap.

## Statutes And Sections

Annotate statutes as explicit spans only, such as `IPC`, `CrPC`, `BNS`, `BNSS`,
`NDPS Act`, `POCSO Act`, `SC/ST Act`, and `Evidence Act`.

Annotate sections separately from statutes. Use the same policy across the
set: include the section marker with the number for a single section span, such
as `Section 302` or `Section 438`. For list expressions, annotate the complete
section phrase when it is one legal reference span, such as
`Sections 406 and 420`, and annotate the nearby statute separately.

Do not invent cross-statute mappings.

## Courts

Annotate explicit court names or recognized court-level mentions, including
`Supreme Court`, `Supreme Court of India`, named High Courts, `Sessions Court`,
`District Court`, `Special Court`, and `trial court`.

Do not infer a court entity from context.

## Legal Roles

Annotate explicit legal-actor role terms such as `petitioner`, `appellant`,
`respondent`, `accused`, `complainant`, `prosecutrix`, `investigating officer`,
`public prosecutor`, and `judge`.

Do not annotate generic pronouns or vague actor words.

## Offences

Annotate offence mentions only when the text explicitly names or clearly
expresses a legal offence concept, such as `murder`,
`criminal breach of trust`, `rape`, `robbery`, `theft`, `cheating`,
`dowry harassment`, `kidnapping`, or `criminal conspiracy`.

Do not infer an offence merely from factual narration if the offence phrase is
absent.

## Procedures

Annotate explicit legal procedural concepts as `LEGAL_PROCEDURE`, including
`anticipatory bail`, `regular bail`, `default bail`, `criminal appeal`,
`revision`, `quashing petition`, `investigation`, `cognizance`,
`charge-sheet`, `charge sheet`, and `final report`.

Do not annotate generic words such as `case`, `matter`, or `application`
unless the complete phrase expresses a recognized procedure.

## Dates

Annotate explicit date spans only. Include relation words when they are part of
the temporal legal signal, such as `before July 2024`,
`after 1 July 2024`, or `post July 2024`. Annotate year-only spans such as
`2023` only when the year acts as a temporal reference in the sentence.

## Organizations And Locations

Annotate companies, agencies, departments, institutions, and government bodies
as `ORGANIZATION`.

Annotate cities, states, districts, and places as `LOCATION`.

Do not double-label a police station as `ORGANIZATION` when it is already
annotated as `POLICE_STATION`.

## FIR And Police Station

Annotate full FIR identifier phrases as `FIR_NUMBER`, for example
`FIR No. 137 of 2023`.

Annotate the full police-station name as `POLICE_STATION`, for example
`Gannavaram Urban Police Station`.

## Zero-Entity Examples

Reviewed examples may legitimately have zero entities. Mark them as
`reviewed` with `gold_entities: []` only after a human reviewer confirms that
no span should be labeled.

Pending examples may also have zero entities before review.

## Ambiguous Cases

When a span is ambiguous, prefer no annotation over guessing. Add a short note
describing why the span was left out or why the chosen type is uncertain.

## Reviewer Workflow

1. Open `docs/LEGAL_NER_GOLD_REVIEW.md` for batch review.
2. Enter candidate spans in the table while checking exact characters.
3. Materialize approved spans into `data/structured/manifests/legal_ner_gold_template.json`.
4. Set each reviewed example to `reviewed`.
5. Run `python3 backend/scripts/validate_legal_ner_eval.py`.
6. Fix any offset, type, duplicate, or text-identity errors before metrics.
