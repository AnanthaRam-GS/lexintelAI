"""Step E4: five trimmed public judgment excerpts for the party gold set (labels filled later by a teammate).

Source: the LegalAI curated corpus (``data/processed/judgments_normalized/``, Indian Kanoon; not in git). Selection,
fixed before any measurement: the 68 corpus judgments whose title has two sides ("_vs_"), excluding the one already
used as the ``judgment`` fixture, sampled with ``random.Random(20261112).sample(candidates, 5)``.

Trimming follows step 10 (the ``judgment.txt`` fixture): each excerpt keeps the cause title and the opening of the
judgment (where the parties are introduced), as listed in ``EXCERPTS`` below; counsel names, appearance lines, reporter
questionnaires, signature blocks, page numbers and download stamps are removed. Provenance (title, court, date, URL,
attribution) is in ``public/SOURCES.md`` and the label files, not in the excerpt text, so that the title line cannot
act as an extra party cue.

    .venv/bin/python experiments/inlegalbert/party_gold/build_public_excerpts.py          # needs the local corpus
    .venv/bin/python experiments/inlegalbert/party_gold/build_public_excerpts.py --check  # compare with committed
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CORPUS = REPO / "data/processed/judgments_normalized"
FIXTURE_DOCUMENT = "indian_kanoon:136492342"
SAMPLE_SEED = 20261112

# doc_id -> (corpus id, [(segment start, segment end inclusive)], [substrings removed], [(old, new) replacements])
EXCERPTS: dict[str, tuple[str, list[tuple[str, str]], list[str], list[tuple[str, str]]]] = {
    "p01_gujarat_hc_2021": ("135745358", [
        ("IN THE HIGH COURT OF GUJARAT AT AHMEDABAD", "R/SPECIAL CRIMINAL APPLICATION NO. 8734 of 2019"),
        ("KARMANBHAI REVABHAI BHARWAD (decd.)", "STATE OF GUJARAT"),
        ("CORAM: HONOURABLE MS. JUSTICE GITA GOPI", "Suit on 16.08.2018."),
    ], ["Page 1 of 18\n", "Page 2 of 18\n", "R/SCR.A/8734/2019 JUDGMENT DATED: 21/10/2021 "], []),
    "p02_andhra_hc_2023": ("161457906", [
        ("HIGH COURT OF ANDHRA PRADESH AT AMARAVATI", "... Respondent."),
        ("DATE OF JUDGMENT PRONOUNCED :", "30.11.2023"),
        ("JUDGMENT:-", "Hospital,\nTirupati."),
    ], ["****\n"], [("\n4\n5)", "\n5)")]),
    "p03_punjab_hc_2023": ("176391710", [
        ("IN THE HIGH COURT OF PUNJAB AND HARYANA AT CHANDIGARH", "...Respondents"),
        ("CORAM:\nHON’BLE MR. JUSTICE JASJIT SINGH BEDI", "HON’BLE MR. JUSTICE JASJIT SINGH BEDI"),
        ("The prayer in the present petition", "on 03.10.2011 and 20.10.2011."),
    ], ["1 of 18\n", "::: Downloaded on - 13-04-2023 06:01:55 :::\n", "CRM-M-3854-2022 (O& M)\n", "::2::\n"], []),
    "p04_supreme_court_2022": ("26223875", [
        ("IN THE SUPREME COURT OF INDIA", ".... Respondent"),
        ("J U D G M E N T", "120B of\nIPC."),
    ], ["1 for short “IPC”\n", "Page 1 of 17\n",
        "Digitally signed by\nVISHAL ANAND\nDate: 2022.04.21\n15:23:14 IST\nReason:\nSignature Not Verified\n",
        "CRIMINAL APPEAL NO.383 OF 2018 "], [("Indian Penal Code1", "Indian Penal Code")]),
    "p05_allahabad_hc_2019": ("87669225", [
        ("HIGH COURT OF JUDICATURE AT ALLAHABAD", "Opposite Party :- State of U.P. and Another"),
        ("Hon'ble Sudhir Agarwal,J.", "to retain his freedom during the trial."),
    ], [], [("Heard Sri Kapil Tyagi, learned counsel for applicant", "Heard learned counsel for applicant")]),
}
# Counsel names that must not survive trimming (checked on every build).
COUNSEL_NAMES = ("DASTOOR", "PRANAV TRIVEDI", "Kalava", "Avnish Mittal", "Ishika Jain", "Navreet", "Akshay Jain",
                 "Ravindra Nath Rai", "Kapil Tyagi")


def sample() -> list[str]:
    candidates = []
    for path in sorted(CORPUS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if "_vs_" in os.path.basename(document["raw_path"]) and document["document_id"] != FIXTURE_DOCUMENT:
            candidates.append(document["document_id"])
    return sorted(c.split(":")[1] for c in random.Random(SAMPLE_SEED).sample(candidates, 5))


def excerpt(corpus_id: str, segments: list[tuple[str, str]], removals: list[str], replacements: list[tuple[str, str]]) -> tuple[str, dict]:
    document = json.loads((CORPUS / f"indian_kanoon_{corpus_id}.json").read_text(encoding="utf-8"))
    text = "\n".join(p["text"] for p in document["paragraphs"])
    parts, cursor = [], 0
    for start, end in segments:
        i = text.index(start, cursor)
        j = text.index(end, i) + len(end)
        parts.append(text[i:j])
        cursor = j
    out = "\n".join(parts) + "\n"
    for item in removals:
        if item not in out:
            raise SystemExit(f"{corpus_id}: removal not found: {item!r}")
        out = out.replace(item, "")
    for old, new in replacements:
        out = out.replace(old, new)
    out = re.sub(r"\n{3,}", "\n\n", out)
    leaked = [name for name in COUNSEL_NAMES if name.lower() in out.lower()]
    if leaked:
        raise SystemExit(f"{corpus_id}: counsel names left: {leaked}")
    title = Path(document["raw_path"]).stem.split("_", 1)[1].replace("_", " ")
    return out, {"corpus_document_id": document["document_id"], "source_sha256": document["source_sha256"], "title": title,
                 "url": f"https://indiankanoon.org/doc/{corpus_id}/"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected_sample = sample()
    if expected_sample != sorted(cid for cid, *_ in EXCERPTS.values()):
        raise SystemExit(f"sample changed: {expected_sample}")
    rows, problems = [], 0
    for doc_id, (corpus_id, segments, removals, replacements) in EXCERPTS.items():
        content, meta = excerpt(corpus_id, segments, removals, replacements)
        path = HERE / "public" / f"{doc_id}.txt"
        rows.append((doc_id, meta, len(content)))
        if args.check:
            if path.read_text(encoding="utf-8") != content:
                print("differs:", path.name)
                problems += 1
        else:
            path.write_text(content, encoding="utf-8")
    sources = ["# Public judgment excerpts: sources", "",
               "Trimmed excerpts of public judgments from the LegalAI curated corpus. Judgment data sourced from Indian "
               "Kanoon API (attribution required, docs/DATA_SOURCES.md). Counsel names, appearance lines, reporter "
               "questionnaires, signature blocks, page numbers and download stamps were removed "
               "(`build_public_excerpts.py`). Party names are as they appear in the public judgments.", "",
               "| Excerpt | Judgment | Corpus id | Characters |", "|---|---|---|---|"]
    sources += [f"| `{d}.txt` | [{m['title']}]({m['url']}) | `{m['corpus_document_id']}` | {n} |" for d, m, n in rows]
    sources_text = "\n".join(sources) + "\n"
    sources_path = HERE / "public" / "SOURCES.md"
    if args.check:
        problems += sources_path.read_text(encoding="utf-8") != sources_text
    else:
        sources_path.write_text(sources_text, encoding="utf-8")
    print("OK" if not problems else f"{problems} differ")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
