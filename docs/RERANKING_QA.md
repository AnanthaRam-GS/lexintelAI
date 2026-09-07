# Reranking QA

This is diagnostic sanity QA for a BGE reranker over retrieved candidates, not a formal retrieval benchmark.

## Configuration

- model: `BAAI/bge-reranker-v2-m3`
- library: `FlagEmbedding`
- device: `cpu`
- candidate_k: 20
- top_k: 5
- max_length: 512
- batch_size: 8
- truncation policy: FlagEmbedding pair tokenizer truncates deterministically to max_length, preserving the query and passage prefix per model tokenizer behavior.

## Rank 1 Movement

| Query | Hybrid Rank 1 | Reranked Rank 1 | Changed |
| --- | --- | --- | --- |
| dowry death section 304B IPC | indian_kanoon:36195540:chunk:0002 (dowry_and_domestic_cruelty/ipc_crpc) | indian_kanoon:26223875:chunk:0003 (dowry_and_domestic_cruelty/ipc_crpc) | True |
| murder conviction section 302 IPC | indian_kanoon:123721856:chunk:0009 (hurt_and_assault/ipc_crpc) | indian_kanoon:123721856:chunk:0009 (hurt_and_assault/ipc_crpc) | False |
| criminal breach of trust section 406 IPC | indian_kanoon:131331418:chunk:0005 (criminal_breach_of_trust/ipc_crpc) | indian_kanoon:13518275:chunk:0005 (criminal_breach_of_trust/ipc_crpc) | True |
| NDPS bail commercial quantity | indian_kanoon:138227421:chunk:0001 (narcotics_related/ipc_crpc) | indian_kanoon:138227421:chunk:0013 (narcotics_related/ipc_crpc) | True |
| anticipatory bail under BNSS | indian_kanoon:100558061:chunk:0004 (other/mixed_or_transition) | indian_kanoon:100558061:chunk:0000 (other/mixed_or_transition) | True |
| rape section 376 IPC | indian_kanoon:31029978:chunk:0024 (sexual_offences/ipc_crpc) | indian_kanoon:179828917:chunk:0048 (sexual_offences/ipc_crpc) | True |
| robbery section 392 IPC | indian_kanoon:177113492:chunk:0002 (theft_and_robbery/ipc_crpc) | indian_kanoon:177113492:chunk:0002 (theft_and_robbery/ipc_crpc) | False |
| common intention section 34 IPC | indian_kanoon:173395727:chunk:0048 (kidnapping/ipc_crpc) | indian_kanoon:173395727:chunk:0048 (kidnapping/ipc_crpc) | False |

## Details

### dowry death section 304B IPC

**pre-rerank hybrid**
- 1. `indian_kanoon:36195540:chunk:0002` dowry_and_domestic_cruelty/ipc_crpc page 6-7 score 0.032258
- 2. `indian_kanoon:83401027:chunk:0001` dowry_and_domestic_cruelty/ipc_crpc page 4-6 score 0.032018
- 3. `indian_kanoon:40368737:chunk:0005` dowry_and_domestic_cruelty/ipc_crpc page 16-17 score 0.031545
- 4. `indian_kanoon:26223875:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 7-8 score 0.030798
- 5. `indian_kanoon:36195540:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 10-11 score 0.030798

**post-rerank**
- 1. `indian_kanoon:26223875:chunk:0003` dowry_and_domestic_cruelty/ipc_crpc page 6-6 pre-rank 9 rerank 5.757544
- 2. `indian_kanoon:36195540:chunk:0002` dowry_and_domestic_cruelty/ipc_crpc page 6-7 pre-rank 1 rerank 5.032125
- 3. `indian_kanoon:26223875:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 7-8 pre-rank 4 rerank 4.708031
- 4. `indian_kanoon:36195540:chunk:0003` dowry_and_domestic_cruelty/ipc_crpc page 8-9 pre-rank 7 rerank 4.389553
- 5. `indian_kanoon:36195540:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 10-11 pre-rank 5 rerank 4.368937

### murder conviction section 302 IPC

**pre-rerank hybrid**
- 1. `indian_kanoon:123721856:chunk:0009` hurt_and_assault/ipc_crpc page 25-27 score 0.032522
- 2. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 0.032522
- 3. `indian_kanoon:30754679:chunk:0002` homicide/ipc_crpc page 7-9 score 0.03031
- 4. `indian_kanoon:199957261:chunk:0009` homicide/ipc_crpc page 25-27 score 0.03009
- 5. `indian_kanoon:15834217:chunk:0003` homicide/ipc_crpc page 10-11 score 0.02837

