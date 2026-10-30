# Retrieval Benchmark Labelling Guide (benchmark v2)

This guide extends the frozen 30-query benchmark (`legalai-retrieval-eval-v1`, 695 labels) with about 70 new
queries. It uses the same relevance scale, the same pooling method and the same blinding, so the new labels can be
merged into a new benchmark version (`legalai-retrieval-eval-v2`) and compared with the old one. The frozen 30
queries and their labels are never changed.

## 1. Writing queries (`queries_template.csv`)

| Column | Content |
|---|---|
| `query_id` | `new-q001`, `new-q002`… (never `eval-q…`, which the frozen set uses) |
| `query_text` | The question as a user or lawyer would type it |
| `mode` | `public` (plain language) or `professional` (a lawyer's research query) |
| `intended_statutes_or_topic` | What a good answer is about, e.g. `IPC 420 / BNS 318 cheating`, `anticipatory bail` |
| `query_type` | `statute_explicit`, `plain_language`, `procedural_relief`, `transition_regime` or `hard_ambiguous` |
| `target_family` | Offence family, e.g. `homicide`, `cheating_and_fraud`, `dowry_and_domestic_cruelty` (list below) |
| `target_regime` | `ipc_crpc`, `bns_bnss` or `mixed_or_transition` |
| `author` | Your name |
| `notes` | Anything a labeller should know; optional |

Rules:
- **Corpus-supported only.** The corpus is 70 trusted criminal-law judgments (1,356 chunks). A query must have at
  least one judgment in the corpus that genuinely addresses it. Out-of-corpus questions belong in the generation
  evaluation's out-of-scope set, not here.
- **No answer leakage.** Do not copy sentences from a judgment into the query, and do not name the case.
- **One issue per query**, except for `hard_ambiguous` queries, which deliberately combine two.

Coverage targets for about 70 queries (to balance the frozen set, which is 25 of 30 IPC/CrPC):

| Dimension | Target |
|---|---|
| Query type | statute_explicit about 20, plain_language about 18, procedural_relief about 14, transition_regime about 10, hard_ambiguous about 8 |
| Regime | at least 15 `bns_bnss` (BNS/BNSS/BSA section numbers or names), at least 10 `mixed_or_transition` (IPC and BNS together, "old law vs new law"), the rest `ipc_crpc` |
| Offence family | at least 4 queries each for: homicide, hurt_and_assault, sexual_offences, theft_and_robbery, cheating_and_fraud, criminal_breach_of_trust, dowry_and_domestic_cruelty, kidnapping, narcotics_related, conspiracy_common_intention; the rest `other` |
| Procedure | at least 14 procedural queries: bail (regular, anticipatory, default), FIR and investigation, quashing (S.482 CrPC / S.528 BNSS), charge, appeal, evidence (confessions, circumstantial evidence, S.113B presumptions) |
| Mode | about half `public`, half `professional` |

IPC and BNS: write some queries with BNS numbers only (e.g. "Section 103 BNS murder"), some with IPC only, and some
mixing both. The corpus is mostly pre-BNS judgments, so BNS-only queries test whether retrieval bridges the two
codes.

## 2. Labelling candidates (`labelling_sheet.csv`)

`generate_pools.py` gives each query 15-25 candidate chunks, pooled from BM25, dense, hybrid and hybrid + rerank
(`legalai-retrieval-pool-v1`). The sheet is **blinded**: it shows no ranks, scores or system names. Do not look
them up. Judge each chunk against the query only.

Fill two columns per row (plus `reviewer`, and `notes` when useful):

**`human_relevance`** (the chunk itself):
- `2`: highly or directly relevant. The chunk states, applies or decides the law or facts the query asks about.
- `1`: partially relevant. Useful context (a related offence, the right provision in passing, a procedural step
  next to the one asked about), but it does not answer the query on its own.
- `0`: not materially relevant. Off-topic, or the query's words appear without bearing on the question.
- `uncertain`: you cannot decide confidently from the excerpt. Use it sparingly; the frozen set has 3 in 695. An
  uncertain label is excluded from the metrics.

**`document_relevant`** (the whole judgment, from the case title and your knowledge of it): `yes`, `no` or
`uncertain`. Chunk and document are judged separately on purpose.
- **Right document, wrong chunk:** the judgment is about the query, but this chunk is a procedural recital or an
  unrelated passage. Mark chunk `0` or `1` and document `yes`.
- **Wrong document, relevant chunk:** the judgment is mainly about something else, but this passage states the law
  asked about. Mark chunk `2` and document `no`. The frozen example is `eval-q030` candidate 17: a cheating /
  breach-of-trust query, a relevant passage, document `no`.

Examples from the frozen set (`eval-q001`, "murder conviction section 302 IPC"):
- **Grade 2, document yes.** *Suresh Ram vs The State Of Bihar* (`indian_kanoon:123721856:chunk:0009`): explains
  culpable homicide and murder and the punishment under Section 302 IPC.
- **Grade 1, document yes.** *Md. Fakar Uddin Barbhuiya vs The State Of Assam* (`indian_kanoon:156271048:chunk:0010`):
  discusses whether intention to cause death was proved, which is relevant reasoning but not a murder conviction
  under Section 302 as such.
- **Grade 0:** a chunk about, say, a bail condition or a different offence that only shares words with the query.

Consistency: label all candidates of a query in one sitting, and re-read your first few labels at the end. If two
people label the same query, they discuss disagreements and record the agreed label with both names in `reviewer`.

## 3. Checking and merging

`validate_labels.py` refuses a sheet that has:
- a value outside the scale;
- an empty label or reviewer;
- duplicate rows;
- rows that are not pooled candidates;
- queries with no labels;
- reused frozen IDs.

When the sheet is clean it writes a **new** benchmark version (frozen 30 + new queries). The frozen files are only
read, and their hashes are checked before and after.

Metrics on v2 use the same definitions as v1:
- **Broad relevance:** grade 1 or 2.
- **Strict relevance:** grade 2.
- **nDCG@5:** graded with gains 2/1/0.
- **Recall:** *pooled* recall, meaning relevant among the judged pool, not across the whole corpus.
