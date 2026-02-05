import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, Iterable
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from sqlmodel import SQLModel, Field, Session, select
from uuid import uuid4

from db.utils import get_engine, init_db


class JobRetrievalBatch(SQLModel, table=True):
    """Model for storing job retrieval batches."""
    id: str = Field(primary_key=True)
    batch_id: str
    started_at: str
    finished_at: str
    sources_checked: int
    jobs_fetched: int
    jobs_new: int
    jobs_updated: int
    jobs_deduped: int
    created_at: str


class Job(SQLModel, table=True):
    """Model for storing individual job postings from Theirstack API."""
    # Primary keys and metadata
    id: str = Field(primary_key=True)
    batch_id: str = Field(foreign_key="jobretrievalbatch.batch_id")
    source: str
    created_at: str
    retrieval_score: float = 0.0
    
    # Core job information
    source_job_id: Optional[int] = None  # Original ID from Theirstack
    job_title: Optional[str] = None
    normalized_title: Optional[str] = None
    description: Optional[str] = None
    company: Optional[str] = None
    company_domain: Optional[str] = None
    company_json: Optional[str] = None  # Stores company_object as JSON
    
    # URLs
    url: Optional[str] = None
    final_url: Optional[str] = None
    source_url: Optional[str] = None
    
    # Location information
    location: Optional[str] = None
    short_location: Optional[str] = None
    long_location: Optional[str] = None
    state_code: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    countries: Optional[str] = None  # JSON array string
    country: Optional[str] = None
    country_codes: Optional[str] = None  # JSON array string
    country_code: Optional[str] = None
    cities: Optional[str] = None  # JSON array string
    continents: Optional[str] = None  # JSON array string
    locations_json: Optional[str] = None  # Stores locations array as JSON
    
    # Dates
    date_posted: Optional[str] = None
    discovered_at: Optional[str] = None
    date_reposted: Optional[str] = None
    reposted: Optional[bool] = None
    
    # Salary information
    salary_string: Optional[str] = None
    min_annual_salary: Optional[int] = None
    min_annual_salary_usd: Optional[int] = None
    max_annual_salary: Optional[int] = None
    max_annual_salary_usd: Optional[int] = None
    avg_annual_salary_usd: Optional[int] = None
    salary_currency: Optional[str] = None
    
    # Work arrangements
    remote: Optional[bool] = None
    hybrid: Optional[bool] = None
    employment_statuses: Optional[str] = None  # JSON array string
    employment_type: Optional[str] = None  # Deprecated - use employment_statuses
    
    # Seniority and application
    seniority: Optional[str] = None
    easy_apply: Optional[bool] = None
    
    # Technologies and skills
    technology_slugs: Optional[str] = None  # JSON array string
    
    # Hiring team information
    hiring_team: Optional[str] = None  # Stores hiring_team array as JSON
    manager_roles: Optional[str] = None  # JSON array string
    
    # Content matching
    matching_phrases: Optional[str] = None  # JSON array string
    matching_words: Optional[str] = None  # JSON array string
    
    # Data quality
    has_blurred_data: Optional[bool] = None
    
    # Deduplication
    dedupe_key_strong: Optional[str] = None
    dedupe_key_soft: Optional[str] = None
    
    # Legacy fields for backward compatibility
    job_id: Optional[str] = None
    canonical_url: Optional[str] = None
    description_text: Optional[str] = None  # Deprecated - use description
    description_hash: Optional[str] = None
    posted_at: Optional[str] = None  # Deprecated - use date_posted
    updated_at: Optional[str] = None  # Deprecated - use date_reposted
    date_found: Optional[str] = None


TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_NAMES = {
    "ref",
    "referrer",
    "source",
    "src",
    "campaign",
    "cmp",
    "tracking",
    "trk",
    "utm",
}


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize URL by removing tracking params and fragments.

    Args:
        url: Input URL string.

    Returns:
        Normalized URL or None.
    """
    if not url:
        return None
    parsed = urlparse(url.strip())
    query_params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k and k.lower() not in TRACKING_PARAM_NAMES
        and not k.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    normalized = parsed._replace(query=urlencode(query_params, doseq=True), fragment="")
    cleaned = urlunparse(normalized)
    if cleaned.endswith("/") and len(cleaned) > len(parsed.scheme + "://"):
        cleaned = cleaned.rstrip("/")
    return cleaned


def normalize_text(value: Optional[str]) -> str:
    """Normalize text to lowercase alphanumeric tokens.

    Args:
        value: Input string.

    Returns:
        Normalized string.
    """
    if not value:
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", value.lower())
    return " ".join(cleaned.split())


def clean_text(value: Optional[str]) -> str:
    """Normalize whitespace.

    Args:
        value: Input string.

    Returns:
        Cleaned string.
    """
    if not value:
        return ""
    return " ".join(value.split())


def sha256_text(value: str) -> str:
    """Compute sha256 hex digest for a string.

    Args:
        value: Input string.

    Returns:
        Hex digest string.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_dedupe_key_strong(source: Optional[str], source_job_id: Optional[str]) -> Optional[str]:
    """Build strong dedupe key from source and source id.

    Args:
        source: Source name.
        source_job_id: Source job id.

    Returns:
        Strong dedupe key or None.
    """
    if not source or not source_job_id:
        return None
    return f"{source}:{source_job_id}"


def build_dedupe_key_soft(company: Optional[str], title: Optional[str], location: Optional[str]) -> Optional[str]:
    """Build soft dedupe key from company, title, and location.

    Args:
        company: Company name.
        title: Job title.
        location: Job location.

    Returns:
        Soft dedupe key or None.
    """
    parts = [normalize_text(company), normalize_text(title), normalize_text(location)]
    if not any(parts):
        return None
    return "|".join(parts)


