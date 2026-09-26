import time


async def write_verified_memory(repo, run_id, incident, evaluation, policy):
    memory_id = f"MEM-{run_id}-{policy.version}"
    memory = {"memory_id": memory_id, "verified": True, "source": "measured_replay",
              "summary": f"{incident['processor']} {incident['break_type']} {incident['delta']}",
              "resolution": policy.matching.model_dump(), "policy_version": policy.version,
              "run_id": run_id, "trace_id": run_id, "actor": "memory_writer", "timestamp": time.time(),
              "idempotency_key": memory_id,
              "outcome": {"auto_resolution_delta": evaluation["candidate"]["auto_resolution_rate"] - evaluation["baseline"]["auto_resolution_rate"],
                          "false_match_rate": evaluation["candidate"]["false_match_rate"]},
              "tags": [f"processor:{incident['processor']}", incident["break_type"]]}
    await repo.db.incident_memories.update_one({"memory_id": memory_id}, {"$setOnInsert": memory}, upsert=True)
    await repo.audit(run_id, "memory_written", {"memory_id": memory_id})
    return memory_id
