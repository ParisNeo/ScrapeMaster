"""
Utility functions and constants for ScrapeMaster.
Provides secure, high-performance HTML/text processing primitives.
"""
from __future__ import annotations
import re
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Union, Optional, Final
from urllib.parse import urlparse, unquote, urljoin, urlunparse
from bs4 import BeautifulSoup, Tag
from ascii_colors import ASCIIColors

# --- Constants ---

DEFAULT_HEADERS: Final[dict[str, str]] = {
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

DEFAULT_CONTENT_SELECTORS: Final[list[str]] = [
    'main',
    'article',
    '.main-content',
    '.content',
    '.docs-body',
    '[role="main"]',
    '#main-content',
    '#content',
    '.post-content',
    '.entry-content',
    '.article-body',
    '.page-content',
]

DEFAULT_TEXT_SELECTORS: Final[list[str]] = [
    "h1", "h2", "h3", "h4", "h5", "h6", 
    "p", "li", "pre", "code", 
    "td", "th", "blockquote", "figcaption"
]

DEFAULT_IMAGE_SELECTORS: Final[list[str]] = ["img", "picture source", "figure img"]

NOISY_SELECTORS: Final[list[str]] = [
    'script', 'style', 'nav', 'footer', 'aside', 
    '.sidebar', '#sidebar', '.widget-area',
    'header', '.header', '#header', '.navbar', '.nav', '.menu', 
    '.toc', '.table-of-contents', '.table-contents',
    '.breadcrumbs', '.breadcrumb', '.pagination', '.pager',
    '.edit-page-link', '.page-edit', '.edit-link',
    '.feedback-widget', '.feedback', '.rating',
    '.related-posts', '.related', '.recommendations',
    '.comments', '#comments', '.comment-list',
    'form', 'button', 'input', 'select', 'textarea',
    '[role="search"]', '[role="navigation"]', '[role="complementary"]', '[role="form"]',
    '.metadata', '.post-meta', '.meta', '.author-info', '.byline',
    '.advertisement', '.ads', '.ad-container', '.banner',
    'iframe', '.social-links', '.share', '.sharing',
    '.print-link', '.print', '.pdf-link',
    'noscript', 'template'
]

DEFAULT_NOISY_SELECTORS: Final[list[str]] = NOISY_SELECTORS

# Enhanced blocker detection: Cloudflare, Incapsula, Distil, AWS WAF, etc.
# Note: Case-insensitive matching is handled by lowercasing input, but we keep original casing for reference
BLOCKER_PHRASES: Final[list[str]] = [
    "please enable javascript",
    "javascript is disabled", 
    "javascript is required",
    "enable cookies to continue",
    "cookies are disabled",
    "browser check running",
    "checking your browser",
    "checking if the site connection is secure",
    "cloudflare",  # Matches "Cloudflare", "cloudflare", "CLOUDFLARE"
    "attention required! cloudflare",
    "just a moment",
    "verify you are human",
    "security challenge",
    "verify you are a real visitor",
    "access denied",
    "403 forbidden",
    "error 403",
    "please complete the security check",
    "captcha verification",
    "recaptcha",
    "hcaptcha",
    "incapsula incident id",
    "distil networks",
    "pardon our interruption",
    "automated queries",
    "unusual traffic",
    "bot detected",
    "checking browser",  # Matches "Checking browser..." from test cases
]

# Pre-compiled regex patterns for performance
_WHITESPACE_RE: Final[re.Pattern] = re.compile(r'\s+')
_CONTROL_CHAR_RE: Final[re.Pattern] = re.compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]')
_SAFE_FILENAME_RE: Final[re.Pattern] = re.compile(r'[^\w\-.]')

# --- Security & Validation ---

@lru_cache(maxsize=1024)
def is_valid_url(url_string: str | None) -> bool:
    """
    Validate URL structure with security checks.
    
    Args:
        url_string: URL to validate
        
    Returns:
        True if valid HTTP/HTTPS URL with domain, False otherwise
    """
    if not url_string or not isinstance(url_string, str):
        return False
    
    url_string = url_string.strip()
    if not url_string or len(url_string) > 2048:  # RFC 2616 limit
        return False
        
    try:
        result = urlparse(url_string)
        if not all([result.scheme, result.netloc]):
            return False
        if result.scheme not in ('http', 'https', 'ftp', 'ftps'):
            return False
        # Security: reject javascript:, file:, data:, etc.
        if any(x in result.scheme.lower() for x in ('javascript', 'data', 'file', 'about', 'chrome')):
            return False
        return True
    except (ValueError, AttributeError):
        return False


