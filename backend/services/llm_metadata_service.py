"""
LLM Metadata Service — dual mode:
  1. Resume extraction  (LlmMetadataService)  → called by /api/upload-resume
  2. Project extraction (ProjectIngestionService) → called by /api/upload-project

Both use Groq to parse raw document text into structured JSON.
"""

import os
import re
import json
import datetime
from typing import List, Dict, Any, Tuple, Optional
from groq import Groq


# ---------------------------------------------------------------------------
# ❶  RESUME extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """
You are a precise resume parser. Given the raw text of a resume, extract the
following information and return it ONLY as a valid JSON object. No markdown
fences, no commentary — raw JSON only.

Fields:
- "candidate_name": string
- "email": string | null
- "phone": string | null
- "linkedin": string | null
- "github": string | null
- "portfolio": string | null
- "current_or_last_role": string | null
- "total_experience_years": number | null (derive from date ranges if not stated)
- "education": string | null                (highest degree + institution)
- "companies_worked_at": [string]
- "key_skills": [string]                    (flat list — keep ALL mentioned skills)
- "summary": string                         (2-3 recruiter-friendly sentences)

- "key_skills": [string]
  IMPORTANT — capture EVERY technology, language, framework, library, tool,
  platform, service, IDE, testing tool, DevOps tool, cloud service, etc.
  Examples: Python, FastAPI, React, Redux, Tailwind CSS, Docker, Kubernetes,
  GitHub Actions, Jest, Pytest, PostgreSQL, Redis, AWS S3, Vercel, Figma,
  VS Code, Postman, Jira …

- "tools_and_technologies": {
    "languages":   [string],
    "frameworks":  [string],
    "libraries":   [string],
    "databases":   [string],
    "devops":      [string],
    "cloud":       [string],
    "testing":     [string],
    "design":      [string],
    "other":       [string]
  }

- "work_experience": [
    {
      "company": string,
      "role": string,
      "start_date": string | null,
      "end_date": string | null,
      "duration_months": number | null,
      "responsibilities": [string],
      "skills_used": [string],
      "projects_at_company": [string]
    }
  ]

- "notable_projects": [
    {
      "name": string,
      "description": string,
      "role": string | null,
      "tech_stack": [string],
      "tools": [string],
      "deployment": string | null,
      "outcome": string | null,
      "duration": string | null
    }
  ]

If a field is not found, use null or an empty array as appropriate.
""".strip()


# ---------------------------------------------------------------------------
# ❷  PROJECT extraction prompt
# ---------------------------------------------------------------------------

PROJECT_EXTRACTION_PROMPT = """
You are a precise technical documentation parser. Given raw text describing a
software project (from a Markdown file, PDF, or plain text), extract every
piece of information and return it ONLY as a valid JSON object matching the
schema below. No markdown fences, no commentary — raw JSON only.

Schema:
{
  "project_name": "string — exact project name",
  "overview": "string — what the project does, its purpose and target audience",
  "tech_stack": {
    "backend":    ["string — languages, frameworks, runtimes used server-side"],
    "frontend":   ["string — UI frameworks, libraries, styling"],
    "database":   ["string — databases, caches, search engines"],
    "infra":      ["string — Docker, Kubernetes, CI/CD, cloud infra"],
    "third_party":["string — external APIs, SDKs, SaaS services"]
  },
  "features": ["string — list every distinct user-facing or system feature"],
  "architecture": {
    "flow": ["string — step-by-step data/request flow; one step per item"],
    "components": ["string — major system components and their responsibility"]
  },
  "database_design": ["string — tables/collections, key fields, relationships, indexes"],
  "api_design": ["string — each route/method/payload description"],
  "core_logic": ["string — key algorithms, business rules, non-obvious decisions"],
  "edge_cases": ["string — edge cases handled and how"],
  "challenges": ["string — problems faced during development and how they were solved"],
  "optimizations": ["string — performance, caching, query, bundle optimizations applied"],
  "deployment": ["string — hosting, CI/CD pipeline, env config, monitoring"],
  "future_improvements": ["string — planned or possible enhancements"]
}

