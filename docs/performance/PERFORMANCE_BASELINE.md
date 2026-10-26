# Performance Baseline (step 12)

This step moves the query models onto Apple MPS, adds startup warm-up, and recalibrates the Groq request-size guard.
No LLM calls were made. Retrieval candidates (20), top-k (5), prompts, the validator, chunking and the stores are
unchanged. Raw outputs (chunk IDs, scores, timings; no text) are in `data/structured/performance/step12/`. The frozen
benchmark files in `data/structured/manifests/` were only read.

Machine: Apple M5, 24 GB, macOS (arm64); torch 2.14.0, FlagEmbedding 1.4.2.

## Configuration chosen

| Setting | Default | Effect |
|---|---|---|
| `LEGALAI_MODEL_DEVICE` | `auto` | MPS when torch reports it available, otherwise CPU. `cpu`, `mps` and `cuda` force a device. An unavailable device resolves to CPU with a warning. |
| `LEGALAI_RERANKER_FP16` | `true` | Reranker in fp16 off CPU. The query embedder always stays fp32, because the index vectors are fp32. |
| `LEGALAI_MODEL_WARMUP` | `true` | Loads both models at startup in a background thread and runs one tiny inference. |

So on this Mac the API runs the **query embedder on MPS in fp32 and the reranker on MPS in fp16**.

If loading or inference fails on MPS or CUDA, the model reloads on CPU, logs `model_device_fallback`, and the call is
retried; the query never fails on a device problem (`services/model_device.py`).

The devices in use appear in the following places:
- the startup log (`query_models_loaded`, `query_models_warmup`);
- `/health` (`models.devices`);
- each `query_timings` log line (`embedder=… reranker=…`);
- the `debug.model_devices` field.

**Existing bug fixed.** `BgeM3EmbeddingProvider` passed `device=`, but FlagEmbedding 1.4.2 takes `devices=`. The
argument was ignored and the library auto-selected MPS, so the query embedder (and ingestion) already ran on MPS
while the reranker ran on CPU. The device is now passed correctly. Ingestion follows `LEGALAI_MODEL_DEVICE` (always
fp32), so it keeps its previous MPS behaviour.

## Ranking equivalence (30 frozen benchmark queries, Hybrid+Rerank)

`backend/scripts/evaluate_model_device.py ranking` re-ran retrieval for each configuration (candidate depth 20, ranks
≤ 15 kept as in the frozen traces). It scored the result with the frozen human judgments, using the analyzer's own
metric code.

| Configuration | Top-5 identical | Max \|score − frozen\| | P@5 | MRR@5 | nDCG@5 | Pooled R@5 | Pooled R@20 | Unjudged chunks in top 15 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Frozen benchmark | — | — | 0.873 | 0.961 | 0.819 | 0.290 | 0.723 | — |
| CPU, fp32 | 30/30 | 0.0 | 0.873 | 0.961 | 0.819 | 0.290 | 0.723 | 0 |
| MPS, all fp32 | 30/30 | 0.00017 | 0.873 | 0.961 | 0.819 | 0.290 | 0.723 | 0 |
| MPS, all fp16 | 30/30 | 0.0138 | 0.873 | 0.961 | 0.819 | 0.290 | 0.723 | 0 |
| **MPS, embedder fp32 + reranker fp16 (chosen)** | **30/30** | **0.0138** | **0.873** | **0.961** | **0.819** | **0.290** | **0.723** | **0** |

- Every metric equals the frozen value exactly (difference 0.0 at 6 decimals), including the strict-relevance variants.
- No query changed its top-5 order on any configuration.
- The CPU run reproduces the frozen scores exactly.

**fp16 margin.** fp16 shifts reranker scores by up to 0.0138. The smallest gap between neighbouring scores in the
frozen top 6 is 0.004 (eval-q012), and 9 of 30 queries have a gap under 0.028. All 30 kept their order, but on new
queries fp16 can occasionally swap two near-tied passages. fp32 drift (0.00017) is well below every top-6 gap. To use
fp32, set `LEGALAI_RERANKER_FP16=false`, which costs about 3 s per query (see below).

