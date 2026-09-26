"""Evaluator-only code. Labels are loaded after business-only predictions."""
import hashlib
import json
from collections import defaultdict

from app.tools.matcher import match


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def score(predictions: dict, truth: list[dict], internal: list[dict]) -> dict:
    guessed = {p["internal_record_id"]: p["processor_record_id"] for p in predictions["auto_matches"]}
    amounts = {r["internal_record_id"]: r["amount_cents"] for r in internal}
    slices = defaultdict(list)
    for g in truth:
        slices[g["pattern"]].append(g)
    by_id = {r["internal_record_id"]: r for r in internal}
    for g in truth:
        row = by_id[g["expected_internal_record_id"]]
        slices[f'processor_{row["processor"]}'].append(g)
        if amounts[g["expected_internal_record_id"]] >= 1_000_000:
            slices["high_value"].append(g)

    def metrics(labels):
        correct = false = high_false = true_negative = false_negative = 0
        false_positive = 0
        correct_ids = []
        for g in labels:
            record_id = g["expected_internal_record_id"]
            prediction = guessed.get(record_id)
            if g["is_true_match"] == 1:
                if prediction == g["expected_processor_record_id"]:
                    correct += 1
                    correct_ids.append(record_id)
                else:
                    false_negative += 1
                    if prediction is not None:
                        false += 1
                        false_positive += 1
                        high_false += amounts[record_id] >= 1_000_000
            else:
                if prediction is None:
                    true_negative += 1
                else:
                    false += 1
                    false_positive += 1
                    high_false += amounts[record_id] >= 1_000_000
        n = len(labels)
        unresolved = n - correct - false
        return {"sample_size": n, "correct_auto": correct, "false_auto": false,
                "unresolved": unresolved, "auto_resolution_rate": correct / max(n, 1),
                "accuracy": (correct + true_negative) / max(n, 1),
                "score": (correct + true_negative) / max(n, 1),
                "true_negative": true_negative, "false_positive": false_positive,
                "false_negative": false_negative,
                "precision": correct / max(correct + false_positive, 1),
                "recall": correct / max(correct + false_negative, 1),
                "false_match_rate": false / max(correct + false, 1),
                "unresolved_rate": unresolved / max(n, 1), "escalation_rate": unresolved / max(n, 1),
                "high_value_false_matches": high_false, "correct_ids": correct_ids}

    result = metrics(truth)
    result["slices"] = {name: {k: v for k, v in metrics(labels).items() if k != "correct_ids"}
                        for name, labels in slices.items()}
    return result


def compare(base, candidate, internal, settlements, truth) -> dict:
    base_predictions = match(internal, settlements, base.matching)
    candidate_predictions = match(internal, settlements, candidate.matching)
    before = score(base_predictions, truth, internal)
    after = score(candidate_predictions, truth, internal)
    regressions = len(set(before.pop("correct_ids")) - set(after.pop("correct_ids")))
    return {"baseline": before, "candidate": after, "regression_count": regressions,
            "dataset_sha256": digest([internal, settlements, truth]),
            "baseline_sha256": digest(base.model_dump()), "candidate_sha256": digest(candidate.model_dump())}
