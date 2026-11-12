"""Step E1: fine-tune InLegalBERT for NER on InLegalNER (recipe frozen in docs/experiments/INLEGALBERT_E1_PROTOCOL.md).

Trains on InLegalNER's 14 native types (BIO, 29 labels) after the leakage exclusion, validates after every epoch by
entity-level exact F1 on the official dev split, keeps the best-validation checkpoint (early stopping, patience 2) and
writes the curves and timings as JSON. It never reads the 36 gold examples.

    caffeinate -i ../../.venv/bin/python train_ner.py --seed 11
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer, get_linear_schedule_with_warmup

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MODEL_DIR = REPO / "models" / "inlegalbert"
MODEL_REVISION = "b5ecfed8ed6cf9d25a3cb8225a8c52f161f7401a"
DATA_DIR = Path.home() / "legalai_datasets" / "inlegalner_2e32a46e6714"
NATIVE_TYPES = ["COURT", "PETITIONER", "RESPONDENT", "JUDGE", "LAWYER", "DATE", "ORG", "GPE", "STATUTE", "PROVISION",
                "PRECEDENT", "CASE_NUMBER", "WITNESS", "OTHER_PERSON"]
LABELS = ["O"] + [f"{prefix}-{t}" for t in NATIVE_TYPES for prefix in ("B", "I")]
LABEL2ID = {label: i for i, label in enumerate(LABELS)}

MAX_LENGTH = 256
STRIDE = 64
BATCH = 16
LEARNING_RATE = 3e-5
WEIGHT_DECAY = 0.01
WARMUP_FRACTION = 0.10
MAX_EPOCHS = 5
PATIENCE = 2
GRAD_CLIP = 1.0


def load_split(split: str, excluded: set[str]) -> tuple[list[dict], dict[str, int]]:
    items, counts = [], {"items": 0, "excluded": 0, "span_text_mismatch": 0, "entities": 0}
    for path in sorted((DATA_DIR / split).glob("NER_*.json")):
        for raw in json.load(open(path, encoding="utf-8")):
            counts["items"] += 1
            if str(raw["id"]) in excluded:
                counts["excluded"] += 1
                continue
            text = raw["data"]["text"]
            entities = []
            for result in raw["annotations"][0]["result"]:
                value = result["value"]
                start, end, label = int(value["start"]), int(value["end"]), value["labels"][0]
                if text[start:end] != value["text"]:
                    counts["span_text_mismatch"] += 1
                    continue
                entities.append((start, end, label))
            counts["entities"] += len(entities)
            items.append({"id": str(raw["id"]), "text": text, "entities": entities})
    return items, counts


def encode(tokenizer, text: str, entities: list[tuple[int, int, str]] | None):
    """Overlapping windows; with entities, also BIO label ids per token (-100 for special tokens)."""
    enc = tokenizer(text, truncation=True, max_length=MAX_LENGTH, stride=STRIDE, return_overflowing_tokens=True,
                    return_offsets_mapping=True)
    windows = []
    char_entity = None
    if entities is not None:
        char_entity = [None] * len(text)
        for index, (start, end, label) in enumerate(entities):
            for position in range(start, end):
                char_entity[position] = (index, start, label)
    for w in range(len(enc["input_ids"])):
        offsets = enc["offset_mapping"][w]
        window = {"input_ids": enc["input_ids"][w], "attention_mask": enc["attention_mask"][w], "offsets": offsets}
        if char_entity is not None:
            labels = []
            for start, end in offsets:
                if start == end:
                    labels.append(-100)
                    continue
                hit = char_entity[start]
                if hit is None:
                    labels.append(LABEL2ID["O"])
                else:
                    _, entity_start, label = hit
                    labels.append(LABEL2ID[("B-" if start == entity_start else "I-") + label])
            window["labels"] = labels
        windows.append(window)
    return windows


def pad(batch: list[dict], device: torch.device) -> dict[str, torch.Tensor]:
    width = max(len(w["input_ids"]) for w in batch)
    out = {
        "input_ids": torch.tensor([w["input_ids"] + [0] * (width - len(w["input_ids"])) for w in batch], device=device),
        "attention_mask": torch.tensor([w["attention_mask"] + [0] * (width - len(w["attention_mask"])) for w in batch], device=device),
    }
    if "labels" in batch[0]:
        out["labels"] = torch.tensor([w["labels"] + [-100] * (width - len(w["labels"])) for w in batch], device=device)
    return out


@torch.no_grad()
def predict_entities(model, tokenizer, texts: list[str], device: torch.device) -> list[list[dict]]:
    """Entities per text: (start, end, native type, confidence = mean label probability over the entity's tokens)."""
    model.eval()
    results = []
    for text in texts:
        windows = encode(tokenizer, text, None)
        best: dict[tuple[int, int], tuple[float, int, float]] = {}  # offsets -> (distance from centre, label, prob)
        for i in range(0, len(windows), 32):
            chunk = windows[i:i + 32]
            probs = torch.softmax(model(**pad(chunk, device)).logits, dim=-1).cpu()
            for w, window in enumerate(chunk):
                n = len(window["input_ids"])
                for t, (start, end) in enumerate(window["offsets"]):
                    if start == end:
                        continue
                    p, label = probs[w, t].max(dim=-1)
                    distance = abs(t - n / 2)
                    key = (start, end)
                    if key not in best or distance < best[key][0]:
                        best[key] = (distance, int(label), float(p))
        entities, current = [], None
        for (start, end), (_, label_id, prob) in sorted(best.items()):
            label = LABELS[label_id]
            if label == "O":
                current = None
                continue
            prefix, entity_type = label.split("-", 1)
            if prefix == "I" and current is not None and current["type"] == entity_type:
                current["end"] = end
                current["probs"].append(prob)
                continue
            current = {"start": start, "end": end, "type": entity_type, "probs": [prob]}
            entities.append(current)
        results.append([{"start": e["start"], "end": e["end"], "type": e["type"],
                         "confidence": round(sum(e["probs"]) / len(e["probs"]), 6)} for e in entities])
    return results


def entity_f1(gold: list[list[tuple[int, int, str]]], predicted: list[list[dict]]) -> dict[str, float]:
    tp = fp = fn = 0
    for g, p in zip(gold, predicted):
        gs = {(s, e, t) for s, e, t in g}
        ps = {(x["start"], x["end"], x["type"]) for x in p}
        tp += len(gs & ps)
        fp += len(ps - gs)
        fn += len(gs - ps)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6), "tp": tp, "fp": fp, "fn": fn}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, default=REPO / "models" / "inlegalbert_ner")
    parser.add_argument("--runs", type=Path, default=HERE / "runs")
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    excluded_ids = json.load(open(DATA_DIR / "excluded_ids.json"))
    train_items, train_counts = load_split("train", set(excluded_ids.get("train", [])))
    dev_items, dev_counts = load_split("dev", set(excluded_ids.get("dev", [])))
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    train_windows = [w for item in train_items for w in encode(tokenizer, item["text"], item["entities"])]
    model = AutoModelForTokenClassification.from_pretrained(
        MODEL_DIR, num_labels=len(LABELS), id2label=dict(enumerate(LABELS)), label2id=LABEL2ID).to(device)

    steps_per_epoch = (len(train_windows) + BATCH - 1) // BATCH
    no_decay = ("bias", "LayerNorm.weight")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": WEIGHT_DECAY},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = torch.optim.AdamW(groups, lr=LEARNING_RATE)
    total_steps = steps_per_epoch * MAX_EPOCHS
    scheduler = get_linear_schedule_with_warmup(optimizer, int(WARMUP_FRACTION * total_steps), total_steps)

    out_dir = args.out / f"seed-{args.seed}"
    log = {"seed": args.seed, "device": str(device), "torch": torch.__version__, "checkpoint": f"law-ai/InLegalBERT@{MODEL_REVISION}",
           "recipe": {"max_length": MAX_LENGTH, "stride": STRIDE, "batch": BATCH, "learning_rate": LEARNING_RATE,
                      "weight_decay": WEIGHT_DECAY, "warmup_fraction": WARMUP_FRACTION, "max_epochs": MAX_EPOCHS,
                      "patience": PATIENCE, "grad_clip": GRAD_CLIP, "labels": len(LABELS)},
           "data": {"train": train_counts, "dev": dev_counts, "train_windows": len(train_windows), "steps_per_epoch": steps_per_epoch},
           "epochs": [], "loss_curve": []}
    dev_gold = [item["entities"] for item in dev_items]
    best_f1, best_epoch, stale = -1.0, 0, 0
    started = time.time()
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        order = list(range(len(train_windows)))
        random.Random(args.seed * 1000 + epoch).shuffle(order)
        epoch_start, losses = time.time(), []
        for step in range(steps_per_epoch):
            batch = pad([train_windows[i] for i in order[step * BATCH:(step + 1) * BATCH]], device)
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            losses.append(float(loss))
            if (step + 1) % 50 == 0:
                log["loss_curve"].append({"epoch": epoch, "step": step + 1, "mean_loss_last_50": round(sum(losses[-50:]) / 50, 5)})
        train_seconds = time.time() - epoch_start
        dev_start = time.time()
        dev_metrics = entity_f1(dev_gold, predict_entities(model, tokenizer, [item["text"] for item in dev_items], device))
        record = {"epoch": epoch, "train_loss": round(sum(losses) / len(losses), 5), "train_seconds": round(train_seconds, 1),
                  "dev_seconds": round(time.time() - dev_start, 1), "dev": dev_metrics}
        improved = dev_metrics["f1"] > best_f1
        if improved:
            best_f1, best_epoch, stale = dev_metrics["f1"], epoch, 0
            model.save_pretrained(out_dir)
            tokenizer.save_pretrained(out_dir)
        else:
            stale += 1
        record["best_so_far"] = improved
        log["epochs"].append(record)
        print(json.dumps(record), flush=True)
        if stale >= PATIENCE:
            log["early_stopped_after_epoch"] = epoch
            break
    log["best_epoch"], log["best_dev_f1"] = best_epoch, best_f1
    log["total_seconds"] = round(time.time() - started, 1)
    args.runs.mkdir(parents=True, exist_ok=True)
    (args.runs / f"seed-{args.seed}.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(json.dumps({"seed": args.seed, "best_epoch": best_epoch, "best_dev_f1": best_f1, "total_seconds": log["total_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
