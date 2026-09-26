"""Detect concentration in observed evidence without evaluator labels."""
from collections import Counter, defaultdict

INCIDENT_MIN_CLUSTER_CASES = 10
INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION = 0.70


def detect_incidents(cases: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for case in cases:
        if case["break_type"] == "AMOUNT_MISMATCH" and case["evidence"]:
            groups[(case["processor"], case["break_type"])].append(case)
    incidents = []
    for (processor, kind), rows in groups.items():
        field = "amount_delta_cents"
        delta, count = Counter(r["evidence"][field] for r in rows).most_common(1)[0]
        concentration = count / len(rows)
        if (count >= INCIDENT_MIN_CLUSTER_CASES and
                concentration >= INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION):
            incidents.append({"processor": processor, "break_type": kind, "delta_field": field,
                              "delta": delta, "count": count, "cluster_size": len(rows),
                              "concentration": concentration,
                              "constant_checks_passed": {name: sum(r["evidence"]["checks"][name] for r in rows)
                                  for name in ("customer", "currency", "merchant", "processor", "reference", "date")}})
    return sorted(incidents, key=lambda i: (-i["count"], i["processor"]))
