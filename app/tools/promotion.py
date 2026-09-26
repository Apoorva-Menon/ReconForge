"""Atomic active-policy pointer; immutable versions provide rollback targets."""
import time

from app.schemas import Policy
from app.tools.backtester import digest


async def promote(repo, run_id):
    db = repo.db
    run = await repo.run(run_id)
    approval = await db.human_approvals.find_one({"run_id": run_id})
    evaluation = await db.policy_evaluations.find_one({"run_id": run_id})
    if not approval or approval["decision"] != "APPROVE" or not evaluation or not evaluation["guardrails"]["passed"]:
        raise ValueError("Promotion requires a passing evaluation and recorded human approval")
    candidate_doc = await db.harness_policies.find_one({"version": run["candidate_version"]})
    candidate = Policy.model_validate(candidate_doc["policy"])
    if digest(candidate.model_dump()) != evaluation["candidate_sha256"]:
        raise ValueError("Candidate changed after evaluation")
    pointer = await db.control.find_one({"_id": "active_policy"})
    key = f"{run_id}:promote"
    if key not in pointer.get("operations", []):
        result = await db.control.update_one({"_id": "active_policy", "policy.version": candidate.parent},
            {"$set": {"policy": candidate.model_dump(), "updated_at": time.time()},
             "$addToSet": {"operations": key}})
        if not result.modified_count:
            raise ValueError("Active policy changed; candidate needs a fresh backtest")
    await db.harness_policies.update_one({"version": candidate.parent}, {"$set": {"status": "ARCHIVED"}})
    await db.harness_policies.update_one({"version": candidate.version}, {"$set": {"status": "ACTIVE"}})
    await repo.audit(run_id, "promoted", {"version": candidate.version, "parent": candidate.parent})
    return candidate


async def rollback(repo, run_id, candidate, reason):
    parent = await repo.db.harness_policies.find_one({"version": candidate.parent})
    key = f"{run_id}:rollback"
    pointer = await repo.db.control.find_one({"_id": "active_policy"})
    if key not in pointer.get("operations", []):
        result = await repo.db.control.update_one({"_id": "active_policy", "policy.version": candidate.version},
            {"$set": {"policy": parent["policy"], "updated_at": time.time()}, "$addToSet": {"operations": key}})
        if not result.modified_count:
            raise ValueError("Cannot roll back a superseded policy")
    await repo.db.harness_policies.update_one({"version": candidate.version}, {"$set": {"status": "ROLLED_BACK"}})
    await repo.db.harness_policies.update_one({"version": candidate.parent}, {"$set": {"status": "ACTIVE"}})
    await repo.audit(run_id, "rolled_back", {"reason": reason})