def sanitize_filename(filename: str, max_length: int = 255, replacement: str = '_') -> str:
    """
    Sanitize a filename to prevent directory traversal and invalid characters.
    
    Args:
        filename: Raw filename (may contain path segments)
        max_length: Maximum allowed length
        replacement: Character to replace invalid chars with
        
    Returns:
        Safe filename string
        
    Security: Removes .., leading dots, and path separators to prevent traversal
    """
    if not filename:
        return 'download'
    
    # Take only the basename to strip directory paths
    filename = Path(filename).name
    
    # Remove dangerous prefixes
    if filename.startswith('.'):
        filename = 'hidden' + filename
    
    # Replace invalid characters
    safe = _SAFE_FILENAME_RE.sub(replacement, filename)
    
    # Collapse multiple replacement chars
    safe = re.sub(re.escape(replacement) + r'{2,}', replacement, safe)
    
    # Remove trailing dots and spaces (Windows compatibility)
    safe = safe.rstrip(' .')
    if not safe:
        safe = 'unnamed'
    
    # Enforce length limit
    if len(safe) > max_length:
        name, ext = safe.rsplit('.', 1) if '.' in safe else (safe, '')
        ext_len = len(ext) + 1 if ext else 0
        safe = name[:max_length - ext_len] + ('.' + ext if ext else '')
    
    return safe


def resolve_safe_path(base_directory: str | Path, filename: str) -> Path:
    """
    Resolve path and ensure it stays within base_directory (prevents path traversal).
    
    Args:
        base_directory: The allowed root directory
        filename: The filename or relative path
        
    Returns:
        Resolved absolute Path
        
    Raises:
        ValueError: If the resolved path escapes the base directory
    """
    base = Path(base_directory).resolve()
    target = (base / sanitize_filename(filename)).resolve()
    
    # Security: Check if the resolved path is still within base_directory
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path traversal detected: {filename} escapes {base_directory}")
    
    return target


# --- Content Extraction & Cleaning ---

