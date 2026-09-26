from pymongo import AsyncMongoClient


def connect(settings):
    if not settings.mongodb_uri:
        raise ValueError("Set MONGODB_URI in .env before starting the backend")
    client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    return client, client[settings.mongodb_db]


async def init_indexes(db):
    for name, keys in {
        "adk_sessions": [("app_name", 1), ("user_id", 1), ("session_id", 1)],
        "adk_events": [("app_name", 1), ("user_id", 1), ("session_id", 1), ("event_id", 1)],
        "internal_ledger": [("internal_record_id", 1)],
        "processor_settlement": [("processor_record_id", 1)],
        "ground_truth": [("label_group_id", 1)],
        "reconciliation_cases": [("internal_record_id", 1)],
        "workflow_runs": [("run_id", 1)],
        "harness_policies": [("version", 1)],
        "policy_evaluations": [("run_id", 1)],
        "doorbell_events": [("event_id", 1)],
        "human_approvals": [("run_id", 1)],
        "incident_memories": [("memory_id", 1)],
        "agent_action_logs": [("idempotency_key", 1)],
        "case_events": [("idempotency_key", 1)],
    }.items():
        await db[name].create_index(keys, unique=True)
    await db.adk_events.create_index([("session_id", 1), ("seq", 1)])
    await db.workflow_runs.create_index("status")
    await db.doorbell_events.create_index([("run_id", 1), ("consumed", 1)])
    await db.internal_ledger.create_index([("dataset_split", 1), ("stream_index", 1)])
    await db.processor_settlement.create_index([("dataset_split", 1), ("stream_index", 1)])
