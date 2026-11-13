# Section labels in answers and briefs (steps 25 and 26)

The answer model names statutory provisions with a one-line label of its own. The citation validator checks
structured citations to retrieved evidence, not these labels, and the docs-site screenshots showed wrong ones:
"Section 309(4) BNS – offences relating to suicide attempts" (309 is robbery), "Section 115(2) BNS – provisions on
medical examination of complainant" (115 is voluntarily causing hurt) and "Section 173 BNS – registration of FIR"
(FIR registration is BNSS 173). Since step 25 every section the model names is resolved against LegalAI's trusted
sources before it reaches a response. The resolver is `backend/app/services/section_labels.py`. It runs in the
response layer (`api/query.py`); no prompt, validator, retrieval code or data changed.

## Where model labels reach a response

| Field | Model output it comes from | Resolved |
|---|---|---|
| `identified_sections[]` (professional) | `explicit_legal_provisions` + `potential_additional_provisions` | yes |
| `case_brief.statutory_provisions[]` and the new `statutory_provision_references[]` | `explicit_legal_provisions` | yes |
| `sections[].title` and the new `sections[].references[]` (public) | `possible_legal_provisions` | yes |
| free text: `applicable_law`, `precedent_analysis`, `key_issues`, the public explanation | model prose | no: section names inside sentences are not rewritten (like case names in answer text, see `docs/evaluation/EVALUATION_2026-10.md`) |

Precedents, parties, chronology, procedure and evidence are not model labels: they come from retrieved evidence or the
uploaded document's local map.

## How a provision is resolved

1. **Parse** with the existing deterministic extractor (`judgment_sections.prepare_judgment_text`,
   `query_analysis.extract_sections`). A label-only normalization runs first: no-break and narrow spaces, "Sec." and
   "§" for "Section" ("§§" for "Sections"), and a statute written before its sections ("IPC Sec. 302" -> "Sections
   302 IPC"). A string that names exactly one statute gives it to its section ("Section 113B Evidence Act"). The
   clause form is kept ("3(1)(r)"). What is left after the section and statute references is the model's label.
2. **Look up**, in order of trust (the first source with an entry wins; sources are never mixed):
   0. **official headings** (step 26): the marginal notes of the Acts as published on India Code, the official
      legislative repository (`data/structured/statute_headings/`, sources and checks in `SOURCES.md` there): the
      exact section, else its parent section (`309(4)` -> `309`; sub-sections inherit the section's heading). IPC,
      Evidence Act, BNS, BNSS and BSA; **not CrPC** (India Code's CrPC is a scanned PDF that could not be read
      reliably). Omitted and repealed sections are recorded but never shown as a title. When an official heading is
      shown, the catalog and mapping titles for the same section stay in `label.other_sources` (`source`,
      `source_key`, `title`, `agrees`), and a note says so when one disagrees;
   1. the legal section catalog (`data/structured/manifests/legal_section_catalog.json`, 62 entries): the exact
      section, else the base section when the catalog lists it (`309(4)` -> `309`);
   2. the IPC-BNS mapping's CYTRAIN rows (`data/processed/ipc_bns/ipc_bns_mapping.csv`, the file
      `load_ipc_bns.py --source cytrain` loads; the database rows are the same apart from the loader's "366-B" ->
      "366B", which the resolver applies too): the BNS description for a BNS section, the IPC description for an IPC
      section listed on its own. Rows keyed by an IPC group label ("415 to 420, 424, …") give no IPC title.
   The mapping's 68 NCRB rows are not used as titles: NCRB prints crime-head names that cover several sections
   ("Robbery (Section 309 (4), 309(6), 311 BNS/…)"), not section titles.
3. **Decide the state:**

| State | When | Shown |
|---|---|---|
| `verified` | a trusted title exists | the trusted title; the model's label is dropped (a note records when it disagreed) |
| `corrected_statute` | the model named one statute of a pair (BNS/BNSS, IPC/CrPC); that statute has no entry for the number or its entry disagrees with the label, and the other statute has an entry for the same number that agrees with it | the corrected statute and the reason; its trusted title when the exact section has one (since step 26, its official heading even if worded differently from the label), else the model's label marked unverified |
| `unverified` | no trusted title | the model's label, marked "Unverified label" |
| `conflict` | the source with entries gives different titles | no title: "Title not shown: the trusted sources disagree" |

**Agreement** between a label and an entry means sharing a content word: stop words and generic legal words
("section", "punishment", "offence", "relating", statute names) are ignored, and words are compared after removing a
common suffix, on their first three to five letters. It only chooses between two trusted entries or notes a
disagreeing label; it never produces a title. A title is never invented.

**Display text** (`statutory_provisions`, public `title`): `Section 309(4) BNS — Robbery`; `Section 103 BNS — Punishment
for murder (statute corrected from BNSS)`; `Section 173 BNSS — Information in cognizable cases (statute corrected from
BNS)`; `Section 113B Evidence Act — … (unverified label)`; `Section 900 BNS (title not shown: trusted sources
disagree)`. The frontend renders the same states from the `label` object (`frontend/lib/section-labels.ts`,
`components/SectionLabelText.tsx`) and shows provisions from older history entries, which have no label, as
unverified.

The Bharatiya Sakshya Adhiniyam is not one of the extractor's statutes (`query_analysis.py` also serves retrieval and
is not changed), so the resolver reads "Section 63 BSA" and "… of the Bharatiya Sakshya Adhiniyam, 2023" itself.

## Official headings (step 26, 2026-11-12) — UNREVIEWED