def is_missing(value: Any) -> bool:
    """Check if value is None or empty string.

    Args:
        value: Any value.

    Returns:
        True if missing, otherwise False.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def merge_job_fields(existing: Job, updates: Dict[str, Any]) -> bool:
    """Merge update fields into an existing Job.

    Args:
        existing: Existing Job record.
        updates: Dict of new fields.

    Returns:
        True if any field was changed.
    """
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        current = getattr(existing, key, None)
        if is_missing(current):
            setattr(existing, key, value)
            changed = True
        elif key in {"date_reposted", "updated_at", "discovered_at"} and value != current:
            setattr(existing, key, value)
            changed = True
    return changed


def find_duplicate(session: Session, job_fields: Dict[str, Any]) -> Optional[Job]:
    """Find existing job by dedupe keys.

    Args:
        session: SQLModel session.
        job_fields: Normalized job fields.

    Returns:
        Job if found, otherwise None.
    """
    dedupe_key_strong = job_fields.get("dedupe_key_strong")
    if dedupe_key_strong:
        stmt = select(Job).where(Job.dedupe_key_strong == dedupe_key_strong)
        existing = session.exec(stmt).first()
        if existing:
            return existing
    canonical_url = job_fields.get("canonical_url")
    if canonical_url:
        stmt = select(Job).where(Job.canonical_url == canonical_url)
        existing = session.exec(stmt).first()
        if existing:
            return existing
    dedupe_key_soft = job_fields.get("dedupe_key_soft")
    description_hash = job_fields.get("description_hash")
    if dedupe_key_soft and description_hash:
        stmt = select(Job).where(
            Job.dedupe_key_soft == dedupe_key_soft,
            Job.description_hash == description_hash,
        )
        existing = session.exec(stmt).first()
        if existing:
            return existing
    return None


def build_job_fields(job_data: Dict[str, Any], batch_id: str, created_at: str) -> Dict[str, Any]:
    """Normalize provider job payload into Job fields.

    Args:
        job_data: Raw job payload dict.
        batch_id: Retrieval batch id.
        created_at: ISO timestamp string.

    Returns:
        Dict of Job fields.
    """
    employment_type = job_data.get("employment_type")
    if not employment_type and job_data.get("employment_statuses"):
        employment_type = job_data.get("employment_statuses", [None])[0]
    description_text = job_data.get("description_text") or job_data.get("description")
    cleaned_description = clean_text(description_text) if description_text else ""
    description_hash = job_data.get("description_hash")
    if not description_hash and cleaned_description:
        description_hash = sha256_text(cleaned_description)
    canonical_url = (
        job_data.get("canonical_url")
        or job_data.get("final_url")
        or job_data.get("url")
        or job_data.get("source_url")
        or ""
    )
    canonical_url = normalize_url(canonical_url) or canonical_url
    source = job_data.get("source", "")
    source_job_id = job_data.get("id") or job_data.get("source_job_id")
    dedupe_key_strong = job_data.get("dedupe_key_strong") or build_dedupe_key_strong(
        source, str(source_job_id) if source_job_id is not None else None
    )
    dedupe_key_soft = job_data.get("dedupe_key_soft") or build_dedupe_key_soft(
        job_data.get("company"),
        job_data.get("job_title") or job_data.get("title"),
        job_data.get("location"),
    )
    return {
        "batch_id": batch_id,
        "source": source,
        "source_job_id": source_job_id,
        "job_id": job_data.get("job_id"),
        "job_title": job_data.get("job_title") or job_data.get("title"),
        "normalized_title": job_data.get("normalized_title"),
        "description": job_data.get("description"),
        "company": job_data.get("company"),
        "company_domain": job_data.get("company_domain"),
        "company_json": json.dumps(job_data.get("company_object")) if job_data.get("company_object") else None,
        "url": job_data.get("url"),
        "final_url": job_data.get("final_url"),
        "source_url": job_data.get("source_url"),
        "canonical_url": canonical_url,
        "location": job_data.get("location"),
        "short_location": job_data.get("short_location"),
        "long_location": job_data.get("long_location"),
        "state_code": job_data.get("state_code"),
        "postal_code": job_data.get("postal_code"),
        "latitude": job_data.get("latitude"),
        "longitude": job_data.get("longitude"),
        "countries": json.dumps(job_data.get("countries")) if job_data.get("countries") else None,
        "country": job_data.get("country"),
        "country_codes": json.dumps(job_data.get("country_codes")) if job_data.get("country_codes") else None,
        "country_code": job_data.get("country_code"),
        "cities": json.dumps(job_data.get("cities")) if job_data.get("cities") else None,
        "continents": json.dumps(job_data.get("continents")) if job_data.get("continents") else None,
        "locations_json": json.dumps(job_data.get("locations")) if job_data.get("locations") else None,
        "date_posted": job_data.get("date_posted") or job_data.get("posted_at"),
        "discovered_at": job_data.get("discovered_at") or job_data.get("date_found"),
        "date_reposted": job_data.get("date_reposted") or job_data.get("updated_at"),
        "reposted": job_data.get("reposted"),
        "salary_string": job_data.get("salary_string"),
        "min_annual_salary": job_data.get("min_annual_salary"),
        "min_annual_salary_usd": job_data.get("min_annual_salary_usd"),
        "max_annual_salary": job_data.get("max_annual_salary"),
        "max_annual_salary_usd": job_data.get("max_annual_salary_usd"),
        "avg_annual_salary_usd": job_data.get("avg_annual_salary_usd"),
        "salary_currency": job_data.get("salary_currency"),
        "remote": job_data.get("remote"),
        "hybrid": job_data.get("hybrid"),
        "employment_statuses": json.dumps(job_data.get("employment_statuses")) if job_data.get("employment_statuses") else None,
        "employment_type": employment_type,
        "seniority": job_data.get("seniority"),
        "easy_apply": job_data.get("easy_apply"),
        "technology_slugs": json.dumps(job_data.get("technology_slugs")) if job_data.get("technology_slugs") else None,
        "hiring_team": json.dumps(job_data.get("hiring_team")) if job_data.get("hiring_team") else None,
        "manager_roles": json.dumps(job_data.get("manager_roles")) if job_data.get("manager_roles") else None,
        "matching_phrases": json.dumps(job_data.get("matching_phrases")) if job_data.get("matching_phrases") else None,
        "matching_words": json.dumps(job_data.get("matching_words")) if job_data.get("matching_words") else None,
        "has_blurred_data": job_data.get("has_blurred_data"),
        "dedupe_key_strong": dedupe_key_strong,
        "dedupe_key_soft": dedupe_key_soft,
        "retrieval_score": job_data.get("retrieval_score", 0.0),
        "description_text": description_text,
        "description_hash": description_hash,
        "posted_at": job_data.get("posted_at"),
        "updated_at": job_data.get("updated_at"),
        "date_found": job_data.get("date_found"),
        "created_at": created_at,
    }


def get_db_path() -> str:
    """Get database path for job search - uses shared database.

    Args:
        None.

    Returns:
        Database path string.
    """
    db_path = os.getenv("DB_PATH")
    if not db_path:
        base_dir = Path(__file__).resolve().parents[2]
        db_path = str(base_dir / "data" / "app.db")
    print(f"[job_search.db] DB_PATH={db_path}")
    return db_path


def save_retrieval_batch(batch_data: Dict[str, Any]) -> list[str]:
    """Save job retrieval batch and associated jobs to database.
    
    Args:
        batch_data: Dictionary containing retrieval_batch metadata, jobs list,
                   and stats.

    Returns:
        List of new or updated job ids.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    batch_meta = batch_data.get("retrieval_batch", {})
    batch_id = batch_meta.get("batch_id")
    stats = batch_data.get("stats", {})
    finished_at = batch_meta.get("finished_at", "")
    new_or_updated_ids: list[str] = []
    seen_ids: set[str] = set()
    jobs_new = 0
    jobs_updated = 0
    jobs_deduped = 0
    
    # Save batch metadata
    batch = JobRetrievalBatch(
        id=str(uuid4()),
        batch_id=batch_id,
        started_at=batch_meta.get("started_at", ""),
        finished_at=finished_at,
        sources_checked=stats.get("sources_checked", 0),
        jobs_fetched=stats.get("jobs_fetched", 0),
        jobs_new=0,
        jobs_updated=0,
        jobs_deduped=0,
        created_at=finished_at,
    )
    
    with Session(engine) as session:
        session.add(batch)
        
        # Save individual jobs
        jobs = batch_data.get("jobs", [])
        for job_data in jobs:
            job_fields = build_job_fields(job_data, batch_id, finished_at)
            existing = find_duplicate(session, job_fields)
            if existing:
                jobs_deduped += 1
                existing.batch_id = batch_id
                if merge_job_fields(existing, job_fields):
                    jobs_updated += 1
                if existing.id not in seen_ids:
                    new_or_updated_ids.append(existing.id)
                    seen_ids.add(existing.id)
            else:
                job = Job(id=str(uuid4()), **job_fields)
                session.add(job)
                jobs_new += 1
                if job.id not in seen_ids:
                    new_or_updated_ids.append(job.id)
                    seen_ids.add(job.id)
        
        batch.jobs_new = jobs_new
        batch.jobs_updated = jobs_updated
        batch.jobs_deduped = jobs_deduped
        session.commit()
    return new_or_updated_ids


