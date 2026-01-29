import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from db import save_retrieval_batch

load_dotenv()

API_URL = "https://api.theirstack.com/v1/jobs/search"
USER_AGENT = "JobSearchAgent/0.1 (+https://example.com; contact=research@example.com)"

DEFAULT_CONFIG = {
    "providers": [
        {
            "name": "theirstack",
            "type": "theirstack",
            "enabled": True,
            "api_key_env": "THEIRSTACK_API_KEY",
            "payload_overrides": {},
        }
    ]
}


def iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def clean_text(text: str) -> str:
    """Normalize whitespace to a single-space, trimmed string."""
    return " ".join(text.split())


def sha256_text(text: str) -> str:
    """Compute a sha256 hex digest for the given text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_description(url: str) -> str | None:
    """Fetch and extract visible text from a job detail page."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=20,
        )
    except requests.RequestException:
        return None
    if not resp.ok or not resp.text:
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    text = clean_text(soup.get_text(" ", strip=True))
    return text if text else None


def resolve_description(job: dict) -> str | None:
    """Return job description text from URL fetch or API field fallback."""
    for candidate in [job.get("final_url"), job.get("source_url")]:
        if not candidate:
            continue
        text = fetch_description(candidate)
        if text:
            return text
    if job.get("description"):
        return clean_text(job.get("description"))
    return None


def build_payload() -> dict:
    """Build the default TheirStack search payload."""
    return {
        "order_by": [
            {"desc": True, "field": "date_posted"},
            {"desc": True, "field": "discovered_at"},
        ],
        "page": 0,
        "limit": 5,
        "job_title_or": ["Corporate development", "Strategy", "Venture"],
        "job_title_not": ["Director", "Intern", "Lead"],
        "job_seniority_or": ["mid_level", "junior"],
        "job_description_contains_or": ["2+ years", "3+ years", "4+ years", "2 years", "3 years", "4 years"],
        "job_title_pattern_and": [],
        "job_title_pattern_or": [],
        "job_title_pattern_not": [],
        "job_country_code_or": ["US"],
        "job_country_code_not": [],
        "posted_at_max_age_days": 3,
        "posted_at_gte": None,
        "posted_at_lte": None,
        "discovered_at_max_age_days": None,
        "discovered_at_min_age_days": None,
        "discovered_at_gte": None,
        "discovered_at_lte": None,
        "job_description_pattern_or": [],
        "job_description_pattern_not": [],
        "job_description_pattern_is_case_insensitive": True,
        "job_description_contains_or": [],
        "job_description_contains_not": [],
        "job_description_pattern_case_sensitive_or": [],
        "remote": None,
        "only_jobs_with_reports_to": None,
        "reports_to_exists": None,
        "final_url_exists": None,
        "only_jobs_with_hiring_managers": None,
        "hiring_managers_exists": None,
        "job_id_or": [],
        "job_id_not": [],
        "job_ids": [],
        "job_seniority_or": [],
        "min_salary_usd": None,
        "max_salary_usd": None,
        "job_technology_slug_or": [],
        "job_technology_slug_not": [],
        "job_technology_slug_and": [],
        "job_location_pattern_or": [
            "Bay Area",
            "San Francisco",
            "San Jose",
            "Mountain View",
            "Sunnyvale",
            "Menlo Park",
            "Burlingame",
            "Redwood City",
            "Cupertino",
            "Palo Alto",
        ],
        "job_location_pattern_not": [],
        "job_location_or": [],
        "job_location_not": [],
        "url_domain_or": [],
        "url_domain_not": [],
        "scraper_name_pattern_or": [],
        "easy_apply": None,
        "employment_statuses_or": None,
        "company_name_or": [],
        "company_name_case_insensitive_or": [],
        "company_id_or": [],
        "company_domain_or": [],
        "company_domain_not": [],
        "company_name_not": [],
        "company_name_partial_match_or": [],
        "company_name_partial_match_not": [],
        "company_linkedin_url_or": [],
        "blur_company_data": False,
        "property_exists_or": [],
        "property_exists_and": [],
        "company_description_pattern_or": [],
        "company_description_pattern_not": [],
        "company_description_pattern_accent_insensitive": False,
        "min_revenue_usd": None,
        "max_revenue_usd": None,
        "min_employee_count": None,
        "max_employee_count": None,
        "min_employee_count_or_null": None,
        "max_employee_count_or_null": None,
        "min_funding_usd": None,
        "max_funding_usd": None,
        "funding_stage_or": [],
        "industry_or": [],
        "industry_not": [],
        "industry_id_or": [],
        "industry_id_not": [],
        "company_tags_or": [],
        "company_type": None,
        "company_investors_or": [],
        "company_investors_partial_match_or": [],
        "company_technology_slug_or": [],
        "company_technology_slug_and": [],
        "company_technology_slug_not": [],
        "only_yc_companies": False,
        "company_location_pattern_or": [],
        "company_country_code_or": [],
        "company_country_code_not": [],
        "company_list_id_or": [],
        "company_list_id_not": [],
        "company_linkedin_url_exists": None,
        "revealed_company_data": None,
        "last_funding_round_date_lte": None,
        "last_funding_round_date_gte": None,
        "include_total_results": False,
        "cursor": None,
    }


