# Candidate Profile Agent (Local MVP)

Local-first Streamlit app that extracts a structured candidate profile from resume text using an OpenAI-compatible LLM, stores inputs/outputs in SQLite, and lets you browse saved candidates.

## Location

This agent lives in `agents/candidate_profile`.

## Setup

```bash
cd agents/candidate_profile
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

Set environment variables:

- `OPENAI_API_KEY` (required)
- `LLM_MODEL` (optional, default set in code)
- `DB_PATH` (optional, default `agents/data/app.db`)

## Run

```bash
cd agents/candidate_profile
streamlit run streamlit_app.py
```

## Notes

- All data is stored locally in SQLite.
- The agent never fabricates missing details. Unknowns are surfaced in `questions_for_user`.
