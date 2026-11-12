# ml-pipeline state for experiments/inlegalbert only

This file exists for the ml-pipeline PreToolUse hook (`hooks/guard_training.py`). The hook looks for
`ml_pipeline/PIPELINE.md` in the tool call's working directory and up to four parent directories, never in
subdirectories, so this file is seen only by tool calls whose working directory is `experiments/inlegalbert/` or
below. Everywhere else in the repository the hook stays fully in force.

Protocol: `docs/experiments/INLEGALBERT_PLAN.md` and `docs/experiments/INLEGALBERT_E1_PROTOCOL.md`.

- Override: the project owner approved training the InLegalBERT NER model for experiment E1 on 2026-11-11 (step E1 brief) - reason: bounded experiment with a protocol and pass thresholds frozen in advance.
- Override: the project owner approved evaluating on the test set (the 36 gold NER examples) once per seed after model selection on the InLegalNER dev split, 2026-11-11 (step E1 brief).
