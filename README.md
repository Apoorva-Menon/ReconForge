# ReconForge

Persistent reconciliation harness built with Google ADK, OpenAI, MongoDB Atlas, and Streamlit.

## Architecture

```text
Transactions -> deterministic matching -> bounded ADK workflow
              -> diagnosis/evolution agents -> deterministic backtest
              -> MongoDB checkpoint -> human approval -> resume/promote/replay
```

Tools measure and execute. Agents reason and orchestrate. MongoDB preserves state and experience. Evaluators judge candidates. Humans authorize policy changes. Only whitelisted reconciliation policy fields may evolve.

## Local setup

Requires Python 3.11+ and `uv`.

```bash
cp .env.example .env
# Set OPENAI_API_KEY and MONGODB_URI in .env
uv sync
python scripts/seed_demo.py
streamlit run ui/app.py
```

ADK discovery/playground entry point: `app.agent:root_agent`.

## Environment

See [.env.example](.env.example). Do not commit credentials. Deterministic seeding and backtesting should work without calling an LLM.

## Demo

The intended flow is seed -> reconcile -> inject a recurring fee mismatch -> diagnose -> propose a bounded policy candidate -> backtest -> approve -> resume -> promote -> replay -> write episode memory. See [docs/demo_script.md](docs/demo_script.md).

## Status

This repository currently contains a generated project skeleton. Application behavior and tests are not implemented yet.