def clean_text(text: str | None) -> str:
    """
    Deep-clean extracted text: normalize whitespace, remove control chars, strip unicode artifacts.
    
    Args:
        text: Raw text string
        
    Returns:
        Cleaned single-line text safe for CSV/JSON storage
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Remove control characters (keep unicode emoji/language)
    text = _CONTROL_CHAR_RE.sub('', text)
    
    # Normalize unicode whitespace (non-breaking spaces, etc.)
    text = text.replace('\u00a0', ' ').replace('\u2028', ' ').replace('\u2029', ' ')
    
    # Collapse multiple whitespace
    text = _WHITESPACE_RE.sub(' ', text).strip()
    
    return text


def extract_main_content_html(
    soup: BeautifulSoup, 
    content_selectors: list[str] | None = None
) -> tuple[Optional[Tag], Optional[str]]:
    """
    Extract primary content container using selector priority with content validation.
    
    Args:
        soup: BeautifulSoup object
        content_selectors: Ordered list of CSS selectors to try
        
    Returns:
        Tuple of (element, selector_used) or (None, None) if not found
    """
    if not soup:
        return None, None
        
    selectors = content_selectors or DEFAULT_CONTENT_SELECTORS
    
    for selector in selectors:
        try:
            element = soup.select_one(selector)
            if not element:
                continue
                
            # Validate: element must contain meaningful text (not just script/style hidden content)
            text_content = element.get_text(strip=True)
            if len(text_content) < 20:  # Skip empty or near-empty containers
                continue
                
            # Additional validation: must have visible content (not just children with display:none)
            # Fixed deprecation warning: use string=True instead of text=True
            if not element.find(string=True, recursive=True):
                continue
                
            return element, selector
            
        except Exception as e:
            ASCIIColors.debug(f"Invalid selector '{selector}': {e}")
            continue
    
    # Fallback to body if no container found
    body = soup.find('body')
    if body and len(body.get_text(strip=True)) > 20:
        return body, 'body (fallback)'
        
    return None, None


def remove_noisy_elements(
    content_element: Tag, 
    noisy_selectors: list[str] | None = None
) -> int:
    """
    Remove boilerplate/noise elements from content container.
    
    Args:
        content_element: BeautifulSoup Tag to clean
        noisy_selectors: CSS selectors of elements to remove
        
    Returns:
        Number of elements removed
    """
    if not content_element:
        return 0
        
    selectors = noisy_selectors or DEFAULT_NOISY_SELECTORS
    removed_count = 0
    
    for selector in selectors:
        try:
            # Use :has() for modern selectors if supported, else standard select
            for element in content_element.select(selector):
                # Safety: don't remove the root element itself
                if element != content_element:
                    element.decompose()
                    removed_count += 1
        except Exception:
            continue
            
    return removed_count


# --- Detection & Analysis ---

def check_for_blocker(html_content: str | None) -> bool:
    """
    Detect if HTML contains bot-blocking or challenge page content.
    
    Checks for Cloudflare, Incapsula, Distil, custom captchas, and forced JS redirects.
    Case-insensitive matching ensures "Cloudflare", "cloudflare", "CLOUDFLARE" all match.
    
    Args:
        html_content: Raw HTML string
        
    Returns:
        True if blocker detected, False otherwise
    """
    if not html_content or not isinstance(html_content, str):
        return False
        
    # Limit scan to first 16KB for performance (blockers usually appear immediately)
    sample = html_content[:16384].lower()
    
    # Check for exact phrases (case-insensitive via lowercase comparison)
    if any(phrase.lower() in sample for phrase in BLOCKER_PHRASES):
        return True
        
    return False


def is_probably_binary(content: bytes) -> bool:
    """
    Quick heuristic to check if content is likely binary (not text).
    
    Args:
        content: Raw bytes
        
    Returns:
        True if likely binary, False if text
    """
    if not content:
        return False
        
    # Check first 8KB
    sample = content[:8192]
    
    # Heuristic 1: Null bytes
    if b'\0' in sample:
        return True
        
    # Heuristic 2: High ratio of non-text characters
    text_chars = bytearray({7, 8, 9, 10, 13, 27} | set(range(0x20, 0x7F)))
    non_text = sum(1 for byte in sample if byte not in text_chars and not byte > 127)
    
    if len(sample) > 0 and (non_text / len(sample)) > 0.30:
        return True
        
    return False


# --- Content Hashing & Analysis ---

def generate_content_hash(content: str | bytes) -> str:
    """
    Generate deterministic MD5 hash for content deduplication.
    
    Args:
        content: String or bytes content
        
    Returns:
        MD5 hex digest
    """
    if isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')
    return hashlib.md5(content).hexdigest()


def calculate_reading_time(text: str, wpm: int = 200) -> float:
    """
    Estimate reading time in minutes.
    
    Args:
        text: Content text
        wpm: Words per minute (average adult reads 200-250)
        
    Returns:
        Minutes (float)
    """
    word_count = len(text.split())
    return round(word_count / wpm, 1)


def detect_content_type(headers: dict[str, str] | None, url: str | None = None) -> str:
    """
    Smart content type detection from headers with URL fallback.
    
    Args:
        headers: HTTP response headers
        url: Request URL (used for extension fallback)
        
    Returns:
        Simplified content type: 'html', 'pdf', 'docx', 'image', 'text', 'binary', 'unknown'
    """
    if headers:
        content_type = headers.get('content-type', '').lower().split(';')[0]
        
        if 'text/html' in content_type:
            return 'html'
        elif 'application/pdf' in content_type:
            return 'pdf'
        elif 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type:
            return 'docx'
        elif 'image/' in content_type:
            return 'image'
        elif 'text/' in content_type:
            return 'text'
        elif 'application/octet-stream' in content_type or 'application/zip' in content_type:
            return 'binary'
            
    # Fallback to URL extension
    if url:
        path = urlparse(url).path.lower()
        if path.endswith('.pdf'):
            return 'pdf'
        elif path.endswith(('.docx', '.doc')):
            return 'docx'
        elif path.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            return 'image'
        elif path.endswith(('.txt', '.csv', '.md')):
            return 'text'
            
    return 'unknown'


# --- URL Utilities ---

def extract_urls(html: str, base_url: str | None = None) -> list[str]:
    """
    Extract all absolute URLs from HTML.
    
    Args:
        html: HTML content
        base_url: Base URL for resolving relative links
        
    Returns:
        List of absolute URLs
    """
    if base_url:
        base = base_url
    else:
        base = ''
        
    # Simple href extraction for performance
    urls = []
    for match in re.finditer(r'href=[\'"](.*?)[\'"]', html, re.IGNORECASE):
        url = match.group(1)
        if base_url:
            url = urljoin(base, url)
        if is_valid_url(url):
            urls.append(url)
            
    return urls


def normalize_url(url: str) -> str:
    """
    Normalize URL for deduplication: lowercase scheme/host, remove fragment, sort query params.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    # Remove default ports
    if (scheme == 'http' and parsed.port == 80) or (scheme == 'https' and parsed.port == 443):
        netloc = parsed.hostname
    elif parsed.port:
        netloc = f"{parsed.hostname}:{parsed.port}"
        
    path = parsed.path or '/'
    
    # Sort query params for consistency
    if parsed.query:
        params = sorted(parsed.query.split('&'))
        query = '&'.join(params)
    else:
        query = ''
        
    # Rebuild without fragment
    parts = (scheme, netloc, path, '', query, '')
    return urlunparse(parts)