def call_theirstack(api_key: str, payload: dict) -> dict:
    """Call the TheirStack search endpoint and return JSON data."""
    response = requests.post(
        API_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
        json=payload,
        timeout=30,
    )
    if response.status_code == 403:
        try:
            err = response.json()
        except ValueError:
            err = {}
        if err.get("error", {}).get("code") == "E-020":
            payload = dict(payload)
            payload["limit"] = min(payload.get("limit", 30), 25)
            response = requests.post(
                API_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": USER_AGENT,
                },
                json=payload,
                timeout=30,
            )
    if not response.ok:
        print(f"Status: {response.status_code}")
        print("Response headers:")
        for key, value in response.headers.items():
            print(f"{key}: {value}")
        print("Response body:")
        print(response.text)
    response.raise_for_status()
    return response.json()


def map_job(job: dict, source: str) -> dict:
    """Map a provider job payload into the normalized job schema."""
    source_job_id = str(job.get("id")) if job.get("id") is not None else None
    canonical_url = job.get("final_url") or job.get("url") or job.get("source_url") or ""
    description_text = resolve_description(job)
    description_hash = sha256_text(description_text) if description_text else None
    location = job.get("short_location") or job.get("location")
    employment = None
    if isinstance(job.get("employment_statuses"), list) and job.get("employment_statuses"):
        employment = job.get("employment_statuses")[0]
    posted_at = job.get("date_posted")
    updated_at = job.get("date_reposted")
    date_found = job.get("discovered_at") or iso_now()
    job_id = source_job_id or description_hash or canonical_url
    dedupe_key_strong = (
        f"{source}:{source_job_id}" if source_job_id else (f"{source}:{canonical_url}" or None)
    )
    dedupe_key_soft = f"{source}:{job.get('company','')}:{job.get('job_title','')}:{location or ''}"
    return {
        "job_id": str(job_id) if job_id is not None else None,
        "source": source,
        "source_job_id": source_job_id,
        "canonical_url": canonical_url,
        "company": job.get("company"),
        "title": job.get("job_title"),
        "location": location,
        "employment_type": employment,
        "posted_at": posted_at,
        "updated_at": updated_at,
        "date_found": date_found,
        "description_text": description_text,
        "description_hash": description_hash,
        "dedupe_key_strong": dedupe_key_strong,
        "dedupe_key_soft": dedupe_key_soft,
        "retrieval_score": 0.0,
    }


@dataclass
class ProviderResult:
    """Container for provider responses."""
    provider_name: str
    jobs: list[dict]


class ProviderClient:
    """Base interface for provider clients."""
    def fetch(self) -> ProviderResult:
        """Fetch jobs from a provider and return a ProviderResult."""
        raise NotImplementedError


class TheirstackClient(ProviderClient):
    """Client for the TheirStack job search API."""
    def __init__(self, provider_config: dict):
        """Initialize client with provider config and environment API key."""
        self.provider_config = provider_config
        api_key_env = provider_config.get("api_key_env", "THEIRSTACK_API_KEY")
        self.api_key = os.getenv(api_key_env)
        if not self.api_key:
            raise RuntimeError(f"Missing {api_key_env} in environment.")

    def fetch(self) -> ProviderResult:
        """Execute the search and map results to the normalized schema."""
        payload = build_payload()
        payload_overrides = self.provider_config.get("payload_overrides") or {}
        payload.update(payload_overrides)
        data = call_theirstack(self.api_key, payload)
        raw_jobs = data.get("data", [])
        mapped_jobs = [map_job(job, self.provider_config.get("name", "theirstack")) for job in raw_jobs]
        return ProviderResult(provider_name=self.provider_config.get("name", "theirstack"), jobs=mapped_jobs)


class JobSearchClient:
    """Orchestrates multiple provider clients from config."""
    def __init__(self, config: dict):
        """Initialize clients based on the provided config."""
        self.config = config
        self.providers = []
        for provider in config.get("providers", []):
            if not provider.get("enabled", True):
                continue
            provider_type = provider.get("type")
            # Add more provider types here as needed
            if provider_type == "theirstack":
                self.providers.append(TheirstackClient(provider))
            else:
                raise ValueError(f"Unsupported provider type: {provider_type}")

    def run(self) -> dict:
        """Run all providers and return the batch output payload."""
        started_at = iso_now()
        jobs = []
        for provider in self.providers:
            result = provider.fetch()
            jobs.extend(result.jobs)
        finished_at = iso_now()
        return {
            "retrieval_batch": {
                "batch_id": str(uuid4()),
                "started_at": started_at,
                "finished_at": finished_at,
            },
            "jobs": jobs,
            "stats": {
                "sources_checked": len(self.providers),
                "jobs_fetched": len(jobs),
                "jobs_new": 0,
                "jobs_updated": 0,
                "jobs_deduped": 0,
            },
        }

    def save_to_db(self, batch_data: dict) -> None:
        """Save retrieval batch and jobs to database.
        
        Args:
            batch_data: Dictionary containing retrieval_batch metadata, jobs list,
                       and stats from the run() method.
        """
        save_retrieval_batch(batch_data)


def main() -> None:
    """CLI entrypoint that runs the job search client with defaults."""
    client = JobSearchClient(DEFAULT_CONFIG)
    output = client.run()
    print(json.dumps(output, indent=2))
    # Save to database
    client.save_to_db(output)


if __name__ == "__main__":
    main()
