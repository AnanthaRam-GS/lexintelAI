# Official section headings: sources (step 26) — UNREVIEWED

Section numbers and their headings (marginal notes) for the Acts below, used by the section-label resolver as its
first trust source (`backend/app/services/section_labels.py`, `docs/SECTION_LABELS.md`). Built by
`backend/scripts/build_statute_headings.py` (`--fetch` downloads, the rest extracts and validates). **UNREVIEWED:**
not checked by a lawyer; the spot checks below are the assistant's.

## Source

**India Code**, the official legislative repository. **`https://indiacode.gov.in` is accepted as India Code's official
address** (project owner's decision, step 26b, 2026-11-13). On 2026-11-12 `https://www.indiacode.nic.in/` returned a
"Site Migration" page saying the website "has been migrated from https://www.indiacode.nic.in to
https://indiacode.gov.in" and redirecting there (page saved during the run, sha256
`3b64e50fd9a02485b2f452c4090c7ef025bf565e4340256a83cb387b7103318c`); the old site's Act pages timed out (HTTP 504
from its CDN). Everything here comes from **https://indiacode.gov.in** (HTTPS), through its public DSpace REST API
(`https://indiacode.gov.in/server/api`). No other site was used, and no heading was typed in by hand.

Retrieved **2026-11-12T16:49:24Z**.

