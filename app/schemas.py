"""Pydantic contracts for records, policies, workflow state, and results."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TransactionRecord(BaseModel):
    transaction_id: str
    amount: float
    currency: str
    date: datetime
    customer_id: str
    reference: str


class TransactionPair(BaseModel):
    pair_id: str
    internal: TransactionRecord
    external: TransactionRecord
    ground_truth_match: bool
    anomaly_type: Literal["exact", "fee_difference", "t_plus_one", "reference_format", "true_mismatch"]


class MatchingPolicy(BaseModel):
    amount_tolerance: float = 0.0
    settlement_day_tolerance: int = 0
    reference_similarity: float = 0.95


class AutomationPolicy(BaseModel):
    auto_resolution_confidence: float = 0.97
    requires_human_approval: bool = True


class Guardrails(BaseModel):
    max_false_match_rate: float = 0.005
    max_false_match_delta: float = 0.001
    min_backtest_samples: int = 1000


class PolicyVersion(BaseModel):
    version: str
    matching: MatchingPolicy
    automation: AutomationPolicy
    guardrails: Guardrails
    status: Literal["candidate", "active", "archived", "rejected"] = "candidate"


class WorkflowCheckpoint(BaseModel):
    run_id: str
    state: Literal["WAITING_FOR_APPROVAL", "WAITING_FOR_EVIDENCE"]
    cluster_id: str
    active_policy_version: str
    candidate_policy_version: str | None = None
    diagnosis: dict | None = None
    backtest_result_id: str | None = None
    pending_event: str
    resume_node: str
    updated_at: datetime


class BacktestResult(BaseModel):
    current_policy_version: str
    candidate_policy_version: str
    dataset_id: str
    evaluated_samples: int
    current_auto_resolution: float
    candidate_auto_resolution: float
    current_false_match_rate: float
    candidate_false_match_rate: float
    current_unresolved: int
    candidate_unresolved: int
    eligible_for_approval: bool
    gate_reasons: list[str]
