# LegalAI Bulk Acquisition Operations

Phase 0 Step 0.4J hardens the existing Indian Kanoon acquisition flow for later staged runs. It does not start a 500+ document acquisition by itself, and it does not change the deterministic quality filters.

## Modes

Bulk acquisition is explicit:

```bash
python3 backend/scripts/acquire_filtered_judgments.py \
  --bulk \
  --run-id bulk_20260904_060000_abcd \
  --bulk-plan data/structured/manifests/bulk_acquisition_plan.json \
  --limit 500 \
  --max-api-requests 2500 \
  --max-search-pages 5
```

Resume an interrupted run:

```bash
python3 backend/scripts/acquire_filtered_judgments.py --resume bulk_20260904_060000_abcd
```

Retry only retryable failures:

```bash
python3 backend/scripts/acquire_filtered_judgments.py --retry-failures bulk_20260904_060000_abcd
```

Print deterministic run statistics:

```bash
python3 backend/scripts/acquire_filtered_judgments.py --bulk-stats bulk_20260904_060000_abcd
```

Rebuild the generated global dedupe index:

```bash
python3 backend/scripts/acquire_filtered_judgments.py --rebuild-dedupe-index
```

## Run State

Run checkpoints live under `data/processed/acquisition_runs/<run_id>/` and are ignored by git. Each run persists:

* `state.json`: durable run metadata, request stats, partition progress, seen sets, failed queue, batch index, and checkpoint version.
* `expanded_queries.json`: the stage plan expanded into query records consumed by the existing acquisition function.
* `candidates.json`, `review.json`, `audit.json`: run-scoped manifests.
* `batches/batch_0001.json`, etc.: bounded candidate batches for large runs.
* `statistics.json`: deterministic summary written at run end.

The checkpoint writer uses temp-file plus atomic rename, matching the existing manifest-safety pattern.

## Dedupe Policy

Bulk mode protects idempotency by carrying forward known records from:

* V1 development judgments
* V2 development judgments
* prescreened V2 judgments
* balanced development judgments
* BNS / BNSS transition validation candidates

The generated dedupe index at `data/structured/manifests/global_corpus_dedupe_index.json` is reconstructable from manifests and should be treated as a cache, not an irreplaceable source of truth.

## Budgets And Rate Control

The Indian Kanoon client tracks exact endpoint request counts for search, document, metadata, original document, other, and total requests.

Configurable provider controls:

* `INDIAN_KANOON_MIN_REQUEST_INTERVAL_MS`
* `INDIAN_KANOON_MAX_RETRIES`
* `INDIAN_KANOON_RETRY_BACKOFF_SECONDS`

401/403 responses stop as non-retryable provider failures. 429, 5xx, and temporary network failures use bounded retries only. Bulk runs checkpoint before stopping on budget exhaustion.

## Review State

Bulk completion is not corpus acceptance. Candidate records preserve `final_automated_decision`, while review manifests preserve separate `human_review_status`. Large-scale human strategy remains a future step.
