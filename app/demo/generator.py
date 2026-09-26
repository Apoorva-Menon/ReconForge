"""The supplied seed-6643 fixture is authoritative; this module loads it."""
import csv
import json
from pathlib import Path

from app.schemas import Policy


class Dataset:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def load(self, name):
        return json.loads((self.directory / f"{name}.json").read_text())

    def business(self, split):
        if split not in {"historical", "live"}:
            raise ValueError("Unknown split")
        internal = self.load(f"{split}_internal_ledger")
        settlements = self.load(f"{split}_processor_settlement")
        if split == "live":
            # Lead with the known fee-drift slice so the demo reaches a real,
            # repeatable evolution incident within the first 300 streamed rows.
            truth = self.load("live_ground_truth")
            phase_order = {"fee_drift": 0, "settlement_drift": 1, "baseline": 2}
            internal_phase = {row["expected_internal_record_id"]: row.get("live_phase", "baseline")
                              for row in truth}
            settlement_phase = {row["expected_processor_record_id"]: row.get("live_phase", "baseline")
                                for row in truth}
            internal.sort(key=lambda row: (phase_order.get(internal_phase.get(row["internal_record_id"]), 3),
                                           row["internal_record_id"]))
            settlements.sort(key=lambda row: (phase_order.get(settlement_phase.get(row["processor_record_id"]), 3),
                                              row["processor_record_id"]))
        return internal, settlements

    def baseline(self):
        # The newer business specification supersedes the dataset's global policy.
        # Preserve supplied files; start with zero tolerance on each processor.
        return Policy(version="v1")

    def seed_memories(self):
        with (self.directory / "incident_memories.csv").open() as handle:
            return [{"memory_id": row["memory_id"], "summary": row["pattern_summary"],
                     "resolution": row["successful_action"], "verified": False,
                     "source": "seed_knowledge", "tags": row["tags"].split(",")}
                    for row in csv.DictReader(handle)]
