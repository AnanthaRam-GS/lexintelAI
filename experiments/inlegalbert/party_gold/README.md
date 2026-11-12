# Party gold set (step E4)

Gold parties and roles for scoring the brief's **Parties & Roles** field: regex-only (today) vs regex + InLegalBERT
(`LEGALAI_NER_BACKEND=combined`). Plan and frozen pass rules: `docs/experiments/NER_PARTY_ROLES_PLAN.md`. The gold
set, this README, the labelling guide and the scorer were committed **before any flag-on run**.

| Source | Documents | Gold | Label status |
|---|---|---|---|
| `fixture` | the 5 professional-brief fixtures (`backend/scripts/tests/fixtures/briefs/`): judgment, FIR, charge sheet, petition, unknown | `gold/f_*.json`, copied from each fixture's `*.expected.json` `parties` | `from_expected_file` |
| `synthetic` | 10 SYNTHETIC documents (`synthetic/*.txt`): 2 FIR, 2 charge sheet, 2 petition, 1 judgment, 2 order, 1 unknown | `gold/s*.json`, **by construction** in `generate_gold.py` | `by_construction` |
| `public` | 5 trimmed public judgment excerpts (`public/*.txt`; sources in `public/SOURCES.md`) | `public/*.labels.json`, **empty** | `unlabelled`, filled by a teammate (`LABELLING_GUIDE.md`) |

Now: 15 documents with gold, 47 gold parties (fixtures 10, synthetic 37), 2 documents with no party
(`f_unknown`, `s10_unknown_legal_aid_minutes`).

**Role vocabulary:** the roles the product's `parties_and_roles` uses: appellant, respondent, petitioner, applicant,
accused, complainant, informant. A party may have `alternative_roles` (e.g. "Appellant/Accused No. 1"). There is no
witness role, so witnesses, investigating officers, judges, counsel, victims and representatives are **not** parties;
in the synthetic documents they are listed under `non_parties` (information only; reporting one is a false positive).

**Synthetic documents.** Every file says `SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD` at the top and bottom. Names,
places, case and FIR numbers and amounts are invented; any resemblance to real persons or organisations is
coincidental. They include organisations (a co-operative bank, private companies, a market committee, a partnership
firm), multi-word names, aliases with "@", several accused, witnesses and complainants, and role cues of several kinds
(labelled lines, cause titles, numbered lists, prose). Each gold file lists what the document `covers`. A line holding
only `\f` is a page break (rendered as a new PDF page, as for the fixtures).

**Public excerpts.** Selected by a fixed rule before any measurement (`build_public_excerpts.py`: seeded sample of the
curated-corpus judgments with two named sides, excluding the fixture's judgment), trimmed as in step 10: cause title and
opening paragraphs, with counsel names, appearance lines, reporter questionnaires, signature blocks, page numbers and
download stamps removed. Judgment data sourced from Indian Kanoon API (attribution in `public/SOURCES.md`).

**Files**
- `generate_gold.py`: writes `synthetic/` and `gold/`, and the empty public label files (never overwrites labelled
  ones); `--check` verifies the committed files byte for byte.
- `build_public_excerpts.py`: builds `public/*.txt` from the local corpus (not in git); `--check` compares.
- `score_parties.py`: the scorer (normalization, strict and partial matching, metrics, paired bootstrap, the six rules);
  `--self-test` runs its own checks and validates any labelled public file.
- `LABELLING_GUIDE.md`: instructions for the teammate who labels the public excerpts.

The results of the measurement are in `experiments/inlegalbert/results/e4_*.json` and
`docs/experiments/NER_PARTY_ROLES_RESULTS.md`. All outputs are UNREVIEWED.