| Act | India Code record | File or records used | sha256 of what was used | Sections in the CSV |
|---|---|---|---|---|
| Indian Penal Code, 1860 (Act 45 of 1860; repealed by Act 45 of 2023) | [123456789/488475](https://indiacode.gov.in/handle/123456789/488475) | `A1860-45.pdf` (bitstream `337c7a03-…`), 1,155,037 bytes | `fa8878e0208e0942e51bcf7e437efa7b6d25baecb04f4cd83da30df44c977f85` | 569 rows: 548 headings, 21 omitted/repealed, 60 lettered |
| Indian Evidence Act, 1872 (Act 1 of 1872; repealed by Act 47 of 2023) | [123456789/488783](https://indiacode.gov.in/handle/123456789/488783) | `A1872-1.pdf` (bitstream `4a3677bf-…`), 822,186 bytes | `06729a1f84e186ae953798766696a736c344dcbd94da2b0cc2a474e7859378ce` | 182 rows: 181 headings, 1 repealed, 18 lettered |
| Code of Criminal Procedure, 1973 (Act 2 of 1974; repealed by Act 46 of 2023) | [123456789/620185](https://indiacode.gov.in/handle/123456789/620185) | `1974-2.pdf` (bitstream `f40e830f-…`), 9,176,717 bytes | `865cc3e1989536882c97d58cd16581e3409745ad53e6f359853bf7472709194b` | **none: skipped** (below) |
| Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023) | [123456789/496548](https://indiacode.gov.in/handle/123456789/496548) | 358 section records (act id `AC_CEN_5_23_00048_2023-45_1719292564123`); `a2023-45.pdf` for spot checks | records `d7a3386e2ecf56b90516fa623387710d61ee1a917dbdaf7dab7c444a03f92cc5`; PDF `d4449e9995b21fd52627811d08f9d21feda6a3678b7e5355b651242d152167f5` | 358 headings |
| Bharatiya Nagarik Suraksha Sanhita, 2023 (Act 46 of 2023) | [123456789/496550](https://indiacode.gov.in/handle/123456789/496550) | 531 section records (act id `AC_CEN_5_23_00049_202346_1719552320687`); `A2023-46.pdf` (English) for spot checks | records `dfe36f5193e3afeab22b5e378117b8000e33b809c6d1c125e4c40fda0b22fcbe`; PDF `572c79880b9f8effc8fa6e39b864101835a0fb5d85b194b90a99d170121a0562` | 531 headings |
| Bharatiya Sakshya Adhiniyam, 2023 (Act 47 of 2023) | [123456789/496549](https://indiacode.gov.in/handle/123456789/496549) | 170 section records (act id `AC_CEN_5_23_00049_2023-47_1719292804654`); `a2023-47.pdf` for spot checks | records `fcc869fcea93bed02f195f577edd4cecfc7083987c8cd35bee90b3231adbb69b`; PDF `554b2b4ae3d9f09bf31e6e1ba2b2cb8a4e7f4f5ffd6f3156736752cbbce116d5` | 170 headings |

Download URLs are `https://indiacode.gov.in/server/api/core/bitstreams/<bitstream uuid>/content`; the full uuids, the
search queries for the section records and the CSV hashes are in `validation.json` (`acts.<Act>.source`). The PDFs and
section texts are **not** committed; only section numbers and headings are.

**Served files differ from the stored checksum.** For every PDF, India Code's own record gives a smaller size and an
MD5 that does not match the file it serves (IPC: recorded 1,104,850 bytes, MD5 `20aa1bf6…`; served 1,155,037 bytes,
MD5 `eb0c3877…`). The served pages carry an "IndiaCode" watermark, which fits the site adding it on download. Each file
was downloaded twice: the text was identical both times; the bytes were identical for every file used here.

## How each Act was read

- **BNS, BNSS, BSA: section records.** India Code publishes each section as a record whose title is the section's
  heading. The heading is used as published (surrounding spaces and the final full stop removed). The counts match the
  Acts: 358, 531 and 170 sections, every number present once, none repealed.
- **IPC, Evidence Act: the Act's PDF, two independent readings.** The *arrangement of sections* (the Act's printed
  list) and the *section heads in the body* ("120B. Punishment of criminal conspiracy.—"). A heading is the body's
  section head, with amendment-footnote markers removed ("2[electronic signature]"), and it is kept only when the
  arrangement corroborates it (`basis` in the CSV):

  | basis | IPC | Evidence Act |
  |---|---:|---:|
  | `pdf_exact` (same text) | 481 | 163 |
  | `pdf_arrangement_adds_notes` (the arrangement adds the sub-notes it lists, e.g. "Provisos.") | 45 | 10 |
  | `pdf_minor_spelling` (similarity >= 0.85; the body's own text is kept) | 22 | 6 |
  | `pdf_exact_after_footnote_marker` ("1145." printed for "1[145.") | 0 | 2 |
  | `pdf_arrangement_marker` ("[Omitted.]" / "[Repealed.]": no heading, `status` omitted/repealed) | 21 | 1 |

- **Left out (no guess), listed in `validation.json`:**
  - IPC 153: the arrangement reads "Want only giving provocation, with intent to cause riot— if rioting be
    committed—if not committed", the body "Wantonly giving provocation with intent to cause riot".
  - IPC 17, 174A, 376AB, 376DA, 376DB: in the arrangement, but no matching section head was read from the body.
  - Evidence Act 4 and 10: the body reading picked up footnote text.
  - Evidence Act 86: in the arrangement only.
  - IPC body heads with no arrangement entry (354E, 376F, 379A, 382C, 509A, 509B) are **State amendments** printed in
    the PDF's footnotes, not sections of the central Act, and are not included.
- **CrPC skipped.** India Code holds only `1974-2.pdf` for the CrPC, a scanned document whose text layer is noisy OCR
  ("tiie", "agair\.st sentence", "37'9."). Headings cannot be extracted reliably from it, so none are stored and CrPC
  sections keep their catalog/mapping titles or stay unverified.
- **CrPC retry (step 26b, 2026-11-13): still skipped.**
  1. *Legislative Department* (`https://www.legislative.gov.in`, HTTPS): the site is a client-rendered application
     whose Act listings load from a third-party content host (`cmsmsde.digifootprint.in`), not from a government
     domain; its sitemap lists another ministry's pages; the usual official file path
     (`/sites/default/files/A1974-02.pdf`) returns 404. No official CrPC text PDF could be fetched from it, and the
     third-party host was not used.
  2. *OCR of India Code's scan* with the project's Tesseract setup (`services/ocr.py`, 259 pages): the result cannot be
     made reliable, for three reasons. (a) The scan is the **Act as enacted in 1974**: sections inserted later (41A-41D,
     166A, 357A, 436A, Chapter XXIA plea bargaining, among others) are absent, so its headings are out of date for
     exactly the provisions most cited today. (b) Its headings are **marginal notes** in the page margin, hyphenated
     over short lines; the body has no heading of its own, so the "both readings agree" rule used for IPC and the
     Evidence Act cannot be applied. (c) The arrangement pages OCR column by column (numbers apart from headings,
     "31." for 311, "» 807." for 307) and several pages are blurred ("Code of Grininal Procedure").
  No spot check was made because no heading was extracted. CrPC sections keep their catalog titles (5) or stay
  unverified.

**Published typos are kept as published**, not corrected: e.g. IPC 312 "Causing miscarraige", IPC 209 "Dishonesty
making false claim in Court", IPC 328 "…with intent to commit and offence", IPC 452 "House-trespass alter preparation…",
Evidence Act 95 "…document unmeaning reference to existing facts" (the arrangement's wording differs; both are in the
`pdf_minor_spelling` list in `validation.json`), and BNS 330 "House-trespass and hous-ebreaking" (India Code's
section record).

## Validation

- **Structure:** no duplicate section numbers in any CSV; BNS 1-358, BNSS 1-531 and BSA 1-170 complete; IPC 1-511 all
  present except 17 and 153 (left out, above), plus 60 lettered sections; Evidence Act 1-167 all present except 4, 10
  and 86, plus 18 lettered sections.
- **Spot checks against the rendered source** (`spot_checks.json`): for each Act, 14 sections (10 fixed, lettered and
  frequently cited, e.g. IPC 120B, 304B, 498A, 376D; Evidence Act 65B, 113B, 145, 161; BNS 309, 115, 303; BNSS 173,
  482, 528; BSA 63, 23, 24; plus 4 drawn at random) were found in the Act's official PDF, the page region was rendered
  to an image and compared by eye with the CSV heading. **70 of 70 match** (14 per Act). For BNS, BNSS and BSA this also
  confirms that the section records agree with the Act's PDF.

## Reproduction basis

Accepted as recorded by the project owner (step 26b).

Section 52(1)(q) of the Copyright Act, 1957, as published on India Code
([123456789/515607](https://indiacode.gov.in/handle/123456789/515607)), reads in part: "the reproduction or publication
of— (i) any matter which has been published in any Official Gazette except an Act of a Legislature; (ii) any Act of a
Legislature subject to the condition that such Act is reproduced or published together with any commentary thereon or
any other original matter; …" (quoted as published). This repository stores only section numbers and section headings,
used inside LegalAI's own analysis, not the text of the Acts; the downloaded PDFs are not committed. No conclusion on
how the provision applies is drawn here.

## Files

- `ipc.csv`, `evidence.csv`, `bns.csv`, `bnss.csv`, `bsa.csv`: `statute, section, heading, status, basis`
  (`status`: `in_force`, `omitted` or `repealed`; omitted and repealed rows have no heading and are never shown as a
  title).
- `validation.json`: per Act, the source (URLs, hashes), the structure check and every extraction decision.
- `spot_checks.json`: the 70 rendered spot checks.
- `crosscheck.csv`: every catalog or mapping title that differs from the official heading, with a judgment
  (`docs/SECTION_LABELS.md`).