Rules:
- Extract ALL information present; do not skip or summarise.
- If a section is not mentioned in the text, return an empty array [] or null.
- Every list item should be a complete, self-contained sentence or phrase.
- Raw JSON only — no backticks, no comments.
""".strip()


# ---------------------------------------------------------------------------
# Helpers — experience date parsing & computation
# ---------------------------------------------------------------------------

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10,
    'november': 11, 'december': 12,
}


def parse_date_to_ym(date_str: str) -> Optional[Tuple[int, int]]:
    if not date_str:
        return None
    s = date_str.strip().lower()
    if s in ('present', 'current', 'now', 'till date', 'to date'):
        now = datetime.date.today()
        return (now.year, now.month)
    m = re.match(r'([a-z]+)[\s\-/](\d{4})', s)
    if m:
        month = MONTH_MAP.get(m.group(1)[:3])
        if month:
            return (int(m.group(2)), month)
    m = re.match(r'(\d{4})[\-/](\d{1,2})', s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.match(r'(\d{1,2})[/\-](\d{4})', s)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m = re.match(r'^(\d{4})$', s)
    if m:
        return (int(m.group(1)), 6)
    return None


def months_between(start: Tuple[int, int], end: Tuple[int, int]) -> int:
    return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]))


def compute_total_experience(work_experience: List[Dict]) -> float:
    intervals: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    fallback_months = 0

    for job in work_experience:
        start = parse_date_to_ym(job.get('start_date') or '')
        end   = parse_date_to_ym(job.get('end_date') or 'Present')
        if start and end:
            intervals.append((start, end))
        else:
            fallback_months += job.get('duration_months') or 0

    intervals.sort()
    merged: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    total_months = sum(months_between(s, e) for s, e in merged) + fallback_months
    return round(total_months / 12, 1)


# ---------------------------------------------------------------------------
# ❶  Resume extraction service
# ---------------------------------------------------------------------------

class LlmMetadataService:
    """Extracts structured resume metadata from raw resume text."""

    def __init__(self, groq_client: Groq):
        self.groq_client = groq_client

    def extract_resume_metadata(self, resume_text: str) -> dict:
        """
        Uses Groq to parse a resume into structured metadata.
        Computes total_experience_years from work_experience date ranges.
        """
        try:
            response = self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user",   "content": f"Here is the resume text:\n\n{resume_text[:8000]}"}
                ],
                model=os.environ.get("EXTRACT_MODEL", "llama-3.3-70b-versatile"),
                temperature=0.0,
            )

            raw_content = response.choices[0].message.content.strip()

            # Strip markdown fences if the model wrapped them
            if raw_content.startswith("```"):
                raw_content = raw_content.strip("`").strip()
                if raw_content.lower().startswith("json"):
                    raw_content = raw_content[4:].strip()

            metadata = json.loads(raw_content)

            work_exp = metadata.get("work_experience") or []
            if work_exp:
                computed = compute_total_experience(work_exp)
                if computed > 0:
                    metadata["total_experience_years"] = computed

            return metadata

        except json.JSONDecodeError as e:
            print(f"Warning: LLM returned invalid JSON (resume): {e}. Using minimal metadata.")
            return {"summary": "Metadata could not be extracted automatically."}
        except Exception as e:
            print(f"LLM resume metadata extraction failed: {e}")
            return {}


# ---------------------------------------------------------------------------
# ❷  Project extraction service
# ---------------------------------------------------------------------------

class ProjectIngestionService:
    """Extracts deep structured project data from raw project document text."""

    def __init__(self, groq_client: Groq):
        self.groq_client = groq_client

    def extract_project_metadata(self, project_text: str) -> dict:
        """
        Uses Groq to parse a project document into the deep project schema.
        The text can come from a .md, .pdf, or .txt file describing ONE project.
        """
        try:
            response = self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": PROJECT_EXTRACTION_PROMPT},
                    {"role": "user",   "content": f"Here is the project document:\n\n{project_text[:10000]}"}
                ],
                model=os.environ.get("EXTRACT_MODEL", "llama-3.3-70b-versatile"),
                temperature=0.0,
            )

            raw_content = response.choices[0].message.content.strip()

            if raw_content.startswith("```"):
                raw_content = raw_content.strip("`").strip()
                if raw_content.lower().startswith("json"):
                    raw_content = raw_content[4:].strip()

            project_data = json.loads(raw_content)
            return project_data

        except json.JSONDecodeError as e:
            print(f"Warning: LLM returned invalid JSON (project): {e}.")
            return {}
        except Exception as e:
            print(f"LLM project extraction failed: {e}")
            return {}