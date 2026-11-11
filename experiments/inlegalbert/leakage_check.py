"""Leakage check (steps E0, E1): public training data vs LegalAI's corpus and gold sets. Prints counts only, never text.

Checks (1) document-ID overlap between a public dataset and the 70 corpus judgments (Indian Kanoon IDs), and
(2) text overlap by 13-word shingles (lower-cased, punctuation stripped) against the corpus chunks and the NER and
section gold texts. A public instance sharing any 13-word shingle with our corpus or gold is flagged for exclusion.

    .venv/bin/python experiments/inlegalbert/leakage_check.py --ilsi ~/legalai_datasets/ilsi_zenodo_6053791
    .venv/bin/python experiments/inlegalbert/leakage_check.py --inlegalner ~/legalai_datasets/inlegalner_2e32a46e6714

InLegalNER (E1): an item (judgment sentence or preamble) is excluded when its Indian Kanoon source document is a corpus
judgment, it shares a 13-word shingle with the corpus or the gold texts, a gold text appears verbatim in it, or it
appears verbatim in a gold text. The excluded item IDs (no text) are written next to the data as excluded_ids.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

SHINGLE = 13


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def shingles(text: str) -> set[int]:
    w = words(text)
    return {hash(" ".join(w[i:i + SHINGLE])) for i in range(max(0, len(w) - SHINGLE + 1))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ilsi", type=Path)
    parser.add_argument("--inlegalner", type=Path)
    args = parser.parse_args()

    corpus_ids, corpus_sh = set(), set()
    for path in glob.glob("data/processed/judgment_chunks/*.json"):
        for chunk in json.load(open(path, encoding="utf-8")):
            corpus_ids.add(str(chunk["source_document_id"]))
            corpus_sh |= shingles(chunk.get("chunk_text") or chunk.get("text") or "")
    ner = json.load(open("data/structured/manifests/legal_ner_gold_template.json"))["examples"]
    sec = json.load(open("data/structured/manifests/legal_section_eval.json"))["examples"]
    gold_texts = [x["text"] for x in ner] + [x["query"] for x in sec]
    gold_sh = set().union(*(shingles(t) for t in gold_texts))
    gold_words = [set(words(t)) for t in gold_texts]
    print(f"corpus: {len(corpus_ids)} documents, {len(corpus_sh)} shingles; gold texts: {len(gold_texts)}, {len(gold_sh)} shingles "
          f"(gold texts are short: shingle overlap needs >= {SHINGLE} words)")
    if args.inlegalner:
        check_inlegalner(args.inlegalner, corpus_ids, corpus_sh, gold_texts, gold_sh)
    if not args.ilsi:
        return

    totals = {}
    for split in ("train", "dev", "test"):
        id_hits = corpus_hits = gold_hits = n = 0
        for line in open(args.ilsi / f"{split}.jsonl", encoding="utf-8"):
            row = json.loads(line)
            n += 1
            sh = shingles(" ".join(row.get("text") or []))
            id_hits += str(row.get("id")) in corpus_ids
            corpus_hits += bool(sh & corpus_sh)
            gold_hits += bool(sh & gold_sh)
        totals[split] = {"cases": n, "id_in_corpus": id_hits, "shares_shingle_with_corpus": corpus_hits,
                         "shares_shingle_with_gold": gold_hits}
    print(json.dumps(totals, indent=1))


def normalized(text: str) -> str:
    return " " + " ".join(words(text)) + " "


def check_inlegalner(root: Path, corpus_ids: set[str], corpus_sh: set[int], gold_texts: list[str], gold_sh: set[int]) -> None:
    gold_norm = [normalized(t) for t in gold_texts]
    excluded: dict[str, list[str]] = {}
    totals = {}
    for split in ("train", "dev"):
        counts = {"items": 0, "source_in_corpus": 0, "shares_shingle_with_corpus": 0, "shares_shingle_with_gold": 0,
                  "gold_text_inside_item": 0, "item_inside_gold_text": 0, "excluded": 0}
        for path in sorted(root.glob(f"{split}/NER_*.json")):
            for item in json.load(open(path, encoding="utf-8")):
                counts["items"] += 1
                text = item["data"]["text"]
                source = str((item.get("meta") or {}).get("source") or "")
                match = re.search(r"indiankanoon\.org/doc/(\d+)", source)
                sh = shingles(text)
                norm = normalized(text)
                reasons = []
                if match and match.group(1) in corpus_ids:
                    reasons.append("source_in_corpus")
                if sh & corpus_sh:
                    reasons.append("shares_shingle_with_corpus")
                if sh & gold_sh:
                    reasons.append("shares_shingle_with_gold")
                if any(g.strip() and g in norm for g in gold_norm):
                    reasons.append("gold_text_inside_item")
                if norm.strip() and any(norm in g for g in gold_norm):
                    reasons.append("item_inside_gold_text")
                for reason in reasons:
                    counts[reason] += 1
                if reasons:
                    counts["excluded"] += 1
                    excluded.setdefault(split, []).append(str(item["id"]))
        totals[split] = counts
    (root / "excluded_ids.json").write_text(json.dumps(excluded, indent=1), encoding="utf-8")
    print(json.dumps({"inlegalner": totals}, indent=1))


if __name__ == "__main__":
    main()