## Reranker truncation

The reranker scores query–passage pairs up to `max_length=512` tokens. Measured with its own (XLM-R) tokenizer over
all 1,356 chunks:
- passages are 838 tokens at the median (p90 1,042, max 1,432); the chunker's own count is 701 at the median, max 851;
- with a median 8-token query, about 500 passage tokens fit;
- **91% of chunks (1,232) are truncated**, and a truncated chunk is scored on about 62% of its text (350 tokens
  dropped on average).

The frozen benchmark was measured this way, and any change to `max_length` changes scores, so it cannot pass the
equivalence check above. It is unchanged and left as an open item: evaluate `max_length=1024` against the human
judgments as a separate, deliberate ranking change.

## Latency (10 fixed benchmark queries × 3 passes, after warm-up)

`backend/scripts/evaluate_model_device.py benchmark` ran queries eval-q001 to eval-q010 through the API's retrieval
path (`retrieve_legal_evidence`), giving 30 samples per configuration.

| Configuration | Rerank p50 | Rerank p95 | Retrieval p50 | Retrieval p95 |
|---|---:|---:|---:|---:|
| CPU, fp32 (before) | 8,002 ms | 9,795 ms | 8,094 ms | 9,906 ms |
| MPS, all fp32 | 5,324 ms | 5,918 ms | 5,405 ms | 6,094 ms |
| MPS, all fp16 | 1,247 ms | 1,378 ms | 1,309 ms | 1,422 ms |
| **MPS, embedder fp32 + reranker fp16 (chosen)** | **1,884 ms** | **2,160 ms** | **1,956 ms** | **2,237 ms** |

- **Rerank speed-up, chosen vs CPU: 4.2× at p50.**
- Run-to-run variance on MPS is about 15–20%: a repeat of the chosen configuration gave a rerank p50 of 1,575 ms (5.1×),
  and a repeat of MPS fp32 gave 4,560 ms.
- MPS fp32 alone gives only 1.5×; most of the gain comes from fp16.
- One of the first fp16 benchmark attempts ended without output inside a shell loop. Rerunning it alone completed
  normally, and every number above comes from a completed run.

### Projected end-to-end time

Each step 11 live run's rerank stage (about 7.3 s on CPU) is replaced with the chosen configuration's 1.6–1.9 s.
Generation times are unchanged.

| Step 11 run | Total then | Projected total |
|---|---:|---:|
| Professional text (R1, R2; generation 7.2–7.5 s) | 14.6–14.8 s | **9.1–9.4 s** |
| Public text (11d P1; generation 3.9 s) | 11.4 s | **5.6–5.9 s** |
| Public PDF (11d P4; generation 4.4 s) | 12.8 s | **7.1–7.4 s** |

All are under the 15 s target, which the professional runs previously only just met.

## Concurrency: one model call at a time (step 18)

**Problem.** Model inference runs in the request threadpool (BE-004), and nothing serialised it. On MPS, two
inferences at once crash the process with a segmentation fault inside the BGE-M3 forward pass
(`modeling_xlm_roberta.py create_position_ids_from_input_ids`). Reproduced with
`backend/scripts/dev/stress_inference.py` (real models, fake LLM, `legalai_rehearsal` restored with `--clean`, store
copies):

| Before the fix | Crashed | Evidence |
|---|---:|---|
| Warm-up on + 10 simultaneous professional queries | **10 of 10** (SIGSEGV) | faulthandler: up to 11 threads in the BGE-M3 forward at once (10 requests + `legalai-model-warmup`); in another crash 8 in BGE-M3 and 4 in the reranker's `compute_score` |
| Warm-up off + 10 simultaneous queries | **3 of 3** (SIGSEGV) | up to 10 request threads in the BGE-M3 forward; no warm-up thread |

So concurrent queries alone crash the backend, not only the warm-up race. The step 12 note above (an fp16 benchmark
attempt that "ended without output") may have been the same crash.

