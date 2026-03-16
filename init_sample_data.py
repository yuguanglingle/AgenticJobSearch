"""Initialize databases with sample data for testing."""
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

# Change to agents directory to make imports work
os.chdir(Path(__file__).parent / "agents")
sys.path.insert(0, str(Path.cwd()))

from job_search.db import init_db as init_job_db, save_retrieval_batch
from candidate_profile.src.db import init_db as init_candidate_db, save_candidate


def init_sample_job_data():
    """Initialize unified database with actual job search sample data.

    Args:
        None.

    Returns:
        None.
    """
    print("Initializing unified database with actual Theirstack response data...")
    
    # Initialize database with shared path
    db_path = str(Path.cwd() / "data" / "app.db")
    engine = init_job_db(db_path)
    
    # Load actual response from file
    response_file = Path.cwd() / "job_search" / "sample_theirstack_response.json"
    with open(response_file, "r") as f:
        # Try to parse as JSON first, if it fails, try as Python dict
        content = f.read()
        try:
            response_data = json.loads(content)
        except json.JSONDecodeError:
            # If JSON parsing fails, evaluate as Python dict
            response_data = eval(content)
    
    # Create batch metadata
    batch_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Extract jobs from response and add source field
    jobs = response_data.get("data", [])
    for job in jobs:
        if "source" not in job:
            job["source"] = "theirstack"
    
    sample_batch = {
        "retrieval_batch": {
            "batch_id": batch_id,
            "started_at": now,
            "finished_at": now,
        },
        "jobs": jobs,  # Use actual jobs from response
        "stats": {
            "sources_checked": 1,
            "jobs_fetched": len(jobs),
            "jobs_new": len(jobs),
            "jobs_updated": 0,
            "jobs_deduped": 0,
        },
    }
    
    # Save to database
    save_retrieval_batch(sample_batch)
    print(f"✓ {len(jobs)} actual jobs from Theirstack saved to database at {db_path}")


def init_sample_candidate_data():
    """Initialize candidate profile database with sample data.

    Args:
        None.

    Returns:
        None.
    """
    print("Initializing candidate profile database...")
    
    # Initialize database with explicit path
    db_path = str(Path.cwd() / "data" / "app.db")
    engine = init_candidate_db(db_path)
    
    now = datetime.now(timezone.utc).isoformat()
    candidate_id = str(uuid4())
    
    # Save sample candidate
    save_candidate(
        candidate_id=candidate_id,
        resume_raw="Sample resume text...",
        candidate_profile_json='{"skills": ["Python", "Strategy"], "experience": "5 years"}',
        llm_model="gpt-4",
        prompt_version="1.0",
        created_at=now,
        updated_at=now,
        preferences={
            "locations": ["San Francisco", "Palo Alto"],
            "remote_preference": "hybrid",
            "role_targets": ["Strategy", "Corp Dev"],
            "industries": ["Tech", "Venture"],
            "dealbreakers": [],
            "comp_min": 150000,
            "work_auth": "US Citizen",
        },
    )
    print(f"✓ Candidate profile database initialized with 1 sample candidate")


if __name__ == "__main__":
    try:
        init_sample_job_data()
        init_sample_candidate_data()
        print("\n✓ All data initialized to unified database!")
        print("\nUnified Database location:")
        print("  - C:\\Users\\yugua\\Projects\\AgenticJobSearch\\agents\\data\\app.db")
        print("\nTables in unified database:")
        print("  - Candidate, CandidatePreferences, AgentRun (from candidate_profile)")
        print("  - JobRetrievalBatch, Job (from job_search)")
        print("\nYou can now open this file in VS Code SQLite extension!")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
