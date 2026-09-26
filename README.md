# ReconForge

Persistent reconciliation harness built with Google ADK, OpenAI, MongoDB Atlas, FastAPI, and React.

## Architecture

```text
Transactions -> deterministic matching -> bounded ADK workflow
              -> diagnosis/evolution agents -> deterministic backtest
              -> MongoDB checkpoint -> human approval -> resume/promote/replay
```

Tools measure and execute. Agents reason and orchestrate. MongoDB preserves state and experience. Evaluators judge candidates. Humans authorize policy changes. Only whitelisted reconciliation policy fields may evolve.

## Local setup

Requires Python 3.11+, `uv`, and Node.js 20+ with npm.

```bash
cp .env.example .env
# Set GEMINI_API_KEY and MONGODB_URI in .env
uv sync
```

Start the API and React development server in separate terminals:

```bash
uv run uvicorn app.api:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

The React development UI runs at http://127.0.0.1:5173 and proxies API calls to the backend on port 8000. The API seeds the demo dataset on startup. To serve a built UI from FastAPI, run `cd frontend && npm run build`; then open http://127.0.0.1:8000.

If the dashboard reports that seed data is missing, check the API terminal for MongoDB or dataset path errors, then run `uv run python scripts/seed_demo.py` from the project root. The Overview page also provides a **Seed demo data** button when the baseline policy is missing.

ADK discovery/playground entry point: `app.agent:root_agent`.

## Environment

See [.env.example](.env.example). Do not commit credentials. Deterministic seeding and backtesting should work without calling an LLM.

## Demo

The intended flow is seed -> reconcile -> inject a recurring fee mismatch -> diagnose -> propose a bounded policy candidate -> backtest -> approve -> resume -> promote -> replay -> write episode memory. See [docs/demo_script.md](docs/demo_script.md).

## Status

The dashboard surfaces live workflow progress, approval decisions, reconciliation health, and deterministic backtest status and fixed guardrail parameters.
