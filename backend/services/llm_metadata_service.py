"""
Enhanced resume-aware chunking service.
 
Key improvements over the original:
  1. Rich project chunks — tech_stack, deployment, tools, outcomes, role per project
  2. Contextual skills — each skill mapped to the projects that used it
  3. Cross-linked experience — job entries reference related skills and projects
  4. Auto-computed experience years from date ranges (not just passed-through)
  5. Skill-frequency stats chunk for "most used", "primary stack" queries
  6. Enhanced LLM extraction prompt with all the missing fields
"""
 
import os
import re
import json
import datetime
from typing import List, Dict, Any, Tuple, Optional
from groq import Groq
 
# ---------------------------------------------------------------------------
# Updated extraction prompt — drop this into your LlmMetadataService
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
- "current_or_last_role": string | null
- "total_experience_years": number | null   (derive from date ranges if not stated)
- "education": string | null                (highest degree)
- "companies_worked_at": [string]
- "key_skills": [string]                    (flat list — keep ALL mentioned skills)
- "summary": string                         (2-3 recruiter-friendly sentences)
 
- "notable_projects": [                     (ONE object per project)
    {
      "name": string,
      "description": string,               (what the project does)
      "role": string | null,               (your role: e.g. "Solo developer", "Backend lead")
      "tech_stack": [string],              (languages, frameworks, libraries)
      "tools": [string],                   (dev tools, IDEs, CI/CD, monitoring)
      "deployment": string | null,         (where/how: "AWS EC2", "Vercel", "Docker + K8s")
      "outcome": string | null,            (impact or result if mentioned)
      "duration": string | null            (e.g. "3 months", "Jan 2023 – Apr 2023")
    }
  ]
 
- "work_experience": [                      (ONE object per job)
    {
      "company": string,
      "role": string,
      "start_date": string | null,         (e.g. "Jan 2021")
      "end_date": string | null,           ("Present" or date)
      "duration_months": number | null,    (calculate if possible)
      "responsibilities": [string],        (key bullet points)
      "skills_used": [string],             (subset of key_skills used in this role)
      "projects_at_company": [string]      (project names that belong to this job)
    }
  ]
 
If a field is not found, use null or an empty array as appropriate.
""".strip()
 
 
# ---------------------------------------------------------------------------
# Experience date parser — computes months from human-readable date strings
# ---------------------------------------------------------------------------
 
MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}
 
 
def parse_date_to_ym(date_str: str) -> Optional[Tuple[int, int]]:
    """
    Converts a fuzzy date string to (year, month).
    Handles: "Jan 2021", "2021-01", "2021", "Present", "Current", etc.
    Returns None if unparseable.
    """
    if not date_str:
        return None
    s = date_str.strip().lower()
    if s in ('present', 'current', 'now', 'till date', 'to date'):
        now = datetime.date.today()
        return (now.year, now.month)
    # "Jan 2021" or "January 2021"
    m = re.match(r'([a-z]+)[\s\-/](\d{4})', s)
    if m:
        month = MONTH_MAP.get(m.group(1)[:3])
        if month:
            return (int(m.group(2)), month)
    # "2021-01" or "01/2021"
    m = re.match(r'(\d{4})[\-/](\d{1,2})', s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.match(r'(\d{1,2})[/\-](\d{4})', s)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    # Just a year
    m = re.match(r'^(\d{4})$', s)
    if m:
        return (int(m.group(1)), 6)   # assume mid-year
    return None
 
 
def months_between(start: Tuple[int, int], end: Tuple[int, int]) -> int:
    return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]))
 
 
def compute_total_experience(work_experience: List[Dict]) -> float:
    """
    Sums non-overlapping employment months across all jobs and returns years.
    Falls back to duration_months if start/end dates are missing.
    """
    intervals: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    fallback_months = 0
 
    for job in work_experience:
        start = parse_date_to_ym(job.get('start_date') or '')
        end   = parse_date_to_ym(job.get('end_date') or 'Present')
        if start and end:
            intervals.append((start, end))
        else:
            fallback_months += job.get('duration_months') or 0
 
    # Merge overlapping intervals so concurrent jobs aren't double-counted
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
# LLM metadata extraction service
# ---------------------------------------------------------------------------

class LlmMetadataService:
    def __init__(self, groq_client: Groq):
        self.groq_client = groq_client

    def extract_resume_metadata(self, resume_text: str) -> dict:
        """
        Uses the Groq LLM to parse a resume into structured metadata.
        Also computes total_experience_years from work_experience date ranges
        so the value is accurate rather than LLM-guessed.
        """
        try:
            response = self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": f"Here is the resume text:\n\n{resume_text[:8000]}"}
                ],
                model=os.environ.get("MODEL", "llama-3.3-70b-versatile"),
                temperature=0.0,
            )

            raw_content = response.choices[0].message.content.strip()

            # Strip markdown code fences if the model wrapped them
            if raw_content.startswith("```"):
                raw_content = raw_content.strip("`").strip()
                if raw_content.lower().startswith("json"):
                    raw_content = raw_content[4:].strip()

            metadata = json.loads(raw_content)

            # Compute accurate experience years from date ranges
            work_exp = metadata.get("work_experience") or []
            if work_exp:
                computed = compute_total_experience(work_exp)
                if computed > 0:
                    metadata["total_experience_years"] = computed

            return metadata

        except json.JSONDecodeError as e:
            print(f"Warning: LLM returned invalid JSON: {e}. Using minimal metadata.")
            return {"summary": "Metadata could not be extracted automatically."}
        except Exception as e:
            print(f"LLM metadata extraction failed: {e}")
            return {}