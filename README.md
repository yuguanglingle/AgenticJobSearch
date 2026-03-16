# AI Job Search System

An AI-powered job discovery and ranking system that automatically finds relevant opportunities and ranks them based on candidate profiles using LLM-based reasoning and feedback learning.

## Key Features

Automated daily job discovery

Candidate profile extraction using LLM

Intelligent job ranking with reasons

UI for candidate to track jobs screened and take actions

Configurable candidate profiles

Reproducible local deployment

## Architecture

See /docs/architecture.md.

The system consists of four main components:

Candidate profile extraction

Job data aggregation

AI-driven job scoring

Feedback learning loop

## Workflow
Job Providers → Filtering → LLM Scoring → Ranking → Feedback Learning

## Quickstart

Clone repository

```git clone https://github.com/yourname/agentic-job-search
cd agentic-job-search```

Install dependencies

```pip install -r requirements.txt```

Create environment variables

```cp .env.example .env```

Add API keys:

```OPENAI_API_KEY=
THEIRSTACK_API_KEY=```

Launch UI

```streamlit run app/ui/streamlit_app.py```


## Example Output

TODO: Include screenshots here.

Ranked job list

Job scoring explanation

Feedback interface

## Future improvement
Multi-source job aggregation

Feedback-driven preference learning
