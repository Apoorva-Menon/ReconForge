import time
import asyncio
from collections import Counter, defaultdict

from app.schemas import Policy
from app.tools.backtester import score
from app.tools.matcher import match


async def rows(collection, query=None):
    return await collection.find(query or {}, {"_id": 0}).to_list(None)


class AgentRepository:
    """Narrow agent-facing capability: verified memory only, never labels/raw DB."""
    def __init__(self, memory_collection):
        self.__memories = memory_collection

    async def verified_memories(self, processor, break_type, top_k=5):
        tags = [f"processor:{processor}", break_type]
        return await self.__memories.find({"verified": True, "tags": {"$all": tags}},
                                         {"_id": 0}).limit(top_k).to_list(None)


class EvaluatorRepository:
    """Only deterministic evaluation code receives this capability."""
    def __init__(self, db):
        self.db = db

    async def corpus(self, split="historical"):
        query = {"dataset_split": split}
        if split == "live":
            held_out = await self.db.evaluation_corpora.find_one({"_id": "live"})
            return held_out["internal"], held_out["settlements"], await rows(self.db.ground_truth, query)
        return (await rows(self.db.internal_ledger, query),
                await rows(self.db.processor_settlement, query),
                await rows(self.db.ground_truth, query))

    async def current_live_metrics(self, policy, position):
        """Score only the ingested live prefix; ground truth stays evaluator-only."""
        internal, settlements, truth = await self.corpus("live")
        processed = min(position, len(internal), len(settlements))
        internal_prefix = internal[:processed]
        settlement_prefix = settlements[:processed]
        internal_ids = {row["internal_record_id"] for row in internal_prefix}
        truth_prefix = [label for label in truth
                        if label["expected_internal_record_id"] in internal_ids]
        predictions = match(internal_prefix, settlement_prefix, policy.matching)
        metrics = score(predictions, truth_prefix, internal_prefix)
        # Do not expose evaluator label-linked IDs through the dashboard payload.
        metrics.pop("correct_ids", None)
        return {"position": processed, "metrics": metrics,
                "operational": predictions["summary"]}


class Repository:
    def __init__(self, db):
        self.db = db
        self.agent = AgentRepository(db.incident_memories)

    async def audit(self, run_id, action, payload=None, *, suffix="", actor="system"):
        key = f"{run_id}:{action}:{suffix}"
        await self.db.agent_action_logs.update_one({"idempotency_key": key}, {"$setOnInsert": {
            "run_id": run_id, "trace_id": run_id, "actor": actor, "action": action,
            "timestamp": time.time(), "payload": payload or {}, "idempotency_key": key}}, upsert=True)

    async def active_policy(self):
        doc = await self.db.control.find_one({"_id": "active_policy"})
        if not doc:
            raise ValueError("Seed the dataset first")
        return Policy.model_validate(doc["policy"])

    async def run(self, run_id):
        return await self.db.workflow_runs.find_one({"run_id": run_id}, {"_id": 0})

    async def stage(self, run_id, node, **fields):
        await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": {
            "current_node": node, "updated_at": time.time(), **fields}})
        await self.audit(run_id, node)

    async def reconcile(self, run_id, policy=None):
        policy = policy or await self.active_policy()
        cursor = await self.db.control.find_one({"_id": "stream"})
        end = (cursor or {}).get("position", 0)
        query = {"dataset_split": "live", "stream_index": {"$lt": end}}
        internal = await rows(self.db.internal_ledger, query)
        settlements = await rows(self.db.processor_settlement, query)
        result = match(internal, settlements, policy.matching)
        unresolved = {r["internal_record_id"]: r for r in result["cases"]}
        matched = {r["internal_record_id"]: r["processor_record_id"] for r in result["auto_matches"]}
        existing = {c["internal_record_id"]: c for c in await rows(self.db.reconciliation_cases)}
        writes = []
        for row in internal:
            record_id = row["internal_record_id"]
            case = unresolved.get(record_id) or {
                "internal_record_id": record_id, "processor_record_id": matched[record_id],
                "candidate_processor_record_ids": [matched[record_id]],
                "status": "RESOLVED_AUTO", "break_type": "MATCHED", "evidence": {}, "processor": row["processor"]}
            prior = existing.get(record_id)
            if prior and (prior["status"], prior["policy_version"], prior["break_type"]) == (case["status"], policy.version, case["break_type"]):
                continue
            case.update(case_id=f"CASE-{record_id}", policy_version=policy.version,
                        amount_cents=row["amount_cents"], currency=row["currency"], run_id=run_id,
                        trace_id=run_id, actor="matcher", updated_at=time.time())
            writes.append(self.db.reconciliation_cases.update_one({"internal_record_id": record_id}, {"$set": case}, upsert=True))
            if not prior or (prior["status"], prior["policy_version"]) != (case["status"], policy.version):
                key = f"{run_id}:{record_id}:{policy.version}:{case['status']}"
                writes.append(self.db.case_events.update_one({"idempotency_key": key}, {"$setOnInsert": {
                    "idempotency_key": key, "run_id": run_id, "trace_id": run_id, "actor": "matcher",
                    "internal_record_id": record_id, "status": case["status"], "policy_version": policy.version,
                    "timestamp": time.time()}}, upsert=True))
        for start in range(0, len(writes), 100):
            await asyncio.gather(*writes[start:start+100])
        await self.db.metric_snapshots.update_one({"_id": f"{run_id}:{policy.version}:{end}"}, {"$set": {
            "run_id": run_id, "policy_version": policy.version, "position": end,
            "timestamp": time.time(), **result["summary"]}}, upsert=True)
        return result

    async def domain_metrics(self):
        cases = await rows(self.db.reconciliation_cases)
        by_currency, by_processor = defaultdict(lambda: {"matched_cents": 0, "outstanding_cents": 0}), defaultdict(Counter)
        for case in cases:
            matched = case["status"] == "RESOLVED_AUTO"
            by_currency[case["currency"]]["matched_cents" if matched else "outstanding_cents"] += case["amount_cents"]
            by_processor[case["processor"]]["matched" if matched else "unresolved"] += 1
        resolved = sum(c["status"] == "RESOLVED_AUTO" for c in cases)
        return {"total": len(cases), "matched": resolved, "unresolved": len(cases)-resolved,
                "match_rate": resolved / max(len(cases), 1), "by_currency": dict(by_currency),
                "by_processor": dict(by_processor),
                "break_buckets": dict(Counter(c["break_type"] for c in cases if c["status"] != "RESOLVED_AUTO"))}
