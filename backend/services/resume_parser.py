import io
from pypdf import PdfReader

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extracts and returns all text from a PDF file given its raw bytes.
    Handles multi-page PDFs and cleans up excess whitespace.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    all_text = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            all_text.append(text.strip())
    
    full_text = "\n\n".join(all_text)
    return full_text
