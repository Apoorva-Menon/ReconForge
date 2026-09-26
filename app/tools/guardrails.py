"""Fixed vetoes; never configurable through model output."""


def decide(evaluation: dict, *, require_improvement: bool = True) -> dict:
    base, candidate = evaluation["baseline"], evaluation["candidate"]
    reasons = []
    # Dataset policy's 1,000 minimum is stricter than the PDF's 500 example.
    if candidate["sample_size"] < 1000:
        reasons.append("insufficient sample (minimum 1000)")
    if candidate["false_match_rate"] > 0.005:
        reasons.append("false-match rate exceeds 0.5%")
    if candidate["false_match_rate"] > base["false_match_rate"] + 0.001:
        reasons.append("false-match regression exceeds 0.1 percentage points")
    if candidate["high_value_false_matches"]:
        reasons.append("high-value false match")
    if evaluation["regression_count"]:
        reasons.append("previously correct matches regressed")
    if require_improvement and candidate["auto_resolution_rate"] < base["auto_resolution_rate"] + 0.03:
        reasons.append("improvement below 3 percentage points")
    return {"passed": not reasons, "reasons": reasons, "requires_human": not reasons}
