import re

def clean_text( text):
    """Cleans the extracted text by removing unnecessary whitespace and other unwanted characters."""
    return re.sub(r'\s+', ' ', text).strip()