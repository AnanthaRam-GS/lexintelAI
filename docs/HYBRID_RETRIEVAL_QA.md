# Hybrid Retrieval QA

This is a diagnostic sanity comparison, not a formal retrieval benchmark.

## Configuration

- dense model: `BAAI/bge-m3`
- BM25: k1=1.5, b=0.75
- tokenizer: `legalai-legal-tokenizer-v1`
- RRF K: 60
- candidate_k: 20
- top_k: 5

## Rank 1 Comparison

| Query | Dense Rank 1 | BM25 Rank 1 | Hybrid Rank 1 |
| --- | --- | --- | --- |
| dowry death section 304B IPC | indian_kanoon:83401027:chunk:0001 (dowry_and_domestic_cruelty/ipc_crpc) | indian_kanoon:40368737:chunk:0005 (dowry_and_domestic_cruelty/ipc_crpc) | indian_kanoon:36195540:chunk:0002 (dowry_and_domestic_cruelty/ipc_crpc) |
| murder conviction section 302 IPC | indian_kanoon:123721856:chunk:0009 (hurt_and_assault/ipc_crpc) | indian_kanoon:31029978:chunk:0024 (sexual_offences/ipc_crpc) | indian_kanoon:123721856:chunk:0009 (hurt_and_assault/ipc_crpc) |
| criminal breach of trust section 406 IPC | indian_kanoon:13518275:chunk:0005 (criminal_breach_of_trust/ipc_crpc) | indian_kanoon:131331418:chunk:0005 (criminal_breach_of_trust/ipc_crpc) | indian_kanoon:131331418:chunk:0005 (criminal_breach_of_trust/ipc_crpc) |
| NDPS bail commercial quantity | indian_kanoon:138227421:chunk:0015 (narcotics_related/ipc_crpc) | indian_kanoon:138227421:chunk:0006 (narcotics_related/ipc_crpc) | indian_kanoon:138227421:chunk:0001 (narcotics_related/ipc_crpc) |
| anticipatory bail under BNSS | indian_kanoon:15148168:chunk:0008 (other/bns_bnss) | indian_kanoon:100558061:chunk:0002 (other/mixed_or_transition) | indian_kanoon:100558061:chunk:0004 (other/mixed_or_transition) |
| rape section 376 IPC | indian_kanoon:125041151:chunk:0010 (sexual_offences/ipc_crpc) | indian_kanoon:179828917:chunk:0025 (sexual_offences/ipc_crpc) | indian_kanoon:31029978:chunk:0024 (sexual_offences/ipc_crpc) |
| robbery section 392 IPC | indian_kanoon:177113492:chunk:0006 (theft_and_robbery/ipc_crpc) | indian_kanoon:177113492:chunk:0002 (theft_and_robbery/ipc_crpc) | indian_kanoon:177113492:chunk:0002 (theft_and_robbery/ipc_crpc) |
| common intention section 34 IPC | indian_kanoon:173395727:chunk:0048 (kidnapping/ipc_crpc) | indian_kanoon:173395727:chunk:0048 (kidnapping/ipc_crpc) | indian_kanoon:173395727:chunk:0048 (kidnapping/ipc_crpc) |

## Top 5 Details

### dowry death section 304B IPC

Overlap dense/BM25=2, dense/hybrid=3, BM25/hybrid=4.

