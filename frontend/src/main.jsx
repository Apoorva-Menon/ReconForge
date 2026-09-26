import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import './styles.css'
import './seed.css'

const API = import.meta.env.VITE_API_URL || ''
const nav = [
  ['overview', '◫', 'Overview'], ['backtesting', '⌁', 'Backtesting'], ['patches', '⌘', 'Patch evolution'],
  ['approval', '✓', 'Human approval'], ['workflow', '◎', 'Workflow'], ['reconciliation', '⇄', 'Reconciliation'],
]
const stages = ['reconcile', 'diagnose', 'memory', 'upgrade', 'backtest', 'guardrails', 'human_approval', 'promote', 'replay', 'memory_write']
const stageNames = { reconcile: 'Reconcile', diagnose: 'Diagnosis', memory: 'Evidence review', upgrade: 'Candidate patch', backtest: 'Backtest', guardrails: 'Guardrails', human_approval: 'Human review', promote: 'Promote', replay: 'Replay', memory_write: 'Verified memory' }
const pct = n => `${((n || 0) * 100).toFixed(1)}%`
const count = n => Number(n || 0).toLocaleString()

async function request(path, body) {
  const response = await fetch(`${API}${path}`, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(result.detail || 'Request failed')
  return result
}

function App() {
  const [page, setPage] = useState('overview')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [events, setEvents] = useState([])
  const refresh = async () => { try { setData(await request('/dashboard')); setError('') } catch (e) { setError(e.message) } }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 4000); return () => clearInterval(timer) }, [])
  const latest = data?.runs?.[0]
  useEffect(() => { if (page === 'workflow' && latest?.run_id) request(`/runs/${latest.run_id}/events`).then(setEvents).catch(() => setEvents([])) }, [page, latest?.run_id])
  const run = data?.runs?.find(r => r.status === 'WAITING_APPROVAL') || latest
  const trigger = data?.current_evaluation?.evolution_threshold || {}
  const active = data?.active_policy || {}
  const evaluation = run?.evaluation || data?.evaluations?.at(-1)
  const history = useMemo(() => (data?.decisions || []).filter(d => d.current_metrics).slice().reverse().map(d => ({
    Records: d.position, Accuracy: (d.current_metrics.accuracy || 0) * 100, 'Auto-resolution': (d.current_metrics.auto_resolution_rate || 0) * 100,
  })), [data])

  async function act(label, path, body) {
    setBusy(true); setNotice(''); setError('')
    try { await request(path, body); setNotice(label); await refresh() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const approval = async decision => { if (run) await act(`Decision recorded: ${decision.toLowerCase()}`, `/runs/${run.run_id}/approval`, { decision }) }
  const start = () => act('Workflow started', '/runs/start', {})
  const navTo = key => setPage(key)

  if (!data && !error) return <div className="loading">Loading ReconForge…</div>
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">R</div><div><b>ReconForge</b><small>RECONCILIATION CONTROL</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <nav>{nav.map(([key, icon, title]) => <button key={key} className={page === key ? 'nav-item selected' : 'nav-item'} onClick={() => navTo(key)}><span>{icon}</span>{title}{key === 'approval' && data?.runs?.some(r => r.status === 'WAITING_APPROVAL') && <i className="nav-dot"/>}</button>)}</nav>
      <div className="sidebar-bottom"><span className="live-dot"/> Live data stream <b>{count(data?.stream?.position)} / {count(data?.stream?.total)}</b><div className="stream-track"><span style={{ width: `${Math.min(100, (data?.stream?.position || 0) / Math.max(1, data?.stream?.total || 1500) * 100)}%` }}/></div></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div><span className="eyebrow">RECONFORGE / {page.toUpperCase()}</span><h1>{nav.find(n => n[0] === page)?.[2]}</h1></div><div className="top-right"><span className="live-pill"><i/> Live · updates every 4 sec</span><button className="icon-button" onClick={refresh} title="Refresh">↻</button><div className="avatar">RF</div></div></header>
      {error && <div className="notice error"><b>Connection issue</b> · {error}</div>}{notice && <div className="notice success">✓ {notice}</div>}
      {!data ? <section className="panel"><h2>Dashboard unavailable</h2><p>Check that the API is running and configured.</p><button className="button" onClick={refresh}>Retry</button></section> : <>
        {page === 'overview' && <Overview data={data} latest={latest} trigger={trigger} history={history} start={start} seed={() => act('Demo dataset seeded', '/demo/seed', {})} busy={busy} go={navTo}/>}
        {page === 'backtesting' && <Backtesting data={data} latest={latest} run={run} evaluation={evaluation} start={start} busy={busy}/>}
        {page === 'patches' && <PatchEvolution data={data}/>}
        {page === 'approval' && <Approval data={data} run={run} evaluation={evaluation} approve={approval} busy={busy} start={start}/>}
        {page === 'workflow' && <Workflow data={data} run={latest} events={events}/>}
        {page === 'reconciliation' && <Reconciliation data={data}/>}
      </>}
      <footer><span>ReconForge · Governed policy evolution</span><span>Deterministic evaluation · Human authorized changes</span></footer>
    </main>
  </div>
}

function Metric({ label, value, hint, icon }) { return <div className="metric-card"><div className="metric-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><small>{hint}</small></div> }
function Status({ value }) { const kind = ['ERROR', 'REJECTED', 'ROLLED_BACK'].includes(value) ? 'bad' : ['WAITING_APPROVAL', 'RUNNING', 'WAITING_FOR_DATA'].includes(value) ? 'warn' : 'good'; return <span className={`status ${kind}`}>{(value || 'PENDING').replaceAll('_', ' ')}</span> }

function WorkflowCard({ run, go }) {
  if (!run) return <div className="panel empty"><div className="empty-icon">◎</div><h3>No workflow run yet</h3><p>When the evaluator detects a recurring incident, the agent workflow appears here.</p></div>
  const index = stages.indexOf(run.current_node)
  return <section className="panel"><div className="panel-heading"><div><div className="eyebrow">AGENT WORKFLOW</div><h2>Latest run</h2></div><Status value={run.status}/></div>
    <div className="run-summary"><div><small>RUN ID</small><code>{run.run_id}</code></div><div><small>CURRENT STAGE</small><b>{stageNames[run.current_node] || run.current_node || 'Starting'}</b></div><div><small>UPDATED</small><b>{run.updated_at ? new Date(run.updated_at * 1000).toLocaleTimeString() : '—'}</b></div></div>
    <div className="stepper">{stages.slice(0, 8).map((stage, i) => <div className={`step ${i < index ? 'done' : i === index ? 'current' : ''}`} key={stage}><span>{i < index ? '✓' : i + 1}</span><small>{stageNames[stage]}</small></div>)}</div>
    {run.error && <div className="error-detail"><b>Workflow error · {run.error}</b><p>{run.error_details?.message || 'No provider details were captured.'}</p>{run.error_details?.status_code && <small>HTTP {run.error_details.status_code}</small>}</div>}
    {run.reason && <div className="soft-callout">{run.reason}</div>}
    {go && <button className="text-button" onClick={() => go('workflow')}>View workflow details →</button>}
  </section>
}

function Overview({ data, latest, trigger, history, start, seed, busy, go }) {
  const m = data.current_evaluation?.current_metrics || {}
  const engineError = data.engine?.last_error
  return <>
    <section className="hero"><div><div className="eyebrow">RECONCILIATION HEALTH</div><h2>Good morning. Here’s your operations snapshot.</h2><p>Monitor live matching, evaluate improvements, and approve safe policy changes.</p></div><button className="button primary" disabled={busy || latest?.status === 'RUNNING'} onClick={start}>＋ Start workflow</button></section>
    {!data.active_policy && <section className="seed-callout"><div><b>Demo data is not initialized</b><p>The baseline policy is missing from MongoDB. Seed the demo data, then refresh this dashboard.</p></div><button className="button primary" disabled={busy} onClick={seed}>Seed demo data</button></section>}
    {engineError && <div className="error-detail"><b>Evaluator / stream error · {engineError}</b><p>{data.engine.last_error_details?.message || 'Open the workflow view for diagnostics.'}</p></div>}
    <div className="metric-grid"><Metric label="Records processed" value={`${count(data.stream.position)} / ${count(data.stream.total)}`} hint="Live stream position" icon="⇄"/><Metric label="Open breaks" value={count(data.domain.unresolved)} hint="Awaiting resolution" icon="!"/><Metric label="Evaluator accuracy" value={m.accuracy == null ? 'Pending' : pct(m.accuracy)} hint={`${count(m.sample_size)} records scored`} icon="⌁"/><Metric label="Active policy" value={data.active_patch_name || activeName(data.active_policy)} hint={data.active_policy?.version || 'Initializing'} icon="◈"/></div>
    <div className="content-grid"><WorkflowCard run={latest} go={go}/><section className="panel"><div className="panel-heading"><div><div className="eyebrow">EVOLUTION TRIGGER</div><h2>Upgrade readiness</h2></div><span className={`status ${trigger.triggered ? 'warn' : 'neutral'}`}>{trigger.triggered ? 'TRIGGERED' : 'MONITORING'}</span></div><p className="muted">A candidate is evaluated when accuracy drops or a recurring processor break is detected.</p><div className="trigger-list"><div><span>Accuracy threshold</span><b>{pct(trigger.min_evaluator_accuracy || .9)}</b></div><div><span>Minimum scored records</span><b>{count(trigger.min_evaluation_records || 100)}</b></div><div><span>Recurring cluster size</span><b>{count(trigger.min_cluster_cases || 10)} cases</b></div></div><button className="text-button" onClick={() => go('backtesting')}>View backtesting →</button></section></div>
    <section className="panel chart-panel"><div className="panel-heading"><div><div className="eyebrow">QUALITY TREND</div><h2>Evaluation performance</h2></div><button className="text-button" onClick={() => go('backtesting')}>All backtests →</button></div>{history.length ? <div className="chart-wrap"><ResponsiveContainer width="100%" height={230}><AreaChart data={history}><defs><linearGradient id="accuracy" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5c71d8" stopOpacity={.2}/><stop offset="100%" stopColor="#5c71d8" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="#edf0f3"/><XAxis dataKey="Records" tickFormatter={count} tickLine={false} axisLine={false}/><YAxis domain={[0,100]} tickFormatter={v => `${v}%`} tickLine={false} axisLine={false}/><Tooltip/><Area type="monotone" dataKey="Accuracy" stroke="#5368cd" fill="url(#accuracy)" strokeWidth={2.5}/><Area type="monotone" dataKey="Auto-resolution" stroke="#21a47a" fill="transparent" strokeWidth={2}/></AreaChart></ResponsiveContainer></div> : <div className="chart-empty">Evaluation history will appear as the stream is processed.</div>}</section>
    <RecentRuns data={data} go={go}/>
  </>
}

function activeName(policy) { return policy?.version === 'v1' ? 'Zero-tolerance baseline' : policy?.version || 'Not initialized' }
function RecentRuns({ data, go }) { return <section className="panel table-panel"><div className="panel-heading"><div><div className="eyebrow">ACTIVITY</div><h2>Recent workflows</h2></div><button className="text-button" onClick={() => go('workflow')}>View activity →</button></div><div className="table-scroll"><table><thead><tr><th>Status</th><th>Stage</th><th>Candidate</th><th>Reason / error</th><th>Last updated</th></tr></thead><tbody>{(data.runs || []).slice(0,5).map(r => <tr key={r.run_id}><td><Status value={r.status}/></td><td>{stageNames[r.current_node] || r.current_node}</td><td>{r.candidate_version || '—'}</td><td>{r.reason || r.error || '—'}</td><td>{r.updated_at ? new Date(r.updated_at * 1000).toLocaleString() : '—'}</td></tr>)}</tbody></table>{!data.runs?.length && <div className="table-empty">No workflows recorded yet.</div>}</div></section> }

function Backtesting({ data, latest, run, evaluation, start, busy }) {
  const status = evaluation ? (evaluation.guardrails?.passed ? 'PASSED' : 'FAILED') : latest?.status === 'ERROR' && latest.current_node === 'backtest' ? 'FAILED' : latest?.current_node === 'backtest' && latest?.status === 'RUNNING' ? 'RUNNING' : latest?.status === 'RUNNING' ? 'QUEUED' : 'NOT STARTED'
  const baseline = evaluation?.baseline || {}, candidate = evaluation?.candidate || {}
  const configs = [['Historical sample minimum', '1,000 records', 'Fixed safety gate'], ['Maximum false-match rate', '0.5%', 'Candidate ceiling'], ['False-match regression', '≤ 0.1 pp', 'Compared with baseline'], ['Correct auto-resolution gain', '≥ 3 pp', 'Required improvement'], ['Match regression count', '0', 'Previously correct matches'], ['Evaluation method', 'Deterministic', 'Ground truth evaluator']]
  return <>
    <section className="hero"><div><div className="eyebrow">POLICY EVALUATION</div><h2>Backtesting</h2><p>Compare the proposed policy against the current baseline on historical labeled data.</p></div><button className="button primary" disabled={busy || latest?.status === 'RUNNING' || latest?.status === 'WAITING_APPROVAL'} onClick={start}>Run evaluation workflow</button></section>
    <section className="panel"><div className="panel-heading"><div><div className="eyebrow">LATEST EVALUATION</div><h2>Backtesting status</h2></div><Status value={status}/></div><div className="metric-grid compact"><Metric label="Baseline sample" value={baseline.sample_size ? count(baseline.sample_size) : '—'} hint="Historical records" icon="▤"/><Metric label="Candidate sample" value={candidate.sample_size ? count(candidate.sample_size) : '—'} hint="Records evaluated" icon="▤"/><Metric label="Baseline accuracy" value={baseline.accuracy == null ? '—' : pct(baseline.accuracy)} hint="Current active policy" icon="⌁"/><Metric label="Candidate accuracy" value={candidate.accuracy == null ? '—' : pct(candidate.accuracy)} hint="Proposed policy" icon="↗"/></div>{latest && <div className="run-line"><span>Workflow stage</span><b>{stageNames[latest.current_node] || latest.current_node}</b><span>Workflow status</span><Status value={latest.status}/></div>}{evaluation?.guardrails?.reasons?.length > 0 && <div className="error-detail"><b>Guardrail failures</b><ul>{evaluation.guardrails.reasons.map(r => <li key={r}>{r}</li>)}</ul></div>}</section>
    <section className="panel table-panel"><div className="panel-heading"><div><div className="eyebrow">FIXED SAFETY PARAMETERS</div><h2>Backtest parameters</h2></div><span className="status neutral">READ ONLY</span></div><p className="muted">Guardrails are fixed in backend policy code; the agent cannot change them. Candidate eligibility requires every check to pass.</p><div className="table-scroll"><table><thead><tr><th>Parameter</th><th>Required value</th><th>Purpose</th><th>Result</th></tr></thead><tbody>{configs.map(([name, value, why], i) => <tr key={name}><td><b>{name}</b></td><td>{value}</td><td>{why}</td><td>{evaluation ? <span className={i === 0 ? (candidate.sample_size >= 1000 ? 'result-pass' : 'result-fail') : i === 1 ? (candidate.false_match_rate <= .005 ? 'result-pass' : 'result-fail') : i === 2 ? (candidate.false_match_rate <= (baseline.false_match_rate || 0) + .001 ? 'result-pass' : 'result-fail') : i === 3 ? (candidate.auto_resolution_rate >= (baseline.auto_resolution_rate || 0) + .03 ? 'result-pass' : 'result-fail') : i === 4 ? (!evaluation.regression_count ? 'result-pass' : 'result-fail') : 'result-pass'}>{i === 5 ? 'Applied' : i === 4 ? `${count(evaluation.regression_count)} regressions` : 'Evaluated'}</span> : <span className="muted">Pending</span>}</td></tr>)}</tbody></table></div></section>
    <RecentRuns data={data} go={() => {}}/>
  </>
}

function Approval({ data, run, evaluation, approve, busy, start }) {
  const pending = run?.status === 'WAITING_APPROVAL'
  const proposal = run?.proposal || {}
  const patch = proposal.candidate_patch || {}
  return <>
    <section className="hero"><div><div className="eyebrow">GOVERNED POLICY CHANGE</div><h2>{pending ? 'Review candidate patch' : 'Human approval'}</h2><p>{pending ? 'A passing backtest is ready for your decision.' : 'Candidates appear here after a successful backtest and guardrail review.'}</p></div><Status value={run?.status}/></section>
    {pending ? <><section className="panel"><div className="panel-heading"><div><div className="eyebrow">PROPOSED CHANGE</div><h2>{patch.processor || 'Processor'} amount tolerance</h2></div><span className="change-pill">{patch.amount_tolerance_cents ?? '—'}¢</span></div><p>{proposal.reason || 'No rationale provided.'}</p><div className="content-grid"><div className="subpanel"><small>RISK</small><p>{proposal.risk || 'Not specified'}</p></div><div className="subpanel"><small>BACKTEST GATE</small><p>{evaluation?.guardrails?.passed ? 'Passed — candidate is eligible for review.' : 'Candidate did not pass the required safety checks.'}</p></div></div><div className="compare-grid"><div><small>ACTIVE POLICY</small><pre>{JSON.stringify(run.baseline_policy?.matching?.processor_amount_tolerance_cents || {}, null, 2)}</pre></div><div><small>CANDIDATE POLICY</small><pre>{JSON.stringify(run.proposed_policy?.matching?.processor_amount_tolerance_cents || { ...run.baseline_policy?.matching?.processor_amount_tolerance_cents, [patch.processor]: patch.amount_tolerance_cents }, null, 2)}</pre></div></div><div className="metric-grid compact"><Metric label="Accuracy" value={pct(evaluation?.candidate?.accuracy)} hint={`Baseline ${pct(evaluation?.baseline?.accuracy)}`} icon="⌁"/><Metric label="Auto-resolution" value={pct(evaluation?.candidate?.auto_resolution_rate)} hint={`Baseline ${pct(evaluation?.baseline?.auto_resolution_rate)}`} icon="↗"/><Metric label="False matches" value={count(evaluation?.candidate?.false_auto)} hint={`Rate ${pct(evaluation?.candidate?.false_match_rate)}`} icon="!"/><Metric label="Backtest records" value={count(evaluation?.candidate?.sample_size)} hint="Deterministic sample" icon="▤"/></div><div className="decision-row"><button className="button danger-outline" disabled={busy} onClick={() => approve('REJECT')}>Reject candidate</button><button className="button primary" disabled={busy || !evaluation?.guardrails?.passed} onClick={() => approve('APPROVE')}>Approve &amp; resume</button></div></section></> : <section className="panel empty"><div className="empty-icon">✓</div><h3>No candidate awaiting approval</h3><p>{run?.status === 'RUNNING' ? `Workflow is currently ${stageNames[run.current_node] || run.current_node}. This page updates automatically.` : run?.status === 'ERROR' ? `Latest workflow failed at ${stageNames[run.current_node] || run.current_node}: ${run.error_details?.message || run.error}` : 'Start an evaluation workflow to look for a safe improvement.'}</p>{!run || run.status !== 'RUNNING' ? <button className="button primary" disabled={busy || run?.status === 'WAITING_FOR_DATA'} onClick={start}>Start workflow</button> : null}</section>}
    <RecentRuns data={data} go={() => {}}/>
  </>
}

function Workflow({ data, run, events }) { return <><section className="hero"><div><div className="eyebrow">EXECUTION MONITOR</div><h2>Workflow activity</h2><p>Watch the agent workflow move from incident evidence to a safely reviewed policy patch.</p></div>{run && <Status value={run.status}/>}</section><WorkflowCard run={run}/><section className="panel"><div className="panel-heading"><div><div className="eyebrow">PERSISTENCE</div><h2>Run checkpoint</h2></div></div>{run ? <div className="detail-grid">{[['Run ID', run.run_id], ['Session', run.session_id], ['Invocation', run.invocation_id], ['Checkpoint stage', run.current_node], ['Last update', run.updated_at ? new Date(run.updated_at * 1000).toLocaleString() : '—'], ['Stream position', count(run.position)]].map(([k,v]) => <div key={k}><small>{k}</small><code>{v || '—'}</code></div>)}</div> : <p>No workflow to inspect.</p>}<h3>Agent audit timeline</h3><div className="table-scroll"><table><thead><tr><th>Action</th><th>Actor</th><th>Time</th><th>Details</th></tr></thead><tbody>{events.map((event,i) => <tr key={event.idempotency_key || i}><td>{event.action}</td><td>{event.actor}</td><td>{event.timestamp ? new Date(event.timestamp * 1000).toLocaleString() : '—'}</td><td><code>{JSON.stringify(event.payload || {})}</code></td></tr>)}</tbody></table>{!events.length && <div className="table-empty">Audit events will appear as the workflow runs.</div>}</div><h3>Recent activity</h3><RecentRuns data={data} go={() => {}}/><h3>Persisted approval signals</h3><div className="table-scroll"><table><thead><tr><th>Run</th><th>Type</th><th>State</th><th>Time</th></tr></thead><tbody>{(data.doorbells || []).map(event => <tr key={event.event_id}><td>{event.run_id}</td><td>{event.kind}</td><td>{event.consumed ? 'Consumed' : 'Pending'}</td><td>{event.timestamp ? new Date(event.timestamp * 1000).toLocaleString() : '—'}</td></tr>)}</tbody></table></div></section></> }

function Reconciliation({ data }) { const domain = data.domain; return <><section className="hero"><div><div className="eyebrow">OPERATIONS</div><h2>Reconciliation</h2><p>Business metrics from the live ledger and processor settlement stream.</p></div></section><div className="metric-grid"><Metric label="Records" value={count(domain.total)} hint="Processed" icon="▤"/><Metric label="Matched" value={count(domain.matched)} hint="Resolved automatically" icon="✓"/><Metric label="Open breaks" value={count(domain.unresolved)} hint="Needs review" icon="!"/><Metric label="Match rate" value={pct(domain.match_rate)} hint="Operational" icon="↗"/></div><section className="panel table-panel"><div className="panel-heading"><div><div className="eyebrow">EXCEPTIONS</div><h2>Open break reasons</h2></div></div><div className="table-scroll"><table><thead><tr><th>Break type</th><th>Open records</th></tr></thead><tbody>{Object.entries(domain.break_buckets || {}).map(([k,v]) => <tr key={k}><td>{k.replaceAll('_',' ')}</td><td>{count(v)}</td></tr>)}</tbody></table></div></section><section className="panel table-panel"><div className="panel-heading"><div><div className="eyebrow">PROCESSORS</div><h2>Resolution summary</h2></div></div><div className="table-scroll"><table><thead><tr><th>Processor</th><th>Matched</th><th>Unresolved</th></tr></thead><tbody>{Object.entries(domain.by_processor || {}).map(([k,v]) => <tr key={k}><td>{k}</td><td>{count(v.matched)}</td><td>{count(v.unresolved)}</td></tr>)}</tbody></table></div></section><section className="panel table-panel"><div className="panel-heading"><div><div className="eyebrow">CASE WORKLIST</div><h2>Open reconciliation cases</h2></div><span className="status neutral">Showing up to 200</span></div><div className="table-scroll"><table><thead><tr><th>Case</th><th>Processor</th><th>Break</th><th>Amount</th><th>Policy</th></tr></thead><tbody>{(data.cases || []).map(c => <tr key={c.case_id || c.internal_record_id}><td>{c.case_id || c.internal_record_id}</td><td>{c.processor}</td><td>{c.break_type}</td><td>{c.currency} {(c.amount_cents / 100).toFixed(2)}</td><td>{c.policy_version}</td></tr>)}</tbody></table>{!data.cases?.length && <div className="table-empty">There are no open reconciliation cases.</div>}</div></section></> }

function PatchEvolution({ data }) {
  const policies = (data.policies || []).slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0))
  return <><section className="hero"><div><div className="eyebrow">VERSION HISTORY</div><h2>Patch logic evolution</h2><p>Track processor amount tolerances across proposed and approved policy versions.</p></div></section><section className="panel chart-panel"><div className="panel-heading"><div><div className="eyebrow">POLICY PARAMETERS</div><h2>Processor tolerance by version</h2></div></div><div className="table-scroll"><table><thead><tr><th>Version</th><th>Name</th><th>Processor tolerances (cents)</th><th>Status</th><th>Created</th></tr></thead><tbody>{policies.map(p => <tr key={p.version}><td><code>{p.version}</code></td><td>{p.patch_name || (p.version === data.active_policy?.version ? 'Active baseline' : 'Policy patch')}</td><td>{Object.entries(p.policy?.matching?.processor_amount_tolerance_cents || {}).map(([k,v]) => `${k}: ${v}¢`).join(' · ') || '—'}</td><td><span className={`status ${p.version === data.active_policy?.version ? 'good' : p.status === 'REJECTED' ? 'bad' : 'neutral'}`}>{p.version === data.active_policy?.version ? 'ACTIVE' : (p.status || 'RECORDED').replaceAll('_',' ')}</span></td><td>{p.created_at ? new Date(p.created_at * 1000).toLocaleDateString() : '—'}</td></tr>)}</tbody></table>{!policies.length && <div className="table-empty">Policy history will appear here.</div>}</div><p className="muted">Only the amount tolerance patch fields are eligible to evolve. Approval activates eligible versions.</p></section></>
}

createRoot(document.getElementById('root')).render(<App />)
