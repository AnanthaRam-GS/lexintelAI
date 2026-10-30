# Team Guide: Adding 70 Benchmark Queries (one page)

Read `LABELLING_GUIDE.md` first; it has the full rules and examples. All commands run from the repository root,
after the normal setup (README).

| Step | Who | What | Time |
|---|---|---|---|
| 1 | Each teammate | Copy `queries_template.csv` to your own file and write your share of queries (about 18 each for 4 people), following the coverage targets in the guide. Use IDs from your range: person 1 `new-q001`-`new-q018`, person 2 `new-q019`-`new-q036`, person 3 `new-q037`-`new-q054`, person 4 `new-q055`-`new-q070`. | 2-3 h |
| 2 | One person | Merge the four files into one `queries.csv`. Check the coverage table (types, regimes, families) and fix any gaps. | 30 min |
| 3 | One person | Generate the pools (no LLM, no API key; about 10 s per query on CPU): `.venv/bin/python data/evaluation/labelling_kit/generate_pools.py --queries queries.csv --out-dir ~/legalai_labelling/pools` | 15 min |
| 4 | Each teammate | Label the candidates of the queries you did **not** write (swap with a partner, so nobody labels their own query). About 23 candidates per query at 30-45 s each is 12-17 min per query, so 18 queries is 4-5 h. Split it into sittings, finishing each query in one sitting. Fill `human_relevance`, `document_relevant`, `reviewer`, `notes`. | 4-5 h each |
| 5 | Each teammate | Check your part: `.venv/bin/python data/evaluation/labelling_kit/validate_labels.py --queries queries.csv --sheet my_part.csv --traces ~/legalai_labelling/pools/pool_traces.json --check-only`. Fix what it lists. | 10 min |
| 6 | One person | Combine the labelled parts into one sheet, validate again, then merge into the new benchmark version: `... validate_labels.py --queries queries.csv --sheet labelled.csv --traces ~/legalai_labelling/pools/pool_traces.json --out-dir data/evaluation/benchmarks/retrieval_v2` | 20 min |
| 7 | One person | Double-label 5 queries (two people each, independently) and report the agreement in the PR. | 1 h |

Do not:
- edit anything in `data/structured/manifests/`; the frozen benchmark is read only;
- look at ranks or scores (`pool_traces.json`) while labelling;
- use an LLM to label.

Total effort: about 25-30 person-hours for about 1,600 labels.