**dense**
- 1. `indian_kanoon:83401027:chunk:0001` dowry_and_domestic_cruelty/ipc_crpc page 4-6 score 0.670892
- 2. `indian_kanoon:36195540:chunk:0002` dowry_and_domestic_cruelty/ipc_crpc page 6-7 score 0.665798
- 3. `indian_kanoon:36195540:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 10-11 score 0.65468
- 4. `indian_kanoon:83401027:chunk:0003` dowry_and_domestic_cruelty/ipc_crpc page 10-11 score 0.635148
- 5. `indian_kanoon:36195540:chunk:0003` dowry_and_domestic_cruelty/ipc_crpc page 8-9 score 0.631828

**lexical**
- 1. `indian_kanoon:40368737:chunk:0005` dowry_and_domestic_cruelty/ipc_crpc page 16-17 score 28.649918
- 2. `indian_kanoon:36195540:chunk:0002` dowry_and_domestic_cruelty/ipc_crpc page 6-7 score 28.413275
- 3. `indian_kanoon:26223875:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 7-8 score 28.324709
- 4. `indian_kanoon:83401027:chunk:0001` dowry_and_domestic_cruelty/ipc_crpc page 4-6 score 27.234337
- 5. `indian_kanoon:83401027:chunk:0002` dowry_and_domestic_cruelty/ipc_crpc page 7-9 score 26.838814

