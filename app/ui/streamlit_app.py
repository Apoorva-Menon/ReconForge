"""Four views over API state. Closing the UI never stops a persisted workflow."""
import os
import time
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
API = os.getenv("RECONFORGE_API_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("RECONFORGE_API_TOKEN", "")
st.set_page_config(page_title="ReconForge", page_icon="↔", layout="wide")


def request(path, data=None):
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    try:
        with httpx.Client(timeout=180, headers=headers) as client:
            response = client.get(API+path) if data is None else client.post(API+path, json=data)
            if response.is_error:
                st.error(response.json().get("detail", "API request failed"))
                return None
            return response.json()
    except (httpx.HTTPError, ValueError):
        st.error("Cannot reach the backend. Start the API and check its configuration.")
        return None


def action(label, path, data, key=None, kind="secondary"):
    if st.button(label, key=key, type=kind):
        with st.spinner("Saving and processing…"):
            result = request(path, data)
        if result is not None:
            st.rerun()


def frame(records):
    return pd.DataFrame(records)


def policy_name(policy):
    return policy.get("patch_name") or (
        "Zero-tolerance baseline" if policy.get("version") == "v1" else policy.get("version", "Unnamed patch"))


def elapsed_label(started_at):
    seconds = max(0, int(time.time() - started_at))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def data_or_stop():
    data = request("/dashboard")
    if data is None:
        st.info("Add MONGODB_URI and GOOGLE_API_KEY to the project .env, then restart the API.")
        st.stop()
    return data


def sidebar():
    data = data_or_stop()
    with st.sidebar:
        st.title("ReconForge")
        st.caption("Seven fixed checks · one evolving patch")
        stream = data["stream"]
        position = stream["position"]
        st.progress(position / 1500, text=f"Stream: {position:,} / 1,500")
        phase = ("Fee drift (early demo signal)" if position < 600 else
                 "Settlement drift" if position < 1100 else
                 "Baseline" if position < 1500 else "Stream complete")
        st.caption(phase)
        if data["active_policy"]:
            st.caption(f"Active patch: {data.get('active_patch_name') or data['active_policy']['version']} ({data['active_policy']['version']})")
        else:
            st.info("Loading the dataset…")
        st.caption("Data collection and evaluation run automatically.")
        st.caption("Your action: review a candidate and approve or reject it.")
        if data["engine"].get("last_error"):
            st.warning(f"Last evaluator error: {data['engine']['last_error']}")


@st.fragment(run_every="5s")
def evaluation_content():
    data = data_or_stop()
    domain = data["domain"]
    stream = data["stream"]
    active_policy = data["active_policy"] or {}
    evaluator = data.get("current_evaluation") or {}
    live_metrics = evaluator.get("current_metrics", {})

    st.subheader("Current reconciliation and evaluator status")
    top = st.columns(5)
    top[0].metric("Records processed", f"{stream['position']:,} / {stream['total']:,}")
    top[1].metric("Records in trouble", f"{domain['unresolved']:,}")
    top[2].metric("Current patch", data.get("active_patch_name") or active_policy.get("version", "Loading"))
    top[3].metric("Evaluator score", f"{live_metrics.get('score', 0):.2%}" if live_metrics else "Pending",
                  "match-decision accuracy")
    top[4].metric("Evaluator sample", f"{live_metrics.get('sample_size', 0):,}")

    detail = st.columns(2)
    with detail[0]:
        st.markdown("**Current evaluator metrics**")
        if live_metrics:
            st.dataframe(frame([
                {"Metric": "Accuracy / score", "Value": f"{live_metrics.get('accuracy', 0):.2%}"},
                {"Metric": "Correct auto-resolution", "Value": f"{live_metrics.get('auto_resolution_rate', 0):.2%}"},
                {"Metric": "Precision", "Value": f"{live_metrics.get('precision', 0):.2%}"},
                {"Metric": "Recall", "Value": f"{live_metrics.get('recall', 0):.2%}"},
                {"Metric": "False-match rate", "Value": f"{live_metrics.get('false_match_rate', 0):.2%}"},
                {"Metric": "Unresolved", "Value": f"{live_metrics.get('unresolved', 0):,}"},
            ]), hide_index=True)
        else:
            st.info("Evaluator scores appear as the live stream is processed.")
        if active_policy:
            st.caption("Active processor amount tolerances")
            st.json(active_policy.get("matching", {}).get("processor_amount_tolerance_cents", {}))
    with detail[1]:
        st.markdown("**Open issue breakdown**")
        buckets = domain.get("break_buckets", {})
        if buckets:
            st.dataframe(frame([{"Mismatch / exception": name, "Records": count}
                                for name, count in sorted(buckets.items(), key=lambda row: -row[1])]), hide_index=True)
        else:
            st.success("No unresolved mismatch cases in the processed records.")
        threshold = evaluator.get("evolution_threshold", {})
        st.markdown("**Evolver trigger threshold**")
        st.write(f"Evolution starts when evaluator accuracy falls below **{threshold.get('min_evaluator_accuracy', 0.90):.0%}** "
                 f"(after {threshold.get('min_evaluation_records', 100)} records), or when at least "
                 f"**{threshold.get('min_cluster_cases', 10)}** same-processor amount breaks share a signed delta "
                 f"at **{threshold.get('min_signed_delta_concentration', 0.70):.0%}** concentration.")
        if threshold.get("triggered"):
            st.warning("Threshold met; the Diagnosis and Upgrader agents are evaluating a bounded patch.")
        elif evaluator:
            st.caption("Threshold not met. The current patch stays active.")

    st.caption("Ground-truth labels are used by deterministic evaluator code for scores and backtests; agent inputs contain aggregate metrics and business evidence, not label IDs or row labels.")
    st.caption("Evaluator score = correct match decisions divided by evaluated records; it counts correct matches and correctly rejected negative examples.")
    score_history = []
    seen_snapshots = set()
    for snapshot in data.get("decisions", []):
        identity = (snapshot.get("position"), snapshot.get("policy_version"))
        if identity in seen_snapshots or not snapshot.get("current_metrics"):
            continue
        seen_snapshots.add(identity)
        metrics = snapshot["current_metrics"]
        score_history.append({"Records processed": snapshot.get("position", 0),
                             "Current patch accuracy": metrics.get("accuracy", 0) * 100,
                             "Correct auto-resolution": metrics.get("auto_resolution_rate", 0) * 100})
    if score_history:
        st.subheader("Live evaluator score over processed records")
        chart = frame(sorted(score_history, key=lambda row: row["Records processed"]))
        st.line_chart(chart.set_index("Records processed"), y_label="Rate (%)")
    evaluations = data["evaluations"]
    if not evaluations:
        st.info("Backtest results will appear when the evaluator finds a stable amount-break pattern and the upgrader proposes a patch.")
    else:
        last = evaluations[-1]
        base, candidate = last["baseline"], last["candidate"]
        cols = st.columns(5)
        cols[0].metric("Candidate accuracy", f"{candidate.get('accuracy', 0):.2%}", f"{(candidate.get('accuracy', 0)-base.get('accuracy', 0))*100:+.2f} pp")
        cols[1].metric("Correct auto-resolution", f"{candidate['auto_resolution_rate']:.2%}", f"{(candidate['auto_resolution_rate']-base['auto_resolution_rate'])*100:+.2f} pp")
        cols[2].metric("False-match rate", f"{candidate['false_match_rate']:.2%}")
        cols[3].metric("Backtest records", f"{candidate['sample_size']:,}")
        cols[4].metric("Guardrails", "PASS" if last["guardrails"]["passed"] else "FAIL")
        chart = [{"Attempt": i+1, "Current patch accuracy": e["baseline"].get("accuracy", 0)*100,
                  "Candidate accuracy": e["candidate"].get("accuracy", 0)*100} for i, e in enumerate(evaluations)]
        st.subheader("Historical backtest accuracy")
        st.line_chart(frame(chart).set_index("Attempt"), y_label="Match-decision accuracy (%)")
        st.caption("Candidate results are proposals. Only approved patches become active.")
        for i, e in reversed(list(enumerate(evaluations))):
            with st.expander(f"Attempt {i+1} · {'PASS' if e['guardrails']['passed'] else 'FAIL'} · {e['candidate_version']}"):
                st.dataframe(frame([{ "Metric": key, "Baseline": e["baseline"][key], "Candidate": e["candidate"][key]}
                    for key in ("accuracy", "auto_resolution_rate", "precision", "recall", "false_match_rate", "correct_auto", "false_auto", "unresolved", "high_value_false_matches")]), hide_index=True)
                st.write("Guardrail reasons:", e["guardrails"]["reasons"] or ["All fixed guardrails passed"])
                st.write("Processor and failure-pattern slices")
                st.dataframe(frame([{ "Slice": k, **v} for k, v in e["candidate"]["slices"].items()]), hide_index=True)
                if e.get("held_out"):
                    held_out = e["held_out"]["candidate"]
                    st.write("Post-promotion live score", {
                        "accuracy": held_out.get("accuracy"),
                        "correct_auto_resolution": held_out.get("auto_resolution_rate"),
                        "false_match_rate": held_out.get("false_match_rate"),
                    })
                st.caption(f"Dataset SHA256: {e['dataset_sha256']}")
    st.subheader("Evaluator decisions")
    st.dataframe(frame(data["decisions"]), hide_index=True)
    st.subheader("Patch history")
    active = (data["active_policy"] or {}).get("version")
    st.dataframe(frame([{ "Patch": policy_name(p), "Version": p["version"], "Status": "ACTIVE" if p["version"] == active else p["status"],
                         **p["policy"]["matching"]["processor_amount_tolerance_cents"]} for p in data["policies"]]), hide_index=True)


def evaluation_page():
    st.title("Evaluation & improvements")
    st.caption("Independent backtests, fixed guardrails, and measured growth across patch versions.")
    evaluation_content()


@st.fragment(run_every="5s")
def patch_evolution_content():
    data = data_or_stop()
    policies = sorted(data["policies"], key=lambda policy: (policy.get("created_at", 0), policy["version"]))
    st.subheader("Processor amount tolerance by patch version")
    st.caption("Each line shows the amount tolerance in cents. Proposed versions appear after backtesting; approval makes a passing version active.")
    if not policies:
        st.info("Patch history will appear after the dataset is initialized.")
        return

    processor_fields = ("PROC_A", "PROC_B", "PROC_C")
    chart_rows = []
    for policy in policies:
        tolerances = policy["policy"]["matching"]["processor_amount_tolerance_cents"]
        chart_rows.append({"Patch version": policy_name(policy),
                           **{processor: tolerances.get(processor, 0) for processor in processor_fields}})
    st.line_chart(frame(chart_rows).set_index("Patch version"), y_label="Tolerance (cents)")
    active_version = (data["active_policy"] or {}).get("version")
    st.dataframe(frame([{
        "Version": policy["version"],
        "Patch": policy_name(policy),
        "Parent": policy["policy"].get("parent") or "—",
        "Status": "ACTIVE" if policy["version"] == active_version else policy.get("status", "UNKNOWN"),
        "PROC_A (¢)": policy["policy"]["matching"]["processor_amount_tolerance_cents"].get("PROC_A", 0),
        "PROC_B (¢)": policy["policy"]["matching"]["processor_amount_tolerance_cents"].get("PROC_B", 0),
        "PROC_C (¢)": policy["policy"]["matching"]["processor_amount_tolerance_cents"].get("PROC_C", 0),
    } for policy in policies]), hide_index=True)


def patch_evolution_page():
    st.title("Patch logic evolution")
    st.caption("See how approved and proposed policy versions change processor-specific amount tolerances.")
    patch_evolution_content()


@st.fragment(run_every="5s")
def approval_content():
    data = data_or_stop()
    pending = [r for r in data["runs"] if r["status"] == "WAITING_APPROVAL"]
    if not pending:
        st.info("No patch is waiting for approval right now.")
        latest = data["runs"][0] if data["runs"] else None
        current = data.get("current_evaluation") or {}
        threshold = current.get("evolution_threshold", {})
        summary = current.get("summary", {})
        status_cols = st.columns(3)
        status_cols[0].metric("Stream processed", f"{data['stream']['position']:,} / {data['stream']['total']:,}")
        status_cols[1].metric("Active patch", data.get("active_patch_name") or "Not initialized")
        status_cols[2].metric("Upgrade trigger", "MET" if threshold.get("triggered") else "Not met")

        if latest:
            st.markdown("**Latest agent workflow**")
            st.write(f"Status: **{latest.get('status', 'UNKNOWN')}** · stage: **{latest.get('current_node', 'unknown')}**")
            if latest.get("reason"):
                st.warning(f"Workflow did not request approval: {latest['reason']}")
            if latest.get("error"):
                details = latest.get("error_details") or {}
                status = details.get("status_code")
                suffix = f" (HTTP {status})" if status else ""
                message = details.get("message")
                st.error(f"Workflow stopped with {latest['error']}{suffix}. The run is saved in MongoDB." +
                         (f" Details: {message}" if message else ""))
                if latest.get("status") == "ERROR":
                    if not message:
                        st.caption("This saved error has no provider details.")
                    st.caption("This checkpoint failed during replay. Start a fresh workflow to try again; the failed run will remain in history.")
                    action("Start fresh workflow", "/runs/start", {},
                           key=f"start-fresh-{latest['run_id']}", kind="primary")
            if latest.get("status") == "WAITING_FOR_DATA":
                st.info("The workflow is saved and waiting for more incoming records before proposing a patch.")
            elif latest.get("status") == "RUNNING":
                st.info("The agents are still analyzing the incident. This page refreshes automatically.")
            elif latest.get("status") == "COMPLETED":
                st.success(f"Patch {latest.get('candidate_version', '')} was approved, activated, and verified.")
            elif latest.get("status") == "ROLLED_BACK":
                st.warning("The approved patch failed its held-out check and was rolled back.")

        if data["engine"].get("last_error"):
            details = data["engine"].get("last_error_details") or {}
            description = details.get("message")
            status = details.get("status_code")
            suffix = f" (HTTP {status})" if status else ""
            st.error(f"Evaluator / stream error: {data['engine']['last_error']}{suffix}" +
                     (f" — {description}" if description else ""))
            if not description:
                st.caption("This is an older saved error without details. A new evaluator failure after the API restart will include them here.")

        if threshold.get("triggered"):
            st.caption("An evaluator accuracy or repeated-incident trigger was met. Check the latest workflow status above for agent or backtest progress.")
        else:
            st.caption(
                f"The upgrader starts below {threshold.get('min_evaluator_accuracy', 0.90):.0%} evaluator accuracy "
                f"(after {threshold.get('min_evaluation_records', 100)} records), or after at least {threshold.get('min_cluster_cases', 10)} "
                f"same-processor amount breaks share a signed delta at {threshold.get('min_signed_delta_concentration', 0.70):.0%} concentration. "
                f"Current open breaks: {summary.get('unresolved', 0):,}."
            )

        if data["runs"]:
            with st.expander("Recent workflow history"):
                st.dataframe(frame([{
                    "Status": run.get("status"),
                    "Stage": run.get("current_node"),
                    "Candidate": run.get("candidate_version", "—"),
                    "Reason / error": run.get("reason") or run.get("error") or "—",
                    "Updated": pd.to_datetime(run["updated_at"], unit="s") if run.get("updated_at") else None,
                } for run in data["runs"][:10]]), hide_index=True)
    for run in pending:
        with st.container(border=True):
            candidate_record = next((item for item in data["policies"]
                                     if item["version"] == run.get("candidate_version")), {})
            st.subheader(policy_name(candidate_record) if candidate_record else "Review proposed processor tolerance change")
            wait_started = run.get("approval_wait_started_at", run.get("updated_at", time.time()))
            doorbell_id = f"{run['run_id']}:approval"
            signal = next((event for event in data["doorbells"] if event.get("event_id") == doorbell_id), None)
            paused, signal_col = st.columns(2)
            paused.metric("Workflow paused", elapsed_label(wait_started), "waiting for your decision")
            signal_col.metric("Resume signal", "Received" if signal else "Waiting for approval",
                              "doorbell consumed" if signal and signal.get("consumed") else
                              "doorbell pending" if signal else "created when you decide")
            st.caption(f"Paused since {pd.to_datetime(wait_started, unit='s').strftime('%Y-%m-%d %H:%M:%S %Z')} · run {run['run_id']}")
            with st.expander("Persisted pause and doorbell details"):
                st.json({
                    "workflow_status": run["status"],
                    "checkpoint_node": run.get("current_node"),
                    "interrupt_id": run.get("interrupt_id"),
                    "session_id": run.get("session_id"),
                    "invocation_id": run.get("invocation_id"),
                    "approval_wait_started_at": wait_started,
                    "resume_doorbell": signal or {
                        "event_id": doorbell_id,
                        "kind": "APPROVAL",
                        "state": "not emitted yet; a decision writes this MongoDB event",
                    },
                })
            proposal = run["proposal"]
            patch = proposal["candidate_patch"]
            old = run["baseline_policy"]["matching"]["processor_amount_tolerance_cents"][patch["processor"]]
            st.markdown("**Patch change**")
            left_patch, right_patch = st.columns(2)
            baseline_record = next((item for item in data["policies"]
                                    if item["version"] == run["baseline_policy"]["version"]),
                                   {"version": run["baseline_policy"]["version"]})
            left_patch.write(f"Current: **{policy_name(baseline_record)}** (`{run['baseline_policy']['version']}`)")
            left_patch.json(run["baseline_policy"]["matching"]["processor_amount_tolerance_cents"])
            right_patch.write(f"Candidate: **{policy_name(candidate_record) if candidate_record else 'Proposed patch'}** (`{run.get('candidate_version', 'pending')}`)")
            candidate_policy = candidate_record.get("policy", {})
            candidate_matching = candidate_policy.get("matching", {}).get("processor_amount_tolerance_cents", {})
            right_patch.json(candidate_matching or {**run["baseline_policy"]["matching"]["processor_amount_tolerance_cents"],
                                                    patch["processor"]: patch["amount_tolerance_cents"]})
            st.metric(f"{patch['processor']} tolerance", f"{patch['amount_tolerance_cents']}¢", f"{patch['amount_tolerance_cents']-old:+}¢ from {old}¢")
            st.write(proposal["reason"])
            st.write("Risk:", proposal["risk"])
            st.markdown("**Trigger evidence and threshold**")
            threshold = (run.get("baseline_evaluator") or {}).get("evolution_threshold", {})
            trigger = run.get("incidents", [])
            observed_count = trigger[0].get("count", 0) if trigger else 0
            st.write(f"Trigger: ≥{threshold.get('min_cluster_cases', 10)} cases and ≥{threshold.get('min_signed_delta_concentration', 0.70):.0%} same signed delta. Observed dominant cluster: {observed_count} cases.")
            st.dataframe(frame(trigger), hide_index=True)
            trouble_breakdown = ((run.get("baseline_evaluator") or {}).get("summary") or {}).get("break_buckets", {})
            trouble_count = (run.get("baseline_evaluator") or {}).get("summary", {}).get("unresolved", 0)
            st.metric("Records in trouble at trigger", f"{trouble_count:,}")
            if trouble_breakdown:
                st.markdown("**Open mismatch / exception breakdown at trigger time**")
                st.dataframe(frame([{"Mismatch / exception": name, "Records": count}
                                    for name, count in sorted(trouble_breakdown.items(), key=lambda row: -row[1])]), hide_index=True)
            live_at_trigger = (run.get("baseline_evaluator") or {}).get("current_metrics", {})
            if live_at_trigger:
                st.markdown("**Evaluator metrics when this proposal was triggered**")
                current_cols = st.columns(6)
                current_cols[0].metric("Current patch", policy_name(baseline_record))
                current_cols[1].metric("Processed at trigger", f"{run.get('position', 0):,}")
                current_cols[2].metric("Current score", f"{live_at_trigger.get('score', 0):.2%}")
                current_cols[3].metric("Correct auto-resolution", f"{live_at_trigger.get('auto_resolution_rate', 0):.2%}")
                current_cols[4].metric("False-match rate", f"{live_at_trigger.get('false_match_rate', 0):.2%}")
                current_cols[5].metric("Evaluator sample", f"{live_at_trigger.get('sample_size', 0):,}")
                st.dataframe(frame([
                    {"Live evaluator metric": label, "Value": f"{live_at_trigger.get(key, 0):.2%}"}
                    for label, key in (("Match-decision accuracy", "accuracy"),
                                       ("Correct auto-resolution", "auto_resolution_rate"),
                                       ("Precision", "precision"), ("Recall", "recall"),
                                       ("False-match rate", "false_match_rate"))
                ] + [
                    {"Live evaluator metric": label, "Value": f"{live_at_trigger.get(key, 0):,}"}
                    for label, key in (("Correct automatic matches", "correct_auto"),
                                       ("False automatic matches", "false_auto"),
                                       ("Open / unresolved records", "unresolved"))
                ]), hide_index=True)
            e = run["evaluation"]
            st.markdown("**Historical backtest against ground truth**")
            st.caption(f"{e['baseline']['sample_size']:,} historical records · deterministic evaluator · fixed guardrails")
            st.caption("Guardrails: at least 1,000 records, false-match rate ≤0.5%, no match regressions, and at least +3 percentage points of correct auto-resolution.")
            st.dataframe(frame([
                {"Metric": label,
                 "Current patch": (f"{e['baseline'].get(key, 0):.2%}" if key in {"accuracy", "auto_resolution_rate", "precision", "recall", "false_match_rate"} else e["baseline"].get(key)),
                 "Proposed patch": (f"{e['candidate'].get(key, 0):.2%}" if key in {"accuracy", "auto_resolution_rate", "precision", "recall", "false_match_rate"} else e["candidate"].get(key))}
                for label, key in (("Match decision accuracy", "accuracy"),
                                   ("Correct auto-resolution rate", "auto_resolution_rate"),
                                   ("Precision", "precision"), ("Recall", "recall"),
                                   ("False-match rate", "false_match_rate"),
                                   ("False automatic matches", "false_auto"),
                                   ("Unresolved records", "unresolved"))
            ]), hide_index=True)
            guardrails = e.get("guardrails", {})
            if guardrails.get("passed"):
                st.success("Backtest passed the guardrails. Approval will hot-swap this patch.")
            else:
                st.error("Backtest failed: " + "; ".join(guardrails.get("reasons", [])))
            if run.get("evidence_requested"):
                st.info("More evidence requested. The patch remains paused; arriving data updates the evidence below.")
                st.json(run.get("additional_evidence", {}))
            st.caption("Saved in MongoDB. Closing this page or restarting the API preserves this request.")
            a, b = st.columns(2)
            with a:
                action("Approve & resume", f"/runs/{run['run_id']}/approval", {"decision": "APPROVE"}, key=f"approve-{run['run_id']}", kind="primary")
            with b:
                action("Reject", f"/runs/{run['run_id']}/approval", {"decision": "REJECT"}, key=f"reject-{run['run_id']}")


def approval_page():
    st.title("Human approval")
    st.caption("Review the proposed patch and evidence before it changes reconciliation behavior.")
    approval_content()


@st.fragment(run_every="5s")
def workflow_content():
    data = data_or_stop()
    latest = data["runs"][0] if data["runs"] else {}
    current = latest.get("current_node", "stream")
    nodes = [("stream", "Independent data stream"), ("reconcile", "7 fixed business functions"),
             ("patch", "Processor amount patch"), ("diagnose", "Evaluator: evidence / keep / upgrade"),
             ("memory", "Verified memory"), ("upgrade", "Upgrader"), ("backtest", "Deterministic backtest"),
             ("guardrails", "Fixed guardrails"), ("human_approval", "Pause / human approval"),
             ("promote", "Hot-swap patch"), ("replay", "Replay & monitor"), ("memory_write", "Verified outcome")]
    definitions = "\n".join(f'{key} [label="{label}", fillcolor="{"#B9F5D0" if current == key else "#EEF2F7"}"];' for key,label in nodes)
    dot = 'digraph { rankdir=LR; node [shape=box, style="rounded,filled", color="#CBD5E1", fontname="Arial"]; '+definitions+'''
    stream -> reconcile -> patch -> diagnose;
    diagnose -> stream [label="KEEP"];
    diagnose -> memory -> upgrade -> backtest -> guardrails -> human_approval;
    human_approval -> promote [label="doorbell: approve"];
    promote -> replay -> memory_write -> stream;
    mongo [label="MongoDB: sessions · checkpoints · doorbells", shape=cylinder, fillcolor="#DDF6E9"];
    human_approval -> mongo [style=dashed]; mongo -> human_approval [label="same invocation", style=dashed];
    }'''
    st.graphviz_chart(dot)
    st.write("Fixed functions: customer, currency, merchant, processor, reference normalization, ±2-day date boundary, final safety decision.")
    if latest:
        st.write("Current state:", latest["status"])
        st.code(f"run_id: {latest['run_id']}\nsession_id: {latest['session_id']}\ninvocation_id: {latest.get('invocation_id')}\nnode: {current}")
        st.dataframe(frame(data["sessions"]), hide_index=True)
        events = request(f"/runs/{latest['run_id']}/events")
        st.subheader("Audit timeline")
        st.dataframe(frame(events or []), hide_index=True)
    st.subheader("Persisted doorbells")
    st.dataframe(frame(data["doorbells"]), hide_index=True)


def workflow_page():
    st.title("Workflow & persistence")
    st.caption("Same objective, later event, same persisted workflow.")
    workflow_content()


@st.fragment(run_every="5s")
def reconciliation_content():
    data = data_or_stop()
    metrics = data["domain"]
    cols = st.columns(4)
    cols[0].metric("Ledger records processed", f"{metrics['total']:,}")
    cols[1].metric("Matched", f"{metrics['matched']:,}")
    cols[2].metric("Open breaks", f"{metrics['unresolved']:,}")
    cols[3].metric("Operational match rate", f"{metrics['match_rate']:.2%}")
    st.caption("Operational match rate counts engine matches. Correctness and false-match rates are measured separately by the backtester.")
    st.subheader("Reconciliation over time")
    if data["snapshots"]:
        chart = frame([{ "Time": pd.to_datetime(s["timestamp"], unit="s"), "Matched": s["matched"], "Open breaks": s["unresolved"]} for s in data["snapshots"]])
        st.line_chart(chart.set_index("Time"))
    left, right = st.columns(2)
    with left:
        st.subheader("Balances by currency")
        st.dataframe(frame([{ "Currency": currency, "Matched amount": amounts["matched_cents"]/100,
                             "Outstanding amount": amounts["outstanding_cents"]/100} for currency, amounts in metrics["by_currency"].items()]), hide_index=True)
        st.caption("Currencies are reported separately; no exchange-rate conversion is applied.")
        st.subheader("Processor resolution")
        st.dataframe(frame([{ "Processor": p, **v} for p,v in metrics["by_processor"].items()]), hide_index=True)
    with right:
        st.subheader("Business-check outcomes")
        st.dataframe(frame([{ "Check": name, "Passed": counts.get("pass",0), "Failed": counts.get("fail",0)} for name,counts in data["checks"].items()]), hide_index=True)
        st.subheader("Break reasons")
        st.dataframe(frame([{ "Reason": key, "Count": value} for key,value in metrics["break_buckets"].items()]), hide_index=True)
    st.subheader("Open cases & evidence")
    st.dataframe(frame(data["cases"]), hide_index=True)
    st.subheader("Verified learning")
    st.dataframe(frame(data["memories"]), hide_index=True)


def reconciliation_page():
    st.title("Reconciliation operations")
    st.caption("Business metrics from the independently streamed ledger and settlement records.")
    reconciliation_content()


sidebar()
st.navigation([
    st.Page(evaluation_page, title="Evaluation & improvements", icon="📈"),
    st.Page(approval_page, title="Human approval", icon="✅"),
    st.Page(patch_evolution_page, title="Patch evolution", icon="📉"),
    st.Page(workflow_page, title="Workflow", icon="🔀"),
    st.Page(reconciliation_page, title="Reconciliation", icon="↔️"),
]).run()