**Fix.** `backend/app/services/inference_lock.py`: one process-wide (reentrant) lock. `DeviceFallbackModel` holds it
for every model load and every inference, so the query embedder, the reranker, the ingestion embedder and the warm-up
never run at once. A request waits at most `LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS` (default 30) and then gets 503
`MODELS_LOADING` (during the warm-up, `Retry-After: 10`) or `MODEL_BUSY` (`Retry-After: 15`). The warm-up and
ingestion wait without a limit. `/health` reports `models.warm_up` (`loading`/`ready`/`failed`/`not_started`) and
`models.inference` (`active`, `waiting`). Model outputs, precision, devices, ranking, `top_k` and candidates are
unchanged: the 30-query ranking check gives 30/30 identical top-5 on MPS (embedder fp32, reranker fp16; max |score −
frozen| 0.013792, as in step 12) and on CPU (difference 0.0), with every metric equal to the frozen value.

**After the fix (MPS, warm-up on).** 5 repetitions × (10 simultaneous queries at startup + 3 rounds of 10 + 5
sequential): **0 crashes, 225 of 225 responses 200**.

| MPS, professional text queries, fake LLM | p50 | p95 | max |
|---|---:|---:|---:|
| Single request (sequential, n = 25) | 1.58 s | 1.66 s | — |
| 10 concurrent, first round (overlaps the 4.1 s load + 1.8 s warm-up; n = 50) | 11.9 s | 19.4 s | 20.8 s |
| 10 concurrent, later rounds (n = 150) | 7.75 s | 15.9 s | 16.4 s |

Under 10 concurrent queries the last one waits for the nine before it (about 10 × 1.5 s), which is what p95 shows.
Before the fix the same load crashed every time, so there is no "before" latency on MPS.

**Why on every device, and the CPU cost.** CPU inference is thread-safe, but PyTorch already spreads one inference
over every core, so concurrent inferences only compete for them. Measured on CPU (1 repetition each, lock timeout
raised to 300 s so that every request waits):

| CPU, 10 concurrent | Later rounds p50 | p95 | Single request |
|---|---:|---:|---:|
| Before (no lock) | 118.8 s | 124.7 s | 10.2 s |
| After (lock) | 51.2 s | 100.8 s | 10.0 s |

Serialising halves the median and lowers p95; single-request latency is unchanged. With the default 30 s timeout on
CPU, measured: a burst of 10 simultaneous queries had 4 answered (9–39 s) and 6 answered `MODEL_BUSY` with
`Retry-After: 15` after 31–35 s, in both rounds, instead of all ten waiting about two minutes. Raise
`LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS` to make CPU requests wait longer instead. CPU is a fallback here; the
deployed configuration is MPS, where 10 concurrent queries all finish well inside the default timeout.

## Warm-up

At startup the server answers `/health` straight away with `models.status = "loading"`, which becomes `"loaded"` with
`load_ms`, `warmup_ms` and the devices. If warm-up fails, `/health` shows `"failed"` and queries load the models on
demand. The models are cached separately from the retrieval service, so the rebuild after an ingestion update reuses
them. A lock stops warm-up and the first request from loading them twice. Since step 18 a query that arrives during the warm-up waits for the model lock (or gets `MODELS_LOADING` after
`LEGALAI_INFERENCE_LOCK_TIMEOUT_SECONDS`); it never runs a model at the same time as the warm-up.

The first query after startup was measured through the real app with a stub answer adapter (no LLM call):

| | Dense retrieval | Rerank | Model load inside the request |
|---|---:|---:|---|
| Warm-up on (`/health` loaded after 6.6 s: load 4.7 s, warm-up 1.5 s) | 94 ms | 935 ms | none |
| Warm-up off | 1,092 ms | 1,256 ms | 4.7 s, in the request's dependency |

With warm-up, the first query's stage timings contain no model load or device placement.

## Non-blocking I/O (BE-004)

