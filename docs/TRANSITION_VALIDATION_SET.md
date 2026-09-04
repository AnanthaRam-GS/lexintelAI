# LegalAI BNS / BNSS Transition Validation Set

Phase 0 Step 0.4I creates a small, separate validation set for post-1 July 2024 BNS / BNSS transition handling.

This set is not part of the reviewed balanced development corpus. It does not change the 30 reviewed balanced candidates, the 28 human-accepted judgments, or the 2 human-rejected judgments recorded in Step 0.4H.

## Purpose

* Validate explicit BNS detection.
* Validate explicit BNSS detection.
* Validate `bns_bnss` regime assignment.
* Validate `mixed_or_transition` regime assignment.
* Preserve post-1 July 2024 judgments that still concern IPC / CrPC.
* Exercise `current_transition` acquisition independently from balanced corpus acquisition.

## Manifests

| Manifest | Purpose |
| --- | --- |
| `data/structured/manifests/transition_validation_queries.json` | Regime-oriented acquisition queries. |
| `data/structured/manifests/transition_validation_candidates.json` | Reviewable transition validation candidates. |
| `data/structured/manifests/transition_validation_review.json` | Pending human review queue for the validation set. |
| `data/structured/manifests/transition_validation_audit.json` | Automated acquisition and filtering audit records. |

Raw PDFs are stored under `data/raw/judgments/indiankanoon/transition_validation/`.

## Acquisition Summary

| Metric | Count |
| --- | ---: |
| reviewable candidates | 10 |
| human pending | 10 |
| human accepted | 0 |
| human rejected | 0 |
| accept_candidate | 7 |
| needs_review | 3 |
| temporal_track `current_transition` | 10 |

## Legal Regime Distribution

| Legal Regime | Count |
| --- | ---: |
| bns_bnss | 5 |
| mixed_or_transition | 3 |
| ipc_crpc | 2 |

## Year Distribution

| Year | Count |
| --- | ---: |
| 2025 | 5 |
| 2026 | 5 |

## Reviewable Case Inventory

| Source ID | Case Name | Court | Year | Regime | Automated Decision | Detected Statutes |
| --- | --- | --- | ---: | --- | --- | --- |
| 106120784 | Ponnama N K vs State Of Kerala on 9 March, 2026 | high_court | 2026 | bns_bnss | needs_review | BNS |
| 41507960 | Sujal Vishwas Attavar vs The State Of Maharashtra on 4 May, 2026 | supreme_court | 2026 | mixed_or_transition | accept_candidate | BNS, BNSS, CrPC |
| 64689335 | Ramanbhai Bholidas Patel vs State Of Gujarat on 12 June, 2026 | high_court | 2026 | ipc_crpc | accept_candidate | CrPC, IPC |
| 120995867 | Bijoy Lakshmi Ghosh @ Bijay Laxmi Ghosh vs State Of West Bengal And Ors on 23 December, 2025 | high_court | 2025 | ipc_crpc | accept_candidate | CrPC, IPC |
| 49977156 | Sunil Baban Wanve And Another vs The State Of Maharashtra And Another on 19 September, 2025 | high_court | 2025 | mixed_or_transition | accept_candidate | BNS, CrPC, IPC |
| 22716486 | Bhima Mukunda Karad vs The State Of Maharashtra And Another on 19 September, 2025 | high_court | 2025 | mixed_or_transition | accept_candidate | BNS, CrPC, IPC |
| 172466729 | Kiran S/O Umesh Choudappanavar vs State Of Karnataka on 25 September, 2025 | high_court | 2025 | bns_bnss | needs_review | BNS |
| 117242710 | Abdul Kareem vs State Of Kerala on 10 April, 2025 | high_court | 2025 | bns_bnss | accept_candidate | BNS, BNSS |
| 140476000 | Anil Kurre vs State Of Chhattisgarh on 16 July, 2026 | supreme_court | 2026 | bns_bnss | needs_review | BNS |
| 2835675 | Ikshan Singh Mehta vs State Of Haryana on 31 August, 2026 | supreme_court | 2026 | bns_bnss | accept_candidate | BNS |
