"""Mongo-backed leases and doorbells wrap ADK's own checkpoint/replay semantics."""
import asyncio
from contextlib import asynccontextmanager, suppress
import time
from uuid import uuid4

from google.adk.runners import Runner
from google.genai import types
from app.error_details import error_details
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.agent import create_app
from app.persistence.mongo_session_service import MongoSessionService
from app.persistence.repositories import EvaluatorRepository, Repository, rows
from app.tools.analytics import (INCIDENT_MIN_CLUSTER_CASES,
                                 INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION,
                                 detect_incidents)

TERMINAL = {"COMPLETED", "REJECTED", "ROLLED_BACK"}


class BusyError(ValueError):
    pass


@asynccontextmanager
async def engine_lease(db):
    owner = str(uuid4())
    try:
        locked = await db.control.find_one_and_update({"_id": "engine_lease", "$or": [
            {"expires_at": {"$lt": time.time()}}, {"owner": owner}]},
            {"$set": {"owner": owner, "expires_at": time.time()+90}}, upsert=True,
            return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        raise BusyError("Evaluator is running; retry shortly") from None

    caller = asyncio.current_task()

    async def heartbeat():
        while True:
            await asyncio.sleep(20)
            try:
                result = await db.control.update_one({"_id": "engine_lease", "owner": owner},
                    {"$set": {"expires_at": time.time()+90}})
                if not result.matched_count:
                    caller.cancel()
                    return
            except Exception:
                caller.cancel()
                return

    task = asyncio.create_task(heartbeat())
    try:
        yield locked
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await db.control.delete_one({"_id": "engine_lease", "owner": owner})


class Controller:
    def __init__(self, db, settings, reasoners=None):
        self.db = db
        self.settings = settings
        self.repo = Repository(db)
        self.evaluator = EvaluatorRepository(db)
        self.sessions = MongoSessionService(db)
        self.reasoners = reasoners

    def runner(self):
        return Runner(app=create_app(self.repo, self.settings.model_name, self.reasoners), session_service=self.sessions)

    async def start(self):
        async with engine_lease(self.db):
            # ERROR runs remain in history, but must not block a fresh run.
            # Their ADK checkpoints may be incompatible with newer workflow code.
            waiting = await self.db.workflow_runs.find_one({"status": {"$in": ["RUNNING", "WAITING_APPROVAL", "WAITING_FOR_DATA"]}})
            if waiting:
                raise BusyError("Resume or resolve the existing workflow before starting another")
            return await self._start()

    async def _start(self):
        # Validate model access configuration before writing a run.
        runner = self.runner()
        policy = await self.repo.active_policy()
        run_id = str(uuid4())
        session_id = f"session-{run_id}"
        prior = await self.db.workflow_runs.find({"status": "REJECTED"}, {"_id": 0, "proposal": 1, "reason": 1}).sort("updated_at", -1).limit(3).to_list(None)
        cursor = await self.db.control.find_one({"_id": "stream"})
        evaluator_state = await self.db.evaluator_decisions.find_one(
            {"_id": f"{cursor['position']}:{policy.version}"}, {"_id": 0})
        await self.sessions.create_session(app_name="reconforge", user_id="demo-user", session_id=session_id,
                                           state={"business_run_id": run_id})
        await self.db.workflow_runs.insert_one({"run_id": run_id, "session_id": session_id,
            "user_id": "demo-user", "invocation_id": None, "status": "RUNNING", "current_node": "start",
            "created_at": time.time(), "updated_at": time.time(), "position": cursor["position"],
            "baseline_policy": policy.model_dump(), "baseline_evaluator": evaluator_state,
            "prior_attempts": prior})
        await self._execute(run_id, runner, types.Content(role="user", parts=[types.Part(text="Evaluate reconciliation and propose a safe improvement.")]))
        return await self.repo.run(run_id)

    async def _execute(self, run_id, runner, message=None):
        run = await self.repo.run(run_id)
        await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": {"status": "RUNNING"}})
        try:
            async for event in runner.run_async(user_id=run["user_id"], session_id=run["session_id"],
                                                invocation_id=run.get("invocation_id"), new_message=message):
                # Runner has already durably appended this event through MongoSessionService.
                fields = {"invocation_id": event.invocation_id, "updated_at": time.time()}
                for call in event.get_function_calls():
                    if call.name == "adk_request_input":
                        kind = (call.args.get("payload") or {}).get("kind", "APPROVAL")
                        fields.update(status="WAITING_FOR_DATA" if kind == "DATA" else "WAITING_APPROVAL",
                                      current_node="waiting_for_data" if kind == "DATA" else "human_approval",
                                      interrupt_id=call.id, wait_kind=kind)
                await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": fields})
                if any(call.name == "adk_request_input" and
                       (call.args.get("payload") or {}).get("kind", "APPROVAL") == "APPROVAL"
                       for call in event.get_function_calls()):
                    await self.db.workflow_runs.update_one(
                        {"run_id": run_id, "approval_wait_started_at": {"$exists": False}},
                        {"$set": {"approval_wait_started_at": time.time()}})
        except Exception as exc:
            details = error_details(exc)
            await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": {
                "status": "ERROR", "error": details["type"], "error_details": details,
                "updated_at": time.time()}})
            raise

    async def approve(self, run_id, decision, actor="demo-user"):
        async with engine_lease(self.db):
            run = await self.repo.run(run_id)
            if not run:
                raise ValueError("Unknown run")
            if decision == "MORE_EVIDENCE":
                if run["status"] != "WAITING_APPROVAL":
                    raise ValueError("Run is not awaiting approval")
                cursor = await self.db.control.find_one({"_id": "stream"})
                await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": {
                    "evidence_requested": True, "evidence_requested_position": cursor["position"]}})
                await self.repo.audit(run_id, "more_evidence_requested", {"position": cursor["position"]},
                                      suffix=str(cursor["position"]), actor=actor)
                return await self.repo.run(run_id)
            if decision not in {"APPROVE", "REJECT"}:
                raise ValueError("Unknown decision")
            existing = await self.db.human_approvals.find_one({"run_id": run_id})
            if existing and existing["decision"] != decision:
                raise ValueError("A different decision is already recorded for this run")
            if run["status"] in TERMINAL:
                return run
            if run["status"] != "WAITING_APPROVAL" and not existing:
                raise ValueError("Run is not awaiting approval")
            await self.db.human_approvals.update_one({"run_id": run_id}, {"$setOnInsert": {
                "run_id": run_id, "decision": decision, "candidate": run["candidate_version"],
                "actor": actor, "timestamp": time.time(), "idempotency_key": f"{run_id}:approval"}}, upsert=True)
            event_id = f"{run_id}:approval"
            await self.db.doorbell_events.update_one({"event_id": event_id}, {"$setOnInsert": {
                "event_id": event_id, "run_id": run_id, "kind": "APPROVAL", "decision": decision,
                "consumed": False, "timestamp": time.time()}}, upsert=True)
            return await self._resume(run_id)

    async def resume(self, run_id):
        async with engine_lease(self.db):
            return await self._resume(run_id)

    async def _resume(self, run_id):
        run = await self.repo.run(run_id)
        if not run:
            raise ValueError("Unknown run")
        if run["status"] in TERMINAL:
            await self.db.doorbell_events.update_many({"run_id": run_id}, {"$set": {"consumed": True}})
            return run
        session = await self.sessions.get_session(app_name="reconforge", user_id=run["user_id"], session_id=run["session_id"])
        # Recover metadata if the process died after committing an ADK event but before indexing it.
        if not run.get("invocation_id") and session.events:
            run["invocation_id"] = session.events[-1].invocation_id
            await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": {"invocation_id": run["invocation_id"]}})
        responses = {r.id for e in session.events for r in e.get_function_responses()}
        pending = [fc for e in session.events for fc in e.get_function_calls()
                   if fc.name == "adk_request_input" and fc.id not in responses]
        message = None
        if pending:
            call = pending[-1]
            kind = (call.args.get("payload") or {}).get("kind", "APPROVAL")
            if kind == "DATA":
                cursor = await self.db.control.find_one({"_id": "stream"})
                position = (call.args.get("payload") or {}).get("position", run["position"])
                if cursor["position"] <= position:
                    return await self.repo.run(run_id)
                response = {"position": cursor["position"]}
                event_id = f"{run_id}:data:{cursor['position']}"
                await self.db.doorbell_events.update_one({"event_id": event_id}, {"$setOnInsert": {
                    "event_id": event_id, "run_id": run_id, "kind": "DATA", "consumed": False,
                    "timestamp": time.time(), "position": cursor["position"]}}, upsert=True)
            else:
                approval = await self.db.human_approvals.find_one({"run_id": run_id})
                if not approval:
                    await self.db.workflow_runs.update_one({"run_id": run_id}, {"$set": {
                        "status": "WAITING_APPROVAL", "interrupt_id": call.id, "wait_kind": "APPROVAL"}})
                    return await self.repo.run(run_id)
                response = {"decision": approval["decision"]}
            message = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                name="adk_request_input", id=call.id, response=response))])
        if not session.events:
            message = types.Content(role="user", parts=[types.Part(text="Evaluate reconciliation.")])
        await self._execute(run_id, self.runner(), message)
        await self.db.doorbell_events.update_many({"run_id": run_id, "consumed": False},
                                                 {"$set": {"consumed": True, "consumed_at": time.time()}})
        return await self.repo.run(run_id)

    async def tick(self):
        async with engine_lease(self.db):
            policy = await self.repo.active_policy()
            cursor = await self.db.control.find_one({"_id": "stream"})
            # Reconciliation keeps processing new data while an upgrade waits for approval.
            measured = await self.repo.reconcile(f"stream-{cursor['position']}-{policy.version}", policy)
            incidents = detect_incidents(measured["cases"])
            current_evaluation = await self.evaluator.current_live_metrics(policy, cursor["position"])
            live_metrics = current_evaluation["metrics"]
            accuracy_threshold = 0.90
            min_evaluation_records = 100
            accuracy_triggered = (
                live_metrics["sample_size"] >= min_evaluation_records
                and live_metrics["accuracy"] < accuracy_threshold
            )
            evolution_triggered = bool(incidents) or accuracy_triggered
            decision = "REQUEST_UPGRADE" if evolution_triggered else "KEEP_CURRENT_PATCH"
            await self.db.evaluator_decisions.update_one({"_id": f"{cursor['position']}:{policy.version}"}, {"$set": {
                "timestamp": time.time(), "position": cursor["position"], "policy_version": policy.version,
                "active_policy": policy.model_dump(), "decision": decision, "incidents": incidents,
                "summary": measured["summary"], "current_metrics": current_evaluation["metrics"],
                "current_score": current_evaluation["metrics"]["score"],
                "current_operational": current_evaluation["operational"],
                "evolution_threshold": {
                    "min_evaluator_accuracy": accuracy_threshold,
                    "min_evaluation_records": min_evaluation_records,
                    "current_accuracy": live_metrics["accuracy"],
                    "accuracy_triggered": accuracy_triggered,
                    "min_cluster_cases": INCIDENT_MIN_CLUSTER_CASES,
                    "min_signed_delta_concentration": INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION,
                    "triggered": evolution_triggered,
                    "observed_clusters": incidents}}}, upsert=True)
            waiting = await self.db.workflow_runs.find_one({"status": {"$in": ["RUNNING", "WAITING_APPROVAL", "WAITING_FOR_DATA"]}})
            if waiting:
                if waiting.get("evidence_requested") and cursor["position"] > waiting.get("evidence_requested_position", 0):
                    await self.db.workflow_runs.update_one({"run_id": waiting["run_id"]}, {"$set": {
                        "additional_evidence": {"position": cursor["position"], "summary": measured["summary"], "incidents": incidents}}})
                return await self._resume(waiting["run_id"])
            engine = await self.db.control.find_one({"_id": "engine"})
            if not (engine or {}).get("enabled"):
                return {"status": "IDLE"}
            if not evolution_triggered:
                return {"status": "AWAITING_EVOLUTION_TRIGGER", "position": cursor["position"],
                        "accuracy": live_metrics["accuracy"], "accuracy_threshold": accuracy_threshold,
                        "incidents": incidents}
            # Bounded attempts avoid charging indefinitely for the same unchanged evidence.
            attempts = await self.db.workflow_runs.count_documents({"position": cursor["position"], "baseline_policy.version": policy.version})
            if attempts >= 3:
                return {"status": "AWAITING_NEW_EVIDENCE", "attempts": attempts}
            return await self._start()
