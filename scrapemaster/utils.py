"""
Utility functions and constants for ScrapeMaster.
"""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# --- Constants ---

# Enhanced Headers - Mimic a common browser setup
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"'
}

# Default selectors for finding the main content area (prioritized order)
DEFAULT_CONTENT_SELECTORS = [
    'main',                 # High priority standard semantic tag
    'article',              # High priority standard semantic tag
    '.main-content',        # Common class name
    '.content',             # Common class name
    '.docs-body',           # Common in documentation sites
    '[role="main"]',        # ARIA role
    '#main-content',        # Common ID
    '#content',             # Common ID
    '.post-content',        # Common in blogs
    '.entry-content',       # Common in blogs/CMS
    # Add more specific selectors if targeting particular site types
]

# Default selectors for extracting all relevant text fragments
DEFAULT_TEXT_SELECTORS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code", "td", "th", "blockquote"]

# Default selectors for image extraction
DEFAULT_IMAGE_SELECTORS = ["img"]

# Selectors for removing noisy elements *within* the main content area
DEFAULT_NOISY_SELECTORS = [
    'script', 'style', 'nav', 'footer', 'aside', '.sidebar', '#sidebar',
    'header', '.header', '#header', '.navbar', '.menu',
    '.toc', '.table-of-contents', '.breadcrumbs', '.breadcrumb', '.pagination',
    '.edit-page-link', '.feedback-widget', '.related-posts', '.comments', '#comments',
    'form', 'button', 'input', '[role="search"]', '[role="navigation"]',
    '[role="complementary"]', '.metadata', '.post-meta', '.author-info',
    '.advertisement', '.ads', 'iframe', '.social-links', '.print-link',
    # Add more as needed based on common patterns
]

# Phrases indicating a JavaScript/Cookie/Captcha blocker page (case-insensitive)
BLOCKER_PHRASES = [
    "enable javascript", "enable cookies", "checking your browser",
    "redirecting", "cloudflare", "verify you are human", "js challenge",
    "please wait", "needs javascript to function", "one moment please",
    "checking browser", "access denied", "security check", "captcha"
]
BLOCKER_REGEX = re.compile('|'.join(BLOCKER_PHRASES), re.IGNORECASE)

# --- Functions ---

def is_valid_url(url_string: str) -> bool:
    """Basic URL validation."""
    if not isinstance(url_string, str):
        return False
    try:
        result = urlparse(url_string)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except ValueError:
        return False

def clean_text(text: str) -> str:
    """Cleans extracted text by removing unnecessary whitespace and normalizing."""
    if not isinstance(text, str):
        return ""
    # Replace multiple whitespace characters (including newlines, tabs) with a single space
    text = re.sub(r'\s+', ' ', text).strip()
    # Optional: Add more specific cleaning rules here if needed
    # e.g., remove specific unicode characters, normalize quotes, etc.
    return text

def check_for_blocker(html_content: str) -> bool:
    """Checks if the HTML content seems to be a JS/Cookie/Captcha blocker page."""
    if not html_content or not isinstance(html_content, str):
        return False
    # Check first few KB for performance, convert to lower case
    text_sample = html_content[:8192].lower() # Increased sample size slightly
    is_blocker = BLOCKER_REGEX.search(text_sample)
    if is_blocker:
        # Optional: Add more sophisticated checks, e.g., very low content diversity
        # or presence of specific known blocker script URLs
        pass
    return bool(is_blocker)

def extract_main_content_html(soup: BeautifulSoup, content_selectors: list = DEFAULT_CONTENT_SELECTORS) -> tuple[BeautifulSoup | None, str | None]:
    """Attempts to find the main content container using a list of selectors."""
    main_content_element = None
    used_selector = None
    if not soup:
        return None, None

    for selector in content_selectors:
        try:
            element = soup.select_one(selector)
            if element:
                # Basic sanity check: does it contain more than just script/style?
                if element.find(text=True, recursive=True):
                    main_content_element = element
                    used_selector = selector
                    break
        except Exception: # Handle potential invalid selectors
            continue

    if not main_content_element:
        # Fallback to body if no specific container found or they were empty
        main_content_element = soup.body
        used_selector = 'body (fallback)'

    return main_content_element, used_selector

def remove_noisy_elements(content_element: BeautifulSoup, noisy_selectors: list = DEFAULT_NOISY_SELECTORS) -> int:
    """Removes elements matching noisy selectors within the given content element."""
    count = 0
    if not content_element:
        return 0

    for noisy_selector in noisy_selectors:
        try:
            elements_to_remove = content_element.select(noisy_selector)
            for element in elements_to_remove:
                element.decompose()
                count += 1
        except Exception as e_decompose:
            # Log warning or ignore errors from invalid selectors/decomposition
            # print(f"Warning: Error decomposing element with selector '{noisy_selector}': {e_decompose}")
            pass
    return count