**post-rerank**
- 1. `indian_kanoon:123721856:chunk:0009` hurt_and_assault/ipc_crpc page 25-27 pre-rank 1 rerank 3.840541
- 2. `indian_kanoon:156271048:chunk:0010` homicide/ipc_crpc page 14-15 pre-rank 16 rerank 3.570825
- 3. `indian_kanoon:179828917:chunk:0048` sexual_offences/ipc_crpc page 80-81 pre-rank 11 rerank 3.356395
- 4. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 pre-rank 2 rerank 3.062141
- 5. `indian_kanoon:189001274:chunk:0010` homicide/ipc_crpc page 19-20 pre-rank 6 rerank 3.025445

### criminal breach of trust section 406 IPC

**pre-rerank hybrid**
- 1. `indian_kanoon:131331418:chunk:0005` criminal_breach_of_trust/ipc_crpc page 13-15 score 0.032522
- 2. `indian_kanoon:13518275:chunk:0005` criminal_breach_of_trust/ipc_crpc page 16-18 score 0.032522
- 3. `indian_kanoon:176391710:chunk:0010` cheating_and_fraud/ipc_crpc page 15-15 score 0.031258
- 4. `indian_kanoon:44731735:chunk:0003` criminal_breach_of_trust/ipc_crpc page 8-9 score 0.030777
- 5. `indian_kanoon:13518275:chunk:0006` criminal_breach_of_trust/ipc_crpc page 18-21 score 0.030536

**post-rerank**
- 1. `indian_kanoon:13518275:chunk:0005` criminal_breach_of_trust/ipc_crpc page 16-18 pre-rank 2 rerank 5.678325
- 2. `indian_kanoon:131331418:chunk:0005` criminal_breach_of_trust/ipc_crpc page 13-15 pre-rank 1 rerank 5.007751
- 3. `indian_kanoon:176391710:chunk:0010` cheating_and_fraud/ipc_crpc page 15-15 pre-rank 3 rerank 3.190571
- 4. `indian_kanoon:44731735:chunk:0003` criminal_breach_of_trust/ipc_crpc page 8-9 pre-rank 4 rerank 2.629096
- 5. `indian_kanoon:13518275:chunk:0006` criminal_breach_of_trust/ipc_crpc page 18-21 pre-rank 5 rerank 2.130814

### NDPS bail commercial quantity

**pre-rerank hybrid**
- 1. `indian_kanoon:138227421:chunk:0001` narcotics_related/ipc_crpc page 3-3 score 0.032002
- 2. `indian_kanoon:138227421:chunk:0008` narcotics_related/ipc_crpc page 10-10 score 0.031754
- 3. `indian_kanoon:138227421:chunk:0015` narcotics_related/ipc_crpc page 17-17 score 0.030478
- 4. `indian_kanoon:138227421:chunk:0013` narcotics_related/ipc_crpc page 15-15 score 0.030366
- 5. `indian_kanoon:138227421:chunk:0009` narcotics_related/ipc_crpc page 11-11 score 0.029324

**post-rerank**
- 1. `indian_kanoon:138227421:chunk:0013` narcotics_related/ipc_crpc page 15-15 pre-rank 4 rerank 4.394574
- 2. `indian_kanoon:138227421:chunk:0006` narcotics_related/ipc_crpc page 8-8 pre-rank 10 rerank 2.552094
- 3. `indian_kanoon:169784101:chunk:0004` narcotics_related/ipc_crpc page 10-11 pre-rank 14 rerank 2.48748
- 4. `indian_kanoon:138227421:chunk:0015` narcotics_related/ipc_crpc page 17-17 pre-rank 3 rerank 2.24702
- 5. `indian_kanoon:138227421:chunk:0001` narcotics_related/ipc_crpc page 3-3 pre-rank 1 rerank 1.561146

### anticipatory bail under BNSS

**pre-rerank hybrid**
- 1. `indian_kanoon:100558061:chunk:0004` other/mixed_or_transition page 17-20 score 0.031514
- 2. `indian_kanoon:100558061:chunk:0003` other/mixed_or_transition page 13-16 score 0.031054
- 3. `indian_kanoon:100558061:chunk:0002` other/mixed_or_transition page 9-12 score 0.030886
- 4. `indian_kanoon:100558061:chunk:0009` other/mixed_or_transition page 32-34 score 0.030798
- 5. `indian_kanoon:183406121:chunk:0002` other/mixed_or_transition page  score 0.030536

