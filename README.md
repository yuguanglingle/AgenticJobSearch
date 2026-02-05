# Agentic Job Search

This repo is organized by agent/component. Each folder under `agents/` contains its own code, dependencies, and UI (if any).

DB_PATH environment variable ⚠️

- The integration scripts and agents use a shared SQLite DB at `data/app.db` by default.
- If the environment variable `DB_PATH` is *unset or an empty string*, the integration runner will set it to the repository's shared `data/app.db` (to avoid accidental writes to an unintended location).
- If you want to use an alternate DB for testing, set `DB_PATH` to an absolute path before running the integration script.

Current components:
- `agents/candidate_profile` (implemented)
- `agents/job_search` (placeholder)
- `agents/job_match` (placeholder)
- `agents/networking` (placeholder)
- `agents/drafting` (placeholder)
- `agents/orchestrator` (placeholder)

## Workflow State Machine (Hard Rule)

`agents/orchestrator/state.py` is the shared workflow/state machine layer and the only place allowed to change job opportunity lifecycle state.

Rules:
- Orchestrator pipelines must write fit results via `state.apply_fit_result(...)` (DISCOVERED → SCREENED for all scored jobs).
- UI and downstream agents may read from the DB, but must use `state.approve(...)`, `state.close(...)`, and `state.mark_applied(...)` for user actions.
- No other module should directly update `job_opportunities.state`, `next_action`, `last_state_changed_at`, or skip flags.

## Job Source Probe

This repo includes a standalone feasibility probe for testing job source ingestion access.

Run:
```
pip install -r requirements.txt
python probe.py --config sources_to_probe.json
```

Outputs:
- Console table with probe results.
- `probe_report.json` with full details and ranked sources.

To add sources, extend `sources_to_probe.json` with a new entry and implement an adapter in `adapters/`.
