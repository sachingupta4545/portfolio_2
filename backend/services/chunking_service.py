"""
Resume-aware + Deep-project chunking service.

Two public entry points:
  • process_and_chunk()      — used by /api/upload-resume
  • process_deep_project()   — used by /api/upload-project

Deep-project chunks are broken into three logical sub-chunks per project so
that BGE-small embeddings stay within the 512-token sweet spot and Qdrant
can retrieve the exact slice a user is asking about.
"""

import re
import datetime
from typing import List, Dict, Any, Tuple, Optional
from services.llm_metadata_service import compute_total_experience

SECTION_HEADERS = {
    'summary':        [r'summary', r'objective', r'profile', r'about me',
                       r'professional summary', r'career objective'],
    'skills':         [r'skills?', r'technical skills?', r'core competencies',
                       r'technologies', r'expertise', r'tools \& technologies', r'tech stack'],
    'experience':     [r'experience', r'work experience', r'professional experience',
                       r'employment history', r'work history', r'career history'],
    'education':      [r'education', r'academic background', r'qualifications?',
                       r'degrees?', r'academics?'],
    'projects':       [r'projects?', r'personal projects?', r'key projects?',
                       r'portfolio', r'side projects?'],
    'certifications': [r'certifications?', r'certificates?', r'awards?',
                       r'achievements?', r'honors?', r'licenses?'],
    'contact':        [r'contact', r'personal information', r'personal details',
                       r'contact information'],
    'languages':      [r'languages?', r'spoken languages?'],
    'interests':      [r'interests?', r'hobbies', r'extra-curricular'],
}