The PDF query routes are `async` (they stream the upload). The blocking work now runs in the threadpool:
- PDF parsing and chunking;
- the document map;
- retrieval and reranking;
- the provider call;
- history saving.

The text query routes and `/health` were already sync, so FastAPI runs them in the threadpool.

`test_model_device.NonBlockingQueryTests` sends a slow mocked public-PDF and professional-PDF query, then calls
`/health` meanwhile:
- with the fix, `/health` answers in under 0.5 s while the query takes 1.5 s;
- with the old inline behaviour, the same test fails (`/health` waited 1.53 s).

The ingest and lawyer-verification upload routes only do short DB calls and file writes, and ingestion's processing
already runs as a sync background task.

## Request-size guard calibration

`backend/scripts/calibrate_request_size_guard.py` rebuilt the exact prompt of all 10 recorded Groq runs. It used the same
query, the captured evidence chunk IDs (all 10 matched), the recorded prompt version and the captured private excerpt
for PDF runs. It then compared `estimate_tokens(prompt + schema)` with Groq's reported `prompt_tokens`. No LLM calls.

| Run | Mode | Prompt | Items | Estimate | Actual | Ratio | Predicted at 1.7 (over by) | Predicted at 1.51 (over by) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 11 P1 | public | v1 | 5 | 4,626 | 5,446 | 1.177 | 7,864 (+2,418) | 6,985 (+1,539) |
| 11 R1 | professional | v1 | 5 | 4,917 | 6,111 | 1.243 | 8,359 (+2,248) | 7,425 (+1,314) |
| 11b P2 | public | v1 | 5 | 4,148 | 5,934 | 1.431 | 7,052 (+1,118) | 6,263 (+329) |
| 11b P3 | public | v1 | 5 | 4,971 | 6,999 | 1.408 | 8,451 (+1,452) | 7,506 (+507) |
| 11b P4 (PDF) | public | v1 | 5 | 5,292 | 6,251 | 1.181 | 8,996 (+2,745) | 7,991 (+1,740) |
| 11b R2 | professional | v1 | 3 | 3,800 | 4,808 | 1.265 | 6,460 (+1,652) | 5,738 (+930) |
| 11c P2 | public | v2 | 3 | 3,096 | 4,283 | 1.383 | 5,263 (+980) | 4,675 (+392) |
| 11c P3 | public | v2 | 5 | 5,167 | 7,163 | 1.386 | 8,784 (+1,621) | 7,802 (+639) |
| 11d P1 | public | v2 | 2 | 2,682 | 3,241 | 1.208 | 4,559 (+1,318) | 4,050 (+809) |
| 11d P4 (PDF) | public | v2 | 2 | 2,710 | 3,287 | 1.213 | 4,607 (+1,320) | 4,092 (+805) |

**New factor: 1.51**, the worst ratio (1.4306) plus a 5% margin. It never underestimates a recorded run; the closest
margin is 329 tokens.

Replaying the guard (ceiling 8,000, output 2,048) on the full 5-item evidence of step 11d:

| Run | Items kept at 1.7 | Items kept at 1.51 |
|---|---:|---:|
| P1 | 2 | 3 |
| P4 | 2 | 3 |

**No matching tokenizer is available locally.** gpt-oss uses `o200k_harmony`, and there is no `tiktoken`,
`openai_harmony` or cached gpt-oss tokenizer offline, so exact counting was not possible. The fixed factor is used;
re-run the calibration script as more live runs are recorded. Only two professional runs (R1, R2)
and no brief runs are in the data, so the factor is least certain for professional and PDF-brief requests.

## Reproduce

```
.venv/bin/python backend/scripts/evaluate_model_device.py ranking   --device mps --fp16 --output-dir <new dir>
.venv/bin/python backend/scripts/evaluate_model_device.py benchmark --device mps --fp16 --output-dir <new dir>
.venv/bin/python backend/scripts/calibrate_request_size_guard.py --runs-dir ~/legalai_reviews/live_runs --output <file>
```

`--output-dir` may not be `data/structured/manifests`.
