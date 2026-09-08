# Retrieval Development Query Expansion Experiment

This is dev-set tuning evidence, not unbiased final benchmark performance.

## Expansion Engine

- types: statute_alias, offence_equivalent, procedure_equivalent, plain_language_legal_mapping, transition_term, hard_negative_disambiguation
- weighting: Q1 appends high-confidence terms; Q2 repeats the original query once before grouped terms; Q3 adds discriminator terms within the same expansion budget
- expansion budget: 10 supplemental terms maximum
- safety: no LLM rewriting, no section cross-mapping, no qrel/candidate-text leakage

## Variants

| Variant | Description |
|---|---|
| Q0 | Original query only baseline reproduction. |
| Q1 | Original query plus high-confidence expansion terms. |
| Q2 | Original query repeated once plus bounded grouped expansion terms. |
| Q3 | Conservative grouped expansion with hard-negative discriminator terms. |

## Overall Dev Results

| Variant | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 | Strict P@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q0 | 0.870 | 0.343 | 0.775 | 0.925 | 0.723 | 0.950 | 0.390 |
| Q1 | 0.850 | 0.334 | 0.797 | 0.900 | 0.716 | 0.950 | 0.420 |
| Q2 | 0.850 | 0.334 | 0.805 | 0.875 | 0.700 | 0.950 | 0.410 |
| Q3 | 0.850 | 0.334 | 0.805 | 0.875 | 0.700 | 0.950 | 0.410 |

## Query-Expansion Focus Results

| Variant | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 | Strict P@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q0 | 0.943 | 0.389 | 0.826 | 1.000 | 0.837 | 0.000 | 0.629 |
| Q1 | 0.971 | 0.399 | 0.815 | 1.000 | 0.887 | 0.000 | 0.714 |
| Q2 | 0.943 | 0.391 | 0.830 | 0.929 | 0.821 | 0.000 | 0.657 |
| Q3 | 0.943 | 0.391 | 0.830 | 0.929 | 0.821 | 0.000 | 0.657 |

## Candidate Generation

- Q0: BM25=186, Dense=188, intersection=99, union=275
- Q1: BM25=190, Dense=187, intersection=125, union=252
- Q2: BM25=206, Dense=183, intersection=129, union=260
- Q3: BM25=206, Dense=183, intersection=129, union=260

## Selection Decision

INCONCLUSIVE — RETAIN BASELINE

No expansion variant cleared the conservative dev-set selection criteria.

## Important Query Findings

- dev-q006: terms=['Code of Criminal Procedure', 'Bharatiya Nyaya Sanhita', 'Bharatiya Nagarik Suraksha Sanhita', 'notice of appearance', 'arrest procedure']; Q0 P@5/nDCG=1.0/1.0; Q3 P@5/nDCG=1.0/1.0
- dev-q009: terms=['criminal breach of trust', 'entrustment', 'misappropriation']; Q0 P@5/nDCG=1.0/0.8535105373852008; Q3 P@5/nDCG=1.0/0.6652642201270017
- dev-q012: terms=['robbery', 'theft', 'hurt', 'fear', 'wrongful restraint']; Q0 P@5/nDCG=0.8/0.9101907216367469; Q3 P@5/nDCG=0.8/0.9238387103352688
- dev-q013: terms=['dowry demand', 'cruelty by husband or relatives']; Q0 P@5/nDCG=1.0/1.0; Q3 P@5/nDCG=1.0/1.0
- dev-q014: terms=['kidnapping', 'lawful guardianship', 'taking', 'enticing']; Q0 P@5/nDCG=1.0/0.8421757737602428; Q3 P@5/nDCG=0.8/0.5760497434079799
- dev-q015: terms=['cheating', 'dishonest inducement', 'fraudulent intention']; Q0 P@5/nDCG=1.0/0.849607409925425; Q3 P@5/nDCG=1.0/0.819972692711383
- dev-q019: terms=['dishonest intention at inception', 'contractual breach', 'civil dispute']; Q0 P@5/nDCG=1.0/0.8274043288765652; Q3 P@5/nDCG=1.0/0.8930068676327362

## Limitations

- 20-query dev set only
- metrics are bounded by the frozen judged pool
- new unjudged chunks are not relevance-labelled
- no production/default retrieval behavior is changed
