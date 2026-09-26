"""Deterministic operations used by the ADK graph."""
import time

from app.persistence.repositories import EvaluatorRepository
from app.schemas import Policy, EvolutionResult, apply_patch
from app.tools.analytics import detect_incidents
from app.tools.backtester import compare, digest
from app.tools.guardrails import decide
from app.tools.memory_tools import write_verified_memory
from app.tools.promotion import promote, rollback


class Operations:
    def __init__(self, repo):
        self.repo = repo
        self.evaluator = EvaluatorRepository(repo.db)

    async def reconcile(self, run_id):
        run = await self.repo.run(run_id)
        policy = Policy.model_validate(run["baseline_policy"])
        await self.repo.stage(run_id, "reconcile")
        result = await self.repo.reconcile(run_id, policy)
        cursor = await self.repo.db.control.find_one({"_id": "stream"})
        incidents = detect_incidents(result["cases"])
        evaluator_state = await self.evaluator.current_live_metrics(policy, cursor["position"])
        await self.repo.stage(run_id, "diagnose", baseline_summary=result["summary"], incidents=incidents,
                              evaluator_metrics=evaluator_state["metrics"])
        return {"run_id": run_id, "position": cursor["position"], "policy": policy.model_dump(), "summary": result["summary"],
                "evaluator_metrics": evaluator_state["metrics"],
                "incident": incidents[0] if incidents else None}

    async def evaluate(self, run_id, proposal):
        await self.repo.stage(run_id, "backtest")
        run = await self.repo.run(run_id)
        base = Policy.model_validate(run["baseline_policy"])
        candidate = apply_patch(base, EvolutionResult.model_validate(proposal), f"v-{run_id}")
        if not run.get("incidents") or proposal["candidate_patch"]["processor"] != run["incidents"][0]["processor"]:
            raise ValueError("Patch must target the processor supported by this run's evidence")
        internal, settlements, truth = await self.evaluator.corpus()
        # Predictions are business-only; labels are confined to compare/score.
        evaluation = compare(base, candidate, internal, settlements, truth)
        evaluation.update(run_id=run_id, candidate_version=candidate.version,
                          baseline_version=base.version, created_at=time.time(), dataset_seed=6643)
        evaluation["guardrails"] = decide(evaluation)
        await self.repo.db.harness_policies.update_one({"version": candidate.version}, {"$setOnInsert": {
            "version": candidate.version, "policy": candidate.model_dump(), "proposal": proposal,
            "status": "ELIGIBLE_FOR_APPROVAL" if evaluation["guardrails"]["passed"] else "REJECTED",
            "patch_name": f'{proposal["candidate_patch"]["processor"]} '
                          f'{proposal["candidate_patch"]["amount_tolerance_cents"]}¢ amount tolerance',
            "created_at": time.time(), "run_id": run_id, "trace_id": run_id,
            "actor": "upgrader", "timestamp": time.time()}}, upsert=True)
        await self.repo.db.policy_evaluations.update_one({"run_id": run_id}, {"$setOnInsert": evaluation}, upsert=True)
        await self.repo.stage(run_id, "guardrails", candidate_version=candidate.version,
                              candidate_policy=candidate.model_dump(), evaluation=evaluation,
                              proposal=proposal)
        return {"run_id": run_id, "candidate_version": candidate.version,
                "policy": candidate.model_dump(), "evaluation": evaluation}

    async def reject(self, run_id, reason):
        run = await self.repo.run(run_id)
        if run.get("candidate_version"):
            await self.repo.db.harness_policies.update_one({"version": run["candidate_version"]}, {"$set": {"status": "REJECTED"}})
        await self.repo.stage(run_id, "rejected", status="REJECTED", reason=reason)
        await self.repo.audit(run_id, "rejection_reason", {"reason": reason})
        return {"status": "REJECTED", "reason": reason}

    async def promote(self, run_id):
        await self.repo.stage(run_id, "promote")
        policy = await promote(self.repo, run_id)
        return policy.model_dump()

    async def replay(self, run_id, policy_data):
        await self.repo.stage(run_id, "replay")
        candidate = Policy.model_validate(policy_data)
        run = await self.repo.run(run_id)
        base = Policy.model_validate(run["baseline_policy"])
        # Held-out live data measures generalization; labels never enter the graph output.
        internal, settlements, truth = await self.evaluator.corpus("live")
        evaluation = compare(base, candidate, internal, settlements, truth)
        check = decide(evaluation, require_improvement=False)
        await self.repo.db.policy_evaluations.update_one({"run_id": run_id}, {"$set": {"held_out": evaluation, "post_guardrails": check}})
        if not check["passed"]:
            await rollback(self.repo, run_id, candidate, check["reasons"])
            await self.repo.reconcile(run_id)
            await self.repo.stage(run_id, "rolled_back", status="ROLLED_BACK")
            return {"status": "ROLLED_BACK"}
        result = await self.repo.reconcile(run_id, candidate)
        await self.repo.stage(run_id, "memory_write", replay_summary=result["summary"])
        return {"status": "VERIFIED", "evaluation": evaluation}

    async def remember(self, run_id, incident, policy_data, replay):
        policy = Policy.model_validate(policy_data)
        memory_id = await write_verified_memory(self.repo, run_id, incident, replay["evaluation"], policy)
        await self.repo.stage(run_id, "completed", status="COMPLETED", memory_id=memory_id)
        return {"status": "COMPLETED", "memory_id": memory_id, "policy_version": policy.version}