**post-rerank**
- 1. `indian_kanoon:100558061:chunk:0000` other/mixed_or_transition page 1-4 pre-rank 14 rerank 4.229004
- 2. `indian_kanoon:100558061:chunk:0003` other/mixed_or_transition page 13-16 pre-rank 2 rerank 3.910837
- 3. `indian_kanoon:100558061:chunk:0002` other/mixed_or_transition page 9-12 pre-rank 3 rerank 3.85037
- 4. `indian_kanoon:100558061:chunk:0004` other/mixed_or_transition page 17-20 pre-rank 1 rerank 3.752236
- 5. `indian_kanoon:100558061:chunk:0001` other/mixed_or_transition page 5-8 pre-rank 7 rerank 3.679966

### rape section 376 IPC

**pre-rerank hybrid**
- 1. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 0.03055
- 2. `indian_kanoon:179828917:chunk:0033` sexual_offences/ipc_crpc page 52-53 score 0.028814
- 3. `indian_kanoon:184937779:chunk:0010` sexual_offences/ipc_crpc page 29-31 score 0.028543
- 4. `indian_kanoon:31029978:chunk:0001` sexual_offences/ipc_crpc page 5-7 score 0.028485
- 5. `indian_kanoon:47759402:chunk:0001` sexual_offences/mixed_or_transition page 4-7 score 0.028373

**post-rerank**
- 1. `indian_kanoon:179828917:chunk:0048` sexual_offences/ipc_crpc page 80-81 pre-rank 16 rerank 2.56476
- 2. `indian_kanoon:47759402:chunk:0001` sexual_offences/mixed_or_transition page 4-7 pre-rank 5 rerank 2.36648
- 3. `indian_kanoon:179828917:chunk:0067` sexual_offences/ipc_crpc page 105-106 pre-rank 15 rerank 2.290203
- 4. `indian_kanoon:125041151:chunk:0001` sexual_offences/ipc_crpc page  pre-rank 9 rerank 2.266853
- 5. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 pre-rank 1 rerank 2.152503

### robbery section 392 IPC

**pre-rerank hybrid**
- 1. `indian_kanoon:177113492:chunk:0002` theft_and_robbery/ipc_crpc page 6-7 score 0.032266
- 2. `indian_kanoon:177113492:chunk:0006` theft_and_robbery/ipc_crpc page 13-14 score 0.032266
- 3. `indian_kanoon:177113492:chunk:0005` theft_and_robbery/ipc_crpc page 11-12 score 0.032258
- 4. `indian_kanoon:177113492:chunk:0003` theft_and_robbery/ipc_crpc page 8-8 score 0.03125
- 5. `indian_kanoon:177113492:chunk:0004` theft_and_robbery/ipc_crpc page 9-10 score 0.029851

**post-rerank**
- 1. `indian_kanoon:177113492:chunk:0002` theft_and_robbery/ipc_crpc page 6-7 pre-rank 1 rerank 4.180445
- 2. `indian_kanoon:177113492:chunk:0005` theft_and_robbery/ipc_crpc page 11-12 pre-rank 3 rerank 3.067137
- 3. `indian_kanoon:177113492:chunk:0004` theft_and_robbery/ipc_crpc page 9-10 pre-rank 5 rerank 2.655489
- 4. `indian_kanoon:177113492:chunk:0006` theft_and_robbery/ipc_crpc page 13-14 pre-rank 2 rerank 2.402187
- 5. `indian_kanoon:177113492:chunk:0000` theft_and_robbery/ipc_crpc page 1-3 pre-rank 9 rerank 1.612664

### common intention section 34 IPC

**pre-rerank hybrid**
- 1. `indian_kanoon:173395727:chunk:0048` kidnapping/ipc_crpc page 102-103 score 0.032787
- 2. `indian_kanoon:199689273:chunk:0006` homicide/ipc_crpc page 13-14 score 0.031498
- 3. `indian_kanoon:173395727:chunk:0053` kidnapping/ipc_crpc page 111-113 score 0.031054
- 4. `indian_kanoon:123721856:chunk:0007` hurt_and_assault/ipc_crpc page 21-22 score 0.030579
- 5. `indian_kanoon:173395727:chunk:0049` kidnapping/ipc_crpc page 103-104 score 0.030415

**post-rerank**
- 1. `indian_kanoon:173395727:chunk:0048` kidnapping/ipc_crpc page 102-103 pre-rank 1 rerank 5.405064
- 2. `indian_kanoon:173395727:chunk:0053` kidnapping/ipc_crpc page 111-113 pre-rank 3 rerank 4.798248
- 3. `indian_kanoon:123721856:chunk:0007` hurt_and_assault/ipc_crpc page 21-22 pre-rank 4 rerank 4.60883
- 4. `indian_kanoon:189001274:chunk:0031` homicide/ipc_crpc page 47-47 pre-rank 6 rerank 4.357894
- 5. `indian_kanoon:173395727:chunk:0047` kidnapping/ipc_crpc page 100-102 pre-rank 12 rerank 3.900388
