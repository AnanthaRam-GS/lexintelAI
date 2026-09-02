# LegalAI Data Sources

## Official Statutory Sources

IPC, BNS, CrPC, and BNSS statutory texts should preferably be acquired from
official government sources such as India Code. Unofficial mirrors must not be
used when an official government source is available.

Each statutory source record must preserve source URL, source provider,
retrieval time, SHA-256 digest, file size, and local raw file path once a file
is downloaded.

## Indian Kanoon Judgments

LegalAI intends to use Indian Kanoon API access only where permitted. API
credentials must never be committed.

Bulk collection must use the documented Indian Kanoon API rather than
uncontrolled website scraping. Every acquired judgment must retain its source
URL and source document ID. Source retrieval time and SHA-256 must be recorded
for every stored raw document.

## Attribution

Current Indian Kanoon API terms require attribution where API-provided
information is used in direct product display, RAG context, or model
fine-tuning.

Manifest records carry an `attribution_required` flag. LegalAI must eventually
expose the required attribution in a prominent product or documentation
location if Indian Kanoon data is used.

Do not copy or modify provider logos into the repository during this task.

## Data Quality

Corpus acquisition and validation should check for:

- duplicate files via SHA-256
- missing metadata
- non-PDF responses
- source traceability
- file corruption
- inconsistent court names
- missing dates

## Corpus Scaling Strategy

Stage A: approximately 20-50 representative documents for pipeline development.

Stage B: approximately 500 judgments for retrieval validation.

Stage C: approximately 2,000 judgments.

Stage D: target approximately 8,000-10,000 judgments only after acquisition,
metadata quality, retrieval behavior, and API usage constraints are validated.

The 8,000-10,000 judgment target is not mandatory before implementation.
