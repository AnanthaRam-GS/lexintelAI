# LegalAI Development Judgment Corpus

## Scope

Phase 0 Step 0.4B targets approximately 30 genuine Indian criminal judgments
for development and review. This corpus is intentionally small so the team can
validate acquisition quality, provenance, attribution, duplicate handling, and
review workflow before any larger corpus collection.

## Current Acquisition Status

No judgments have been acquired yet because `INDIAN_KANOON_API_TOKEN` is not
configured in the local environment. The query plan and acquisition tooling are
ready for controlled use once API credentials are available.

## Planned Composition

The planned query set covers ten offence families with about three useful
judgments per group, subject to actual source quality:

- homicide
- hurt and assault
- theft and robbery
- cheating and fraud
- criminal breach of trust
- kidnapping
- sexual offences
- dowry and domestic cruelty
- conspiracy and common intention
- narcotics-related criminal matters

Court diversity should include Supreme Court and High Court judgments where
possible. District or Sessions-level material may be included only when
reliably available from the approved source.

Temporal diversity should include pre-2015, 2015-2019, 2020-2023, and 2024
onwards where suitable criminal judgments exist.

Legal regime labels must be based on actual statutory context. A post-July 2024
judgment must not automatically be classified as BNS/BNSS.

## Human Review

Every acquired development judgment must enter
`data/structured/manifests/development_judgment_review.json` with
`human_review_status` set to `pending`. The team must review relevance,
metadata quality, source traceability, and suitability before any downstream
RAG or NLP use.

## Attribution

Indian Kanoon-acquired records must set `attribution_required` to `true` and
retain attribution text suitable for later product display. API credentials and
provider logos must not be committed.

## Reconstruction

Raw judgment binaries are intentionally excluded from Git under
`data/raw/judgments/indiankanoon/`. Another developer can reconstruct local raw
files using:

- `data/structured/manifests/development_judgment_queries.json`
- `data/structured/manifests/development_judgments.json`
- `backend/scripts/acquire_development_judgments.py`
- valid Indian Kanoon API access through `INDIAN_KANOON_API_TOKEN`

Run dry-run first:

```bash
python3 backend/scripts/acquire_development_judgments.py --dry-run
```

Then acquire in stages only after credentials are configured:

```bash
python3 backend/scripts/acquire_development_judgments.py --limit 3
python3 backend/scripts/validate_corpus.py
```

Proceed toward 10 and then approximately 30 only if the earlier stage validates.
