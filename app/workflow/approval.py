from google.adk.events import RequestInput
from google.adk.workflow import node


@node(name="human_approval", rerun_on_resume=False)
async def approval_node(node_input: dict):
    yield RequestInput(interrupt_id=f"approval-{node_input['run_id']}",
                       message="Approve this backtested reconciliation policy?",
                       payload=node_input)


@node(name="wait_for_data", rerun_on_resume=False)
async def wait_for_data(node_input: dict):
    yield RequestInput(interrupt_id=f"data-{node_input['run_id']}-{node_input['position']}",
                       message="Waiting for new transaction evidence", payload={**node_input, "kind": "DATA"})
