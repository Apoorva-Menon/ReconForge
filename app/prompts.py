DIAGNOSIS = """Return exactly one JSON object with these keys and no others:
{"hypothesis": string, "confidence": number from 0 to 1, "evidence": [string],
"alternative_hypotheses": [string], "requested_analyses": [string], "status":
"READY_FOR_MEMORY_SEARCH" or "NEED_MORE_EVIDENCE"}. No prose or Markdown.
Use only measured evidence; never invent metrics or access evaluator labels. Put
concise observed facts in evidence and a concise explanation in hypothesis. If
evidence is weak, use low confidence, explain what is missing in requested_analyses,
and set status to NEED_MORE_EVIDENCE. Do not propose or change policy."""

MEMORY = """Return exactly one JSON object with these keys and no others:
{"memory_ids": [string], "relevance": string}. No prose or Markdown. Use only
supplied verified memories. Put only supplied memory_id values in memory_ids; use
an empty list when none match. Keep relevance to one short sentence. Do not echo the
incident, records, or memory contents. Do not invent outcomes or override safety
checks or human approval."""

EVOLUTION = """Return exactly one JSON object with all six keys shown below and no others:
{
  "parent_version": "string copied from policy.version",
  "candidate_patch": {
    "processor": "PROC_A or PROC_B or PROC_C",
    "amount_tolerance_cents": integer from 0 to 25
  },
  "reason": "short string",
  "expected_effect": "short string",
  "risk": "short string",
  "required_eval_slices": ["string"]
}
Every key is required, including reason, expected_effect, and risk. Use an empty
array for required_eval_slices when appropriate. No prose or Markdown outside the
JSON object.

Propose exactly one patch using the observed incident, current policy, diagnosis,
and aggregate evaluator metrics. The processor must equal the incident processor.
Choose the smallest tolerance supported by the signed delta (for example, 3 cents
for a stable -3 cent fee). Explain the evidence in reason, the intended change in
expected_effect, and a concrete downside in risk. Do not change other processors,
fixed matching checks, dates, references, guardrails, or labels. Metrics are
aggregates only; never infer or request per-record ground-truth labels. The patch is
only a candidate: independent backtesting and human approval are still required."""
