import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from pydantic import BaseModel, Field

from background.config import BASE_DIR
from background.config import load_alert_config
from web import crud


OPENAI_IMPORT_ERROR = None
RAW_RESPONSE_DIR = BASE_DIR / "runtime" / "bright_data"
DEFAULT_OPENAI_RELEVANCE_SYSTEM_PROMPT = (
    "You score LinkedIn jobs for a candidate. Use candidate_profile and "
    "objective as the primary relevance criteria. Return structured results. "
    "Each result must include index, score "
    "from 0 to 100, include boolean, severity as info or high, and reason. "
    "Set include=true only when score is at least minimum_alert_score."
)


class JobScore(BaseModel):
    index: int
    score: int = Field(ge=0, le=100)
    include: bool
    severity: Literal["info", "high"]
    reason: str


class JobScoresResponse(BaseModel):
    results: list[JobScore]

try:
    from openai import OpenAI
except ImportError as exc:
    OpenAI = None
    OPENAI_IMPORT_ERROR = exc


def text(value: Any) -> str:
    return str(value or "").strip()


def first_value(item: dict, keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return text(value)
    return ""


def int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def response_error_message(response: requests.Response, label: str) -> str:
    body = response.text.strip()
    if len(body) > 2000:
        body = body[:2000] + "...[truncated]"
    return f"Bright Data {label} failed: {response.status_code} {response.reason}. Body: {body}"


def normalize_job(item: dict) -> dict[str, str]:
    title = first_value(item, ["title", "job_title", "job_title_text", "position", "name"])
    company = first_value(item, ["company", "company_name", "company_name_text", "organization", "employer"])
    location = first_value(item, ["location", "job_location", "formatted_location", "job_location_text"])
    remote = first_value(item, ["remote", "workplace_type", "workplace", "workplace_preference"])
    url = first_value(item, ["url", "job_url", "apply_url", "link", "job_posting_url"])
    input_payload = item.get("input")
    if not url and isinstance(input_payload, dict):
        url = first_value(input_payload, ["url", "job_url", "link"])
    description = first_value(item, ["description", "job_description", "summary", "about"])
    posted_at = first_value(item, ["posted_at", "date_posted", "listed_at", "created_at"])

    return {
        "title": title,
        "company": company,
        "location": location,
        "remote": remote,
        "url": url,
        "description": description,
        "posted_at": posted_at,
    }


def is_error_row(item: dict) -> bool:
    return bool(item.get("error") or item.get("error_code"))


def is_usable_job(item: dict) -> bool:
    job = normalize_job(item)
    return bool(job["title"] and job["url"])


def score_job(item: dict, config: dict) -> int:
    normalized = normalize_job(item)
    searchable_text = " ".join(
        [
            normalized["title"],
            normalized["description"],
            normalized["location"],
            normalized["remote"],
        ]
    ).lower()

    score = 0

    if any(term in searchable_text for term in ("devops", "platform", "sre", "kubernetes", "cloud", "reliability")):
        score += 45

    if any(term in searchable_text for term in ("automation", "ci/cd", "terraform", "linux", "observability")):
        score += 25

    if "remote" in searchable_text:
        score += 20

    if normalized["posted_at"]:
        score += 10

    return min(score, 100)


def ai_relevance_enabled(config: dict) -> bool:
    relevance = config.get("openai_relevance", {})
    return bool(relevance.get("enabled", False))


def openai_relevance_config(config: dict) -> dict:
    return config.get("openai_relevance", {})


def openai_min_score(config: dict) -> int:
    return int_value(openai_relevance_config(config).get("min_score"), 70)


def openai_max_jobs_to_score(config: dict) -> int:
    return int_value(openai_relevance_config(config).get("max_jobs_to_score"), 0)


def build_ai_job_payload(items: list[dict]) -> list[dict]:
    jobs = []
    for index, item in enumerate(items):
        job = normalize_job(item)
        jobs.append(
            {
                "index": index,
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "remote": job["remote"],
                "posted_at": job["posted_at"],
                "description": job["description"][:1800],
            }
        )
    return jobs


def job_summary(job: dict) -> str:
    parts = [job.get("title"), job.get("company"), job.get("location")]
    return " - ".join(text(part) for part in parts if text(part)) or "Untitled job"


def score_jobs_with_openai(items: list[dict], config: dict) -> dict[int, dict]:
    relevance = openai_relevance_config(config)
    if not ai_relevance_enabled(config):
        return {}

    api_key_env = text(relevance.get("api_key_env", "OPENAI_API_KEY"))
    if not os.getenv(api_key_env):
        print(f"[linkedin_jobs] OpenAI relevance disabled: missing {api_key_env}", flush=True)
        return {}

    if OpenAI is None:
        print(f"[linkedin_jobs] OpenAI relevance disabled: package not installed ({OPENAI_IMPORT_ERROR})", flush=True)
        return {}

    client = OpenAI(api_key=os.getenv(api_key_env))
    model = text(relevance.get("model", "gpt-4.1-mini"))
    system_prompt = text(relevance.get("system_prompt")) or DEFAULT_OPENAI_RELEVANCE_SYSTEM_PROMPT
    profile = text(relevance.get("profile"))
    objective = text(relevance.get("objective"))
    min_score = openai_min_score(config)
    batch_size = max(1, int_value(relevance.get("batch_size"), 10))
    scored: dict[int, dict] = {}

    for offset in range(0, len(items), batch_size):
        batch = items[offset : offset + batch_size]
        jobs = build_ai_job_payload(batch)
        prompt = {
            "candidate_profile": profile,
            "objective": objective,
            "minimum_alert_score": min_score,
            "jobs": jobs,
        }

        print(f"[linkedin_jobs] OpenAI scoring {len(batch)} jobs with {model}", flush=True)
        for job in jobs:
            print(f"[linkedin_jobs]   -> #{job['index']} {job_summary(job)}", flush=True)

        try:
            response = client.responses.parse(
                model=model,
                text_format=JobScoresResponse,
                input=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": (
                            "Candidate profile:\n"
                            f"{profile}\n\n"
                            "Objective:\n"
                            f"{objective}\n\n"
                            f"Minimum alert score: {min_score}\n\n"
                            "Jobs JSON:\n"
                            f"{json.dumps(prompt, ensure_ascii=False)}"
                        ),
                    },
                ],
            )
            payload = response.output_parsed
        except Exception as exc:
            if exc.__class__.__module__.startswith("openai"):
                raise
            print(f"[linkedin_jobs] OpenAI relevance parse failed: {exc}", flush=True)
            continue
        if payload is None:
            print("[linkedin_jobs] OpenAI relevance parse failed: empty parsed response", flush=True)
            continue

        for parsed_result in payload.results:
            result = parsed_result.model_dump()
            index = int_value(result.get("index"), -1)
            if 0 <= index < len(batch):
                scored[offset + index] = result
                print(
                    "[linkedin_jobs]   <- "
                    f"#{offset + index} score={result.get('score')} "
                    f"include={result.get('include')} severity={result.get('severity')} "
                    f"reason={text(result.get('reason'))[:140]}",
                    flush=True,
                )

    print(f"[linkedin_jobs] OpenAI relevance scored={len(scored)}", flush=True)
    return scored