**hybrid**
- 1. `indian_kanoon:36195540:chunk:0002` dowry_and_domestic_cruelty/ipc_crpc page 6-7 score 0.032258
- 2. `indian_kanoon:83401027:chunk:0001` dowry_and_domestic_cruelty/ipc_crpc page 4-6 score 0.032018
- 3. `indian_kanoon:40368737:chunk:0005` dowry_and_domestic_cruelty/ipc_crpc page 16-17 score 0.031545
- 4. `indian_kanoon:26223875:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 7-8 score 0.030798
- 5. `indian_kanoon:36195540:chunk:0004` dowry_and_domestic_cruelty/ipc_crpc page 10-11 score 0.030798

### murder conviction section 302 IPC

Overlap dense/BM25=2, dense/hybrid=3, BM25/hybrid=3.

**dense**
- 1. `indian_kanoon:123721856:chunk:0009` hurt_and_assault/ipc_crpc page 25-27 score 0.662532
- 2. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 0.661747
- 3. `indian_kanoon:123692674:chunk:0009` homicide/ipc_crpc page  score 0.651908
- 4. `indian_kanoon:179828917:chunk:0048` sexual_offences/ipc_crpc page 80-81 score 0.647125
- 5. `indian_kanoon:199957261:chunk:0009` homicide/ipc_crpc page 25-27 score 0.647043

**lexical**
- 1. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 12.991113
- 2. `indian_kanoon:123721856:chunk:0009` hurt_and_assault/ipc_crpc page 25-27 score 12.891541
- 3. `indian_kanoon:176922161:chunk:0011` homicide/ipc_crpc page 20-21 score 12.149786
- 4. `indian_kanoon:15834217:chunk:0000` homicide/ipc_crpc page 1-3 score 11.884483
- 5. `indian_kanoon:30754679:chunk:0002` homicide/ipc_crpc page 7-9 score 11.708377

**hybrid**
- 1. `indian_kanoon:123721856:chunk:0009` hurt_and_assault/ipc_crpc page 25-27 score 0.032522
- 2. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 0.032522
- 3. `indian_kanoon:30754679:chunk:0002` homicide/ipc_crpc page 7-9 score 0.03031
- 4. `indian_kanoon:199957261:chunk:0009` homicide/ipc_crpc page 25-27 score 0.03009
- 5. `indian_kanoon:15834217:chunk:0003` homicide/ipc_crpc page 10-11 score 0.02837

### criminal breach of trust section 406 IPC

Overlap dense/BM25=3, dense/hybrid=4, BM25/hybrid=4.

**dense**
- 1. `indian_kanoon:13518275:chunk:0005` criminal_breach_of_trust/ipc_crpc page 16-18 score 0.705527
- 2. `indian_kanoon:131331418:chunk:0005` criminal_breach_of_trust/ipc_crpc page 13-15 score 0.65388
- 3. `indian_kanoon:176391710:chunk:0010` cheating_and_fraud/ipc_crpc page 15-15 score 0.59299
- 4. `indian_kanoon:131331418:chunk:0006` criminal_breach_of_trust/ipc_crpc page 15-17 score 0.590833
- 5. `indian_kanoon:13518275:chunk:0006` criminal_breach_of_trust/ipc_crpc page 18-21 score 0.588494

**lexical**
- 1. `indian_kanoon:131331418:chunk:0005` criminal_breach_of_trust/ipc_crpc page 13-15 score 24.876484
- 2. `indian_kanoon:13518275:chunk:0005` criminal_breach_of_trust/ipc_crpc page 16-18 score 23.022044
- 3. `indian_kanoon:44731735:chunk:0002` criminal_breach_of_trust/ipc_crpc page 6-7 score 20.422404
- 4. `indian_kanoon:44731735:chunk:0003` criminal_breach_of_trust/ipc_crpc page 8-9 score 20.391967
- 5. `indian_kanoon:176391710:chunk:0010` cheating_and_fraud/ipc_crpc page 15-15 score 19.503964

**hybrid**
- 1. `indian_kanoon:131331418:chunk:0005` criminal_breach_of_trust/ipc_crpc page 13-15 score 0.032522
- 2. `indian_kanoon:13518275:chunk:0005` criminal_breach_of_trust/ipc_crpc page 16-18 score 0.032522
- 3. `indian_kanoon:176391710:chunk:0010` cheating_and_fraud/ipc_crpc page 15-15 score 0.031258
- 4. `indian_kanoon:44731735:chunk:0003` criminal_breach_of_trust/ipc_crpc page 8-9 score 0.030777
- 5. `indian_kanoon:13518275:chunk:0006` criminal_breach_of_trust/ipc_crpc page 18-21 score 0.030536

### NDPS bail commercial quantity

Overlap dense/BM25=2, dense/hybrid=4, BM25/hybrid=3.

**dense**
- 1. `indian_kanoon:138227421:chunk:0015` narcotics_related/ipc_crpc page 17-17 score 0.583444
- 2. `indian_kanoon:138227421:chunk:0008` narcotics_related/ipc_crpc page 10-10 score 0.571113
- 3. `indian_kanoon:138227421:chunk:0001` narcotics_related/ipc_crpc page 3-3 score 0.567635
- 4. `indian_kanoon:138227421:chunk:0009` narcotics_related/ipc_crpc page 11-11 score 0.553199
- 5. `indian_kanoon:116547627:chunk:0004` narcotics_related/unknown page 17-20 score 0.529222

**lexical**
- 1. `indian_kanoon:138227421:chunk:0006` narcotics_related/ipc_crpc page 8-8 score 25.727003
- 2. `indian_kanoon:138227421:chunk:0001` narcotics_related/ipc_crpc page 3-3 score 22.51791
- 3. `indian_kanoon:138227421:chunk:0013` narcotics_related/ipc_crpc page 15-15 score 22.024971
- 4. `indian_kanoon:138227421:chunk:0008` narcotics_related/ipc_crpc page 10-10 score 19.881511
- 5. `indian_kanoon:169784101:chunk:0002` narcotics_related/ipc_crpc page 6-7 score 19.072941

**hybrid**
- 1. `indian_kanoon:138227421:chunk:0001` narcotics_related/ipc_crpc page 3-3 score 0.032002
- 2. `indian_kanoon:138227421:chunk:0008` narcotics_related/ipc_crpc page 10-10 score 0.031754
- 3. `indian_kanoon:138227421:chunk:0015` narcotics_related/ipc_crpc page 17-17 score 0.030478
- 4. `indian_kanoon:138227421:chunk:0013` narcotics_related/ipc_crpc page 15-15 score 0.030366
- 5. `indian_kanoon:138227421:chunk:0009` narcotics_related/ipc_crpc page 11-11 score 0.029324

### anticipatory bail under BNSS

Overlap dense/BM25=1, dense/hybrid=3, BM25/hybrid=3.

**dense**
- 1. `indian_kanoon:15148168:chunk:0008` other/bns_bnss page 18-19 score 0.595052
- 2. `indian_kanoon:100558061:chunk:0004` other/mixed_or_transition page 17-20 score 0.573917
- 3. `indian_kanoon:100558061:chunk:0009` other/mixed_or_transition page 32-34 score 0.570906
- 4. `indian_kanoon:15148168:chunk:0004` other/bns_bnss page 9-9 score 0.569835
- 5. `indian_kanoon:183406121:chunk:0002` other/mixed_or_transition page  score 0.569563

**lexical**
- 1. `indian_kanoon:100558061:chunk:0002` other/mixed_or_transition page 9-12 score 19.144047
- 2. `indian_kanoon:100558061:chunk:0003` other/mixed_or_transition page 13-16 score 19.144047
- 3. `indian_kanoon:100558061:chunk:0001` other/mixed_or_transition page 5-8 score 19.117366
- 4. `indian_kanoon:100558061:chunk:0000` other/mixed_or_transition page 1-4 score 19.097404
- 5. `indian_kanoon:100558061:chunk:0004` other/mixed_or_transition page 17-20 score 15.294537

**hybrid**
- 1. `indian_kanoon:100558061:chunk:0004` other/mixed_or_transition page 17-20 score 0.031514
- 2. `indian_kanoon:100558061:chunk:0003` other/mixed_or_transition page 13-16 score 0.031054
- 3. `indian_kanoon:100558061:chunk:0002` other/mixed_or_transition page 9-12 score 0.030886
- 4. `indian_kanoon:100558061:chunk:0009` other/mixed_or_transition page 32-34 score 0.030798
- 5. `indian_kanoon:183406121:chunk:0002` other/mixed_or_transition page  score 0.030536

### rape section 376 IPC

Overlap dense/BM25=0, dense/hybrid=0, BM25/hybrid=3.

**dense**
- 1. `indian_kanoon:125041151:chunk:0010` sexual_offences/ipc_crpc page  score 0.574339
- 2. `indian_kanoon:173395727:chunk:0046` kidnapping/ipc_crpc page 98-100 score 0.552031
- 3. `indian_kanoon:173395727:chunk:0003` kidnapping/ipc_crpc page 9-11 score 0.551749
- 4. `indian_kanoon:77330685:chunk:0004` kidnapping/ipc_crpc page 6-6 score 0.548636
- 5. `indian_kanoon:173395727:chunk:0031` kidnapping/ipc_crpc page 69-70 score 0.544184

**lexical**
- 1. `indian_kanoon:179828917:chunk:0025` sexual_offences/ipc_crpc page 40-41 score 13.085064
- 2. `indian_kanoon:125041151:chunk:0001` sexual_offences/ipc_crpc page  score 11.717685
- 3. `indian_kanoon:47759402:chunk:0001` sexual_offences/mixed_or_transition page 4-7 score 11.356146
- 4. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 11.016178
- 5. `indian_kanoon:184937779:chunk:0010` sexual_offences/ipc_crpc page 29-31 score 10.249755

**hybrid**
- 1. `indian_kanoon:31029978:chunk:0024` sexual_offences/ipc_crpc page 71-73 score 0.03055
- 2. `indian_kanoon:179828917:chunk:0033` sexual_offences/ipc_crpc page 52-53 score 0.028814
- 3. `indian_kanoon:184937779:chunk:0010` sexual_offences/ipc_crpc page 29-31 score 0.028543
- 4. `indian_kanoon:31029978:chunk:0001` sexual_offences/ipc_crpc page 5-7 score 0.028485
- 5. `indian_kanoon:47759402:chunk:0001` sexual_offences/mixed_or_transition page 4-7 score 0.028373

### robbery section 392 IPC

Overlap dense/BM25=4, dense/hybrid=4, BM25/hybrid=4.

**dense**
- 1. `indian_kanoon:177113492:chunk:0006` theft_and_robbery/ipc_crpc page 13-14 score 0.673786
- 2. `indian_kanoon:177113492:chunk:0005` theft_and_robbery/ipc_crpc page 11-12 score 0.648252
- 3. `indian_kanoon:177113492:chunk:0002` theft_and_robbery/ipc_crpc page 6-7 score 0.617961
- 4. `indian_kanoon:177113492:chunk:0003` theft_and_robbery/ipc_crpc page 8-8 score 0.596609
- 5. `indian_kanoon:136492342:chunk:0001` theft_and_robbery/ipc_crpc page 2-2 score 0.575338

**lexical**
- 1. `indian_kanoon:177113492:chunk:0002` theft_and_robbery/ipc_crpc page 6-7 score 23.039292
- 2. `indian_kanoon:177113492:chunk:0005` theft_and_robbery/ipc_crpc page 11-12 score 20.253
- 3. `indian_kanoon:177113492:chunk:0006` theft_and_robbery/ipc_crpc page 13-14 score 18.3008
- 4. `indian_kanoon:177113492:chunk:0003` theft_and_robbery/ipc_crpc page 8-8 score 13.506126
- 5. `indian_kanoon:177113492:chunk:0000` theft_and_robbery/ipc_crpc page 1-3 score 11.851793

**hybrid**
- 1. `indian_kanoon:177113492:chunk:0002` theft_and_robbery/ipc_crpc page 6-7 score 0.032266
- 2. `indian_kanoon:177113492:chunk:0006` theft_and_robbery/ipc_crpc page 13-14 score 0.032266
- 3. `indian_kanoon:177113492:chunk:0005` theft_and_robbery/ipc_crpc page 11-12 score 0.032258
- 4. `indian_kanoon:177113492:chunk:0003` theft_and_robbery/ipc_crpc page 8-8 score 0.03125
- 5. `indian_kanoon:177113492:chunk:0004` theft_and_robbery/ipc_crpc page 9-10 score 0.029851

### common intention section 34 IPC

Overlap dense/BM25=2, dense/hybrid=4, BM25/hybrid=3.

**dense**
- 1. `indian_kanoon:173395727:chunk:0048` kidnapping/ipc_crpc page 102-103 score 0.708688
- 2. `indian_kanoon:173395727:chunk:0049` kidnapping/ipc_crpc page 103-104 score 0.702686
- 3. `indian_kanoon:123721856:chunk:0007` hurt_and_assault/ipc_crpc page 21-22 score 0.696819
- 4. `indian_kanoon:199689273:chunk:0006` homicide/ipc_crpc page 13-14 score 0.674323
- 5. `indian_kanoon:189001274:chunk:0031` homicide/ipc_crpc page 47-47 score 0.674219

**lexical**
- 1. `indian_kanoon:173395727:chunk:0048` kidnapping/ipc_crpc page 102-103 score 16.386565
- 2. `indian_kanoon:173395727:chunk:0053` kidnapping/ipc_crpc page 111-113 score 16.229078
- 3. `indian_kanoon:199689273:chunk:0006` homicide/ipc_crpc page 13-14 score 16.219735
- 4. `indian_kanoon:173395727:chunk:0047` kidnapping/ipc_crpc page 100-102 score 16.143902
- 5. `indian_kanoon:199689273:chunk:0005` homicide/ipc_crpc page 11-12 score 15.739392

**hybrid**
- 1. `indian_kanoon:173395727:chunk:0048` kidnapping/ipc_crpc page 102-103 score 0.032787
- 2. `indian_kanoon:199689273:chunk:0006` homicide/ipc_crpc page 13-14 score 0.031498
- 3. `indian_kanoon:173395727:chunk:0053` kidnapping/ipc_crpc page 111-113 score 0.031054
- 4. `indian_kanoon:123721856:chunk:0007` hurt_and_assault/ipc_crpc page 21-22 score 0.030579
- 5. `indian_kanoon:173395727:chunk:0049` kidnapping/ipc_crpc page 103-104 score 0.030415
