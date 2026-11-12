# Labelling guide: parties and roles in 5 public judgment excerpts

**For:** a LegalAI teammate. **Time:** about 10 minutes per excerpt, under an hour in all.
**Why:** these labels are the only real (non-synthetic) test data for deciding whether the InLegalBERT model should
help fill the brief's "Parties & Roles". Please label from the text alone.

## Before you start
- **Do not run LegalAI, the scorer or any model on these excerpts, and do not look at any system output for them,
  before you finish.** Labels must not be influenced by what the system finds.
- In particular, do not open `backend/scripts/tests/fixtures/party_roles_flag_off_snapshot.json` or
  `experiments/inlegalbert/results/e4_party_roles.json`: they hold system output.
- Do not edit the excerpt texts (`public/*.txt`). Only edit the matching `public/*.labels.json`.
- Files, in `experiments/inlegalbert/party_gold/public/`:
  `p01_gujarat_hc_2021`, `p02_andhra_hc_2023`, `p03_punjab_hc_2023`, `p04_supreme_court_2022`,
  `p05_allahabad_hc_2019` (`.txt` to read, `.labels.json` to fill).

## What counts as a party
A **party** is any person or organisation **named in the excerpt** to whom the excerpt gives one of these seven roles,
in this proceeding or in the underlying criminal case:

`appellant`, `respondent`, `petitioner`, `applicant`, `accused`, `complainant`, `informant`

Use only these words (lower case).
- "Opposite party" and "non-applicant" mean `respondent`.
- "Original petitioner" (including one who has died, "decd.") and a person substituted as petitioner are both
  `petitioner`.
- A party named only by an official designation (e.g. "Commissioner of Police" given as respondent No. 2):
  label the designation as written, as the name.
- A party mentioned without any name ("the complainant", "and another", "the Bank" with no bank name) is **not** labelled: there is no name to find.

**Not parties** (do not label): judges, counsel and prosecutors, witnesses (PW-, LW-, CW-), doctors, investigating
or police officers acting in their duty, deceased victims, relatives and other third persons (buyers, neighbours)
who have none of the seven roles, courts, and the names in **cited cases** (e.g. "State vs. X (1978) 2 SCC 411" is a
precedent, not a party).

## Roles
- `role`: the role in the cause title of this proceeding; if there is no cause title, the first role the excerpt gives.
- `alternative_roles`: any other of the seven roles the excerpt gives the same party, e.g. "Appellant/Accused No. 1"
  -> `"role": "appellant", "alternative_roles": ["accused"]`; an applicant described as "the complainant" ->
  `"role": "applicant", "alternative_roles": ["complainant"]`. Use `[]` when there is none.
- One entry per party, even if the excerpt names them many times.

## Names
- Copy the **fullest form** of the name that appears in the excerpt (e.g. "A. Kuppaiah" rather than "Kuppaiah").
- Leave out honorifics (Shri, Smt., Sri, Mr., Dr., M/s), parentage ("S/o ..."), age, address, "rep. by ...",
  "through ...", "& Ors.", "and anr.".
- Keep aliases with "@": "Neelam @ Neeraj".
- Capitalisation does not matter (the scorer ignores case, honorifics and punctuation).
- Each named member of "X & Ors." is a separate party **if the excerpt names them** with their role (e.g.
  "appellant No. 2, Sitaram Ninave" -> appellant).
- A State or government is a party when it is a party ("State of Madhya Pradesh", respondent).

## The file format
Fill `parties`, then set `label_status` to `"labelled"`, `labeller` to your name or initials, and `labelled_on` to
the date. Use `notes` for anything you were unsure about (please do not guess silently). Example (from a different
document):

```json
{
 "doc_id": "pXX_example",
 "source": "public",
 "synthetic": false,
 "text_file": "experiments/inlegalbert/party_gold/public/pXX_example.txt",
 "label_status": "labelled",
 "labeller": "AB",
 "labelled_on": "2026-11-20",
 "parties": [
  {"name": "Neelam @ Neeraj", "role": "applicant", "alternative_roles": ["accused"]},
  {"name": "State of Madhya Pradesh", "role": "respondent", "alternative_roles": []}
 ],
 "notes": ""
}
```

An excerpt with no named party has `"parties": []` and `"label_status": "labelled"`.

## When you have finished
1. Check the files: `.venv/bin/python experiments/inlegalbert/party_gold/score_parties.py --self-test`. It reports
   a bad role or a missing labeller.
2. Commit the five label files only, on their own commit ("labels: party gold public excerpts (labeller XX)"), and
   tell the project owner. The measurement is then re-run with the public excerpts included
   (`experiments/inlegalbert/e4_party_roles.py`); nothing else changes.
