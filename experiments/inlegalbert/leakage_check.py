"""Step E0 leakage check: public training data vs LegalAI's corpus and gold sets. Prints counts only, never text.

Checks (1) document-ID overlap between a public dataset and the 70 corpus judgments (Indian Kanoon IDs), and
(2) text overlap by 13-word shingles (lower-cased, punctuation stripped) against the corpus chunks and the NER and
section gold texts. A public instance sharing any 13-word shingle with our corpus or gold is flagged for exclusion.

    .venv/bin/python experiments/inlegalbert/leakage_check.py --ilsi ~/legalai_datasets/ilsi_zenodo_6053791
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
    parser.add_argument("--ilsi", type=Path, required=True)
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


if __name__ == "__main__":
    main()
