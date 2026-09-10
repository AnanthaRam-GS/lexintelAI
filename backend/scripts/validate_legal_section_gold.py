import json
import re
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_PATH = REPO_ROOT / "data/structured/manifests/legal_section_eval.json"
CATALOG_PATH = REPO_ROOT / "data/structured/manifests/legal_section_catalog.json"
SUMMARY_PATH = REPO_ROOT / "data/structured/manifests/legal_section_gold_summary.json"

VALID_RELEVANCE = {"primary", "relevant", "not_relevant", "uncertain"}
EXPECTED_PREDICTOR_SHA256 = "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c"
EXPECTED_COUNTS = {
    "examples": 36,
    "reviewed": 36,
    "pending": 0,
    "primary": 36,
    "relevant": 24,
    "uncertain": 1,
    "positive": 60,
    "total": 61,
    "zero_positive_ids": ["sec-q026", "sec-q027", "sec-q035"],
}

EXPECTED_QUERIES = {
    "sec-q001": "Section 302 IPC murder bail before Sessions Court",
    "sec-q002": "Can Section 438 CrPC anticipatory bail apply in a cheating FIR?",
    "sec-q003": "After July 2024, which BNS section covers murder?",
    "sec-q004": "BNSS provision for anticipatory bail after commencement of new criminal laws",
    "sec-q005": "Robbery with hurt and stolen mobile phone under old criminal law",
    "sec-q006": "False promise to repay money and dishonest inducement complaint",
    "sec-q007": "Entrusted company funds were misappropriated by an employee",
    "sec-q008": "Minor girl abducted from lawful guardianship before July 2024",
    "sec-q009": "POCSO sexual assault complaint involving a child victim",
    "sec-q010": "Dowry harassment and cruelty by husband under IPC",
    "sec-q011": "Criminal conspiracy and common intention in a murder case",
    "sec-q012": "Ganja recovery and NDPS bail for small quantity",
    "sec-q013": "Default bail after charge sheet delay in NDPS case",
    "sec-q014": "FIR quashing petition before High Court in matrimonial dispute",
    "sec-q015": "Notice before arrest safeguard for non-cognizable looking complaint",
    "sec-q016": "BNS cheating section for online payment fraud",
    "sec-q017": "BNSS regular bail before High Court after July 2024",
    "sec-q018": "Theft of jewellery from house under IPC",
    "sec-q019": "Attempted murder with knife injury under BNS",
    "sec-q020": "Grievous hurt caused during assault after new criminal laws",
    "sec-q021": "Rape allegation before July 2024 with later trial pending",
    "sec-q022": "Caste abuse in public view and SC/ST Act bail",
    "sec-q023": "Section 420 IPC and Section 406 IPC both alleged in business dispute",
    "sec-q024": "Section 103 BNS and Section 302 IPC transition issue",
    "sec-q025": "Which law applies to an offence committed before July 2024 but FIR filed later?",
    "sec-q026": "How to file a certified copy application in court?",
    "sec-q027": "Property partition dispute between brothers with no criminal allegation",
    "sec-q028": "Police refused to register FIR in assault complaint",
    "sec-q029": "Regular bail in murder case under CrPC",
    "sec-q030": "Quashing of FIR for cheating and criminal breach of trust",
    "sec-q031": "Heroin possession and conspiracy under NDPS Act",
    "sec-q032": "Common intention in robbery case under old IPC",
    "sec-q033": "Can anticipatory bail be sought for a POCSO allegation?",
    "sec-q034": "BNS kidnapping from guardian and sexual assault allegation",
    "sec-q035": "Medical negligence complaint seeking compensation only",
    "sec-q036": "BNSS default bail when investigation period expires",
}

EXPLICIT_GUARDRAILS = {
    "sec-q001": {("IPC", "302", "primary")},
    "sec-q002": {("CrPC", "438", "primary")},
    "sec-q023": {("IPC", "420", "primary"), ("IPC", "406", "primary")},
    "sec-q024": {("BNS", "103", "primary"), ("IPC", "302", "primary")},
}

MIXED_TRANSITION_GUARDRAILS = {
    "sec-q024": {("BNS", "103", "primary"), ("IPC", "302", "primary")},
    "sec-q025": {("BNS", "358", "relevant"), ("BNSS", "531", "relevant")},
    "sec-q028": {("CrPC", "154(3)", "relevant"), ("BNSS", "173(4)", "relevant")},
    "sec-q033": {("CrPC", "438", "relevant"), ("BNSS", "482", "relevant")},
}


def normalize_statute(statute: str) -> str:
    return re.sub(r"\s+", " ", statute.strip()).casefold()


def normalize_section(section: str) -> str:
    return re.sub(r"\s+", "", section.strip()).casefold()


