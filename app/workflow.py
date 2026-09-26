"""Bounded ADK workflow and explicit state transition contract."""

WORKFLOW_STATES = (
    "MATCHING",
    "PATTERN_DETECTED",
    "DIAGNOSING",
    "PROPOSING",
    "BACKTESTING",
    "WAITING_FOR_APPROVAL",
    "PROMOTING",
    "REPLAYING",
    "OBSERVING",
    "COMPLETED",
)


def build_workflow():
    """Construct the workflow using the installed Google ADK workflow API."""
    raise NotImplementedError("Wire bounded ADK transitions after checking the installed API")
