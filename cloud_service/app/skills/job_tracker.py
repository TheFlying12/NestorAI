"""Job Tracker skill — search remote jobs across multiple boards and track applications."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_service.app.models import JobApplication
from cloud_service.app.skills.agent_loop import run as agent_run

logger = logging.getLogger("cloud.skills.job_tracker")

JOB_SEARCH_TIMEOUT = 15.0
JOB_SEARCH_MAX_PER_SOURCE = 5

VALID_STATUSES = {"applied", "screening", "interview", "offer", "rejected", "withdrawn"}
STATUS_EMOJI = {
    "applied": "📤", "screening": "📞", "interview": "🤝",
    "offer": "🎉", "rejected": "❌", "withdrawn": "🚫",
}

JOB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": (
                "Search for remote jobs across multiple job boards (Remotive + RemoteOK + Arbeitnow). "
                "ALWAYS call this when the user wants to find or search for jobs, even if their request is vague. "
                "For vague requests like 'find me any job', use query='software engineer'. "
                "If a search returns no results, the tool automatically retries with broader terms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Job search keywords. Extract the core role/technology, e.g.: "
                            "'machine learning', 'python backend', 'product manager', 'react developer'. "
                            "For vague requests, use 'software engineer'. "
                            "Do NOT include filler words like 'remote', 'jobs', 'find', 'any'."
                        ),
                    },
                    "job_type": {
                        "type": "string",
                        "enum": ["any", "full_time", "contract", "part_time"],
                        "description": "Employment type filter (default: any)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_application",
            "description": "Save a job to the pipeline after searching. Call when user says 'save it', 'save #2', 'track this one', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "url": {"type": "string", "description": "Job posting URL"},
                    "salary_range": {"type": "string", "description": "e.g. '$90k–$130k'"},
                    "notes": {"type": "string"},
                },
                "required": ["company", "role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipeline",
            "description": "Show the user's tracked job applications, optionally filtered by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": list(VALID_STATUSES),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipeline_stats",
            "description": "Show a stage-by-stage overview of all applications with response rate.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_application_status",
            "description": "Move an application to a new stage (e.g. applied → interview).",
            "parameters": {
                "type": "object",
                "properties": {
                    "application_id": {"type": "integer"},
                    "status": {"type": "string", "enum": list(VALID_STATUSES)},
                    "notes": {"type": "string", "description": "What happened"},
                },
                "required": ["application_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application",
            "description": "Get full details for a specific application by ID.",
            "parameters": {
                "type": "object",
                "properties": {"application_id": {"type": "integer"}},
                "required": ["application_id"],
            },
        },
    },
]


# ─── Job board fetchers ────────────────────────────────────────────────────────

def _fmt_salary(sal_min, sal_max) -> str:
    if sal_min and sal_max:
        return f"${int(sal_min):,}–${int(sal_max):,}"
    if sal_min:
        return f"${int(sal_min):,}+"
    return ""


async def _fetch_remotive(query: str, job_type: str = "any") -> List[Dict]:
    """Remotive — full-text search. Falls back to latest software jobs if search is empty."""
    headers = {"User-Agent": "NestorAI/1.0"}

    async def _get(url: str) -> List[Dict]:
        async with httpx.AsyncClient(timeout=JOB_SEARCH_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json().get("jobs", [])

    def _to_result(j: Dict) -> Dict:
        return {
            "company": j.get("company_name", "Unknown"),
            "role": j.get("title", "Unknown"),
            "url": j.get("url", ""),
            "salary": j.get("salary", "").strip(),
            "location": j.get("candidate_required_location", "Worldwide"),
            "tags": ", ".join((j.get("tags") or [])[:4]),
            "job_type": j.get("job_type", ""),
            "source": "Remotive",
        }

    try:
        jobs = await _get(f"https://remotive.com/api/remote-jobs?search={quote(query)}&limit=20")
        if job_type != "any":
            jobs = [j for j in jobs if j.get("job_type", "") == job_type]
        if jobs:
            return [_to_result(j) for j in jobs[:JOB_SEARCH_MAX_PER_SOURCE]]
    except Exception as exc:
        logger.warning("Remotive search failed query=%r: %s", query, exc)

    # Fallback: browse latest software-dev listings and score by keyword overlap
    try:
        jobs = await _get("https://remotive.com/api/remote-jobs?category=software-dev&limit=30")
        query_words = set(query.lower().split())
        scored = []
        for j in jobs:
            title_words = set(j.get("title", "").lower().split())
            score = len(query_words & title_words)
            scored.append((score, j))
        scored.sort(key=lambda x: -x[0])
        top = [j for _, j in scored[:JOB_SEARCH_MAX_PER_SOURCE]] or jobs[:JOB_SEARCH_MAX_PER_SOURCE]
        return [_to_result(j) for j in top]
    except Exception as exc:
        logger.warning("Remotive fallback failed: %s", exc)
        return []


async def _fetch_remoteok(query: str) -> List[Dict]:
    """RemoteOK — tag-based. Uses the first keyword as the tag."""
    primary = query.split()[0].lower()
    try:
        async with httpx.AsyncClient(timeout=JOB_SEARCH_TIMEOUT) as client:
            r = await client.get(
                f"https://remoteok.com/api?tag={quote(primary)}",
                headers={"User-Agent": "NestorAI/1.0"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("RemoteOK failed query=%r: %s", query, exc)
        return []

    results = []
    for j in (data[1:] if isinstance(data, list) else []):
        if not isinstance(j, dict):
            continue
        results.append({
            "company": j.get("company", "Unknown"),
            "role": j.get("position", "Unknown"),
            "url": j.get("url") or j.get("apply_url", ""),
            "salary": _fmt_salary(j.get("salary_min"), j.get("salary_max")),
            "location": "Remote",
            "tags": ", ".join((j.get("tags") or [])[:4]),
            "job_type": "",
            "source": "RemoteOK",
        })
        if len(results) >= JOB_SEARCH_MAX_PER_SOURCE:
            break
    return results


async def _fetch_arbeitnow(query: str) -> List[Dict]:
    """Arbeitnow — reliable fallback, returns latest remote jobs filtered by keyword."""
    try:
        async with httpx.AsyncClient(timeout=JOB_SEARCH_TIMEOUT) as client:
            r = await client.get(
                "https://arbeitnow.com/api/job-board-api",
                headers={"User-Agent": "NestorAI/1.0"},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
    except Exception as exc:
        logger.warning("Arbeitnow failed: %s", exc)
        return []

    query_words = set(query.lower().split())
    scored = []
    for j in data:
        if not j.get("remote", False):
            continue
        title_words = set(j.get("title", "").lower().split())
        tag_words = set(t.lower() for t in (j.get("tags") or []))
        score = len(query_words & (title_words | tag_words))
        scored.append((score, j))

    scored.sort(key=lambda x: -x[0])
    results = []
    for _, j in scored[:JOB_SEARCH_MAX_PER_SOURCE]:
        results.append({
            "company": j.get("company_name", "Unknown"),
            "role": j.get("title", "Unknown"),
            "url": j.get("url", ""),
            "salary": "",
            "location": "Remote",
            "tags": ", ".join((j.get("tags") or [])[:4]),
            "job_type": ", ".join(j.get("job_types") or []),
            "source": "Arbeitnow",
        })
    return results


async def _search_all(query: str, job_type: str = "any") -> List[Dict]:
    """Search all three sources concurrently, deduplicate, return up to 8 results."""
    remotive, remoteok, arbeitnow = await asyncio.gather(
        _fetch_remotive(query, job_type),
        _fetch_remoteok(query),
        _fetch_arbeitnow(query),
        return_exceptions=True,
    )
    seen: set = set()
    merged: List[Dict] = []
    for batch in (remotive, remoteok, arbeitnow):
        if isinstance(batch, Exception):
            continue
        for job in batch:
            key = (job["company"].lower()[:30], job["role"].lower()[:40])
            if key not in seen:
                seen.add(key)
                merged.append(job)
            if len(merged) >= 8:
                return merged
    return merged


def _format_results(jobs: List[Dict], query: str) -> str:
    if not jobs:
        return (
            f"[TOOL: 0 results for query='{query}']. "
            f"Retry search_jobs with a shorter, simpler keyword "
            f"(e.g. if query was 'machine learning engineer', retry with 'machine learning' or 'python'). "
            f"If the user was vague, retry with 'software engineer'."
        )
    lines = [f"**{len(jobs)} remote jobs** matching '{query}':\n"]
    for i, j in enumerate(jobs, 1):
        parts = [f"{i}. **{j['company']}** — {j['role']}"]
        meta = []
        if j.get("salary"):
            meta.append(j["salary"])
        if j.get("job_type"):
            meta.append(j["job_type"].replace("_", " "))
        if j.get("location") and j["location"] not in ("Remote", "Worldwide"):
            meta.append(j["location"])
        meta.append(j["source"])
        parts.append("   " + " · ".join(meta))
        if j.get("tags"):
            parts.append(f"   Tags: {j['tags']}")
        if j.get("url"):
            parts.append(f"   {j['url']}")
        lines.append("\n".join(parts))
    lines.append("\nSay 'save #N' to add one to your pipeline, or ask me to filter by type/salary.")
    return "\n\n".join(lines)


# ─── Tool executor ─────────────────────────────────────────────────────────────

async def _execute_tool(name: str, args: Dict, db: AsyncSession, user_id: str) -> str:
    if name == "search_jobs":
        query = args.get("query", "").strip() or DEFAULT_QUERY
        job_type = args.get("job_type", "any")

        jobs = await _search_all(query, job_type)
        return _format_results(jobs, query)

    if name == "save_application":
        app = JobApplication(
            user_id=user_id,
            company=args["company"],
            role=args["role"],
            url=args.get("url"),
            salary_range=args.get("salary_range"),
            status="applied",
            notes=args.get("notes"),
        )
        db.add(app)
        await db.commit()
        await db.refresh(app)
        return (
            f"✅ Saved to pipeline (ID: {app.id}): **{app.company}** — {app.role}. "
            f"Say 'update {app.id} to screening' when you hear back."
        )

    if name == "get_pipeline":
        status_filter = args.get("status")
        q = select(JobApplication).where(JobApplication.user_id == user_id)
        if status_filter and status_filter in VALID_STATUSES:
            q = q.where(JobApplication.status == status_filter)
        q = q.order_by(JobApplication.applied_at.desc())
        result = await db.execute(q)
        apps = result.scalars().all()
        if not apps:
            return (
                f"No applications{' with status ' + status_filter if status_filter else ''} yet. "
                "Search for jobs to get started!"
            )
        lines = []
        for a in apps:
            emoji = STATUS_EMOJI.get(a.status, "•")
            days_ago = (datetime.now(timezone.utc) - a.applied_at).days
            age = f"{days_ago}d ago" if days_ago > 0 else "today"
            salary = f" · {a.salary_range}" if a.salary_range else ""
            lines.append(f"[{a.id}] {emoji} **{a.company}** — {a.role}{salary} | {a.status} | {age}")
        return f"{len(apps)} application(s):\n" + "\n".join(lines)

    if name == "get_pipeline_stats":
        result = await db.execute(
            select(JobApplication.status, func.count(JobApplication.id).label("n"))
            .where(JobApplication.user_id == user_id)
            .group_by(JobApplication.status)
        )
        rows = result.all()
        if not rows:
            return "No applications yet."
        total = sum(r.n for r in rows)
        lines = [f"Pipeline — {total} total:\n"]
        for status in ["applied", "screening", "interview", "offer", "rejected", "withdrawn"]:
            count = next((r.n for r in rows if r.status == status), 0)
            if count:
                emoji = STATUS_EMOJI.get(status, "•")
                lines.append(f"  {emoji} {status.title():<12} {'█' * count}  {count}")
        active = sum(r.n for r in rows if r.status in {"screening", "interview", "offer"})
        applied = next((r.n for r in rows if r.status == "applied"), 0)
        if applied + active > 0:
            rate = int(active / (applied + active) * 100)
            lines.append(f"\nResponse rate: {rate}% ({active} responses / {applied + active} sent)")
        return "\n".join(lines)

    if name == "update_application_status":
        app_id = int(args["application_id"])
        new_status = args["status"]
        result = await db.execute(
            select(JobApplication).where(
                JobApplication.id == app_id, JobApplication.user_id == user_id
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            return f"Application ID {app_id} not found."
        old_status = app.status
        app.status = new_status
        if args.get("notes"):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            app.notes = (app.notes or "").rstrip() + f"\n[{ts}] {args['notes']}"
        app.updated_at = datetime.now(timezone.utc)
        await db.commit()
        emoji = STATUS_EMOJI.get(new_status, "•")
        return f"{emoji} [{app_id}] {app.company} — {app.role}: {old_status} → {new_status}."

    if name == "get_application":
        app_id = int(args["application_id"])
        result = await db.execute(
            select(JobApplication).where(
                JobApplication.id == app_id, JobApplication.user_id == user_id
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            return f"Application ID {app_id} not found."
        days_ago = (datetime.now(timezone.utc) - app.applied_at).days
        parts = [
            f"[{app.id}] {STATUS_EMOJI.get(app.status, '')} **{app.company}** — {app.role}",
            f"Status: {app.status} · Applied {days_ago}d ago",
        ]
        if app.url:
            parts.append(f"URL: {app.url}")
        if app.salary_range:
            parts.append(f"Salary: {app.salary_range}")
        if app.notes:
            parts.append(f"Notes:\n{app.notes.strip()}")
        return "\n".join(parts)

    return f"Unknown tool: {name}"


# ─── Skill entry point ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a proactive job search assistant. Today: {today}.

## Search behaviour
The search_jobs tool queries three job boards simultaneously. Job boards use keyword matching, so:
- The query should be the core role or technology, not a full sentence. "machine learning" not "find machine learning jobs".
- If the tool returns 0 results, that means the keyword wasn't indexed — call search_jobs again with a simpler or shorter term. You can call it multiple times.
- If the user is vague ("find me anything", "just look for something", "any job"), interpret that as a broad search and use "software engineer" as the query.
- Casual words like "twin", "bro", "man" are slang/filler — ignore them when constructing the query.

## After search results
- Always show the apply URL for each result.
- Ask if the user wants to save any to their pipeline.
- "Save #2" or "save the Stripe one" → call save_application with those details.

## Pipeline updates
When the user mentions progress on an application, call update_application_status:
- Got a call / phone screen → 'screening'
- Had an interview → 'interview'
- Received an offer → 'offer'
- Got rejected → 'rejected'

Keep responses concise. The job listings speak for themselves."""


async def handle_stream(
    user_id: str,
    text: str,
    context_messages: List[Dict],
    llm_stream,
    llm_complete_with_tools,
    db: AsyncSession,
):
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=today)}]
    messages.extend(context_messages)
    messages.append({"role": "user", "content": text})

    try:
        async for token in agent_run(
            messages=messages,
            tools=JOB_TOOLS,
            tool_executor=_execute_tool,
            llm_complete_with_tools=llm_complete_with_tools,
            llm_stream=llm_stream,
            db=db,
            user_id=user_id,
        ):
            yield token
    except Exception:
        logger.warning("Job tracker failed", exc_info=True)
        yield "I hit an error searching for jobs. Please try again."
