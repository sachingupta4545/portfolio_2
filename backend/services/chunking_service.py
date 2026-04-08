import re
import datetime
from typing import List, Dict, Any, Tuple, Optional

class ChunkingService:
    """
    Resume-aware semantic chunking service.

    Instead of blindly splitting every 500 characters, this service:
    1. Detects resume sections (Skills, Experience, Education, Projects, etc.)
    2. Creates one focused chunk per section
    3. Splits Experience further by individual job entry (not by character count)
    4. Creates structured "overview" chunks from LLM-extracted metadata
    5. Deduplicates — same content is never stored twice
    6. Attaches lightweight metadata to each chunk (no repeated arrays)
    """

    # Maps section types to their common header patterns
    SECTION_HEADERS = {
        'summary':          [r'summary', r'objective', r'profile', r'about me', r'professional summary', r'career objective'],
        'skills':           [r'skills?', r'technical skills?', r'core competencies', r'technologies', r'expertise', r'tools & technologies', r'tech stack'],
        'experience':       [r'experience', r'work experience', r'professional experience', r'employment history', r'work history', r'career history'],
        'education':        [r'education', r'academic background', r'qualifications?', r'degrees?', r'academics?'],
        'projects':         [r'projects?', r'personal projects?', r'key projects?', r'portfolio', r'side projects?'],
        'certifications':   [r'certifications?', r'certificates?', r'awards?', r'achievements?', r'honors?', r'licenses?'],
        'contact':          [r'contact', r'personal information', r'personal details', r'contact information'],
        'languages':        [r'languages?', r'spoken languages?'],
        'interests':        [r'interests?', r'hobbies', r'extra-curricular'],
    }

    def __init__(self):
        self._section_map = self._build_section_map()

    def _build_section_map(self) -> List[Tuple[re.Pattern, str]]:
        """Pre-compiles regex patterns for fast section header detection."""
        compiled = []
        for section, patterns in self.SECTION_HEADERS.items():
            combined = '|'.join(patterns)
            pat = re.compile(rf'^(?:{combined})\s*[:\-]?\s*$', re.IGNORECASE)
            compiled.append((pat, section))
        return compiled

    def _detect_section_header(self, line: str) -> Optional[str]:
        """Returns section type if line is a section header, else None."""
        stripped = line.strip()
        if not stripped or len(stripped) > 60:  # Headers are short
            return None
        for pattern, section in self._section_map:
            if pattern.match(stripped):
                return section
        return None

    def _split_into_sections(self, text: str) -> List[Tuple[str, str]]:
        """
        Splits raw resume text into (section_name, content) pairs.
        Falls back to 'general' for content before any detected header.
        """
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

        # Don't forget the last section
        content = '\n'.join(current_lines).strip()
        if content:
            sections.append((current_section, content))

        return sections

    def _split_experience_by_job(self, text: str) -> List[str]:
        """
        Splits an experience section into individual job entries.
        Uses date patterns (2019, Jan 2020, Present) to detect job boundaries.
        """
        date_pattern = re.compile(
            r'\b(\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}|present|current)\b',
            re.IGNORECASE
        )
        lines = text.split('\n')
        entries: List[str] = []
        current_entry: List[str] = []

        for line in lines:
            # A new job entry starts when we see a date on a short line (title/company line)
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

    def process_and_chunk(self, text: str, source_metadata: Dict[str, Any] = None) -> Dict[str, List]:
        """
        Main entry point. Accepts raw resume text + LLM-extracted metadata.
        Returns a deduplicated, section-aware list of chunks and their metadata.
        """
        base_meta = source_metadata or {}
        ingest_time = datetime.datetime.now().isoformat()

        # Lightweight core fields attached to every chunk (no large arrays)
        core_meta = {
            k: base_meta[k]
            for k in ['candidate_name', 'email', 'phone', 'current_or_last_role',
                      'total_experience_years', 'source', 'document_type']
            if base_meta.get(k)
        }
        core_meta['ingest_time'] = ingest_time

        documents: List[str] = []
        metadatas: List[Dict] = []
        seen: set = set()  # For deduplication

        def add_chunk(doc: str, section: str):
            """Adds a chunk only if its content hasn't been seen before."""
            key = doc.strip()[:120]
            if key in seen or not doc.strip():
                return
            seen.add(key)
            documents.append(doc.strip())
            metadatas.append({**core_meta, 'section': section, 'chunk_index': len(documents) - 1})

        # ── Chunk 1: Profile Overview ──────────────────────────────────────────
        # A single structured chunk with all identity-level facts.
        profile_lines = []
        for label, key in [
            ("Candidate", "candidate_name"),
            ("Role", "current_or_last_role"),
            ("Experience", "total_experience_years"),
            ("Education", "education"),
            ("Email", "email"),
            ("Phone", "phone"),
            ("LinkedIn", "linkedin"),
            ("GitHub", "github"),
        ]:
            val = base_meta.get(key)
            if val:
                suffix = " years" if key == "total_experience_years" else ""
                profile_lines.append(f"{label}: {val}{suffix}")

        if base_meta.get("companies_worked_at"):
            profile_lines.append(f"Companies: {', '.join(base_meta['companies_worked_at'])}")

        if base_meta.get("summary"):
            profile_lines.append(f"\nSummary: {base_meta['summary']}")

        if profile_lines:
            add_chunk('\n'.join(profile_lines), 'profile_overview')

        # ── Chunk 2: Skills ────────────────────────────────────────────────────
        # One dedicated chunk for all skills — never repeated elsewhere.
        if base_meta.get("key_skills"):
            skills_text = "Key Skills & Technologies:\n" + '\n'.join(
                f"  • {s}" for s in base_meta["key_skills"]
            )
            add_chunk(skills_text, 'skills')

        # ── Chunk 3: Projects ──────────────────────────────────────────────────
        # One dedicated chunk listing all notable projects.
        if base_meta.get("notable_projects"):
            proj_lines = ["Notable Projects:"]
            for p in base_meta["notable_projects"]:
                name = p.get("name", "")
                desc = p.get("description", "")
                proj_lines.append(f"  • {name}: {desc}")
            add_chunk('\n'.join(proj_lines), 'projects')

        # ── Chunks 4+: Raw section text ────────────────────────────────────────
        # Parse the raw resume text into sections and create focused chunks.
        raw_sections = self._split_into_sections(text)

        for section_name, section_content in raw_sections:
            if not section_content.strip():
                continue

            if section_name == 'experience':
                # Split experience into one chunk per job entry
                job_entries = self._split_experience_by_job(section_content)
                if job_entries:
                    for i, job in enumerate(job_entries, 1):
                        labeled = f"Work Experience (Position {i}):\n{job}"
                        add_chunk(labeled, 'experience')
                else:
                    # Couldn't detect job boundaries — store as one chunk
                    add_chunk(f"Work Experience:\n{section_content}", 'experience')

            elif section_name == 'skills':
                # We already have a structured skills chunk — skip raw repetition
                # unless raw text adds new information (tools not in metadata)
                if base_meta.get("key_skills"):
                    continue  # Already captured above
                add_chunk(f"Skills:\n{section_content}", 'skills')

            elif section_name == 'projects':
                if base_meta.get("notable_projects"):
                    continue  # Already captured above
                add_chunk(f"Projects:\n{section_content}", 'projects')

            else:
                # All other sections: one chunk each
                add_chunk(f"{section_name.replace('_', ' ').title()}:\n{section_content}", section_name)

        print(f"✅ Chunking complete: {len(documents)} unique chunks created (sections: {set(m['section'] for m in metadatas)})")
        return {"documents": documents, "metadatas": metadatas}
