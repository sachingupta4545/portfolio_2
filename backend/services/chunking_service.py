import re
import datetime
from typing import List, Dict, Any, Tuple, Optional
from services.llm_metadata_service import compute_total_experience

SECTION_HEADERS = {
    'summary':        [r'summary', r'objective', r'profile', r'about me',
                       r'professional summary', r'career objective'],
    'skills':         [r'skills?', r'technical skills?', r'core competencies',
                       r'technologies', r'expertise', r'tools & technologies', r'tech stack'],
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
 
 
 
# ---------------------------------------------------------------------------
# Main chunking service
# ---------------------------------------------------------------------------
 
class ChunkingService:
    """
    Resume-aware chunking service with rich project, skills, and experience chunks.
 
    Design goals:
    - Every fact about a project lives inside one self-contained chunk so the
      LLM never needs to join information across chunks to answer "what stack
      did you use for X?"
    - Skills are stored with project context so "which projects used Python?"
      has a direct answer.
    - Experience years are computed from date ranges — not trusted from the
      LLM's guess — and stored in a dedicated stats chunk.
    - Deduplication: same content is never stored twice.
    """
 
    def __init__(self):
        self._section_map = self._build_section_map()
 
    # ── Section detection ────────────────────────────────────────────────────
 
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
 
    # ── Chunk builders ───────────────────────────────────────────────────────
 
    def _build_project_chunk(self, project: Dict) -> str:
        """
        Builds a rich, self-contained project chunk.
 
        A recruiter chatbot can answer ALL of these from a single chunk:
          - "What did you build?"          → description
          - "What stack did you use?"      → tech_stack
          - "How did you deploy it?"       → deployment
          - "What tools did you use?"      → tools
          - "What was the outcome?"        → outcome
          - "What was your role?"          → role
        """
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
 
    def _build_skills_chunk(self, key_skills: List[str], projects: List[Dict]) -> str:
        """
        Builds a contextual skills chunk.
 
        Maps each skill to the projects that used it so the LLM can answer:
          - "Which projects used React?"
          - "Have you used Kubernetes in production?"
        """
        # Build a reverse map: skill -> [project names]
        skill_to_projects: Dict[str, List[str]] = {}
        for skill in key_skills:
            skill_to_projects[skill] = []
 
        for proj in projects:
            proj_name = proj.get('name', '')
            for tech in proj.get('tech_stack', []):
                # Case-insensitive partial match
                for skill in key_skills:
                    if skill.lower() in tech.lower() or tech.lower() in skill.lower():
                        if proj_name not in skill_to_projects.get(skill, []):
                            skill_to_projects.setdefault(skill, []).append(proj_name)
            for tool in proj.get('tools', []):
                for skill in key_skills:
                    if skill.lower() in tool.lower() or tool.lower() in skill.lower():
                        if proj_name not in skill_to_projects.get(skill, []):
                            skill_to_projects.setdefault(skill, []).append(proj_name)
 
        lines = ["Skills & Technologies (with project context):"]
        for skill in key_skills:
            linked = skill_to_projects.get(skill, [])
            if linked:
                lines.append(f"  • {skill} — used in: {', '.join(linked)}")
            else:
                lines.append(f"  • {skill}")
 
        return '\n'.join(lines)
 
    def _build_experience_chunk(self, job: Dict, i: int) -> str:
        """
        Builds a cross-linked experience chunk that references related skills
        and projects so the LLM can connect them without cross-chunk reasoning.
        """
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
 
    def _build_stats_chunk(
        self,
        total_exp_years: float,
        work_experience: List[Dict],
        key_skills: List[str],
        projects: List[Dict],
    ) -> str:
        """
        A dedicated stats chunk for aggregate queries:
          - "How many years of experience do you have?"
          - "What are your top skills?"
          - "How many projects have you built?"
        """
        lines = ["Career statistics & summary:"]
        lines.append(f"Total professional experience: {total_exp_years} years")
 
        if work_experience:
            lines.append(f"Number of positions held: {len(work_experience)}")
            companies = [j.get('company', '') for j in work_experience if j.get('company')]
            if companies:
                lines.append(f"Companies: {', '.join(companies)}")
 
        if projects:
            lines.append(f"Total projects: {len(projects)}")
            all_tech: Dict[str, int] = {}
            for p in projects:
                for t in p.get('tech_stack', []):
                    all_tech[t] = all_tech.get(t, 0) + 1
                for t in p.get('tools', []):
                    all_tech[t] = all_tech.get(t, 0) + 1
            if all_tech:
                top = sorted(all_tech.items(), key=lambda x: x[1], reverse=True)[:8]
                lines.append(
                    "Most-used technologies: "
                    + ', '.join(f"{t} ({c}x)" for t, c in top)
                )
            deployments = list({
                p['deployment'] for p in projects if p.get('deployment')
            })
            if deployments:
                lines.append(f"Deployment platforms used: {', '.join(deployments)}")
 
        if key_skills:
            lines.append(f"Total skills listed: {len(key_skills)}")
 
        return '\n'.join(lines)
 
    # ── Public API ───────────────────────────────────────────────────────────
 
    def process_and_chunk(
        self,
        text: str,
        source_metadata: Dict[str, Any] = None,
    ) -> Dict[str, List]:
        """
        Main entry point.
 
        Args:
            text:            Raw resume text.
            source_metadata: Dict returned by LlmMetadataService.extract_resume_metadata().
 
        Returns:
            {"documents": [...], "metadatas": [...]}  — ready for Qdrant upsert.
        """
        base_meta = source_metadata or {}
        ingest_time = datetime.datetime.now().isoformat()
 
        # Lightweight identity metadata attached to every chunk
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
            metadatas.append({
                **core_meta,
                'section': section,
                'chunk_index': len(documents) - 1,
            })
 
        # ── Computed experience years ────────────────────────────────────────
        work_experience: List[Dict] = base_meta.get('work_experience') or []
        computed_years = compute_total_experience(work_experience)
        # Fallback: trust LLM value if we couldn't compute
        if computed_years == 0.0 and base_meta.get('total_experience_years'):
            computed_years = float(base_meta['total_experience_years'])
 
        # ── Chunk: profile overview ──────────────────────────────────────────
        profile_lines = []
        for label, key in [
            ("Candidate", "candidate_name"),
            ("Role", "current_or_last_role"),
            ("Education", "education"),
            ("Email", "email"),
            ("Phone", "phone"),
            ("LinkedIn", "linkedin"),
            ("GitHub", "github"),
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
 
        # ── Chunk: rich project chunks (one per project) ─────────────────────
        projects: List[Dict] = base_meta.get('notable_projects') or []
        for project in projects:
            chunk_text = self._build_project_chunk(project)
            add_chunk(chunk_text, 'project')
 
        # ── Chunk: contextual skills ─────────────────────────────────────────
        key_skills: List[str] = base_meta.get('key_skills') or []
        if key_skills:
            skills_chunk = self._build_skills_chunk(key_skills, projects)
            add_chunk(skills_chunk, 'skills')
 
        # ── Chunks: cross-linked experience (one per job) ────────────────────
        for i, job in enumerate(work_experience, 1):
            chunk_text = self._build_experience_chunk(job, i)
            add_chunk(chunk_text, 'experience')
 
        # ── Chunk: career stats ──────────────────────────────────────────────
        stats_chunk = self._build_stats_chunk(
            computed_years, work_experience, key_skills, projects
        )
        add_chunk(stats_chunk, 'stats')
 
        # ── Chunks: raw section text (fallback / supplementary) ──────────────
        # We still parse raw text for anything the LLM might have missed:
        # certifications, education details, languages, interests, etc.
        raw_sections = self._split_into_sections(text)
        for section_name, section_content in raw_sections:
            if not section_content.strip():
                continue
 
            if section_name == 'experience':
                # Only add raw experience chunks if we didn't get structured data
                if not work_experience:
                    job_entries = self._split_experience_by_job(section_content)
                    for j, job_raw in enumerate(job_entries or [section_content], 1):
                        add_chunk(f"Work Experience (Position {j}):\n{job_raw}", 'experience')
 
            elif section_name in ('skills', 'projects'):
                # Already have rich structured chunks for these — skip raw repetition
                # unless structured data was completely absent
                if section_name == 'skills' and not key_skills:
                    add_chunk(f"Skills:\n{section_content}", 'skills')
                elif section_name == 'projects' and not projects:
                    add_chunk(f"Projects:\n{section_content}", 'projects')
 
            elif section_name not in ('general',):
                # Education, certifications, languages, interests, etc.
                label = section_name.replace('_', ' ').title()
                add_chunk(f"{label}:\n{section_content}", section_name)
 
        sections_used = set(m['section'] for m in metadatas)
        print(
            f"✅ Chunking complete: {len(documents)} unique chunks "
            f"(sections: {sections_used}, experience: {computed_years} yrs)"
        )
        return {"documents": documents, "metadatas": metadatas}