Source, per-Act counts, hashes, extraction rules and checks: `data/structured/statute_headings/SOURCES.md`; built by
`backend/scripts/build_statute_headings.py`.

| Act | Read from | Headings | Omitted / repealed | Not stored | Spot checks (rendered source) |
|---|---|---:|---:|---|---|
| IPC | the Act's India Code PDF, arrangement and body cross-checked | 548 (60 lettered) | 21 | 153, 17, 174A, 376AB, 376DA, 376DB (not corroborated) | 14/14 |
| Evidence Act | the same | 181 (18 lettered) | 1 | 4, 10, 86 | 14/14 |
| BNS | India Code section records | 358 | 0 | — | 14/14 (against the Act's PDF) |
| BNSS | India Code section records | 531 | 0 | — | 14/14 |
| BSA | India Code section records | 170 | 0 | — | 14/14 |
| CrPC | — | **skipped**: India Code's only CrPC file is a scanned PDF with noisy OCR text | | | |

`www.indiacode.nic.in` now redirects to `indiacode.gov.in` (the old site says it has migrated); the data comes from
the new address. Published spelling errors are kept as published (e.g. IPC 312 "Causing miscarraige").

### Coverage before and after (`backend/scripts/section_label_coverage.py`, no provider calls)

| | Before (catalog + mapping) | After (official headings first) |
|---|---:|---:|
| Corpus-cited sections with a trusted title (distinct, of 370) | 57 (catalog 40, mapping 17) | **214** (official 201, catalog 13) |
| By rows (of 920) | 280 | **583** |
| IPC (173 distinct) | 26 | 161 |
| CrPC (105) | 5 | 5 |
| Evidence Act (13) | 0 | 12 |
| BNS (16) / BNSS (12) | 13 / 5 | 16 / 12 |
| NDPS (32) / POCSO (17) / SC/ST (2) | 5 / 3 / 0 | 5 / 3 / 0 |
| Saved step 22-24 provision strings resolving to a trusted title | 128 of 300 sections | 169 of 300 |
| Checkable labels (one section, a model label, a trusted title or correction) | 96 | **130** |
| Mismatches among them | 16 | **27** |

The 12 IPC sections still without a title: 5 omitted or repealed (13, 15, 56, 58, 161), 2 not corroborated (17,
174A), and 5 that are not IPC sections (9B, 18A, 18B, 23A, 113B: citation-extraction artefacts in the corpus).

**Mismatches, re-counted.** The 16 of step 25 are all still mismatches (13 are now checked against the official
heading). The 11 new ones are labels that had no trusted title before; by hand, 5 are wrong labels (BNSS 103
"transitional provision"; IPC 318 "fraudulent or dishonest conduct", IPC 318 is concealment of birth; IPC 138
"dishonour of cheque", which is section 138 of the Negotiable Instruments Act; BNSS 176 "chargesheet filing"; BNSS 173
"investigation report") and 6 name the section's subject in other words, which the word-overlap rule cannot see (BNSS
173 "FIR registration" for "Information in cognizable cases"; Evidence Act 27 "deemed custody"). In all 27 the
official heading is what is shown.

### Official headings vs the catalog and the mapping

Every catalog or mapping title that differs from the official heading of the same section
(`data/structured/statute_headings/crosscheck.csv`, `section_label_coverage.py --crosscheck`): **151** (catalog 25 of
the 43 entries with an official heading; mapping 126 of 325). Judgments: *meaning differs* and *describes use, not
subject* were made by hand (listed in the script); the rest by the documented rules, read through by hand.

