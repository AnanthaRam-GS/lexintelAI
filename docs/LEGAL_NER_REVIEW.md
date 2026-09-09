# Legal NER Human Review Packet

Version: `legalai-ner-eval-v1`

Schema: `legalai-ner-schema-v1`

Status: `READY FOR HUMAN NER ANNOTATION`

These examples are independently authored short legal-style queries and
sentences. They are separate from the frozen retrieval benchmark and do not
copy retrieval qrels, ranks, scores, or candidate relevance labels.

Annotators should fill human gold entities only after reviewing the exact text.
Deterministic suggestions, if generated separately with the NER baseline, are
not gold labels.

Entity types: `PERSON`, `ORGANIZATION`, `COURT`, `LOCATION`, `DATE`, `STATUTE`,
`SECTION`, `CASE_CITATION`, `CASE_NAME`, `LEGAL_PROCEDURE`, `OFFENCE`,
`LEGAL_ROLE`, `POLICE_STATION`, `FIR_NUMBER`.

## Annotation Slots

For each example:

- Entity span:
- Entity type:
- Notes:

## Examples

### ner-q001

Text: Section 302 IPC was considered by the Supreme Court.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q002

Text: Can anticipatory bail under Section 438 CrPC be granted in a 2023 cheating case?

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q003

Text: An appeal under Section 482 BNSS was filed in the Karnataka High Court.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q004

Text: Which BNS provision applies after 1 July 2024 for a murder allegation?

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q005

Text: The Delhi High Court heard a petition by Ramesh Kumar against State of NCT of Delhi.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q006

Text: FIR No. 137 of 2023 was registered at Gannavaram Urban Police Station.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q007

Text: A complaint was filed at Hauz Qazi Police Station for criminal breach of trust.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q008

Text: State of Maharashtra v. Arjun Singh involved Section 420 IPC.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q009

Text: The accused sought default bail after the charge-sheet was delayed.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

### ner-q010

Text: A minor was lured away from Bengaluru and sexually assaulted.

Gold annotation slots:

- Entity span:
- Entity type:
- Notes:

Additional examples are in `data/structured/manifests/legal_ner_eval.json`.