def extract_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("data", "items", "results", "jobs"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def save_raw_response(label: str, body: str) -> Path:
    RAW_RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_RESPONSE_DIR / f"{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.raw"
    path.write_text(body, encoding="utf-8")
    print(f"[linkedin_jobs] raw response saved={path}", flush=True)
    return path


def parse_payload_text(body: str, debug: bool = False) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        if debug:
            print("[linkedin_jobs] raw response follows:", flush=True)
            print(body, flush=True)

        items = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                items.append(value)

        if items:
            print(f"[linkedin_jobs] parsed ndjson items={len(items)}", flush=True)
            if debug:
                print(f"[linkedin_jobs] first ndjson item={json.dumps(items[0], ensure_ascii=False)}", flush=True)
            return items

        raise


def parse_response_payload(response: requests.Response, label: str | None = None, debug: bool = False) -> Any:
    if label and debug:
        save_raw_response(label, response.text)

    try:
        return response.json()
    except ValueError:
        return parse_payload_text(response.text, debug=debug)


def extract_snapshot_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("snapshot_id", "snapshot", "id"):
        value = payload.get(key)
        if value:
            return text(value)

    return ""


def fetch_snapshot_items(provider: dict, api_token: str, snapshot_id: str) -> list[dict]:
    snapshot_url_template = provider.get(
        "snapshot_url",
        "https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}?format=json",
    )
    snapshot_url = snapshot_url_template.format(snapshot_id=snapshot_id)
    timeout_seconds = int(provider.get("snapshot_timeout_seconds", provider.get("timeout_seconds", 300)))
    poll_interval_seconds = int(provider.get("snapshot_poll_interval_seconds", 15))
    debug = bool_value(provider.get("debug_save_raw_responses"), False)
    deadline = time.monotonic() + timeout_seconds
    print(f"[linkedin_jobs] snapshot_id={snapshot_id}", flush=True)
    print(f"[linkedin_jobs] waiting for Bright Data snapshot", flush=True)

    while True:
        response = requests.get(
            snapshot_url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=60,
        )
        print(f"[linkedin_jobs] snapshot status={response.status_code}", flush=True)

        if response.status_code in (202, 409) and time.monotonic() < deadline:
            print(f"[linkedin_jobs] snapshot not ready, sleeping {poll_interval_seconds}s", flush=True)
            time.sleep(poll_interval_seconds)
            continue

        if response.status_code in (202, 409):
            raise TimeoutError(f"Bright Data snapshot {snapshot_id} was not ready after {timeout_seconds}s")

        if not response.ok:
            message = response_error_message(response, "snapshot")
            print(f"[linkedin_jobs] {message}", flush=True)
            raise RuntimeError(message)
        payload = parse_response_payload(response, f"snapshot_{snapshot_id}", debug=debug)
        if isinstance(payload, dict):
            print(f"[linkedin_jobs] snapshot payload keys={list(payload.keys())}", flush=True)
        elif isinstance(payload, list):
            print(f"[linkedin_jobs] snapshot payload list length={len(payload)}", flush=True)

        items = extract_items(payload)
        print(f"[linkedin_jobs] extracted snapshot rows={len(items)}", flush=True)
        return items


def build_discovery_inputs(config: dict) -> list[dict]:
    explicit_searches = config.get("searches", [])
    return [
        {key: value for key, value in search.items() if value not in ("", None, [])}
        for search in explicit_searches
        if isinstance(search, dict) and text(search.get("keyword"))
    ]


def build_bright_data_params(provider: dict) -> dict[str, str]:
    api_url = provider.get("api_url", "")
    existing_query = dict(parse_qsl(urlsplit(api_url).query))
    params = {
        "dataset_id": text(provider.get("dataset_id", existing_query.get("dataset_id", "gd_lpfll7v5hcqtkxl6l"))),
        "include_errors": text(existing_query.get("include_errors", "true")),
        "type": text(existing_query.get("type", "discover_new")),
        "discover_by": text(existing_query.get("discover_by", "keyword")),
    }

    limit_per_input = int_value(provider.get("limit_per_input"), 0)
    if limit_per_input > 0:
        params["limit_per_input"] = str(limit_per_input)

    return {key: value for key, value in params.items() if value}


def bright_data_trigger_url(provider: dict) -> str:
    api_url = provider.get("api_url", "https://api.brightdata.com/datasets/v3/trigger")
    split_url = urlsplit(api_url)
    path = split_url.path.replace("/datasets/v3/scrape", "/datasets/v3/trigger")
    return urlunsplit((split_url.scheme, split_url.netloc, path, "", ""))


def fetch_bright_data_jobs(config: dict) -> list[dict]:
    provider = config.get("bright_data", {})
    api_url = bright_data_trigger_url(provider)
    token_env = provider.get("api_token_env", "BRIGHT_DATA_API_TOKEN")
    api_token = os.getenv(token_env)
    search_inputs = build_discovery_inputs(config)
    debug = bool_value(provider.get("debug_save_raw_responses"), False)

    if not config.get("enabled", False):
        raise RuntimeError("LinkedIn job sync is disabled in config")

    if not api_url:
        raise RuntimeError("Missing linkedin_jobs.bright_data.api_url in config")

    if not search_inputs:
        raise RuntimeError("Missing linkedin_jobs.searches in config")

    if not api_token:
        raise RuntimeError(f"Missing Bright Data token env var: {token_env}")

    params = build_bright_data_params(provider)
    limit_per_input = int_value(provider.get("limit_per_input"), 0)

    print(f"[linkedin_jobs] Bright Data discovery inputs={len(search_inputs)}", flush=True)
    for search in search_inputs:
        print(
            "[linkedin_jobs]   search "
            f"keyword={search.get('keyword')!r} location={search.get('location')!r} "
            f"remote={search.get('remote')!r} time_range={search.get('time_range')!r}",
            flush=True,
        )
    if limit_per_input > 0:
        print(f"[linkedin_jobs] limit_per_input={limit_per_input}", flush=True)
    print(f"[linkedin_jobs] trigger endpoint={api_url}?{urlencode(params)}", flush=True)

    response = requests.post(
        api_url,
        params=params,
        json=search_inputs,
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=int(provider.get("timeout_seconds", 180)),
    )
    print(f"[linkedin_jobs] trigger status={response.status_code}", flush=True)
    if not response.ok:
        message = response_error_message(response, "trigger")
        print(f"[linkedin_jobs] {message}", flush=True)
        raise RuntimeError(message)
    response_payload = parse_response_payload(response, "trigger", debug=debug)
    if isinstance(response_payload, dict):
        print(f"[linkedin_jobs] trigger payload keys={list(response_payload.keys())}", flush=True)
    elif isinstance(response_payload, list):
        print(f"[linkedin_jobs] trigger payload list length={len(response_payload)}", flush=True)

    items = extract_items(response_payload)
    print(f"[linkedin_jobs] extracted trigger items={len(items)}", flush=True)
    if items:
        return items

    snapshot_id = extract_snapshot_id(response_payload)
    if snapshot_id:
        return fetch_snapshot_items(provider, api_token, snapshot_id)

    print("[linkedin_jobs] no items and no snapshot_id found in trigger response", flush=True)
    return []


def filter_job_rows(items: list[dict]) -> list[dict]:
    filtered = []
    error_rows = 0
    unusable_rows = 0

    for item in items:
        if is_error_row(item):
            error_rows += 1
            continue

        if not is_usable_job(item):
            unusable_rows += 1
            continue

        filtered.append(item)

    print(
        f"[linkedin_jobs] usable jobs={len(filtered)} error_rows={error_rows} unusable_rows={unusable_rows}",
        flush=True,
    )
    return filtered


def load_items_from_file(path: str) -> list[dict]:
    raw_path = Path(path)
    payload = parse_payload_text(raw_path.read_text(encoding="utf-8"), debug=False)
    items = extract_items(payload)
    print(f"[linkedin_jobs] loaded rows from file={len(items)} path={raw_path}", flush=True)
    return items


def sync_once(session, items_override: list[dict] | None = None) -> dict:
    started_at = datetime.now()
    config = load_alert_config().get("linkedin_jobs", {})
    source = "bright_data_linkedin_jobs"

    try:
        items = items_override if items_override is not None else fetch_bright_data_jobs(config)
        print(f"[linkedin_jobs] raw rows before filtering={len(items)}", flush=True)
        items = filter_job_rows(items)

        max_jobs_to_score = openai_max_jobs_to_score(config)
        if max_jobs_to_score > 0 and len(items) > max_jobs_to_score:
            print(
                f"[linkedin_jobs] limiting jobs sent to relevance scoring from {len(items)} to {max_jobs_to_score}",
                flush=True,
            )
            items = items[:max_jobs_to_score]

        min_score = openai_min_score(config)
        exclude_companies = {text(company).lower() for company in config.get("exclude_companies", [])}
        ai_scores = score_jobs_with_openai(items, config)
        alerts_created = 0

        for index, item in enumerate(items):
            normalized = normalize_job(item)
            company = normalized["company"].lower()
            if company and company in exclude_companies:
                print(f"[linkedin_jobs] excluded company={company}", flush=True)
                continue

            ai_score = ai_scores.get(index)
            score = int_value(ai_score.get("score"), 0) if ai_score else score_job(item, config)
            include_job = bool(ai_score.get("include", score >= min_score)) if ai_score else score >= min_score
            if not include_job or score < min_score:
                title = normalized["title"] or "LinkedIn job match"
                location = normalized["location"]
                print(f"[linkedin_jobs] skipped score={score} min_score={min_score} title={title!r} location={location!r}", flush=True)
                continue

            title = normalized["title"] or "LinkedIn job match"
            company_label = normalized["company"]
            location = normalized["location"]
            url = normalized["url"]
            external_id = first_value(item, ["id", "job_id", "external_id", "url", "job_url"]) or f"{title}-{company_label}-{location}"
            reason = text(ai_score.get("reason")) if ai_score else ""
            description = " - ".join(part for part in [company_label, location, reason] if part)
            severity = text(ai_score.get("severity")) if ai_score else ""
            if severity not in ("info", "high"):
                severity = "high" if score >= 85 else "info"

            crud.upsert_alert(
                session,
                alert_type="job",
                source=source,
                external_id=external_id,
                title=title,
                description=description or None,
                url=url or None,
                severity=severity,
                score=score,
                payload=item,
                synced_at=datetime.now(),
            )
            alerts_created += 1
            print(f"[linkedin_jobs] alert upserted score={score} title={title!r} company={company_label!r} location={location!r}", flush=True)

        crud.record_alert_run(
            session,
            source=source,
            status="ok",
            items_seen=len(items),
            alerts_created=alerts_created,
            started_at=started_at,
            finished_at=datetime.now(),
        )
        return {"synced": True, "items_seen": len(items), "alerts_created": alerts_created, "error": None}
    except Exception as exc:
        status = "skipped" if "disabled" in str(exc).lower() or "missing" in str(exc).lower() else "error"
        crud.record_alert_run(
            session,
            source=source,
            status=status,
            message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(),
        )
        return {"synced": False, "items_seen": 0, "alerts_created": 0, "error": str(exc)}


def main() -> None:
    from web.database import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Sync Bright Data LinkedIn job matches into Albus alerts")
    parser.add_argument("--from-file", help="Replay a saved Bright Data raw response instead of calling the API")
    args = parser.parse_args()

    init_db()
    items_override = load_items_from_file(args.from_file) if args.from_file else None

    with SessionLocal() as session:
        print(sync_once(session, items_override=items_override), flush=True)


if __name__ == "__main__":
    main()
