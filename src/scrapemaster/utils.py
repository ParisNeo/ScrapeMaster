import re

def clean_text(text):
    cleaned = re.sub(r'\s+', ' ', text).strip()
    return cleaned
