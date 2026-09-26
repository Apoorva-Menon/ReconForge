"""Fixed business checks, deduplication, and one-to-one safety."""
from collections import Counter, defaultdict
from datetime import date

from app.schemas import MatchingPolicy
from app.tools.business import make_match_decision, normalize_reference

BUSINESS_FIELDS = ("merchant_id", "customer_id", "processor", "channel", "country",
                   "amount_cents", "currency", "settlement_date", "reference")


def deduplicate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in BUSINESS_FIELDS)].append(row)
    originals, duplicates = [], []
    for group in groups.values():
        group.sort(key=lambda r: r["received_time"])
        if len(group) > 1 and group[0]["received_time"] == group[1]["received_time"]:
            originals.extend(group)
            continue
        originals.append(group[0])
        duplicates.extend({"processor_record_id": r["processor_record_id"],
                           "canonical_id": group[0]["processor_record_id"]} for r in group[1:])
    return originals, duplicates


def match(internal: list[dict], settlements: list[dict], policy: MatchingPolicy) -> dict:
    canonical, duplicates = deduplicate(settlements)
    index = defaultdict(list)
    for row in canonical:
        index[normalize_reference(row["reference"])].append(row)
    provisional, cases = [], []
    check_counts = defaultdict(Counter)
    for row in internal:
        candidates = index.get(normalize_reference(row["reference"]), [])
        accepted, evidence = [], []
        for other in candidates:
            decision = make_match_decision(row, other, policy)
            for name, passed in decision["checks"].items():
                check_counts[name]["pass" if passed else "fail"] += 1
            item = {"processor": row["processor"],
                    "amount_delta_cents": other["amount_cents"] - row["amount_cents"],
                    "date_delta_days": (date.fromisoformat(other["settlement_date"]) - date.fromisoformat(row["settlement_date"])).days,
                    "tolerance_cents": policy.processor_amount_tolerance_cents.get(row["processor"], 0),
                    "checks": decision["checks"]}
            evidence.append(item)
            if decision["decision"] == "MATCH":
                accepted.append(other)
        case = {"internal_record_id": row["internal_record_id"],
                "candidate_processor_record_ids": [r["processor_record_id"] for r in candidates],
                "processor": row["processor"], "evidence": evidence[0] if len(evidence) == 1 else {},
                "status": "OPEN", "break_type": "NO_CANDIDATE"}
        if len(accepted) == 1:
            provisional.append({"internal_record_id": row["internal_record_id"],
                                "processor_record_id": accepted[0]["processor_record_id"], "case": case})
        else:
            if len(accepted) > 1 or len(candidates) > 1:
                case["break_type"] = "AMBIGUOUS"
            elif evidence:
                reasons = {"customer": "CUSTOMER_MISMATCH", "currency": "CURRENCY_MISMATCH",
                           "merchant": "MERCHANT_MISMATCH", "processor": "PROCESSOR_MISMATCH",
                           "reference": "REFERENCE_MISMATCH", "date": "DATE_BOUNDARY", "amount_patch": "AMOUNT_MISMATCH"}
                case["break_type"] = next(reason for key, reason in reasons.items() if not evidence[0]["checks"][key])
            cases.append(case)
    counts = Counter(p["processor_record_id"] for p in provisional)
    matches = []
    for p in provisional:
        if counts[p["processor_record_id"]] > 1:
            p["case"]["break_type"] = "AMBIGUOUS"
            cases.append(p["case"])
        else:
            matches.append({k: v for k, v in p.items() if k != "case"})
    return {"auto_matches": matches, "cases": cases, "duplicates": duplicates,
            "summary": {"total": len(internal), "matched": len(matches), "unresolved": len(cases),
                        "duplicates": len(duplicates), "check_counts": dict(check_counts),
                        "break_buckets": dict(Counter(c["break_type"] for c in cases))}}