class ChunkingService:
    """
    Resume-aware chunking service with rich project, skills, and experience
    chunks. Also handles deep-project sub-chunking for /api/upload-project.
    """

    def __init__(self):
        self._section_map = self._build_section_map()

    # ── Section detection ─────────────────────────────────────────────────────

    def _build_section_map(self) -> List[Tuple[re.Pattern, str]]:
        compiled = []
        for section, patterns in SECTION_HEADERS.items():
            combined = '|'.join(patterns)
            pat = re.compile(rf'^(?:{combined})\s*[:\-]?\s*$', re.IGNORECASE)
            compiled.append((pat, section))
        return compiled

    def _detect_section_header(self, line: str) -> Optional[str]:
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            return None
        for pattern, section in self._section_map:
            if pattern.match(stripped):
                return section
        return None

    def _split_into_sections(self, text: str) -> List[Tuple[str, str]]:
        lines = text.split('\n')
        sections: List[Tuple[str, str]] = []
        current_section = 'general'
        current_lines: List[str] = []

        for line in lines:
            detected = self._detect_section_header(line)
            if detected:
                content = '\n'.join(current_lines).strip()
                if content:
                    sections.append((current_section, content))
                current_section = detected
                current_lines = []
            else:
                current_lines.append(line)

        content = '\n'.join(current_lines).strip()
        if content:
            sections.append((current_section, content))
        return sections

    def _split_experience_by_job(self, text: str) -> List[str]:
        date_pattern = re.compile(
            r'\b(\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}'
            r'|present|current)\b',
            re.IGNORECASE
        )
        lines = text.split('\n')
        entries: List[str] = []
        current_entry: List[str] = []

        for line in lines:
            is_boundary = (
                date_pattern.search(line)
                and len(line.strip()) < 120
                and current_entry
                and any(l.strip() for l in current_entry)
            )
            if is_boundary:
                entries.append('\n'.join(current_entry).strip())
                current_entry = [line]
            else:
                current_entry.append(line)

        if current_entry:
            entries.append('\n'.join(current_entry).strip())
        return [e for e in entries if e.strip()]

    # ── Resume chunk builders ─────────────────────────────────────────────────

    def _build_project_chunk(self, project: Dict) -> str:
        lines = [f"Project: {project.get('name', 'Unnamed project')}"]
        if project.get('role'):
            lines.append(f"Role: {project['role']}")
        if project.get('description'):
            lines.append(f"Description: {project['description']}")
        if project.get('tech_stack'):
            lines.append(f"Tech stack: {', '.join(project['tech_stack'])}")
        if project.get('tools'):
            lines.append(f"Tools used: {', '.join(project['tools'])}")
        if project.get('deployment'):
            lines.append(f"Deployment: {project['deployment']}")
        if project.get('outcome'):
            lines.append(f"Outcome / impact: {project['outcome']}")
        if project.get('duration'):
            lines.append(f"Duration: {project['duration']}")
        return '\n'.join(lines)

    def _build_skills_chunk(self, key_skills: List[str], tools_and_technologies: Dict, projects: List[Dict]) -> str:
        lines = ["Skills & Technologies:"]

        # Categorised tech breakdown
        categories = {
            "Languages":    tools_and_technologies.get("languages", []),
            "Frameworks":   tools_and_technologies.get("frameworks", []),
            "Libraries":    tools_and_technologies.get("libraries", []),
            "Databases":    tools_and_technologies.get("databases", []),
            "DevOps":       tools_and_technologies.get("devops", []),
            "Cloud":        tools_and_technologies.get("cloud", []),
            "Testing":      tools_and_technologies.get("testing", []),
            "Design":       tools_and_technologies.get("design", []),
            "Other Tools":  tools_and_technologies.get("other", []),
        }
        for label, items in categories.items():
            if items:
                lines.append(f"  {label}: {', '.join(items)}")

        # Skill → project mapping
        skill_to_projects: Dict[str, List[str]] = {s: [] for s in key_skills}
        for proj in projects:
            proj_name = proj.get('name', '')
            for tech in proj.get('tech_stack', []) + proj.get('tools', []):
                for skill in key_skills:
                    if skill.lower() in tech.lower() or tech.lower() in skill.lower():
                        if proj_name not in skill_to_projects.get(skill, []):
                            skill_to_projects.setdefault(skill, []).append(proj_name)

        linked_skills = [
            f"  • {s} — used in: {', '.join(skill_to_projects[s])}"
            if skill_to_projects.get(s) else f"  • {s}"
            for s in key_skills
        ]
        if linked_skills:
            lines.append("Skills with project context:")
            lines.extend(linked_skills)

        return '\n'.join(lines)

    def _build_experience_chunk(self, job: Dict, i: int) -> str:
        lines = [f"Work Experience (Position {i}):"]
        if job.get('role'):
            lines.append(f"Role: {job['role']}")
        if job.get('company'):
            lines.append(f"Company: {job['company']}")
        start = job.get('start_date') or ''
        end   = job.get('end_date') or ''
        if start or end:
            lines.append(f"Period: {start} – {end}".strip(' –'))
        if job.get('duration_months'):
            lines.append(f"Duration: ~{job['duration_months']} months")
        if job.get('responsibilities'):
            lines.append("Responsibilities:")
            for r in job['responsibilities']:
                lines.append(f"  • {r}")
        if job.get('skills_used'):
            lines.append(f"Skills used: {', '.join(job['skills_used'])}")
        if job.get('projects_at_company'):
            lines.append(f"Projects: {', '.join(job['projects_at_company'])}")
        return '\n'.join(lines)

    def _build_stats_chunk(self, total_exp_years: float, work_experience: List[Dict],
                           key_skills: List[str], projects: List[Dict]) -> str:
        lines = ["Career statistics & summary:"]
        lines.append(f"Total professional experience: {total_exp_years} years")
        if work_experience:
            lines.append(f"Number of positions held: {len(work_experience)}")
            companies = [j.get('company', '') for j in work_experience if j.get('company')]
            if companies:
                lines.append(f"Companies: {', '.join(companies)}")
        if projects:
            lines.append(f"Total projects in resume: {len(projects)}")
            all_tech: Dict[str, int] = {}
            for p in projects:
                for t in p.get('tech_stack', []) + p.get('tools', []):
                    all_tech[t] = all_tech.get(t, 0) + 1
            if all_tech:
                top = sorted(all_tech.items(), key=lambda x: x[1], reverse=True)[:8]
                lines.append("Most-used technologies: " + ', '.join(f"{t} ({c}x)" for t, c in top))
        if key_skills:
            lines.append(f"Total skills listed: {len(key_skills)}")
        return '\n'.join(lines)

    # ── Deep-project chunk builders ───────────────────────────────────────────

    def _build_deep_project_chunks(self, p: Dict) -> List[Tuple[str, str]]:
        """
        Splits a deep project JSON into 3 focused sub-chunks.
        Returns list of (chunk_text, sub_section_label).
        """
        name = p.get("project_name") or p.get("name") or "Unknown Project"
        chunks: List[Tuple[str, str]] = []

        # --- Chunk A: Overview, Features & Tech Stack ---
        a_lines = [f"Project: {name}"]
        if p.get("overview"):
            a_lines.append(f"Overview: {p['overview']}")

        ts = p.get("tech_stack") or {}
        if isinstance(ts, dict):
            for label, items in [
                ("Backend",     ts.get("backend", [])),
                ("Frontend",    ts.get("frontend", [])),
                ("Database",    ts.get("database", [])),
                ("Infra",       ts.get("infra", [])),
                ("Third-party", ts.get("third_party", [])),
            ]:
                if items:
                    a_lines.append(f"Tech Stack — {label}: {', '.join(items)}")
        elif isinstance(ts, list):
            a_lines.append(f"Tech Stack: {', '.join(ts)}")

        if p.get("features"):
            a_lines.append("Features:")
            for f_item in p["features"]:
                a_lines.append(f"  • {f_item}")

        chunks.append(('\n'.join(a_lines), 'project_overview'))

        # --- Chunk B: Architecture, DB Design & API Design ---
        b_lines = [f"Project: {name} — Architecture & Data Design"]

        arch = p.get("architecture") or {}
        if arch.get("flow"):
            b_lines.append("Architecture Flow:")
            for step in arch["flow"]:
                b_lines.append(f"  → {step}")
        if arch.get("components"):
            b_lines.append("Components:")
            for comp in arch["components"]:
                b_lines.append(f"  • {comp}")

        if p.get("database_design"):
            b_lines.append("Database Design:")
            for d in p["database_design"]:
                b_lines.append(f"  • {d}")

        if p.get("api_design"):
            b_lines.append("API Design:")
            for api in p["api_design"]:
                b_lines.append(f"  • {api}")

        if len(b_lines) > 1:
            chunks.append(('\n'.join(b_lines), 'project_architecture'))

        # --- Chunk C: Core Logic, Edge Cases, Challenges, Optimizations, Deployment, Future ---
        c_lines = [f"Project: {name} — Engineering & Operations"]

        if p.get("core_logic"):
            c_lines.append("Core Logic:")
            for item in p["core_logic"]:
                c_lines.append(f"  • {item}")

        if p.get("edge_cases"):
            c_lines.append("Edge Cases:")
            for item in p["edge_cases"]:
                c_lines.append(f"  • {item}")

        if p.get("challenges"):
            c_lines.append("Challenges:")
            for item in p["challenges"]:
                c_lines.append(f"  • {item}")

        if p.get("optimizations"):
            c_lines.append("Optimizations:")
            for item in p["optimizations"]:
                c_lines.append(f"  • {item}")

        if p.get("deployment"):
            c_lines.append("Deployment:")
            for item in p["deployment"]:
                c_lines.append(f"  • {item}")

        if p.get("future_improvements"):
            c_lines.append("Future Improvements:")
            for item in p["future_improvements"]:
                c_lines.append(f"  • {item}")

        if len(c_lines) > 1:
            chunks.append(('\n'.join(c_lines), 'project_engineering'))

        return chunks

    # ── Public API ────────────────────────────────────────────────────────────

    def process_and_chunk(self, text: str, source_metadata: Dict[str, Any] = None) -> Dict[str, List]:
        """
        Entry point for /api/upload-resume.
        Produces profile, skills, experience, project summary, and stats chunks.
        """
        base_meta = source_metadata or {}
        ingest_time = datetime.datetime.now().isoformat()

        core_meta = {
            k: base_meta[k]
            for k in ['candidate_name', 'email', 'phone', 'current_or_last_role', 'source', 'document_type']
            if base_meta.get(k)
        }
        core_meta['ingest_time'] = ingest_time

        documents: List[str] = []
        metadatas: List[Dict] = []
        seen: set = set()

        def add_chunk(doc: str, section: str):
            key = doc.strip()[:150]
            if key in seen or not doc.strip():
                return
            seen.add(key)
            documents.append(doc.strip())
            metadatas.append({**core_meta, 'section': section, 'chunk_index': len(documents) - 1})

        work_experience: List[Dict] = base_meta.get('work_experience') or []
        computed_years = compute_total_experience(work_experience)
        if computed_years == 0.0 and base_meta.get('total_experience_years'):
            computed_years = float(base_meta['total_experience_years'])

        # Profile overview
        profile_lines = []
        for label, key in [
            ("Candidate", "candidate_name"), ("Role", "current_or_last_role"),
            ("Education", "education"),      ("Email", "email"),
            ("Phone", "phone"),              ("LinkedIn", "linkedin"),
            ("GitHub", "github"),            ("Portfolio", "portfolio"),
        ]:
            val = base_meta.get(key)
            if val:
                profile_lines.append(f"{label}: {val}")
        if computed_years:
            profile_lines.append(f"Experience: {computed_years} years")
        companies = base_meta.get('companies_worked_at')
        if companies:
            profile_lines.append(f"Companies: {', '.join(companies)}")
        if base_meta.get('summary'):
            profile_lines.append(f"\nSummary: {base_meta['summary']}")
        if profile_lines:
            add_chunk('\n'.join(profile_lines), 'profile_overview')

        # Skills (with categorised tech breakdown)
        key_skills: List[str] = base_meta.get('key_skills') or []
        tools_and_tech: Dict = base_meta.get('tools_and_technologies') or {}
        projects: List[Dict] = base_meta.get('notable_projects') or []
        if key_skills or tools_and_tech:
            skills_chunk = self._build_skills_chunk(key_skills, tools_and_tech, projects)
            add_chunk(skills_chunk, 'skills')

        # Project summary chunks (brief — full details come from /api/upload-project)
        for project in projects:
            add_chunk(self._build_project_chunk(project), 'project_summary')

        # Experience chunks
        for i, job in enumerate(work_experience, 1):
            add_chunk(self._build_experience_chunk(job, i), 'experience')

        # Stats chunk
        stats_chunk = self._build_stats_chunk(computed_years, work_experience, key_skills, projects)
        add_chunk(stats_chunk, 'stats')

        # Raw section fallbacks
        raw_sections = self._split_into_sections(text)
        for section_name, section_content in raw_sections:
            if not section_content.strip():
                continue
            if section_name == 'experience' and not work_experience:
                for j, job_raw in enumerate(self._split_experience_by_job(section_content) or [section_content], 1):
                    add_chunk(f"Work Experience (Position {j}):\n{job_raw}", 'experience')
            elif section_name == 'skills' and not key_skills and not tools_and_tech:
                add_chunk(f"Skills:\n{section_content}", 'skills')
            elif section_name == 'projects' and not projects:
                add_chunk(f"Projects:\n{section_content}", 'projects')
            elif section_name not in ('general',):
                label = section_name.replace('_', ' ').title()
                add_chunk(f"{label}:\n{section_content}", section_name)

        sections_used = set(m['section'] for m in metadatas)
        print(f"✅ Resume chunking complete: {len(documents)} chunks (sections: {sections_used}, exp: {computed_years} yrs)")
        return {"documents": documents, "metadatas": metadatas}

    def process_deep_project(self, project_data: Dict, source_filename: str = "") -> Dict[str, List]:
        """
        Entry point for /api/upload-project.
        Splits a rich project JSON into 3 focused sub-chunks.
        """
        ingest_time = datetime.datetime.now().isoformat()
        project_name = project_data.get("project_name") or project_data.get("name") or "Unknown Project"

        core_meta = {
            "project_name":  project_name,
            "document_type": "project",
            "source":        source_filename,
            "ingest_time":   ingest_time,
        }

        documents: List[str] = []
        metadatas: List[Dict] = []
        seen: set = set()

        def add_chunk(doc: str, sub_section: str):
            key = doc.strip()[:150]
            if key in seen or not doc.strip():
                return
            seen.add(key)
            documents.append(doc.strip())
            metadatas.append({
                **core_meta,
                "section":     "project",
                "sub_section": sub_section,
                "chunk_index": len(documents) - 1,
            })

        for chunk_text, label in self._build_deep_project_chunks(project_data):
            add_chunk(chunk_text, label)

        print(f"✅ Project chunking complete: {len(documents)} sub-chunks for '{project_name}'")
        return {"documents": documents, "metadatas": metadatas}