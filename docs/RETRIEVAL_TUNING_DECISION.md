# Retrieval Tuning Decision

The 30-query benchmark has now been inspected, so it must remain baseline diagnostic evidence rather than an unbiased post-tuning test set.

| Potential Change | Evidence For | Evidence Against | Risk | Recommendation |
|---|---|---|---|---|
| BM25 k1/b tuning | BM25 trails hybrid modestly on broad P@5 and nDCG. | BM25 already has strong statute-explicit performance; no parameter sweep evidence. | Overfit 30-query benchmark. | MORE EVALUATION DATA NEEDED |
| legal tokenizer changes | Some lexical gaps remain in transition and procedural queries. | Tokenizer already preserves section/statute tokens and BM25 P@5 is high. | Could regress exact statute matching. | MORE EVALUATION DATA NEEDED |
| query expansion | Candidate-generation gaps and ambiguous/composite queries appear. | Expansion can add noise; current benchmark is now inspected. | High overfitting risk. | TARGETED TUNING JUSTIFIED |
| explicit statute/section weighting | Statute-explicit hybrid P@5 is best, suggesting section signals matter. | Weakest cases are not only statute misses. | May over-prioritize bare provisions over facts. | MORE EVALUATION DATA NEEDED |
| legal regime filtering/boosting | 4 primary legal-regime failures plus small transition subset. | Only 3 transition-regime queries; evidence is sparse. | Could hide useful old/new law cross references. | TARGETED TUNING JUSTIFIED |
| RRF K tuning | Hybrid improves pooled recall@20 over BM25 and Dense. | Hybrid P@5/nDCG gains are modest and stable; no clear RRF-specific failure dominates. | Directly tuning on this benchmark would bias results. | MORE EVALUATION DATA NEEDED |
| dense-only changes | Dense has strong document hit@5 and good nDCG. | Hybrid and rerank already use dense evidence; dense model change is high blast radius. | Model churn and cache/index rebuild cost. | NO TUNING NEEDED |
| reranker max_length | Reranker improves graded nDCG@5. | Broad P@5 is unchanged and harmful cases exist. | Longer inputs increase latency and may overfit. | MORE EVALUATION DATA NEEDED |
| reranker candidate depth | Rerank improves pooled recall@20 and strict metrics. | Top20 is censored; depth effects cannot be isolated from frozen traces. | More review workload and latency. | MORE EVALUATION DATA NEEDED |
| chunk-size changes | Right-document/wrong-chunk count is 32. | Changing chunks invalidates the frozen benchmark and index. | Large rebuild and comparability loss. | MORE EVALUATION DATA NEEDED |
| metadata-aware reranking | Document/chunk mismatch and regime evidence suggest metadata could help ordering. | Needs separate dev set and careful ablation. | Can encode brittle shortcuts. | TARGETED TUNING JUSTIFIED |

## Overfitting Safeguard

Use a separate tuning/dev query set before changing retrieval parameters, or freeze a held-out subset before any tuning. Do not repeatedly tune against all 30 evaluated queries and report the same set as unbiased final performance.

## Go / No-Go

TARGETED RETRIEVAL TUNING JUSTIFIED: prioritize legal-regime filtering/boosting, query expansion experiments, and metadata-aware reranking on a separate development set.