| Judgment | Catalog | Mapping |
|---|---:|---:|
| meaning differs | 0 | 8 (IPC 366B; seven 376A-376E headings filed under IPC 376) |
| describes use, not subject | 2 (BNSS 35 "Arrest safeguards", BNSS 187 "Default bail context") | 0 |
| sub-section specific (the catalog titles a sub-section; the official heading is the section's) | 3 (BNS 3(5) "Common intention", BNSS 173(4), BNSS 187(3)) | — |
| wording only | 20 (e.g. "Murder" / "Punishment for murder") | 26 (mostly the heading with a sub-section tag, "Cheating. 318 (1)") |
| not a title (statute text or a bare sub-section reference) | — | 92 |

The official heading wins in every case; nothing is dropped (`other_sources`). Because a sub-section inherits its
section's official heading, the catalog's sub-section titles (BNS 3(5) "Common intention", BNSS 173(4)) are no longer
shown for those sub-sections; they stay in `other_sources`.

<details><summary>All 151 disagreements</summary>

| Source | Section | Official heading | Other title | Judgment |
|---|---|---|---|---|
| mapping | IPC 366B | Importation of girl from foreign country | Kidnapping, abducting or inducing woman to compel her marriage, etc | meaning differs |
| mapping | IPC 376 | Punishment for rape | Punishment for rape on woman under twelve years of age | meaning differs |
| mapping | IPC 376 | Punishment for rape | Punishment for causing death or resulting in persistent vegetative state of victim | meaning differs |
| mapping | IPC 376 | Punishment for rape | Sexual intercourse by husband upon his wife during separation | meaning differs |
| mapping | IPC 376 | Punishment for rape | Sexual intercourse by a person in authority | meaning differs |
| mapping | IPC 376 | Punishment for rape | Gang rape | meaning differs |
| mapping | IPC 376 | Punishment for rape | Punishment for gang rape on woman under sixteen years of age. 376DB. Punishment for gang rape on woman unde… | meaning differs |
| mapping | IPC 376 | Punishment for rape | Punishment for repeat offenders | meaning differs |
| catalog | BNSS 187 | Procedure when investigation cannot be completed in twenty-four hours | Default bail context | describes use, not subject |
| catalog | BNSS 35 | When police may arrest without warrant | Arrest safeguards | describes use, not subject |
| catalog | BNS 3(5) | General explanations | Common intention | sub-section specific |
| catalog | BNSS 173(4) | Information in cognizable cases | Information to Superintendent of Police | sub-section specific |
| catalog | BNSS 187(3) | Procedure when investigation cannot be completed in twenty-four hours | Investigation not completed within twenty-four hours | sub-section specific |
| mapping | BNS 118 | Voluntarily causing hurt or grievous hurt by dangerous weapons or means | Voluntarily causing hurt or grievous hurt by dangerous weapons or means. 118(1) | wording only |
| mapping | BNS 119 | Voluntarily causing hurt or grievous hurt to extort property, or to constrain to an illegal act | Voluntarily causing hurt or grievous hurt to extort property, or to constrain to an illegal act. 119(1) | wording only |
| mapping | BNS 120 | Voluntarily causing hurt or grievous hurt to extort confession, or to compel restoration of property | Voluntarily causing hurt or grievous hurt to extort confession, or to compel restoration of property. 120(1) | wording only |
| mapping | BNS 121 | Voluntarily causing hurt or grievous hurt to deter public servant from his duty | Voluntarily causing hurt or grievous hurt to deter public servant from his duty. 121(1) | wording only |
| mapping | BNS 122 | Voluntarily causing hurt or grievous hurt on provocation | Voluntarily causing hurt or grievous hurt on provocation. 122(1) | wording only |
| mapping | BNS 124 | Voluntarily causing grievous hurt by use of acid, etc | Voluntarily causing grievous hurt by use of acid, etc. 124(1) | wording only |
| mapping | BNS 140 | Kidnapping or abducting in order to murder or for ransom, etc | Kidnapping or abducting in order to murder or for ransom etc. 140(1) | wording only |
| mapping | BNS 268 | Personation of assessor | Personation of an assessor | wording only |
| mapping | BNS 318 | Cheating | Cheating. 318 (1) | wording only |
| mapping | BNS 324 | Mischief | Mischief. 324 (1) | wording only |
| mapping | BNS 326 | Mischief by injury, inundation, fire or explosive substance, etc | Mischief by injury, inundation, fire or explosive substance, etc. 326 (a) | wording only |
| mapping | BNS 327 | Mischief with intent to destroy or make unsafe a rail, aircraft, decked vessel or one of twenty tons burden | Mischief with intent to destroy or make unsafe a rail, aircraft, decked vessel or one of twenty tons burden… | wording only |
| mapping | BNS 330 | House-trespass and hous-ebreaking | House-trespass and house-breaking. 330(1) | wording only |
| mapping | BNS 331 | Punishment for house-trespass or house-breaking | Punishment for house-trespass or house-breaking. 331 (1) | wording only |
| mapping | BNS 332 | House-trespass in order to commit offence | House-trespass in order to commit offence. 332 (a) | wording only |
| mapping | BNS 336 | Forgery | Forgery 336 (1) | wording only |
| mapping | BNS 340 | Forged document or electronic record and using it as genuine | Forged document or electronic record and using it as genuine. 340 (1) | wording only |
| mapping | BNS 341 | Making or possessing counterfeit seal, etc., with intent to commit forgery punishable under section 338 | Making or possessing counterfeit seal, etc., with intent to commit forgery punishable under section 338. 34… | wording only |
| mapping | BNS 342 | Counterfeiting device or mark used for authenticating documents described in section 338, or possessing counterfeit marked material | Counterfeiting device or mark used for authenticating documents described in section 338, or possessing cou… | wording only |
| mapping | BNS 347 | Counterfeiting a property mark | Counterfeiting a property mark. 347 (1) | wording only |
| mapping | BNS 350 | Making a false mark upon any receptacle containing goods | Making a false mark upon any receptacle containing goods. 350 (1) | wording only |
| mapping | BNS 351 | Criminal intimidation | Criminal intimidation. 351 (1) | wording only |
| mapping | BNS 65 | Punishment for rape in certain cases | Punishment for rape in certain cases. 65(1) | wording only |
| mapping | BNS 70 | Gang rape | Gang rape. 70(1) | wording only |
| mapping | BNS 82 | Marrying again during lifetime of husband or wife | Marrying again during lifetime of husband or wife. 82(1) | wording only |
| mapping | BNS 93 | Exposure and abandonment of child under twelve years of age, by parent or person having care of it | Exposure and abandonment of child under twelve years, by parent or person having care of it | wording only |
| catalog | BNS 103 | Punishment for murder | Murder | wording only |
| catalog | BNS 115 | Voluntarily causing hurt | Voluntarily causing hurt or grievous hurt | wording only |
| catalog | BNS 64 | Punishment for rape | Rape | wording only |
| catalog | BNS 85 | Husband or relative of husband of a woman subjecting her to cruelty | Cruelty by husband or relatives | wording only |
| catalog | BNSS 482 | Direction for grant of bail to person apprehending arrest | Anticipatory bail | wording only |
| catalog | BNSS 483 | Special powers of High Court or Court of Session regarding bail | Bail by High Court or Court of Session | wording only |
| catalog | BNSS 528 | Saving of inherent powers of High Court | Inherent powers of High Court | wording only |
| catalog | IPC 120B | Punishment of criminal conspiracy | Criminal conspiracy | wording only |
| catalog | IPC 302 | Punishment for murder | Murder | wording only |
| catalog | IPC 304 | Punishment for culpable homicide not amounting to murder | Culpable homicide not amounting to murder | wording only |
| catalog | IPC 323 | Punishment for voluntarily causing hurt | Voluntarily causing hurt | wording only |
| catalog | IPC 325 | Punishment for voluntarily causing grievous hurt | Voluntarily causing grievous hurt | wording only |
| catalog | IPC 34 | Acts done by several persons in furtherance of common intention | Common intention | wording only |
| catalog | IPC 363 | Punishment for kidnapping | Kidnapping | wording only |
| catalog | IPC 376 | Punishment for rape | Rape | wording only |
| catalog | IPC 379 | Punishment for theft | Theft | wording only |
| catalog | IPC 380 | Theft in dwelling house, etc | Theft in dwelling house | wording only |
| catalog | IPC 392 | Punishment for robbery | Robbery | wording only |
| catalog | IPC 406 | Punishment for criminal breach of trust | Criminal breach of trust | wording only |
| catalog | IPC 498A | Husband or relative of husband of a woman subjecting her to cruelty | Cruelty by husband or relatives | wording only |
| mapping | BNS 117(2) | Voluntarily causing grievous hurt | Whoever, except in the case provided for by sub-section | not a title |
| mapping | BNS 118(1) | Voluntarily causing hurt or grievous hurt by dangerous weapons or means | Whoever, except in the case provided for by sub-section | not a title |
| mapping | BNS 119(1) | Voluntarily causing hurt or grievous hurt to extort property, or to constrain to an illegal act | Whoever voluntarily causes hurt for the purpose of extorting from the sufferer, or from any person interest… | not a title |
| mapping | BNS 119(2) | Voluntarily causing hurt or grievous hurt to extort property, or to constrain to an illegal act | Whoever voluntarily causes grievous hurt for any purpose referred to in sub-section (1), shall be punished … | not a title |
| mapping | BNS 120(1) | Voluntarily causing hurt or grievous hurt to extort confession, or to compel restoration of property | Whoever voluntarily causes hurt for the purpose of extorting from the sufferer or from any person intereste… | not a title |
| mapping | BNS 120(2) | Voluntarily causing hurt or grievous hurt to extort confession, or to compel restoration of property | Whoever voluntarily causes grievous hurt for any purpose referred to in sub-section (1), shall be punished … | not a title |
| mapping | BNS 121(1) | Voluntarily causing hurt or grievous hurt to deter public servant from his duty | Whoever voluntarily causes hurt to any person being a public servant in the discharge of his duty as such p… | not a title |
| mapping | BNS 122(1) | Voluntarily causing hurt or grievous hurt on provocation | Whoever voluntarily causes hurt on grave and sudden provocation, if he neither intends nor knows himself to… | not a title |
| mapping | BNS 122(2) | Voluntarily causing hurt or grievous hurt on provocation | Whoever voluntarily causes grievous hurt on grave and sudden provocation, if he neither intends nor knows h… | not a title |
| mapping | BNS 124(1) | Voluntarily causing grievous hurt by use of acid, etc | Whoever causes permanent or partial damage or deformity to, or burns or maims or disfigures or disables, an… | not a title |
| mapping | BNS 124(2) | Voluntarily causing grievous hurt by use of acid, etc | Whoever throws or attempts to throw acid on any person or attempts to administer acid to any person, or att… | not a title |
| mapping | BNS 125(a) | Act endangering life or personal safety of others | where hurt is caused, shall be punished with imprisonment of either description for a term which may extend… | not a title |
| mapping | BNS 125(b) | Act endangering life or personal safety of others | where grievous hurt is caused, shall be punished with imprisonment of either description for a term which m… | not a title |
| mapping | BNS 126(2) | Wrongful restraint | Whoever wrongfully restrains any person shall be punished with simple imprisonment for a term which may ext… | not a title |
| mapping | BNS 127(2) | Wrongful confinement | Whoever wrongfully confines any person shall be punished with imprisonment of either description for a term… | not a title |
| mapping | BNS 127(3) | Wrongful confinement | Whoever wrongfully confines any person for three days, or more, shall be punished with imprisonment of eith… | not a title |
| mapping | BNS 127(4) | Wrongful confinement | Whoever wrongfully confines any person for ten days or more, shall be punished with imprisonment of either … | not a title |
| mapping | BNS 127(5) | Wrongful confinement | Whoever keeps any person in wrongful confinement, knowing that a writ for the liberation of that person has… | not a title |
| mapping | BNS 127(6) | Wrongful confinement | Whoever wrongfully confines any person in such manner as to indicate an intention that the confinement of s… | not a title |
| mapping | BNS 127(7) | Wrongful confinement | Whoever wrongfully confines any person for the purpose of extorting from the person confined, or from any p… | not a title |
| mapping | BNS 127(8) | Wrongful confinement | Whoever wrongfully confines any person for the purpose of extorting from the person confined or any person … | not a title |
| mapping | BNS 137(2) | Kidnapping | Whoever kidnaps any person from India or from lawful guardianship shall be punished with imprisonment of ei… | not a title |
| mapping | BNS 140(1) | Kidnapping or abducting in order to murder or for ransom, etc | Whoever kidnaps or abducts any person in order that such person may be murdered or may be so disposed of as… | not a title |
| mapping | BNS 140(2) | Kidnapping or abducting in order to murder or for ransom, etc | Whoever kidnaps or abducts any person or keeps a person in detention after such kidnapping or abduction, an… | not a title |
| mapping | BNS 140(3) | Kidnapping or abducting in order to murder or for ransom, etc | Whoever kidnaps or abducts any person with intent to cause that person to be secretly and wrongfully confin… | not a title |
| mapping | BNS 140(4) | Kidnapping or abducting in order to murder or for ransom, etc | Whoever kidnaps or abducts any person in order that such person may be subjected, or may be so disposed of … | not a title |
| mapping | BNS 178(2) | Counterfeiting coin, Government stamps, currency-notes or bank-notes | “coin” shall have the same meaning as assigned to it in section 2 of the Coinage Act, 2011 and includes met… | not a title |
| mapping | BNS 178(5) | Counterfeiting coin, Government stamps, currency-notes or bank-notes | the offence of “counterfeiting coin” includes diminishing the weight or alteration of the composition, or a… | not a title |
| mapping | BNS 189(2) | Unlawful assembly | Whoever, being aware of facts which render any assembly an unlawful assembly, intentionally joins that asse… | not a title |
| mapping | BNS 189(3) | Unlawful assembly | Whoever joins or continues in an unlawful assembly, knowing that such unlawful assembly has been commanded … | not a title |
| mapping | BNS 189(4) | Unlawful assembly | Whoever, being armed with any deadly weapon, or with anything which, used as a weapon of offence, is likely… | not a title |
| mapping | BNS 189(5) | Unlawful assembly | Whoever knowingly joins or continues in any assembly of five or more persons likely to cause a disturbance … | not a title |
| mapping | BNS 189(6) | Unlawful assembly | Whoever hires or engages, or employs, or promotes, or connives at the hiring, engagement or employment of a… | not a title |
| mapping | BNS 191(2) | Rioting | Whoever is guilty of rioting, shall be punished with imprisonment of either description for a term which ma… | not a title |
| mapping | BNS 191(3) | Rioting | Whoever is guilty of rioting, being armed with a deadly weapon or with anything which, used as a weapon of … | not a title |
| mapping | BNS 194(2) | Affray | Whoever commits an affray, shall be punished with imprisonment of either description for a term which may e… | not a title |
| mapping | BNS 260 | Intentional omission to apprehend on part of public servant bound to apprehend person under sentence or lawfully committed | Intentional omission to apprehend on the part of public servant bound to apprehend person under sentence or… | not a title |
| mapping | BNS 318(1) | Cheating | Whoever, by deceiving any person, fraudulently or dishonestly induces the person so deceived to deliver any… | not a title |
| mapping | BNS 318(2) | Cheating | Whoever cheats shall be punished with imprisonment of either description for a term which may extend to thr… | not a title |
| mapping | BNS 318(3) | Cheating | Whoever cheats with the knowledge that he is likely thereby to cause wrongful loss to a person whose intere… | not a title |
| mapping | BNS 318(4) | Cheating | Whoever cheats and thereby dishonestly induces the person deceived to deliver any property to any person, o… | not a title |
| mapping | BNS 319(1) | Cheating by personation | A person is said to cheat by personation if he cheats by pretending to be some other person, or by knowingl… | not a title |
| mapping | BNS 319(2) | Cheating by personation | Whoever cheats by personation shall be punished with imprisonment of either description for a term which ma… | not a title |
| mapping | BNS 324(1) | Mischief | Whoever with intent to cause, or knowing that he is likely to cause, wrongful loss or damage to the public … | not a title |
| mapping | BNS 324(2) | Mischief | Whoever commits mischief shall be punished with imprisonment of either description for a term which may ext… | not a title |
| mapping | BNS 324(6) | Mischief | Whoever commits mischief, having made preparation for causing to any person death, or hurt, or wrongful res… | not a title |
| mapping | BNS 326(a) | Mischief by injury, inundation, fire or explosive substance, etc | doing any act which causes, or which he knows to be likely to cause, a diminution of the supply of water fo… | not a title |
| mapping | BNS 326(b) | Mischief by injury, inundation, fire or explosive substance, etc | doing any act which renders or which he knows to be likely to render any public road, bridge, navigable riv… | not a title |
| mapping | BNS 326(c) | Mischief by injury, inundation, fire or explosive substance, etc | doing any act which causes or which he knows to be likely to cause an inundation or an obstruction to any p… | not a title |
| mapping | BNS 326(d) | Mischief by injury, inundation, fire or explosive substance, etc | destroying or moving any sign or signal used for navigation of rail, aircraft or ship or other thing placed… | not a title |
| mapping | BNS 326(e) | Mischief by injury, inundation, fire or explosive substance, etc | destroying or moving any land-mark fixed by the authority of a public servant, or by any act which renders … | not a title |
| mapping | BNS 326(f) | Mischief by injury, inundation, fire or explosive substance, etc | fire or any explosive substance intending to cause, or knowing it to be likely that he will thereby cause, … | not a title |
| mapping | BNS 326(g) | Mischief by injury, inundation, fire or explosive substance, etc | fire or any explosive substance, intending to cause, or knowing it to be likely that he will thereby cause,… | not a title |
| mapping | BNS 327(1) | Mischief with intent to destroy or make unsafe a rail, aircraft, decked vessel or one of twenty tons burden | Whoever commits mischief to any rail, aircraft, or a decked vessel or any vessel of a burden of twenty tons… | not a title |
| mapping | BNS 327(2) | Mischief with intent to destroy or make unsafe a rail, aircraft, decked vessel or one of twenty tons burden | Whoever commits, or attempts to commit, by fire or any explosive substance, such mischief as is described i… | not a title |
| mapping | BNS 329(2) | Criminal trespass and house-trespass | Whoever commits criminal trespass by entering into or remaining in any building, tent or vessel used as a h… | not a title |
| mapping | BNS 329(3) | Criminal trespass and house-trespass | Whoever commits criminal trespass shall be punished with imprisonment of either description for a term whic… | not a title |
| mapping | BNS 329(4) | Criminal trespass and house-trespass | Whoever commits house-trespass shall be punished with imprisonment of either description for a term which m… | not a title |
| mapping | BNS 330(1) | House-trespass and hous-ebreaking | Whoever commits house-trespass having taken precautions to conceal such house-trespass from some person who… | not a title |
| mapping | BNS 331(1) | Punishment for house-trespass or house-breaking | Whoever commits lurking house-trespass or house-breaking, shall be punished with imprisonment of either des… | not a title |
| mapping | BNS 331(2) | Punishment for house-trespass or house-breaking | Whoever commits lurking house-trespass or house-breaking after sunset and before sunrise, shall be punished… | not a title |
| mapping | BNS 331(5) | Punishment for house-trespass or house-breaking | Whoever commits lurking house-trespass, or house-breaking, having made preparation for causing hurt to any … | not a title |
| mapping | BNS 331(6) | Punishment for house-trespass or house-breaking | Whoever commits lurking house-trespass or house-breaking after sunset and before sunrise, having made prepa… | not a title |
| mapping | BNS 331(7) | Punishment for house-trespass or house-breaking | Whoever, whilst committing lurking house-trespass or house-breaking, causes grievous hurt to any person or … | not a title |
| mapping | BNS 331(8) | Punishment for house-trespass or house-breaking | If, at the time of the committing of lurking house-trespass or house-breaking after sunset and before sunri… | not a title |
| mapping | BNS 332(a) | House-trespass in order to commit offence | punishable with death, shall be punished with imprisonment for life, or with rigorous imprisonment for a te… | not a title |
| mapping | BNS 334(2) | Dishonestly breaking open receptacle containing property | Whoever, being entrusted with any closed receptacle which contains or which he believes to contain property… | not a title |
| mapping | BNS 336(2) | Forgery | Whoever commits forgery shall be punished with imprisonment of either description for a term which may exte… | not a title |
| mapping | BNS 336(3) | Forgery | Whoever commits forgery, intending that the document or electronic record forged shall be used for the purp… | not a title |
| mapping | BNS 336(4) | Forgery | Whoever commits forgery, intending that the document or electronic record forged shall harm the reputation … | not a title |
| mapping | BNS 340(1) | Forged document or electronic record and using it as genuine | A false document or electronic record made wholly or in part by forgery is designated a forged document or … | not a title |
| mapping | BNS 340(2) | Forged document or electronic record and using it as genuine | Whoever fraudulently or dishonestly uses as genuine any document or electronic record which he knows or has… | not a title |
| mapping | BNS 341(1) | Making or possessing counterfeit seal, etc., with intent to commit forgery punishable under section 338 | Whoever makes or counterfeits any seal, plate or other instrument for making an impression, intending that … | not a title |
| mapping | BNS 341(2) | Making or possessing counterfeit seal, etc., with intent to commit forgery punishable under section 338 | Whoever makes or counterfeits any seal, plate or other instrument for making an impression, intending that … | not a title |
| mapping | BNS 342(1) | Counterfeiting device or mark used for authenticating documents described in section 338, or possessing counterfeit marked material | Whoever counterfeits upon, or in the substance of, any material, any device or mark used for the purpose of… | not a title |
| mapping | BNS 342(2) | Counterfeiting device or mark used for authenticating documents described in section 338, or possessing counterfeit marked material | Whoever counterfeits upon, or in the substance of, any material, any device or mark used for the purpose of… | not a title |
| mapping | BNS 345(3) | Property mark | Whoever uses any false property mark shall, unless he proves that he acted without intent to defraud, be pu… | not a title |
| mapping | BNS 347(1) | Counterfeiting a property mark | Whoever counterfeits any property mark used by any other person shall be punished with imprisonment of eith… | not a title |
| mapping | BNS 347(2) | Counterfeiting a property mark | Whoever counterfeits any property mark used by a public servant, or any mark used by a public servant to de… | not a title |
| mapping | BNS 350(1) | Making a false mark upon any receptacle containing goods | Whoever makes any false mark upon any case, package or other receptacle containing goods, in a manner reaso… | not a title |
| mapping | BNS 350(2) | Making a false mark upon any receptacle containing goods | Whoever makes use of any false mark in any manner prohibited under sub-section | not a title |
| mapping | BNS 351(1) | Criminal intimidation | Whoever threatens another by any means, with any injury to his person, reputation or property, or to the pe… | not a title |
| mapping | BNS 351(2) | Criminal intimidation | Whoever commits the offence of criminal intimidation shall be punished with imprisonment of either descript… | not a title |
| mapping | BNS 351(3) | Criminal intimidation | Whoever commits the offence of criminal intimidation by threatening to cause death or grievous hurt, or to … | not a title |
| mapping | BNS 65(1) | Punishment for rape in certain cases | Whoever, commits rape on a woman under sixteen years of age shall be punished with rigorous imprisonment fo… | not a title |
| mapping | BNS 65(2) | Punishment for rape in certain cases | Whoever, commits rape on a woman under twelve years of age shall be punished with rigorous imprisonment for… | not a title |
| mapping | BNS 70(1) | Gang rape | Where a woman is raped by one or more persons constituting a group or acting in furtherance of a common int… | not a title |
| mapping | BNS 70(2) | Gang rape | Where a woman under eighteen years of age is raped by one or more persons constituting a group or acting in… | not a title |
| mapping | BNS 82(1) | Marrying again during lifetime of husband or wife | Whoever, having a husband or wife living, marries in any case in which such marriage is void by reason of i… | not a title |
| mapping | BNS 82(2) | Marrying again during lifetime of husband or wife | Whoever commits the offence under sub-section | not a title |
| mapping | IPC 376 | Punishment for rape | 376(3) | not a title |
| mapping | IPC 498A | Husband or relative of husband of a woman subjecting her to cruelty | Explanation | not a title |

</details>

## Step 26c: document-evidence statute correction (frozen 2026-11-13, before any test) — UNREVIEWED

**Rule** (`section_labels.document_evidence`; frozen here before it was implemented or tested):

1. **Scope.** Professional answers with an uploaded document (`/query/professional/pdf`, brief and question mode).
   Text queries and public answers are never touched.
2. **When it is considered.** A section the answer names as statute S, number n, with S in a sister pair (BNS/BNSS,
   IPC/CrPC, Evidence Act/BSA), whose step 25-26b resolution is **neither** `corrected_statute` **nor** flagged
   `model_label_differs`: that is, the answer gave no label, a label with no content words, or a label that agrees with
   S's trusted entries.
3. **Document citations.** The uploaded document's own text (every private chunk) is read with the project's existing
   extractor (`judgment_sections.prepare_judgment_text` + `query_analysis.extract_sections`), which attaches a section
   to the statute written next to it, by full name ("Section 173 of the Bharatiya Nagarik Suraksha Sanhita, 2023") or
   standard abbreviation (BNS, BNSS, IPC, CrPC, Cr.P.C., Evidence Act); the Bharatiya Sakshya Adhiniyam / BSA, which the
   extractor does not know, is read with the resolver's BSA pattern ("Section N BSA", "BSA Section N", "Section N of the
   Bharatiya Sakshya Adhiniyam"). Before that, a full Act name followed by an abbreviation in parentheses has the
   abbreviation removed: **the full name outranks the abbreviation** ("Bharatiya Nagarik Suraksha Sanhita (BNS)" counts
   as BNSS). Numbers are compared on the section (sub-sections included: "173(2)" is a citation of 173).
4. **Correction.** If the document cites n under the sister statute S' **and never cites n under S**, the reference
   becomes `corrected_statute` to S' with `correction_reason = "document_evidence"`, `document_evidence_id` = the first
   private chunk (P#) that cites S' n, S' n's trusted title when it has exactly one (the official heading first), and
   the answer's `model_label` kept.
5. **No change** when the document cites n under both statutes, or under neither, or when step 2 does not hold.
   Label-based corrections (step 26b) get `correction_reason = "label"`.

**Test plan, before any live call.** Every saved brief or private-PDF output of steps 22-26b (step 22 B1-B5, the five
brief fixtures; step 25 charge sheet and FIR; step 26 FIR; step 26b charge sheet and FIR), each with the document it was
run on (the fixture, rendered and parsed as an upload), and a fixture probe (every section each fixture cites, named
once under its own statute and once under the sister statute, with no label). Each named section is judged by hand
*before* the rule is run: the statute the answer meant. Outcomes: correct correction, wrong correction, no-op. **Wrong
corrections must be 0**, or no live call is made.

## Step 26b: label checks, sub-section titles, flagged mapping rows (2026-11-13) — UNREVIEWED

**The model's label is always kept** in `label.model_label`, for audit; it is never shown as a trusted title.

**Wrong-statute rule** (`section_labels.label_matches_section`), defined before it was tested:
- *"Clearly does not match"*: the label shares no content word (the `agrees` rule: stop words and generic legal words
  ignored, words compared on their stem) with **any** trusted entry of the named statute's section with that number:
  the official heading, every catalog title, description, alias and concept, and every mapping description
  (sub-section entries included). Using every trusted description, not only the official heading, keeps synonyms
  that the catalog records (BNSS 173(4): "refusal to register fir", concept `fir_registration`) from counting as a
  mismatch.
- If it clearly does not match **and** the same number in the sister statute matches the label, the state is
  `corrected_statute`: the sister statute, its trusted title (the official heading when there is one), and a note with
  the reason. Sister statutes: BNS/BNSS, IPC/CrPC, Evidence Act/BSA.
- If it clearly does not match and no sister statute matches, the trusted title is shown with
  `label.model_label_differs = true` and a note ("the answer's own label differs").

**Confusion table** on the 27 saved step 22-24 mismatches (`backend/scripts/tests/fixtures/wrong_statute_cases.json`,
judged by hand before the rule was run; the BNS 173 "registration of FIR" case is one of them):

| Hand judgment \ rule outcome | keep (verified) | corrected statute | flag "label differs" |
|---|---:|---:|---:|
| label correct for the named section (11) | 5 | 0 | 6 |
| wrong statute, sister statute fits (5) | 0 | **5** | 0 |
| wrong label, no sister fits (11) | 0 | 0 | **11** |

21 of 27 agree. Every wrong statute is corrected (BNSS 103 "murder" -> BNS 103; IPC 482 -> CrPC 482; BNS 173
"registration of FIR" -> BNSS 173; BNS 528 -> BNSS 528; BNS 531(2)(a) -> BNSS 531), every wrong label is flagged, and
no label is corrected wrongly. The 6 disagreements are correct labels written as synonyms or uses ("challenge to
investigation" for BNSS 528, "dishonest dealing" for IPC 406, "deemed custody" for Evidence Act 27); they are flagged
although right, and the trusted title is still what is shown.

**Limit seen live (step 26b).** The rule needs a label. In the live FIR brief the answer wrote "Section 173 BNS" with
no label of its own (its summary calls the Act "the Bharatiya Nagarik Suraksha Sanhita (BNS)"), so BNS 173 was shown
with its own heading, "Punishment for bribery", and not corrected.

**Exact sub-section titles.** When the catalog has a title for the exact sub-section, it is the primary title and the
section's official heading is shown alongside (`label.section_heading`, `section_heading_source`,
`section_heading_key`): `Section 3(5) BNS — Common intention (sub-section, catalog); General explanations (section
heading, official)`; `Section 173(4) BNSS — Information to Superintendent of Police (sub-section, catalog);
Information in cognizable cases (section heading, official)`. Otherwise the official section heading stays primary.

**Flagged mapping rows.** The CYTRAIN mapping rows whose description differs in meaning from the official heading are
listed in `data/structured/statute_headings/mapping_conflicts.csv` (generated with `section_label_coverage.py
--crosscheck ... --mapping-conflicts ...`): 9 rows, IPC 366B (BNS 87) and eight IPC 376 rows (BNS 65(2), 66, 67, 68,
70, 70(1), 70(2), 71) carrying the headings of sections 376A-376E. The source descriptions are not edited and no
migration was needed. The IPC-BNS analytics endpoint and tab show each row's official IPC and BNS heading where one
exists (a sub-section takes its section's) and keep the source description underneath, marked "Conflicts with the
official heading" for the flagged rows. On the dev data: 438 rows, 9 flagged, an official BNS heading on 435 and an
official IPC heading on 50 (most IPC keys are group labels such as "415 to 420, 424", which have no single heading).

**CrPC retry**: still no official headings (`data/structured/statute_headings/SOURCES.md`), so coverage is unchanged
from step 26: 214 of 370 cited sections.

## Coverage of the trusted sources before step 26 (2026-11-08)

- **Catalog:** 62 entries (IPC 20, BNS 15, BNSS 8, CrPC 7, NDPS Act 6, POCSO Act 3, SC/ST Act 3), every one with a
  canonical name.
- **Mapping:** all 438 rows have IPC and BNS descriptions. Used as titles: 316 keys from the 370 CYTRAIN rows (BNS
  284, IPC 32). 325 CYTRAIN rows are keyed by IPC group labels. Two IPC keys have several different descriptions
  (IPC 376: 9; IPC 498A: 2), so they would be conflicts, but the catalog has both.
- **Corpus-cited sections** (`document_sections`, 920 rows, 370 distinct statute + section): 57 distinct sections
  have a trusted title (catalog 40, mapping 17) and 313 do not. By rows, 280 of 920 (catalog 236, mapping 44).

| Statute | Distinct cited | With a trusted title |
|---|---:|---:|
| IPC | 173 | 26 |
| CrPC | 105 | 5 |
| NDPS Act | 32 | 5 |
| BNS | 16 | 13 |
| POCSO Act | 17 | 3 |
| Evidence Act | 13 | 0 |
| BNSS | 12 | 5 |
| SC/ST Act | 2 | 0 |

The gaps are mostly CrPC procedure, the Evidence Act and most IPC sections outside the catalog: for those, answers
show the model's label marked unverified.

## Model labels in saved outputs (step 22-24, before the resolver; step 25 counts)

Saved responses and answers outside the repository (step 22 live runs, the step 24 evaluation including superseded
records; no provider calls): 287 provision strings, which resolve to 123 verified, 5 corrected-statute and 172
unverified sections. **Rule:** a provision is checkable when it names one section, carries a model label, and has a
trusted title or a statute correction; it is a mismatch when the statute was corrected or the label shares no
content word with the trusted entry.

- **96 checkable, 16 mismatches** (step 22: 8, step 24: 8).
- **5 wrong statutes:** BNSS 103 "murder" (BNS 103), IPC 482 "inherent powers" (CrPC 482), BNS 173 "registration of
  FIR" (BNSS 173), BNS 528 "power to quash FIRs" (BNSS 528), BNS 531(2)(a) "saving clause" (BNSS 531).
- **11 label disagreements;** by hand, 5 are wrong labels (BNS 309(4) "suicide attempts", BNS 115(2) "false
  statements", BNS 173 "investigation report filing", NDPS 21 "procedural safeguards for search and seizure", IPC
  354B "obscene material") and 6 describe the section's use rather than its subject ("challenge to charge-sheet" for
  BNSS 528). In every case the trusted title is what is now shown.

## Limits

- Titles are only as good as their sources, and all are **UNREVIEWED** for legal review. The official headings are
  the Acts' own marginal notes, extracted and spot-checked (70/70) but not reviewed by a lawyer; CrPC has none. Some mapping
  descriptions are statute text rather than titles ("Whoever cheats shall be punished…"), and the catalog's BNS 115
  title is "Voluntarily causing hurt or grievous hurt" for the whole section.
- Coverage is 214 of 370 cited sections (57 before step 26); CrPC (105 cited sections, 5 titled), NDPS, POCSO and
  SC/ST Act sections mostly stay unverified.
- A wrong statute is corrected only when the model's label agrees with the other statute's entry. A label-less or
  differently worded "Section 173 BNS" shows BNS 173's heading ("Punishment for bribery"), which is the true heading of
  the section cited, not of the section the answer may have meant (seen live in step 26).
- The statute correction covers only the BNS/BNSS and IPC/CrPC pairs, and only when the other statute's entry agrees
  with the label. A wrong section number in the right statute is shown with the trusted title of the number cited.
- Section names inside free text are not resolved.
- Tests: `backend/scripts/tests/test_section_labels.py`; frontend `components/SectionLabelText.test.tsx` and
  `app/public/response-adapter.labels.test.tsx`.
