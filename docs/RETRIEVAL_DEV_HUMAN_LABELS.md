# Retrieval Development Set Human Labels

- development version: `legalai-retrieval-dev-v1`
- queries: 20
- candidate judgments: 474
- reviewed: 474
- pending: 0
- reviewer: Ananthu

## Relevance Policy

- 2 = highly/directly relevant
- 1 = partially/usefully relevant
- 0 = not materially relevant
- uncertain = insufficient evidence

Counts: grade 2 = 103, grade 1 = 174, grade 0 = 197, uncertain = 0.

## Document Relevance

Document relevance counts: yes = 260, no = 214, uncertain = 0.

## Future Metric Interpretation

Broad relevance treats grade 1 or grade 2 as relevant. Strict sensitivity treats grade 2 only as relevant.

## Development-Set Status

THIS IS A TUNING / DEVELOPMENT SET. It may be inspected and reused during tuning. It must not replace the frozen 30-query benchmark as the unbiased baseline reference.

## Edge Cases

- dev-q006 grade-2 count = 0
- dev-q007 grade-2 count = 0
- dev-q012 preserves robbery-vs-theft discrimination
- dev-q016 preserves court metadata sensitivity

No dev performance metrics are reported here.
