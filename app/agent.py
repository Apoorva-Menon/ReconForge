"""ADK dynamic workflow; completed child nodes are checkpointed by ADK."""
import json

from google.adk import Context, Workflow
from google.adk.apps import App, ResumabilityConfig
from google.adk.workflow import node

from app.agents import create_agents
from app.schemas import DiagnosisResult, EvolutionResult, MemoryResult
from app.workflow.approval import approval_node, wait_for_data
from app.workflow.nodes import Operations


def as_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return json.loads(value) if isinstance(value, str) else value


def create_app(repo, model_name, reasoners=None):
    agents = reasoners if reasoners is not None else create_agents(model_name)
    ops = Operations(repo)

    @node(name="reconcile")
    async def reconcile(node_input: str):
        return await ops.reconcile(node_input)

    @node(name="retrieve_memory")
    async def retrieve(node_input: dict):
        incident = node_input["incident"]
        return await repo.agent.verified_memories(incident["processor"], incident["break_type"],
                                                  node_input["policy"]["retrieval"]["memory_top_k"])

    @node(name="evaluate_candidate")
    async def evaluate(node_input: dict):
        return await ops.evaluate(node_input["run_id"], node_input["proposal"])

    @node(name="reject")
    async def reject(node_input: dict):
        return await ops.reject(node_input["run_id"], node_input["reason"])

    @node(name="promote")
    async def promote(node_input: str):
        return await ops.promote(node_input)

    @node(name="replay")
    async def replay(node_input: dict):
        return await ops.replay(node_input["run_id"], node_input["policy"])

    @node(name="write_memory")
    async def remember(node_input: dict):
        return await ops.remember(**node_input)

    @node(name="reconciliation_workflow", rerun_on_resume=True)
    async def workflow(ctx: Context, node_input):
        run_id = ctx.state["business_run_id"]
        measured = await ctx.run_node(reconcile, run_id)
        while not measured["incident"]:
            await repo.stage(run_id, "waiting_for_data", status="WAITING_FOR_DATA")
            await ctx.run_node(wait_for_data, {"run_id": run_id, "position": measured["position"]})
            measured = await ctx.run_node(reconcile, run_id)
        diagnosis = DiagnosisResult.model_validate(as_dict(await ctx.run_node(agents["diagnosis"], measured)))
        await repo.stage(run_id, "memory", diagnosis=diagnosis.model_dump())
        if diagnosis.status == "NEED_MORE_EVIDENCE" or diagnosis.confidence < measured["policy"]["escalation"]["confidence_min"]:
            return await ctx.run_node(reject, {"run_id": run_id, "reason": "Diagnosis needs stronger evidence"})
        memories = await ctx.run_node(retrieve, measured)
        interpretation = MemoryResult.model_validate(as_dict(await ctx.run_node(agents["memory"], {
            "incident": measured["incident"], "memories": memories})))
        if not set(interpretation.memory_ids) <= {m["memory_id"] for m in memories}:
            return await ctx.run_node(reject, {"run_id": run_id, "reason": "Memory agent cited unknown evidence"})
        await repo.stage(run_id, "upgrade", retrieved_memory_ids=interpretation.memory_ids)
        run = await repo.run(run_id)
        proposal = EvolutionResult.model_validate(as_dict(await ctx.run_node(agents["evolution"], {
            "policy": measured["policy"], "diagnosis": diagnosis.model_dump(),
            "evaluator_metrics": measured["evaluator_metrics"],
            "incident": measured["incident"], "memories": memories,
            "memory_interpretation": interpretation.model_dump(), "prior_attempts": run.get("prior_attempts", [])})))
        package = await ctx.run_node(evaluate, {"run_id": run_id, "proposal": proposal.model_dump()})
        if not package["evaluation"]["guardrails"]["passed"]:
            return await ctx.run_node(reject, {"run_id": run_id, "reason": "; ".join(package["evaluation"]["guardrails"]["reasons"])})
        decision = await ctx.run_node(approval_node, package)
        if as_dict(decision).get("decision") != "APPROVE":
            return await ctx.run_node(reject, {"run_id": run_id, "reason": "Human rejected candidate"})
        policy = await ctx.run_node(promote, run_id)
        result = await ctx.run_node(replay, {"run_id": run_id, "policy": policy})
        if result["status"] == "ROLLED_BACK":
            return result
        return await ctx.run_node(remember, {"run_id": run_id, "incident": measured["incident"],
                                             "policy_data": policy, "replay": result})

    return App(name="reconforge", root_agent=Workflow(name="reconforge_workflow", edges=[("START", workflow)]),
               resumability_config=ResumabilityConfig(is_resumable=True))
