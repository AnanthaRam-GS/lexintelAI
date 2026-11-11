"""Step E0 timing probe for InLegalBERT on this Mac: forward passes only, no training, no dataset text.

Measures forward-pass time and MPS memory on synthetic token IDs for the two heads the experiment would use (token
classification for NER, multi-label sequence classification for statute identification). A fine-tuning step is
estimated as 3 x the forward time (forward + backward ~ 2 x forward + optimizer update); optimizer memory is
computed from the parameter count. Usage:

    .venv/bin/python experiments/inlegalbert/timing_probe.py --model models/inlegalbert --repeats 50
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import time

import torch
from transformers import AutoModelForSequenceClassification, AutoModelForTokenClassification

SEED = 20261111
TRAIN_STEP_FACTOR = 3.0


def probe(kind: str, model_path: str, device: torch.device, batch: int, seq_len: int, repeats: int) -> dict:
    torch.manual_seed(SEED)
    if kind == "ner":
        model = AutoModelForTokenClassification.from_pretrained(model_path, num_labels=29)  # 14 types, BIO
    else:
        model = AutoModelForSequenceClassification.from_pretrained(
            model_path, num_labels=100, problem_type="multi_label_classification")  # ILSI: 100 IPC sections
    model.to(device).eval()
    params = sum(p.numel() for p in model.parameters())
    times = []
    with torch.no_grad():
        for step in range(repeats + 5):
            input_ids = torch.randint(1000, 30000, (batch, seq_len), device=device)
            start = time.perf_counter()
            model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids))
            if device.type == "mps":
                torch.mps.synchronize()
            if step >= 5:
                times.append(time.perf_counter() - start)
    forward = statistics.median(times)
    result = {
        "kind": kind, "batch": batch, "seq_len": seq_len, "repeats": repeats, "parameters": params,
        "median_forward_s": round(forward, 4),
        "estimated_train_step_s": round(TRAIN_STEP_FACTOR * forward, 3),
        "estimated_train_examples_per_s": round(batch / (TRAIN_STEP_FACTOR * forward), 1),
        # fp32 weights + gradients + two AdamW moments.
        "estimated_weights_grads_adam_gib": round(params * 4 * 4 / 2**30, 2),
    }
    if device.type == "mps":
        result["mps_driver_allocated_gib_forward"] = round(torch.mps.driver_allocated_memory() / 2**30, 2)
        torch.mps.empty_cache()
    del model
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/inlegalbert")
    parser.add_argument("--repeats", type=int, default=50)
    args = parser.parse_args()
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    configs = [("ner", 16, 128), ("ner", 8, 256), ("classifier", 8, 512), ("classifier", 16, 256)]
    results = [probe(kind, args.model, device, batch, seq, args.repeats) for kind, batch, seq in configs]
    print(json.dumps({"device": str(device), "torch": torch.__version__, "seed": SEED, "train_step_factor": TRAIN_STEP_FACTOR,
                      "peak_rss_gib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30, 2),
                      "results": results}, indent=1))


if __name__ == "__main__":
    main()
