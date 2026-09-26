"""Strict contracts: LLM output cannot alter fixed safety rules."""
from typing import Literal, Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchingPolicy(StrictModel):
    processor_amount_tolerance_cents: dict[Literal["PROC_A", "PROC_B", "PROC_C"], Annotated[int, Field(ge=0, le=25, strict=True)]] = Field(
        default_factory=lambda: {"PROC_A": 0, "PROC_B": 0, "PROC_C": 0})

    @field_validator("processor_amount_tolerance_cents")
    @classmethod
    def all_processors(cls, value):
        if set(value) != {"PROC_A", "PROC_B", "PROC_C"}:
            raise ValueError("Patch must include all three processor tolerances")
        return value


class RetrievalPolicy(StrictModel):
    memory_top_k: int = Field(default=5, ge=1, le=10, strict=True)


class EscalationPolicy(StrictModel):
    confidence_min: float = Field(default=0.7, ge=0.5, le=0.99)


class Policy(StrictModel):
    version: str
    parent: str | None = None
    matching: MatchingPolicy = Field(default_factory=MatchingPolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    escalation: EscalationPolicy = Field(default_factory=EscalationPolicy)


class DiagnosisResult(StrictModel):
    hypothesis: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    alternative_hypotheses: list[str] = Field(default_factory=list)
    requested_analyses: list[str] = Field(default_factory=list)
    status: Literal["READY_FOR_MEMORY_SEARCH", "NEED_MORE_EVIDENCE"]


class MemoryResult(StrictModel):
    memory_ids: list[str]
    relevance: str


class PolicyPatch(StrictModel):
    processor: Literal["PROC_A", "PROC_B", "PROC_C"]
    amount_tolerance_cents: int = Field(ge=0, le=25, strict=True)


class EvolutionResult(StrictModel):
    parent_version: str
    candidate_patch: PolicyPatch
    reason: str
    expected_effect: str
    risk: str
    required_eval_slices: list[str] = Field(default_factory=list)


def apply_patch(base: Policy, proposal: EvolutionResult, version: str) -> Policy:
    if proposal.parent_version != base.version:
        raise ValueError("Candidate references a stale parent policy")
    data = base.model_dump()
    data.update(version=version, parent=base.version)
    patch = proposal.candidate_patch
    data["matching"]["processor_amount_tolerance_cents"][patch.processor] = patch.amount_tolerance_cents
    return Policy.model_validate(data)