def get_retrieval_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a batch and its jobs from database.
    
    Args:
        batch_id: The batch ID to retrieve.
        
    Returns:
        Dictionary with batch metadata and jobs, or None if not found.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    
    with Session(engine) as session:
        # Get batch
        statement = select(JobRetrievalBatch).where(
            JobRetrievalBatch.batch_id == batch_id
        )
        batch = session.exec(statement).first()
        
        if not batch:
            return None
        
        # Get jobs for this batch
        statement = select(Job).where(Job.batch_id == batch_id)
        jobs = session.exec(statement).all()
        
        jobs_list = [
            {
                "job_id": job.job_id,
                "source": job.source,
                "source_job_id": job.source_job_id,
                "canonical_url": job.canonical_url,
                "company": job.company,
                "title": job.job_title,
                "location": job.location,
                "employment_type": job.employment_type,
                "posted_at": job.date_posted or job.posted_at,
                "updated_at": job.date_reposted or job.updated_at,
                "date_found": job.discovered_at or job.date_found,
                "description_text": job.description_text or job.description,
                "description_hash": job.description_hash,
                "dedupe_key_strong": job.dedupe_key_strong,
                "dedupe_key_soft": job.dedupe_key_soft,
                "retrieval_score": job.retrieval_score,
            }
            for job in jobs
        ]
        
        return {
            "retrieval_batch": {
                "batch_id": batch.batch_id,
                "started_at": batch.started_at,
                "finished_at": batch.finished_at,
            },
            "jobs": jobs_list,
            "stats": {
                "sources_checked": batch.sources_checked,
                "jobs_fetched": batch.jobs_fetched,
                "jobs_new": batch.jobs_new,
                "jobs_updated": batch.jobs_updated,
                "jobs_deduped": batch.jobs_deduped,
            },
        }


def get_recent_jobs(limit: int = 100) -> list[Dict[str, Any]]:
    """Retrieve recent jobs from database.
    
    Args:
        limit: Maximum number of jobs to retrieve.
        
    Returns:
        List of job dictionaries.
    """
    db_path = get_db_path()
    engine = init_db(db_path)
    
    with Session(engine) as session:
        statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
        jobs = session.exec(statement).all()
        
        return [
            {
                "job_id": job.job_id,
                "source": job.source,
                "company": job.company,
                "title": job.job_title,
                "location": job.location,
                "canonical_url": job.canonical_url,
                "posted_at": job.date_posted or job.posted_at,
                "date_found": job.discovered_at or job.date_found,
            }
            for job in jobs
        ]
