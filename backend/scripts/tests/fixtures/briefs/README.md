# Professional brief fixtures (BRIEF-003)

Each `<name>.txt` is a document for the professional upload-brief pipeline, and
`<name>.expected.json` lists what a correct brief must contain. The expectations
were written from each document's own content, before the extraction code was
changed, and are not copied from any code output.

| Fixture | Type | Content |
|---|---|---|
| `judgment.txt` | judgment | Trimmed excerpt of a public judgment from the curated corpus (Neelam @ Neeraj vs The State Of Madhya Pradesh, Madhya Pradesh High Court, 8 February 2019, Indian Kanoon). Counsel names and signature blocks removed. |
| `fir_synthetic.txt` | FIR | SYNTHETIC |
| `chargesheet_synthetic.txt` | charge sheet / final report | SYNTHETIC |
| `petition_synthetic.txt` | petition | SYNTHETIC |
| `unknown_synthetic.txt` | unknown / ambiguous | SYNTHETIC |

Every synthetic fixture says `SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD` at
the top and bottom. Its names (for example "Meera Placeholder", "Ravi
Sampleton"), places ("Fictionalpur", "Samplepur", "Fictionaland") and case, FIR and
amount figures are invented. They contain no phone numbers, addresses of real
places, or identity numbers. A line containing only `\f` marks a page
break; the tests render each fixture into a real PDF, one page per part, and
run it through the product parser, chunker and local document map.

Expected-output fields: `document_type`; `parties` (name and role that must
appear); `dated_events` (ISO dates that the chronology must contain, in sorted
order); `procedural_stages` (stage labels that must appear);
`evidence_categories` (categories that must be detected) and
`absent_evidence_categories` (categories that must not be).
