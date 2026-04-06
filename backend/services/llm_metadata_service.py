import os
import json
from groq import Groq

EXTRACTION_PROMPT = """
You are a precise resume parser. Given the raw text of a resume, extract the following information and return it ONLY as a valid JSON object with no extra commentary. Do not add markdown code blocks. Just return raw JSON.

Fields to extract:
- "candidate_name": Full name of the candidate (string)
- "email": Email address (string or null)
- "phone": Phone number (string or null)
- "linkedin": LinkedIn profile URL (string or null)
- "github": GitHub profile URL (string or null)
- "total_experience_years": Estimated years of professional experience as a number (integer or float, or null if unclear)
- "current_or_last_role": Most recent job title (string or null)
- "key_skills": A flat list of the most important technical and soft skills (array of strings)
- "notable_projects": A list of project names with one-line descriptions (array of objects with "name" and "description")
- "education": Highest degree or relevant qualification (string or null)
- "companies_worked_at": List of companies the candidate has worked at (array of strings)
- "summary": A 2-3 sentence recruiter-friendly summary of this candidate (string)

If a field is not found, use null.
"""

class LlmMetadataService:
    def __init__(self, groq_client: Groq):
        self.groq_client = groq_client
    
    def extract_resume_metadata(self, resume_text: str) -> dict:
        """
        Uses the Groq LLM to intelligently parse a resume's raw text into
        structured metadata (skills, experience, projects, etc.).
        Returns a dictionary of extracted fields.
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
            
            # Strip markdown code fences if the model wrapped in them
            if raw_content.startswith("```"):
                raw_content = raw_content.strip("`").strip()
                if raw_content.lower().startswith("json"):
                    raw_content = raw_content[4:].strip()
            
            metadata = json.loads(raw_content)
            return metadata
        except json.JSONDecodeError as e:
            print(f"Warning: LLM returned invalid JSON: {e}. Using minimal metadata.")
            return {"summary": "Metadata could not be extracted automatically."}
        except Exception as e:
            print(f"LLM metadata extraction failed: {e}")
            return {}
