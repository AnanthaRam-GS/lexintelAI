"""Section-label coverage before and after the official headings (step 26). Read-only; no provider calls.

- **Corpus-cited sections:** every distinct (statute, section) in ``document_sections`` (read-only query on
  ``--database-url-env``), and which trusted source gives it a title, with the step 25 sources (catalog + mapping)
  and with the official headings first.
- **Saved model labels:** the provision strings in the saved step 22-24 outputs (``--reviews-dir``, outside the
  repository), counted with the step 25 rule: a provision is *checkable* when it names one section, carries a model
  label and gets a trusted title or a statute correction; it is a *mismatch* when the statute was corrected or the
  label shares no content word with the trusted title.

    APP_ENV=test DATABASE_URL=... .venv/bin/python backend/scripts/section_label_coverage.py --reviews-dir ~/legalai_reviews
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import glob
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.section_labels import (  # noqa: E402
    agrees,
    build_sources,
    canonical_section,
    comparable,
    parse_provision,
    resolve_provision,
)


def title_source(sources, statute: str, section: str) -> str:
    entries = sources.entries(statute, section)
    if not entries:
        return "none"
    if len({comparable(entry.title) for entry in entries}) > 1:
        return "conflict"
    return entries[0].source


def corpus_coverage(rows: list[tuple[str, str]], sources) -> dict:
    distinct = sorted(set(rows))
    by_statute: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for statute, section in distinct:
        by_statute[statute][title_source(sources, statute, section)] += 1
    return {
        "rows": len(rows), "rows_by_source": dict(collections.Counter(title_source(sources, s, x) for s, x in rows)),
        "distinct": len(distinct), "distinct_by_source": dict(collections.Counter(title_source(sources, s, x) for s, x in distinct)),
        "by_statute": {statute: dict(counter) for statute, counter in sorted(by_statute.items())},
        "untitled": [f"{s} {x}" for s, x in distinct if title_source(sources, s, x) == "none"],
    }


def saved_provisions(reviews: Path) -> list[tuple[str, str]]:
    occurrences: list[tuple[str, str]] = []
    for path in sorted(glob.glob(f"{reviews}/live_runs/20261030T_step22/*.json")):
        data = json.load(open(path, encoding="utf-8"))
        response = data.get("response") if isinstance(data, dict) else None
        if isinstance(response, dict):
            occurrences += [("step22", item["section"]) for item in response.get("identified_sections") or []]
            occurrences += [("step22", item["title"]) for item in response.get("sections") or []]
    for folder in ("raw", "raw_superseded_step24"):
        for path in sorted(glob.glob(f"{reviews}/eval_runs/2026-10_v3_groq/{folder}/*/*.json")):
            answer = json.load(open(path, encoding="utf-8")).get("answer") or {}
            for key in ("explicit_legal_provisions", "potential_additional_provisions", "possible_legal_provisions"):
                occurrences += [("step24" if folder == "raw" else "step24_superseded", text) for text in answer.get(key) or []]
    return occurrences


def label_check(occurrences: list[tuple[str, str]], sources) -> dict:
    states: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    checkable = mismatches = 0
    mismatch_list: list[str] = []
    per_origin: collections.Counter = collections.Counter()
    for origin, text in occurrences:
        parsed = parse_provision(text)
        references = resolve_provision(text, sources)
        for reference in references:
            states[reference.label.state] += 1
            if reference.label.state in ("verified", "corrected_statute"):
                by_source[reference.label.source] += 1
        if len(parsed.mentions) == 1 and parsed.label and references[0].label.state in ("verified", "corrected_statute"):
            checkable += 1
            label = references[0].label
            if label.state == "corrected_statute" or label.model_label_differs or (label.note or "").startswith("The answer's own label"):
                mismatches += 1
                per_origin[origin] += 1
                mismatch_list.append(f"{text!r} -> {references[0].statute} {references[0].section}: "
                                     f"{label.title or label.model_label} [{label.source}]")
    return {"provision_strings": len(occurrences), "states": dict(states), "titled_by_source": dict(by_source),
            "checkable": checkable, "mismatches": mismatches, "mismatches_by_origin": dict(per_origin),
            "mismatch_list": sorted(set(mismatch_list))}


# Hand-reviewed judgments (step 26) that the rules below cannot make: which disagreements are about meaning.
REVIEWED_MEANING_DIFFERS = {
    ("ipc_bns_mapping", "IPC", "366B"): "the mapping gives section 366's subject (kidnapping to compel marriage)",
    ("ipc_bns_mapping", "IPC", "376"): "the mapping files the headings of sections 376A-376E under section 376",
}
REVIEWED_USE_NOT_SUBJECT = {
    ("section_catalog", "BNSS", "187"): "names the consequence (default bail), not the section's subject",
    ("section_catalog", "BNSS", "35"): "names the purpose (arrest safeguards), not the section's subject",
}
_STATUTE_TEXT = re.compile(r"^(?:Whoever|Where|If|A person|The offence)\b|shall be punished|^\d+(?:\(\w+\))*$|^Explanation$", re.IGNORECASE)
_LOWERCASE_START = re.compile(r"^[“\"]?[a-z]")  # a clause cut out of the statute text ("doing any act which ...")


def crosscheck(sources) -> list[dict]:
    """Every catalog or mapping title that differs from the official heading of the same section, with a judgment."""
    rows = []
    for name, table in (("section_catalog", sources.catalog), ("ipc_bns_mapping", sources.mapping)):
        for (statute, section), entries in sorted(table.items()):
            base = canonical_section(section) or section
            official = sources.official.get((statute, section)) or sources.official.get((statute, base))
            if not official:
                continue
            heading = official[0]
            for entry in entries:
                if comparable(entry.title) == comparable(heading.title):
                    continue
                shared = agrees(entry.title, [heading]) or agrees(heading.title, [entry])
                key = (name, statute, base)
                tagged = re.fullmatch(rf"{re.escape(heading.title)}\.?\s*\d+\s*\(\w+\)", entry.title, re.IGNORECASE)
                bare_reference = re.fullmatch(r"\d+(?:\(\w+\))*|Explanation", entry.title.strip())
                if bare_reference:
                    judgment, why = "not a title", "a bare sub-section reference or label, not a heading"
                elif key in REVIEWED_MEANING_DIFFERS and not tagged:
                    judgment, why = "meaning differs", REVIEWED_MEANING_DIFFERS[key]
                elif (name, statute, section) in REVIEWED_USE_NOT_SUBJECT:
                    judgment, why = "describes use, not subject", REVIEWED_USE_NOT_SUBJECT[(name, statute, section)]
                elif tagged:
                    judgment, why = "wording only", "the heading followed by a sub-section tag"
                elif name == "ipc_bns_mapping" and (_STATUTE_TEXT.search(entry.title.strip()) or _LOWERCASE_START.search(entry.title.strip())
                                                  or len(entry.title.split()) > 18):
                    judgment, why = "not a title", "statute text or a sub-section reference, not a heading"
                elif section != base and name == "section_catalog":
                    judgment, why = "sub-section specific", f"the catalog titles sub-section {section}; the official heading is section {base}'s"
                elif shared:
                    judgment, why = "wording only", "same subject in other words"
                else:
                    judgment, why = "needs review", "no shared content word"
                rows.append({"source": name, "statute": statute, "section": section, "official_heading": heading.title,
                             "other_title": entry.title, "judgment": judgment, "reason": why})
    return rows


def mapping_conflicts(sources, crosscheck_rows: list[dict]) -> list[dict]:
    """The mapping (CYTRAIN) rows whose IPC or BNS description is judged to differ in meaning from the official heading.

    Each crosscheck row judged "meaning differs" for the mapping is matched back to every CSV row with the same section
    and the same description (compared as in the resolver). The source descriptions are not edited; the analytics API
    flags these rows (step 26b).
    """
    from backend.app.services.section_labels import clean_title, load_mapping_rows, normalize_section  # noqa: PLC0415

    wanted = {(r["statute"], r["section"], comparable(r["other_title"])): r for r in crosscheck_rows
              if r["source"] == "ipc_bns_mapping" and r["judgment"] == "meaning differs"}
    out = []
    for row in load_mapping_rows():
        ipc = re.sub(r"(?<=\d)-(?=[A-Za-z]\b)", "", (row.get("ipc_section") or "").strip())
        for side, section, description in (("ipc", ipc, row.get("ipc_description") or ""), ("bns", (row.get("bns_section") or "").strip(),
                                                                                              row.get("bns_description") or "")):
            statute = "IPC" if side == "ipc" else "BNS"
            if not re.fullmatch(r"\d+[A-Za-z]*(?:\([0-9A-Za-z]+\))*", section):
                continue
            key = (statute, normalize_section(section), comparable(clean_title(description)))
            if key in wanted:
                out.append({"source": "CYTRAIN", "ipc_section": row.get("ipc_section"), "bns_section": row.get("bns_section"),
                            "side": side, "description": description, "official_heading": wanted[key]["official_heading"],
                            "reason": wanted[key]["reason"]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--reviews-dir", type=Path, default=Path.home() / "legalai_reviews")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--crosscheck", type=Path, help="write the official-vs-catalog/mapping disagreements (CSV) and exit")
    parser.add_argument("--mapping-conflicts", type=Path, help="with --crosscheck: also write the flagged mapping rows (CSV)")
    args = parser.parse_args()
    if args.crosscheck:
        rows = crosscheck(build_sources())
        with args.crosscheck.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(collections.Counter((r["source"], r["judgment"]) for r in rows))
        if args.mapping_conflicts:
            flagged = mapping_conflicts(build_sources(), rows)
            with args.mapping_conflicts.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(flagged[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(flagged)
            print("flagged mapping rows:", len(flagged))
        return 0
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    engine = create_engine(os.environ[args.database_url_env])
    with engine.connect() as connection:
        rows = [(r.statute, r.section) for r in connection.execute(text("select statute, section from document_sections"))]
    before, after = build_sources(heading_rows=[]), build_sources()
    occurrences = saved_provisions(args.reviews_dir)
    result = {"corpus": {"before": corpus_coverage(rows, before), "after": corpus_coverage(rows, after)},
              "saved_labels": {"before": label_check(occurrences, before), "after": label_check(occurrences, after)}}
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for when in ("before", "after"):
        c, s = result["corpus"][when], result["saved_labels"][when]
        print(f"== {when}: corpus distinct {c['distinct']} by source {c['distinct_by_source']}; rows {c['rows']} by source {c['rows_by_source']}")
        for statute, counts in c["by_statute"].items():
            print(f"     {statute:14} {counts}")
        print(f"   saved labels: {s['provision_strings']} strings, states {s['states']}, titled by {s['titled_by_source']}; "
              f"checkable {s['checkable']}, mismatches {s['mismatches']} {s['mismatches_by_origin']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
