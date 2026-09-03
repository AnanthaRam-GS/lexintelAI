# LegalAI Development Judgment Corpus

## Scope

Phase 0 Step 0.4B targets approximately 30 genuine Indian criminal judgments
for development and review. This corpus is intentionally small so the team can
validate acquisition quality, provenance, attribution, duplicate handling, and
review workflow before any larger corpus collection.

## Current Acquisition Status

Credentialed acquisition reached the Stage 2 development checkpoint with ten
validated active judgments. Acquisition toward the approximate target of 30
judgments is paused for human review because the early source results are
materially skewed toward homicide matters and produced several irrelevant,
failed, or duplicate candidates.

Current manifest status:

- validated: 10
- excluded irrelevant: 2
- excluded duplicate: 1
- failed: 1
- pending human review: 13

The active validated corpus currently contains eight homicide records and two
hurt-and-assault records. All legal regime labels remain `unknown` until human
review confirms statutory context.

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

Acquisition status and human review status are independent. Acquisition status
describes automated selection and acquisition behavior, including technical
failures, duplicate detection, or query-level exclusions. Human review status
is the only field that determines whether a document is suitable for the
LegalAI development corpus. For example, a candidate marked
`excluded_irrelevant` during acquisition may still be manually accepted,
rejected, or reassigned to a different offence family after source inspection.

Use `backend/scripts/generate_judgment_review_report.py` to create the
deterministic review packet at `docs/DEVELOPMENT_CORPUS_REVIEW.md`. Use
`backend/scripts/review_development_judgment.py` only after a human reviewer
has made an explicit decision.

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
