"""Idempotent seed and independent ingestion cursor."""
import time
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.persistence.repositories import Repository


async def seed(db, dataset):
    # _id upserts make interrupted imports repeatable without clearing existing data.
    for split in ("historical", "live"):
        internal, settlements = dataset.business(split)
        if split == "live":
            await db.evaluation_corpora.update_one({"_id": "live"}, {"$setOnInsert": {
                "internal": internal, "settlements": settlements}}, upsert=True)
        for name, records, id_field in [("internal_ledger", internal, "internal_record_id"),
                                         ("processor_settlement", settlements, "processor_record_id")]:
            # Live business data is added exclusively by the separate stream.
            if split == "live":
                continue
            existing = {r[id_field] async for r in db[name].find({}, {id_field: 1})}
            pending = [{**r, "dataset_split": split} for r in records if r[id_field] not in existing]
            if pending:
                await db[name].insert_many(pending, ordered=False)
        # Evaluation truth is stored separately and never exposed through agent tools.
        records = dataset.load(f"{split}_ground_truth")
        existing = {r["label_group_id"] async for r in db.ground_truth.find({}, {"label_group_id": 1})}
        pending = [r for r in records if r["label_group_id"] not in existing]
        if pending:
            await db.ground_truth.insert_many(pending, ordered=False)
    base = dataset.baseline()
    await db.harness_policies.update_one({"version": base.version}, {"$setOnInsert": {
        "version": base.version, "status": "ACTIVE", "patch_name": "Zero-tolerance baseline",
        "policy": base.model_dump(), "created_at": time.time()}}, upsert=True)
    await db.control.update_one({"_id": "active_policy"}, {"$setOnInsert": {"policy": base.model_dump(), "operations": []}}, upsert=True)
    await db.control.update_one({"_id": "stream"}, {"$setOnInsert": {"position": 0, "total": 1500}}, upsert=True)
    await db.control.update_one({"_id": "engine"}, {"$setOnInsert": {"enabled": False, "interval_seconds": 15}}, upsert=True)
    for memory in dataset.seed_memories():
        await db.incident_memories.update_one({"memory_id": memory["memory_id"]}, {"$setOnInsert": memory}, upsert=True)
    await Repository(db).audit("seed", "dataset_loaded", {"seed": 6643})
    return {"seed": 6643, "historical_records": 8000, "stream_total": 1500}


async def advance(db, dataset, count):
    cursor = await db.control.find_one({"_id": "stream"})
    if not cursor:
        raise ValueError("Seed the dataset first")
    owner = str(uuid4())
    claimed = await db.control.find_one_and_update({"_id": "stream", "$or": [
        {"lease_until": {"$lt": time.time()}}, {"lease_until": {"$exists": False}}]},
        {"$set": {"lease_until": time.time()+120, "lease_owner": owner}}, return_document=ReturnDocument.AFTER)
    if not claimed:
        raise ValueError("Another stream batch is being ingested")
    try:
        start, end = claimed["position"], min(1500, claimed["position"] + count)
        internal, settlements = dataset.business("live")
        for name, records, id_field in [("internal_ledger", internal, "internal_record_id"),
                                         ("processor_settlement", settlements, "processor_record_id")]:
            for i in range(start, end):
                record = {**records[i], "dataset_split": "live", "stream_index": i}
                await db[name].update_one({id_field: record[id_field]}, {"$setOnInsert": record}, upsert=True)
        # Data is committed before the cursor becomes visible to the reconciler.
        await db.control.update_one({"_id": "stream", "lease_owner": owner},
            {"$set": {"position": end, "updated_at": time.time()}})
        event_id = f"data:{start}:{end}"
        await db.doorbell_events.update_one({"event_id": event_id}, {"$setOnInsert": {
            "event_id": event_id, "kind": "DATA", "position": end, "consumed": False, "timestamp": time.time()}}, upsert=True)
        await Repository(db).audit("stream", "batch_arrived", {"start": start, "end": end}, suffix=event_id)
        return {"start": start, "position": end, "total": 1500}
    finally:
        await db.control.update_one({"_id": "stream", "lease_owner": owner},
            {"$unset": {"lease_owner": "", "lease_until": ""}})
