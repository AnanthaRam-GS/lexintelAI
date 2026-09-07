# Retrieval Evaluation Human Labels

- evaluation version: `legalai-retrieval-eval-v1`
- queries: 30
- candidate judgments: 695
- reviewed: 695
- pending: 0
- reviewer: Ananthu

## Relevance Semantics

- 2: highly/directly relevant
- 1: partially/usefully relevant
- 0: not materially relevant
- uncertain: insufficient evidence

Counts: grade 2 = 251, grade 1 = 222, grade 0 = 219, uncertain = 3.

## Document Relevance

Document relevance is recorded separately as yes, no, or uncertain.

Counts: yes = 466, no = 223, uncertain = 6.

## Future Metric Policy

Broad relevance treats grade 1 or grade 2 as relevant. Strict relevance treats grade 2 only as relevant. Uncertain labels are excluded from binary relevance denominators unless a later methodology explicitly states otherwise.

## Freeze And Blinding

The review packet remained blinded from retriever ranks and scores. Machine retrieval traces remain separate from the human judgment manifest. The frozen retrieval configuration remains BAAI/bge-m3 dense retrieval, BM25 k1=1.5 b=0.75, hybrid RRF K=60, and BAAI/bge-reranker-v2-m3 reranking.

## Benchmark Edge Cases

- right document / wrong chunk
- wrong document / relevant chunk
- sparse transition pools
- q024 has no grade-2 result
- q028 has no grade-2 result

Retrieval-system performance metrics are not reported in this document.