def normalize_key(statute: str, section: str) -> tuple[str, str]:
    return (normalize_statute(statute), normalize_section(section))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_gold() -> dict:
    payload = load_json(EVAL_PATH)
    catalog = load_json(CATALOG_PATH)
    summary = load_json(SUMMARY_PATH)
    errors: list[str] = []

    catalog_entries = catalog["entries"]
    catalog_by_key = {normalize_key(entry["statute"], entry["section"]): entry for entry in catalog_entries}
    if len(catalog_entries) != 62:
        errors.append(f"catalog_entries={len(catalog_entries)}")
    if len(catalog_by_key) != len(catalog_entries):
        errors.append("duplicate normalized catalog keys")

    examples = payload["examples"]
    ids = [example["example_id"] for example in examples]
    if len(examples) != EXPECTED_COUNTS["examples"]:
        errors.append(f"examples={len(examples)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate example ids")
    if ids != [f"sec-q{i:03d}" for i in range(1, 37)]:
        errors.append("example ids are not sec-q001..sec-q036 in order")

    relevance_counts: Counter[str] = Counter()
    missing: list[tuple[str, str, str]] = []
    duplicate_judgments: list[str] = []
    conflicts: list[str] = []
    subsection_flattening: list[tuple[str, str, str]] = []

    for example in examples:
        example_id = example["example_id"]
        if example.get("query") != EXPECTED_QUERIES.get(example_id):
            errors.append(f"query changed for {example_id}")
        if example.get("review_status") != "reviewed":
            errors.append(f"{example_id} not reviewed")
        if example.get("reviewer") != "Ananthu":
            errors.append(f"{example_id} reviewer missing")
        if not example.get("reviewed_at"):
            errors.append(f"{example_id} reviewed_at missing")

        seen: dict[tuple[str, str], str] = {}
        for gold in example["gold_sections"]:
            relevance = gold.get("relevance")
            if relevance not in VALID_RELEVANCE:
                errors.append(f"{example_id} invalid relevance {relevance}")
                continue
            relevance_counts[relevance] += 1
            key = normalize_key(gold["statute"], gold["section"])
            if key not in catalog_by_key:
                missing.append((example_id, gold["statute"], gold["section"]))
            elif gold["section"] != catalog_by_key[key]["section"]:
                subsection_flattening.append((example_id, gold["section"], catalog_by_key[key]["section"]))
            if key in seen:
                duplicate_judgments.append(f"{example_id}:{gold['statute']}:{gold['section']}")
                if seen[key] != relevance:
                    conflicts.append(f"{example_id}:{gold['statute']}:{gold['section']}")
            seen[key] = relevance

    reviewed = sum(1 for example in examples if example["review_status"] == "reviewed")
    pending = sum(1 for example in examples if example["review_status"] == "pending")
    zero_positive_ids = sorted(example["example_id"] for example in examples if not example["gold_sections"])
    positive = relevance_counts["primary"] + relevance_counts["relevant"]
    total = sum(relevance_counts.values())

    if reviewed != EXPECTED_COUNTS["reviewed"]:
        errors.append(f"reviewed={reviewed}")
    if pending != EXPECTED_COUNTS["pending"]:
        errors.append(f"pending={pending}")
    for label in ["primary", "relevant", "uncertain"]:
        if relevance_counts[label] != EXPECTED_COUNTS[label]:
            errors.append(f"{label}={relevance_counts[label]}")
    if positive != EXPECTED_COUNTS["positive"]:
        errors.append(f"positive={positive}")
    if total != EXPECTED_COUNTS["total"]:
        errors.append(f"total={total}")
    if zero_positive_ids != EXPECTED_COUNTS["zero_positive_ids"]:
        errors.append(f"zero_positive_ids={zero_positive_ids}")
    if missing:
        errors.append(f"missing_catalog_membership={missing}")
    if duplicate_judgments:
        errors.append(f"duplicate_judgments={duplicate_judgments}")
    if conflicts:
        errors.append(f"conflicting_relevance={conflicts}")
    if subsection_flattening:
        errors.append(f"subsection_flattening={subsection_flattening}")

    for group_name, guardrails in [("explicit", EXPLICIT_GUARDRAILS), ("mixed_transition", MIXED_TRANSITION_GUARDRAILS)]:
        examples_by_id = {example["example_id"]: example for example in examples}
        for example_id, required in guardrails.items():
            actual = {
                (gold["statute"], gold["section"], gold["relevance"])
                for gold in examples_by_id[example_id]["gold_sections"]
            }
            if not required.issubset(actual):
                errors.append(f"{group_name} guardrail failed for {example_id}")

    expected_summary = {
        "example_count": 36,
        "reviewed": 36,
        "pending": 0,
        "primary_count": 36,
        "relevant_count": 24,
        "uncertain_count": 1,
        "positive_count": 60,
        "total_judgment_count": 61,
        "zero_positive_example_count": 3,
        "zero_positive_example_ids": ["sec-q026", "sec-q027", "sec-q035"],
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            errors.append(f"summary {key}={summary.get(key)}")

    return {
        "examples": len(examples),
        "reviewed": reviewed,
        "pending": pending,
        "primary": relevance_counts["primary"],
        "relevant": relevance_counts["relevant"],
        "uncertain": relevance_counts["uncertain"],
        "positive": positive,
        "total_annotated": total,
        "zero_positive_ids": zero_positive_ids,
        "catalog_entries": len(catalog_entries),
        "missing": missing,
        "duplicate_judgments": duplicate_judgments,
        "conflicting_relevance": conflicts,
        "normalization_conflicts": 0 if len(catalog_by_key) == len(catalog_entries) else 1,
        "valid": not errors,
        "errors": errors,
    }


def main() -> int:
    result = validate_gold()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
