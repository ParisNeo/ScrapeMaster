"""
ScrapeMaster Core Module: Provides the main ScrapeMaster class for web scraping.
"""
import time
import random
import pickle
import json
import re
import io
import hashlib
import asyncio
import sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from collections import deque
import xml.etree.ElementTree as ET

# Dependency Management with pipmaster
try:
    import pipmaster as pm
    pm.ensure_packages([
        "requests",
        "beautifulsoup4",
        "lxml",
        "selenium",
        "webdriver-manager",
        "undetected-chromedriver",
        "markdownify",
        "markdown",
        "ascii_colors",
        "youtube_transcript_api",
        "wikipedia",
        "pypdf",
        "python-docx",
        "aiohttp",
        "xmltodict",
        "curl_cffi",
        "playwright"
    ]) 
except ImportError:
    print("Warning: pipmaster not found. Please install it ('pip install pipmaster') for automatic dependency management.")
except Exception as e:
    print(f"Warning: Error during pipmaster dependency check: {e}")

# Core Imports
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from ascii_colors import ASCIIColors

# Attempt to import undetected_chromedriver
try:
    import undetected_chromedriver as uc
    UNDETECTED_AVAILABLE = True
except ImportError:
    uc = None 
    UNDETECTED_AVAILABLE = False

# YouTube API Import
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    YOUTUBE_AVAILABLE = True
except ImportError:
    YOUTUBE_AVAILABLE = False

# Wikipedia Library Import
try:
    import wikipedia
    WIKIPEDIA_AVAILABLE = True
except ImportError:
    WIKIPEDIA_AVAILABLE = False

# Lightweight Document Parsers
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# Async Support
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# Playwright Support
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    async_playwright = None
    PLAYWRIGHT_AVAILABLE = False

# Curl CFFI (TLS spoofing)
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    curl_requests = None
    CURL_CFFI_AVAILABLE = False

# XML Parsing for sitemaps
try:
    import xmltodict
    XMLTODICT_AVAILABLE = True
except ImportError:
    XMLTODICT_AVAILABLE = False

# Local Imports
from .utils import (
    clean_text, is_valid_url, check_for_blocker, extract_main_content_html, remove_noisy_elements,
    DEFAULT_HEADERS, DEFAULT_CONTENT_SELECTORS, DEFAULT_TEXT_SELECTORS, DEFAULT_IMAGE_SELECTORS,
    DEFAULT_NOISY_SELECTORS
)
from .exceptions import (
    ScrapeMasterError, PageFetchError, StrategyError, BlockerDetectedError,
    DriverInitializationError, ParsingError
)

# Available strategies
SUPPORTED_STRATEGIES = ["requests", "selenium", "undetected", "wikipedia", "local_parser", "playwright", "sitemap", "curl_cffi"]
DEFAULT_STRATEGY_ORDER = ["wikipedia", "local_parser", "requests", "playwright", "selenium", "undetected"] 

def _clean_markdown_code_blocks(markdown_text: str) -> str:
    """Uses regex to remove lines containing only numbers within Markdown code blocks."""
    if not markdown_text or "```" not in markdown_text:
        return markdown_text 

    cleaned_lines = []
    in_code_block = False
    line_number_pattern = re.compile(r"^\s*\d+\.?\s*$")

    for line in markdown_text.splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            cleaned_lines.append(line) 
            continue

        if in_code_block:
            if line_number_pattern.match(line):
                continue
            else:
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)

def _parse_and_markdownify(html_content: str,
                           content_selectors: list = DEFAULT_CONTENT_SELECTORS,
                           noisy_selectors: list = DEFAULT_NOISY_SELECTORS,
                           post_processors: list = None
                           ) -> tuple[str | None, str | None]:
    """Parses HTML, extracts main content, cleans noise, returns Markdown (with code block cleaning)."""
    if not html_content:
        return None, "Error: Received empty HTML content."

    try:
        soup = BeautifulSoup(html_content, 'lxml')
        main_content_element, used_selector = extract_main_content_html(soup, content_selectors)

        if not main_content_element:
             return None, "Error: Could not find main content or body tag."

        ASCIIColors.debug(f"Main content identified using selector: '{used_selector}'")

        removed_noise_count = remove_noisy_elements(main_content_element, noisy_selectors)
        ASCIIColors.debug(f"Removed {removed_noise_count} general noisy elements.")

        cleaned_text_sample = main_content_element.get_text(strip=True)[:500].lower()
        if check_for_blocker(cleaned_text_sample):
             ASCIIColors.warning("Content container holds blocker message after cleaning.")
             return None, f"Blocker identified within '{used_selector}' after cleaning."

        ASCIIColors.info("Converting cleaned HTML to Markdown...")
        html_string = str(main_content_element)
        markdown_text = md(html_string, heading_style="ATX", escape_underscores=False, default_title=True)

        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text).strip()
        markdown_text = _clean_markdown_code_blocks(markdown_text)
        
        if post_processors:
            for processor in post_processors:
                if callable(processor):
                    try:
                        markdown_text = processor(markdown_text)
                    except Exception as e:
                        ASCIIColors.warning(f"Post-processor failed: {e}")

        ASCIIColors.success("Markdown conversion and cleaning complete.")
        return markdown_text, None 

    except Exception as e:
        import traceback
        error_msg = f"Error during parsing/markdownify: {e}"
        ASCIIColors.error(error_msg)
        raise ParsingError(error_msg) from e

class ScrapeMaster:
    """
    A versatile web scraping class using multiple strategies for fetching and extracting web content.
    Supports async operations, Playwright, structured data extraction, sitemap-based crawling,
    smart rate limiting, content deduplication, and export pipelines.
    """
    _custom_strategies = {}
    
    def __init__(self, url: str | None = None, strategy: list[str] | str = 'auto', headless: bool = True):
        self._validate_url(url)
        self.initial_url = url
        self.current_url = url
        self.headless = headless

        # Initialize attributes before strategy resolution (required for __del__)
        self.driver = None
        self.current_soup = None 
        self.html_content = "" 
        self.last_error = None 
        self.last_strategy_used = None

        # Resolve strategy after URL is set
        self.strategy = self._resolve_strategy(strategy)

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

        self.user_agents = list(DEFAULT_HEADERS.values()) 

        # Content cache for deduplication
        self._content_cache = {}
        self._strategy_cache = {}

        # Rate limiting state
        self._last_request_time = {}
        self._consecutive_failures = {}

        print(f"ScrapeMaster initialized. Strategy: {self.strategy}, Headless: {self.headless}")
        if 'undetected' in self.strategy and not UNDETECTED_AVAILABLE:
            ASCIIColors.warning("Specified 'undetected' strategy, but library is not available.")

    @classmethod
    def register_strategy(cls, name: str, fetcher_func: callable):
        """Register a custom scraping strategy.
        
        Args:
            name: Strategy name (will be available in strategy lists)
            fetcher_func: Callable that takes (scraper_instance, url) and returns (html, soup, error)
        """
        cls._custom_strategies[name] = fetcher_func
        if name not in SUPPORTED_STRATEGIES:
            SUPPORTED_STRATEGIES.append(name)
        ASCIIColors.info(f"Registered custom strategy: {name}")

    def _validate_url(self, url: str | None):
        if url is not None and not is_valid_url(url):
            raise ValueError(f"Invalid initial URL provided: {url}")

    def _resolve_strategy(self, strategy: list[str] | str) -> list[str]:
        """Resolves the strategy argument into a validated list, handling 'auto' logic."""
        if strategy == 'auto':
            strat_order = list(DEFAULT_STRATEGY_ORDER)
            
            if self.current_url and "wikipedia.org" in self.current_url:
                if "wikipedia" in strat_order:
                    strat_order.remove("wikipedia")
                strat_order.insert(0, "wikipedia")
                ASCIIColors.info("Wikipedia URL detected: Prioritizing 'wikipedia' library strategy.")
            elif "wikipedia" in strat_order:
                strat_order.remove("wikipedia")
            
            if self.current_url:
                try:
                    domain = urlparse(self.current_url).netloc
                    if domain in self._strategy_cache:
                        cached = self._strategy_cache[domain]
                        if cached in strat_order:
                            strat_order.remove(cached)
                            strat_order.insert(0, cached)
                            ASCIIColors.debug(f"Using cached strategy '{cached}' for {domain}")
                except Exception:
                    pass
            
            return [s for s in strat_order if s in SUPPORTED_STRATEGIES]

        if isinstance(strategy, str):
            strategy = [strategy]
        if not isinstance(strategy, list):
            raise ValueError("Strategy must be 'auto' or a list of strings.")

        validated_strategy = []
        for s in strategy:
            if s in SUPPORTED_STRATEGIES:
                validated_strategy.append(s)
            else:
                ASCIIColors.warning(f"Unsupported strategy '{s}' ignored.")
        if not validated_strategy:
            raise ValueError("No valid strategies provided.")
        return validated_strategy

    def set_url(self, url: str):
        self._validate_url(url)
        self.current_url = url
        self.current_soup = None 
        self.html_content = ""
        self.last_error = None
        ASCIIColors.info(f"Target URL set to: {url}")

    def get_last_error(self) -> str | None:
        return self.last_error

    def _get_driver_path(self) -> str | None:
        try:
            ASCIIColors.debug("Getting ChromeDriver path via webdriver-manager...")
            driver_path = ChromeDriverManager().install()
            ASCIIColors.debug(f"Using ChromeDriver at: {driver_path}")
            return driver_path
        except Exception as e_wdm:
            self.last_error = f"Error finding/installing ChromeDriver: {e_wdm}"
            ASCIIColors.error(self.last_error)
            return None

    def _setup_selenium_options(self, for_undetected: bool = False) -> webdriver.ChromeOptions:
        options = webdriver.ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")

        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.session.headers['User-Agent']}")
        options.add_argument("window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--log-level=3") 

        # YouTube consent bypass settings
        options.add_argument("--accept-cookies")
        options.add_argument("--disable-features=ConsentAwarenessComponent")

        if not for_undetected:
            options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
            options.add_experimental_option('useAutomationExtension', False)
            prefs = {
                "profile.default_content_setting_values.cookies": 1,
                "profile.default_content_setting_values.javascript": 1,
                # Accept all cookies automatically (including YouTube's consent)
                "profile.cookie_controls_mode": 0
            }
            options.add_experimental_option("prefs", prefs)
        return options

    def _quit_driver(self):
        if hasattr(self, 'driver') and self.driver:
            try:
                self.driver.quit()
                ASCIIColors.debug("WebDriver instance quit.")
            except Exception as e:
                ASCIIColors.warning(f"Error quitting WebDriver: {e}")
            finally:
                self.driver = None

    def __del__(self):
        self._quit_driver()

    def _smart_delay(self, domain: str, attempt: int = 0):
        """Implements exponential backoff with jitter."""
        base_delay = 1.0
        if attempt > 0:
            delay = min(300, base_delay * (2 ** attempt)) + random.uniform(0, 1)
        else:
            delay = base_delay + random.uniform(0, 0.5)
        
        now = time.time()
        last_time = self._last_request_time.get(domain, 0)
        time_since_last = now - last_time
        if time_since_last < delay:
            actual_delay = delay - time_since_last
            ASCIIColors.debug(f"Rate limiting {domain}: waiting {actual_delay:.2f}s")
            time.sleep(actual_delay)
        
        self._last_request_time[domain] = time.time()

    def _get_domain(self, url: str) -> str:
        """Extract domain for rate limiting tracking."""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"

    def _content_hash(self, content: bytes) -> str:
        """Generate MD5 hash of content for deduplication."""
        return hashlib.md5(content).hexdigest()

    def _cache_content(self, url: str, content: bytes) -> bool:
        """Cache content and return True if new/changed, False if duplicate."""
        content_hash = self._content_hash(content)
        if url in self._content_cache and self._content_cache[url] == content_hash:
            return False
        self._content_cache[url] = content_hash
        return True

    def scrape_structured_data(self, fetch_strategy: list[str] | str | None = None) -> dict | None:
        """Extract JSON-LD, Microdata, and OpenGraph structured data from page."""
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        if not self.current_soup:
            if not self._fetch_content(strategy_to_use):
                return None

        if not self.current_soup:
            return None

        data = {
            "json_ld": [],
            "microdata": [],
            "opengraph": {}
        }

        try:
            for script in self.current_soup.find_all('script', type='application/ld+json'):
                try:
                    json_data = json.loads(script.string)
                    data["json_ld"].append(json_data)
                except (json.JSONDecodeError, TypeError):
                    continue

            for meta in self.current_soup.find_all('meta', property=re.compile(r'^og:')):
                prop = meta.get('property', '').replace('og:', '')
                content = meta.get('content', '')
                if prop and content:
                    data["opengraph"][prop] = content

            for elem in self.current_soup.find_all(itemscope=True):
                item_type = elem.get('itemtype', '')
                props = {}
                for prop in elem.find_all(itemprop=True):
                    prop_name = prop.get('itemprop', '')
                    if prop.has_attr('content'):
                        prop_value = prop['content']
                    elif prop.has_attr('href'):
                        prop_value = urljoin(self.current_url, prop['href'])
                    else:
                        prop_value = prop.get_text().strip()
                    props[prop_name] = prop_value
                
                if item_type or props:
                    data["microdata"].append({"type": item_type, "properties": props})

            if not data["json_ld"] and not data["microdata"] and not data["opengraph"]:
                return None

            return data

        except Exception as e:
            ASCIIColors.error(f"Error extracting structured data: {e}")
            return None

    def scrape_from_sitemap(self, sitemap_url: str | None = None, url_pattern: str | None = None, limit: int = 100) -> list[str]:
        """Discover URLs from sitemap.xml and return list of URLs to scrape."""
        if not sitemap_url:
            if not self.initial_url:
                raise ValueError("No URL provided and no initial URL set")
            parsed = urlparse(self.initial_url)
            sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

        if not is_valid_url(sitemap_url):
            raise ValueError(f"Invalid sitemap URL: {sitemap_url}")

        urls = []
        seen_sitemaps = set()
        
        def parse_sitemap(url: str, depth: int = 0):
            if url in seen_sitemaps or depth > 3:
                return
            seen_sitemaps.add(url)
            
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                
                if XMLTODICT_AVAILABLE:
                    data = xmltodict.parse(response.content)
                    self._parse_sitemap_dict(data, urls, url_pattern, seen_sitemaps, depth, limit)
                else:
                    root = ET.fromstring(response.content)
                    self._parse_sitemap_xml(root, urls, url_pattern, seen_sitemaps, depth, limit)
                    
            except Exception as e:
                ASCIIColors.warning(f"Error parsing sitemap {url}: {e}")

        parse_sitemap(sitemap_url)
        
        final_urls = []
        for u in urls:
            if len(final_urls) >= limit:
                break
            if url_pattern:
                if re.search(url_pattern, u):
                    final_urls.append(u)
            else:
                final_urls.append(u)
        
        ASCIIColors.success(f"Found {len(final_urls)} URLs in sitemap (limit: {limit})")
        return final_urls[:limit]

    def _parse_sitemap_dict(self, data: dict, urls: list, url_pattern: str, seen: set, depth: int, limit: int):
        """Parse sitemap data structure from xmltodict."""
        if 'sitemapindex' in data:
            sub_sitemaps = data['sitemapindex'].get('sitemap', [])
            if not isinstance(sub_sitemaps, list):
                sub_sitemaps = [sub_sitemaps]
            for sitemap in sub_sitemaps[:3]:
                if isinstance(sitemap, dict) and 'loc' in sitemap:
                    self.parse_sitemap(sitemap['loc'], depth + 1)
        elif 'urlset' in data:
            url_entries = data['urlset'].get('url', [])
            if not isinstance(url_entries, list):
                url_entries = [url_entries]
            for entry in url_entries:
                if isinstance(entry, dict) and 'loc' in entry:
                    urls.append(entry['loc'])
                if len(urls) >= limit:
                    break

    def _parse_sitemap_xml(self, root, urls: list, url_pattern: str, seen: set, depth: int, limit: int):
        """Parse sitemap using standard ElementTree (fallback)."""
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemaps = root.findall('.//ns:sitemap', namespace)
        if sitemaps:
            for sitemap in sitemaps[:3]:
                loc = sitemap.find('ns:loc', namespace)
                if loc is not None:
                    self.parse_sitemap(loc.text, depth + 1)
        
        for url_elem in root.findall('.//ns:url', namespace):
            loc = url_elem.find('ns:loc', namespace)
            if loc is not None:
                urls.append(loc.text)
            if len(urls) >= limit:
                break

    def _try_playwright(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts fetching with Playwright."""
        if not PLAYWRIGHT_AVAILABLE:
            return None, None, "Playwright library not available"
        
        ASCIIColors.info("-- Strategy: Trying Playwright --")
        
        async def _fetch():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    page = await browser.new_page()
                    for key, value in self.session.headers.items():
                        await page.set_extra_http_headers({key: value})
                    
                    await page.goto(self.current_url, wait_until='networkidle', timeout=45000)
                    await page.wait_for_timeout(2000)
                    html = await page.content()
                    return html
                finally:
                    await browser.close()

        try:
            html_content = asyncio.run(_fetch())
            
            if check_for_blocker(html_content):
                return None, None, "Blocker page detected (Playwright)"
            
            soup = BeautifulSoup(html_content, 'lxml')
            return html_content, soup, None
            
        except Exception as e:
            return None, None, f"Playwright error: {e}"

    def _try_curl_cffi(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Use curl_cffi to impersonate Chrome TLS fingerprint."""
        if not CURL_CFFI_AVAILABLE:
            return None, None, "curl_cffi not available"
        
        ASCIIColors.info("-- Strategy: Trying curl_cffi (TLS spoof) --")
        try:
            response = curl_requests.get(
                self.current_url, 
                headers=self.session.headers,
                impersonate="chrome110",
                timeout=30
            )
            
            html = response.text
            if check_for_blocker(html):
                return None, None, "Blocker detected (curl_cffi)"
            
            soup = BeautifulSoup(html, 'lxml')
            return html, soup, None
            
        except Exception as e:
            return None, None, f"curl_cffi error: {e}"

    async def scrape_many_async(self, urls: list[str], max_concurrent: int = 10, 
                                extract_markdown: bool = True, timeout: int = 30) -> list[dict]:
        """
        Async batch scraping with aiohttp.
        
        Args:
            urls: List of URLs to scrape
            max_concurrent: Maximum concurrent requests
            extract_markdown: Whether to convert to markdown
            timeout: Per-request timeout in seconds
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp is required for async scraping. Install with: pip install aiohttp")

        semaphore = asyncio.Semaphore(max_concurrent)
        results = []
        
        async def fetch_one(url: str):
            async with semaphore:
                domain = self._get_domain(url)
                attempt = self._consecutive_failures.get(domain, 0)
                self._smart_delay(domain, attempt)
                
                try:
                    async with aiohttp.ClientSession(headers=self.session.headers) as session:
                        async with session.get(url, timeout=timeout) as response:
                            content = await response.read()
                            
                            if not self._cache_content(url, content):
                                return {"url": url, "skipped": True, "reason": "duplicate_content"}
                            
                            html = content.decode('utf-8', errors='ignore')
                            
                            if extract_markdown:
                                md_text, error = _parse_and_markdownify(html)
                                return {"url": url, "markdown": md_text, "error": error}
                            else:
                                soup = BeautifulSoup(html, 'lxml')
                                texts = [clean_text(el.get_text()) for el in soup.select('p')]
                                return {"url": url, "texts": texts}
                                
                except Exception as e:
                    self._consecutive_failures[domain] = self._consecutive_failures.get(domain, 0) + 1
                    return {"url": url, "error": str(e)}
                else:
                    self._consecutive_failures[domain] = 0

        tasks = [fetch_one(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        processed = []
        for res in results:
            if isinstance(res, Exception):
                processed.append({"error": str(res)})
            elif isinstance(res, dict):
                processed.append(res)
        
        return processed

    def scrape_many(self, urls: list[str], **kwargs) -> list[dict]:
        """Synchronous wrapper for async bulk scraping."""
        return asyncio.run(self.scrape_many_async(urls, **kwargs))

    def save_screenshot(self, filename: str | None = None, full_page: bool = False) -> str | None:
        """Capture screenshot using active Selenium/Undetected driver."""
        if not self.driver:
            ASCIIColors.warning("Cannot save screenshot: no active driver. Use selenium strategy first.")
            return None
        
        if not filename:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            domain = self._get_domain(self.current_url).replace('.', '_')
            filename = f"screenshot_{domain}_{timestamp}.png"
        
        filename = re.sub(r'[^\w\-.]', '_', filename)
        
        try:
            if full_page:
                original_size = self.driver.get_window_size()
                required_height = self.driver.execute_script(
                    "return Math.max(document.body.scrollHeight, document.body.offsetHeight, "
                    "document.documentElement.clientHeight, document.documentElement.scrollHeight, "
                    "document.documentElement.offsetHeight);"
                )
                self.driver.set_window_size(original_size['width'], required_height)
                
            self.driver.save_screenshot(filename)
            ASCIIColors.success(f"Screenshot saved: {filename}")
            return filename
        except Exception as e:
            ASCIIColors.error(f"Failed to save screenshot: {e}")
            self.last_error = f"Screenshot failed: {e}"
            return None

    def scrape_infinite_scroll(self, scroll_pause: float = 2.0, max_scrolls: int = 10) -> str | None:
        """Handle infinite scroll or 'Load More' pagination. Returns markdown."""
        if not self.driver:
            ASCIIColors.warning("Initializing driver for infinite scroll.")
            _, soup, _ = self._try_selenium(use_undetected=False)
            if not self.driver:
                return None

        try:
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            scrolls = 0
            
            while scrolls < max_scrolls:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(scroll_pause)
                
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    try:
                        load_more = self.driver.find_element(By.CSS_SELECTOR, 
                            "button.load-more, a.load-more, .show-more, [class*='pagination'] button")
                        load_more.click()
                        time.sleep(scroll_pause)
                    except Exception:
                        break
                
                last_height = new_height
                scrolls += 1
            
            self.html_content = self.driver.page_source
            self.current_soup = BeautifulSoup(self.html_content, 'lxml')
            return self.scrape_markdown()
            
        except Exception as e:
            ASCIIColors.error(f"Error during infinite scroll: {e}")
            return None

    def export_to_json(self, filepath: str, include_metadata: bool = True) -> bool:
        """Export current scrape result to JSON file."""
        filepath = Path(filepath)
        if ".." in filepath.parts:
            raise ValueError("Invalid filepath: directory traversal not allowed")
            
        try:
            data = {
                "url": self.current_url,
                "markdown": self.scrape_markdown() if self.current_soup else None,
                "timestamp": time.time(),
                "strategy": self.last_strategy_used
            }
            if include_metadata:
                data["structured_data"] = self.scrape_structured_data() if self.current_soup else None
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            ASCIIColors.error(f"Export failed: {e}")
            return False

    def export_to_notion(self, database_id: str, token: str) -> bool:
        """Push scraped content to Notion database."""
        if not token.startswith('secret_'):
            raise ValueError("Invalid Notion integration token format")
        
        try:
            content = self.scrape_markdown()
            if not content:
                return False
            
            url = "https://api.notion.com/v1/pages"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }
            
            blocks = []
            chunks = [content[i:i+2000] for i in range(0, len(content), 2000)]
            for chunk in chunks[:100]:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}
                })
            
            payload = {
                "parent": {"database_id": database_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": self.current_url}}]}
                },
                "children": blocks
            }
            
            response = requests.post(url, headers=headers, json=payload)
            return response.status_code == 200
            
        except Exception as e:
            ASCIIColors.error(f"Notion export failed: {e}")
            return False

    def export_to_obsidian(self, vault_path: str, filename: str | None = None) -> str | None:
        """Save markdown to Obsidian vault with wikilinks."""
        vault = Path(vault_path)
        if not vault.exists():
            ASCIIColors.error(f"Vault path does not exist: {vault_path}")
            return None
        
        if not filename:
            parsed = urlparse(self.current_url or "unknown")
            base = parsed.path.split('/')[-1] or 'index'
            filename = re.sub(r'[^\w\-]', '_', base)[:50] + '.md'
        else:
            filename = Path(filename).name
        
        filepath = vault / filename
        
        try:
            content = self.scrape_markdown()
            if not content:
                return None
            
            frontmatter = f"""---
url: {self.current_url}
scraped: {time.strftime('%Y-%m-%d %H:%M:%S')}
tags: [scrapemaster]
---
"""
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(frontmatter + "\n" + content)
            return str(filepath)
        except Exception as e:
            ASCIIColors.error(f"Obsidian export failed: {e}")
            return None

    def scrape_incremental(self, cache_file: str = ".scrape_cache.db") -> dict:
        """Scrape using content-hash cache to skip unchanged pages."""
        cache_file = Path(cache_file)
        if ".." in cache_file.parts:
            raise ValueError("Invalid cache file path")
        
        conn = sqlite3.connect(str(cache_file))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS page_cache 
            (url TEXT PRIMARY KEY, content_hash TEXT, last_modified REAL)
        """)
        
        results = {"updated": [], "skipped": []}
        
        if self.current_url:
            if not self.current_soup:
                self._fetch_content(self.strategy)
            
            if self.current_soup:
                current_hash = self._content_hash(self.html_content.encode())
                cursor.execute("SELECT content_hash FROM page_cache WHERE url = ?", (self.current_url,))
                row = cursor.fetchone()
                
                if not row or row[0] != current_hash:
                    cursor.execute("""
                        INSERT OR REPLACE INTO page_cache (url, content_hash, last_modified)
                        VALUES (?, ?, ?)
                    """, (self.current_url, current_hash, time.time()))
                    results["updated"].append({
                        "url": self.current_url,
                        "markdown": self.scrape_markdown()
                    })
                else:
                    results["skipped"].append(self.current_url)
        
        conn.commit()
        conn.close()
        return results

    def capture_network_requests(self, wait_seconds: int = 5) -> list[dict]:
        """Capture network requests (API calls) during page load using Playwright."""
        if not PLAYWRIGHT_AVAILABLE:
            ASCIIColors.warning("Network interception requires Playwright")
            return []
        
        requests_data = []
        
        async def _capture():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                page = await browser.new_page()
                
                async def handle_response(response):
                    try:
                        body = await response.body()
                        requests_data.append({
                            "url": response.url,
                            "status": response.status,
                            "content_type": response.headers.get("content-type", ""),
                            "body_preview": body[:1000] if body else None
                        })
                    except Exception:
                        pass
                
                page.on("response", handle_response)
                
                try:
                    await page.goto(self.current_url, wait_until='networkidle')
                    await page.wait_for_timeout(wait_seconds * 1000)
                except Exception:
                    pass
                finally:
                    await browser.close()
        
        asyncio.run(_capture())
        return requests_data

    def _try_wikipedia(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts to fetch content using the official Wikipedia library."""
        if not WIKIPEDIA_AVAILABLE:
            return None, None, "wikipedia library not installed"
        
        ASCIIColors.info("-- Strategy: Trying 'wikipedia' library --")
        try:
            parsed = urlparse(self.current_url)
            if "wikipedia.org" not in parsed.netloc:
                return None, None, "Not a Wikipedia URL"

            parts = parsed.netloc.split('.')
            if len(parts) >= 3:
                lang = parts[0]
                wikipedia.set_lang(lang)
            
            path_parts = parsed.path.split('/')
            if len(path_parts) > 2 and path_parts[1] == 'wiki':
                title = unquote(path_parts[2])
            else:
                return None, None, "Could not parse Wikipedia title from URL"

            ASCIIColors.info(f"Fetching Wikipedia page: {title}")
            page = wikipedia.page(title, auto_suggest=False)
            
            html_content = page.html()
            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Wikipedia: Fetch and parse successful.")
            return html_content, soup, None

        except wikipedia.exceptions.DisambiguationError as e:
            return None, None, f"Wikipedia Ambiguity: {e}"
        except wikipedia.exceptions.PageError:
            return None, None, "Wikipedia Page Not Found"
        except Exception as e:
            return None, None, f"Wikipedia Strategy Error: {e}"

    def _try_local_parser(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts to download and parse files (PDF, DOCX)."""
        ASCIIColors.info("-- Strategy: Trying 'local_parser' for documents --")
        
        if not self.current_url:
            return None, None, "No URL set"
            
        try:
            ASCIIColors.info(f"Downloading file: {self.current_url}")
            self.set_random_user_agent()
            response = self.session.get(self.current_url, timeout=30)
            response.raise_for_status()
            
            file_stream = io.BytesIO(response.content)
            parsed_path = urlparse(self.current_url).path.lower()
            
            extracted_text = ""
            file_type = "unknown"

            if parsed_path.endswith(".pdf"):
                if not PYPDF_AVAILABLE:
                     return None, None, "PDF detected but pypdf library is missing."
                file_type = "PDF"
                ASCIIColors.info("Processing as PDF...")
                reader = PdfReader(file_stream)
                texts = []
                for page in reader.pages:
                    texts.append(page.extract_text() or "")
                extracted_text = "\n\n".join(texts)

            elif parsed_path.endswith(".docx"):
                if not DOCX_AVAILABLE:
                    return None, None, "DOCX detected but python-docx library is missing."
                file_type = "DOCX"
                ASCIIColors.info("Processing as DOCX...")
                doc = DocxDocument(file_stream)
                extracted_text = "\n\n".join([p.text for p in doc.paragraphs])
                
            else:
                return None, None, f"URL does not end with a supported document extension (.pdf, .docx). Path: {parsed_path}"

            if not extracted_text.strip():
                 return None, None, f"{file_type} parsing resulted in empty text."

            html_content = f"<html><body><div class='document-content'><h1>Document Content ({file_type})</h1><pre>{extracted_text}</pre></div></body></html>"
            soup = BeautifulSoup(html_content, 'lxml')
            
            ASCIIColors.success(f"Local Parser: Successfully extracted text from {file_type}.")
            return html_content, soup, None

        except requests.exceptions.RequestException as e:
            return None, None, f"Download failed: {e}"
        except Exception as e:
             return None, None, f"Local Parsing Error: {e}"

    def _try_requests(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts fetching with the requests library."""
        ASCIIColors.info("-- Strategy: Trying simple HTTP request (requests) --")
        if not self.current_url: return None, None, "No URL set"
        try:
            self.set_random_user_agent() 
            response = self.session.get(self.current_url, timeout=25)
            ASCIIColors.debug(f"Requests Status Code: {response.status_code}")

            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type and 'application/xhtml+xml' not in content_type:
                return None, None, f"Non-HTML content type received: {content_type}"

            response.raise_for_status() 
            html_content = response.content.decode(response.encoding or 'utf-8', errors='ignore')

            if check_for_blocker(html_content):
                ASCIIColors.warning("Requests: Blocker page detected.")
                return None, None, "Blocker page detected" 

            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Requests: Fetch and parse successful.")
            
            domain = self._get_domain(self.current_url)
            self._strategy_cache[domain] = "requests"
            
            return html_content, soup, None 

        except requests.exceptions.RequestException as e:
            error_msg = f"Requests Error: {e}"
            ASCIIColors.error(error_msg)
            if hasattr(e, 'response') and e.response is not None:
                 if e.response.status_code == 403:
                     return None, None, "Requests: 403 Forbidden" 
                 else:
                     return None, None, f"Requests: HTTP Error {e.response.status_code}"
            else: 
                raise PageFetchError(error_msg) from e 
        except Exception as e:
            error_msg = f"Requests: Unexpected error: {e}"
            ASCIIColors.error(error_msg)
            raise ScrapeMasterError(error_msg) from e 

    def _run_selenium_attempt(self, driver: webdriver.Chrome) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Core logic shared by Selenium and UC strategies."""
        if not self.current_url: return None, None, "No URL set"
        try:
            driver.set_page_load_timeout(45)
            driver.implicitly_wait(3)

            ASCIIColors.info("Navigating to URL...")
            driver.get(self.current_url)

            wait_time = 25
            ASCIIColors.info(f"Waiting up to {wait_time}s for page elements...")
            wait = WebDriverWait(driver, wait_time)
            body_present = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            if not body_present:
                raise StrategyError("Body element not found after wait.")

            time.sleep(2) 

            ASCIIColors.info("Retrieving page source...")
            html_content = driver.page_source
            if not html_content:
                raise StrategyError("Selenium retrieved empty page source.")

            if check_for_blocker(html_content):
                ASCIIColors.warning("Selenium/UC: Blocker page detected after wait.")
                return None, None, "Blocker page detected" 

            ASCIIColors.info("Parsing HTML with BeautifulSoup...")
            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Selenium/UC: Fetch and parse successful.")
            
            domain = self._get_domain(self.current_url)
            self._strategy_cache[domain] = "selenium"
            
            return html_content, soup, None 

        except TimeoutException:
            error_msg = f"Selenium/UC: Timed out waiting for page elements ({wait_time}s)."
            ASCIIColors.error(error_msg)
            try:
                html_on_timeout = driver.page_source
                if check_for_blocker(html_on_timeout):
                    return None, None, "Blocker page detected (on timeout)"
            except Exception: pass 
            return None, None, error_msg 
        except WebDriverException as e:
            error_msg = f"Selenium/UC: WebDriver Error: {e.msg[:500]}"
            ASCIIColors.error(error_msg)
            return None, None, error_msg
        except Exception as e:
            error_msg = f"Selenium/UC: Unexpected error during run: {e}"
            ASCIIColors.error(error_msg)
            raise StrategyError(error_msg) from e 

    def _try_selenium(self, use_undetected: bool) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts fetching with Selenium or undetected-chromedriver."""
        driver_type = "undetected-chromedriver" if use_undetected else "standard Selenium"
        ASCIIColors.info(f"-- Strategy: Trying {driver_type} --")

        if use_undetected and not UNDETECTED_AVAILABLE:
            return None, None, "undetected-chromedriver library not available"

        driver_path = self._get_driver_path()
        if not driver_path and not use_undetected: 
             raise DriverInitializationError(self.last_error or "Could not get driver path.")
        
        options = self._setup_selenium_options(for_undetected=use_undetected)
        self._quit_driver() 

        try:
            ASCIIColors.info(f"Initializing {driver_type}...")
            start_time = time.time()
            if use_undetected:
                try:
                    self.driver = uc.Chrome(
                        options=options,
                        version_main=None,
                        headless=self.headless,
                        use_subprocess=True
                    )
                except WebDriverException as uc_e:
                    ASCIIColors.warning(f"UC auto-init failed: {uc_e}. Retrying with manual path...")
                    if driver_path:
                         self.driver = uc.Chrome(
                            driver_executable_path=driver_path,
                            options=options,
                            headless=self.headless,
                            use_subprocess=True
                        )
                    else:
                        raise uc_e

            else:
                service = ChromeService(executable_path=driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)

            init_time = time.time() - start_time
            ASCIIColors.debug(f"{driver_type} initialized in {init_time:.2f}s.")

            return self._run_selenium_attempt(self.driver)

        except WebDriverException as e:
            error_msg = f"{driver_type} Initialization/Run Error: {e.msg[:500]}"
            ASCIIColors.error(error_msg)
            self._quit_driver() 
            if "session not created" in str(e).lower() or "connection refused" in str(e).lower():
                ASCIIColors.warning("Tip: This often indicates a Chrome version mismatch or a zombie Chrome process.")
            
            if "initialized" not in locals(): 
                 raise DriverInitializationError(error_msg) from e
            else:
                 return None, None, error_msg
        except Exception as e:
            error_msg = f"{driver_type}: Unexpected error: {e}"
            ASCIIColors.error(error_msg)
            self._quit_driver() 
            raise StrategyError(error_msg) from e 

    def _fetch_content(self, strategy_list: list[str]) -> bool:
        """Orchestrates fetching content using the specified strategies."""
        if not self.current_url:
            self.last_error = "Cannot fetch: URL not set."
            ASCIIColors.error(self.last_error)
            return False

        doc_extensions = {'.pdf', '.docx'}
        try:
            parsed_url = urlparse(self.current_url)
            path_ext = Path(parsed_url.path).suffix.lower()
            is_doc = path_ext in doc_extensions
            
            if not is_doc and "arxiv.org" in parsed_url.netloc and "/pdf/" in parsed_url.path:
                is_doc = True
            
            if is_doc:
                ASCIIColors.info(f"Document file detected (ext: '{path_ext}'): Enforcing 'local_parser' strategy.")
                strategy_list = ['local_parser']
        except Exception:
            pass

        ASCIIColors.info(f"--- Starting fetch for: {self.current_url} ---")
        ASCIIColors.info(f"Using strategies: {strategy_list}")

        self.current_soup = None
        self.html_content = ""
        self.last_error = "No strategies succeeded." 
        self.last_strategy_used = None

        for strategy_name in strategy_list:
            html = None
            soup = None
            error_msg = None 

            try:
                if strategy_name in self._custom_strategies:
                    html, soup, error_msg = self._custom_strategies[strategy_name](self, self.current_url)
                elif strategy_name == "wikipedia":
                    html, soup, error_msg = self._try_wikipedia()
                elif strategy_name == "local_parser":
                    html, soup, error_msg = self._try_local_parser()
                elif strategy_name == "requests":
                    html, soup, error_msg = self._try_requests()
                elif strategy_name == "playwright":
                    html, soup, error_msg = self._try_playwright()
                elif strategy_name == "curl_cffi":
                    html, soup, error_msg = self._try_curl_cffi()
                elif strategy_name == "selenium":
                    html, soup, error_msg = self._try_selenium(use_undetected=False)
                elif strategy_name == "undetected":
                    if UNDETECTED_AVAILABLE:
                        html, soup, error_msg = self._try_selenium(use_undetected=True)
                    else:
                        error_msg = "skipped (library unavailable)"
                        ASCIIColors.warning("-- Strategy: Skipping undetected-chromedriver (unavailable) --")
                        continue 
                else:
                    ASCIIColors.warning(f"Unknown strategy '{strategy_name}' encountered.")
                    continue

                if html is not None and soup is not None:
                    self.html_content = html
                    self.current_soup = soup
                    self.last_error = None
                    self.last_strategy_used = strategy_name
                    ASCIIColors.success(f"--- Fetch successful using strategy: {strategy_name} ---")
                    self._quit_driver() 
                    return True
                elif error_msg:
                    self.last_error = f"{strategy_name.capitalize()}: {error_msg}"
                    ASCIIColors.warning(f"Strategy '{strategy_name}' failed: {error_msg}")
                    continue 
                else:
                     self.last_error = f"{strategy_name.capitalize()}: Strategy returned unexpected empty result."
                     ASCIIColors.error(self.last_error)

            except (DriverInitializationError, PageFetchError, StrategyError, ScrapeMasterError) as e:
                self.last_error = f"{strategy_name.capitalize()} Error: {e}"
                ASCIIColors.critical(f"--- Definitive error during '{strategy_name}' strategy: {e} ---")
                if isinstance(e, DriverInitializationError):
                    pass 
            except Exception as e:
                self.last_error = f"{strategy_name.capitalize()} Unexpected Error: {e}"
                ASCIIColors.critical(f"--- Unexpected critical error during '{strategy_name}' strategy: {e} ---")
                import traceback
                ASCIIColors.error(traceback.format_exc())

        ASCIIColors.error(f"--- Fetch failed after trying all strategies. Last status: {self.last_error} ---")
        self._quit_driver() 
        return False

    def scrape_text(self, selectors: list[str] | None = None, fetch_strategy: list[str] | str | None = None) -> list[str]:
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        if not self.current_soup: 
             if not self._fetch_content(strategy_to_use):
                 return [] 

        if not self.current_soup: 
             self.last_error = "Cannot scrape text: No valid page content fetched."
             ASCIIColors.error(self.last_error)
             return []

        selectors = selectors or DEFAULT_TEXT_SELECTORS
        texts = []
        try:
            for selector in selectors:
                elements = self.current_soup.select(selector)
                for el in elements:
                    texts.append(clean_text(el.get_text()))
            ASCIIColors.debug(f"Scraped {len(texts)} text fragments using selectors: {selectors}")
        except Exception as e:
            raise ParsingError(f"Error during text scraping with selectors {selectors}: {e}") from e

        return texts

    def scrape_images(self, selectors: list[str] | None = None, fetch_strategy: list[str] | str | None = None) -> list[str]:
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        if not self.current_soup:
             if not self._fetch_content(strategy_to_use):
                 return []

        if not self.current_soup or not self.current_url:
             self.last_error = "Cannot scrape images: No valid page content or URL."
             ASCIIColors.error(self.last_error)
             return []

        selectors = selectors or DEFAULT_IMAGE_SELECTORS
        image_urls = []
        try:
            for selector in selectors:
                img_elements = self.current_soup.select(selector)
                for img in img_elements:
                    if img.has_attr('src'):
                        src = img['src']
                        if isinstance(src, str) and src.strip():
                             abs_url = urljoin(self.current_url, src)
                             if is_valid_url(abs_url): 
                                 image_urls.append(abs_url)
            ASCIIColors.debug(f"Scraped {len(image_urls)} image URLs using selectors: {selectors}")
        except Exception as e:
            raise ParsingError(f"Error during image scraping with selectors {selectors}: {e}") from e

        return image_urls

    def scrape_markdown(self,
                        content_selectors: list[str] | None = None,
                        noisy_selectors: list[str] | None = None,
                        fetch_strategy: list[str] | str | None = None,
                        max_depth: int = 0,
                        crawl_delay: float = 0.5,
                        allowed_domains: list[str] | None = None,
                        post_processors: list[callable] = None
                        ) -> str | None:
        """Fetches content, cleans it, and converts to Markdown. Supports post-processors."""
        if max_depth > 0:
            results = self.scrape_all(
                max_depth=max_depth,
                crawl_delay=crawl_delay,
                allowed_domains=allowed_domains,
                content_selectors=content_selectors,
                noisy_selectors=noisy_selectors,
                convert_to_markdown=True,
                fetch_strategy=fetch_strategy
            )
            return results['markdown'] if results else None

        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        if not self.current_soup:
            if not self._fetch_content(strategy_to_use):
                return None

        if not self.current_soup:
            self.last_error = "Cannot convert to Markdown: No valid page content fetched."
            ASCIIColors.error(self.last_error)
            return None

        content_selectors = content_selectors or DEFAULT_CONTENT_SELECTORS
        noisy_selectors = noisy_selectors or DEFAULT_NOISY_SELECTORS

        markdown_text, error = _parse_and_markdownify(
            self.html_content, 
            content_selectors=content_selectors,
            noisy_selectors=noisy_selectors,
            post_processors=post_processors
        )

        if error:
            self.last_error = f"Markdown Conversion Failed: {error}"
            return None

        return markdown_text

    def scrape_all(self,
                   max_depth: int = 0, 
                   crawl_delay: float = 0.5, 
                   allowed_domains: list[str] | None = None, 
                   text_selectors: list[str] | None = None,
                   image_selectors: list[str] | None = None,
                   content_selectors: list[str] | None = None, 
                   noisy_selectors: list[str] | None = None,   
                   convert_to_markdown: bool = False,         
                   download_images_output_dir: str | None = None,
                   fetch_strategy: list[str] | str | None = None,
                   use_sitemap: bool = False,
                   sitemap_url: str | None = None,
                   url_pattern: str | None = None,
                   sitemap_limit: int = 100
                   ) -> dict | None:
        """Performs a comprehensive scrape. Now supports sitemap-based discovery."""
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        start_url = self.current_url or self.initial_url 

        if not start_url:
            self.last_error = "Cannot scrape: No initial URL provided."
            ASCIIColors.error(self.last_error)
            return None

        if use_sitemap:
            urls_to_scrape = self.scrape_from_sitemap(sitemap_url, url_pattern, sitemap_limit)
            if not urls_to_scrape:
                ASCIIColors.warning("No URLs found in sitemap, falling back to standard crawl")
            else:
                ASCIIColors.info(f"Using sitemap mode: {len(urls_to_scrape)} URLs found")
                results = self.scrape_many(urls_to_scrape, extract_markdown=convert_to_markdown)
                return {
                    "markdown": "\n\n".join([r.get("markdown", "") for r in results if "markdown" in r]),
                    "urls": [r["url"] for r in results if "url" in r],
                    "failed": [r for r in results if "error" in r]
                }

        if max_depth == 0:
            ASCIIColors.info(f"Performing single-page scrape for: {start_url}")
            if not self._fetch_content(strategy_to_use):
                 ASCIIColors.error("scrape_all failed: Could not fetch content for the single page.")
                 return None 

            results = {
                'markdown': None, 'texts': [], 'image_urls': [],
                'visited_urls': [start_url], 'failed_urls': []
            }
            try:
                results['texts'] = self.scrape_text(selectors=text_selectors, fetch_strategy=None) 
            except ParsingError as e: ASCIIColors.warning(f"Error scraping text: {e}")
            try:
                results['image_urls'] = self.scrape_images(selectors=image_selectors, fetch_strategy=None) 
            except ParsingError as e: ASCIIColors.warning(f"Error scraping images: {e}")
            if convert_to_markdown:
                try:
                    results['markdown'] = self.scrape_markdown(
                        content_selectors=content_selectors,
                        noisy_selectors=noisy_selectors,
                        fetch_strategy=None
                    ) 
                except ParsingError as e: ASCIIColors.warning(f"Error converting to markdown: {e}")

            if download_images_output_dir and results['image_urls']:
                self.download_images(results['image_urls'], download_images_output_dir)
            return results

        else:
            # --- Multi-Page Crawling Logic ---
            output_path = Path(download_images_output_dir) if download_images_output_dir else None
            if output_path: 
                 output_path.mkdir(parents=True, exist_ok=True)

            visited = set()
            queue = [(start_url, 0)] 
            aggregated_markdown = []
            aggregated_texts = []
            aggregated_image_urls = set() 
            successfully_visited = []
            failed_urls = []

            if allowed_domains is None:
                try:
                    initial_domain = urlparse(start_url).netloc
                    allowed_domains = [initial_domain] if initial_domain else []
                except Exception:
                     allowed_domains = [] 
            if not allowed_domains:
                 ASCIIColors.warning("Could not determine allowed domain. Restricting crawl to max_depth=0.")
                 return self.scrape_all(max_depth=0, 
                                        crawl_delay=crawl_delay, allowed_domains=allowed_domains,
                                        text_selectors=text_selectors, image_selectors=image_selectors,
                                        content_selectors=content_selectors, noisy_selectors=noisy_selectors,
                                        convert_to_markdown=convert_to_markdown,
                                        download_images_output_dir=download_images_output_dir,
                                        fetch_strategy=fetch_strategy)


            ASCIIColors.info(f"Starting website crawl from {start_url}, max_depth={max_depth}, allowed_domains={allowed_domains}")
            page_count = 0

            while queue:
                current_url, current_depth = queue.pop(0)

                if current_url in visited or current_depth > max_depth:
                    continue

                try:
                    current_domain = urlparse(current_url).netloc
                    if current_domain not in allowed_domains:
                        ASCIIColors.debug(f"Skipping external domain: {current_url}")
                        continue
                except Exception:
                     ASCIIColors.warning(f"Could not parse domain for {current_url}, skipping.")
                     continue


                visited.add(current_url)
                page_count += 1
                ASCIIColors.info(f"Crawling [Depth:{current_depth}, Page:{page_count}]: {current_url}")

                self.set_url(current_url) 
                page_markdown = None
                page_texts = []
                page_image_urls = []
                fetch_success = self._fetch_content(strategy_to_use) 

                if fetch_success and self.current_soup:
                    successfully_visited.append(current_url)
                    try:
                         page_texts = self.scrape_text(selectors=text_selectors, fetch_strategy=None)
                         aggregated_texts.extend(page_texts)
                    except ParsingError as e: ASCIIColors.warning(f"Error scraping text on {current_url}: {e}")
                    try:
                         page_image_urls = self.scrape_images(selectors=image_selectors, fetch_strategy=None)
                         aggregated_image_urls.update(page_image_urls) 
                    except ParsingError as e: ASCIIColors.warning(f"Error scraping images on {current_url}: {e}")
                    if convert_to_markdown:
                        try:
                            page_markdown = self.scrape_markdown(
                                content_selectors=content_selectors,
                                noisy_selectors=noisy_selectors,
                                fetch_strategy=None
                            )
                            if page_markdown:
                                 aggregated_markdown.append(f"\n\n## Scraped Content from: {current_url}\n\n---\n\n{page_markdown}")
                        except ParsingError as e: ASCIIColors.warning(f"Error converting to markdown on {current_url}: {e}")

                    if current_depth < max_depth:
                        links = self.current_soup.select('a[href]')
                        for link in links:
                            href = link.get('href')
                            if isinstance(href, str) and href.strip():
                                try:
                                    next_url = urljoin(current_url, href.strip())
                                    parsed_next = urlparse(next_url)
                                    if parsed_next.scheme in ['http', 'https'] and parsed_next.fragment == '':
                                        if next_url not in visited:
                                            queue.append((next_url, current_depth + 1))
                                except Exception:
                                     pass 
                else:
                     ASCIIColors.error(f"Failed to scrape page {current_url}. Error: {self.get_last_error()}")
                     failed_urls.append(current_url)

                if queue: 
                    ASCIIColors.debug(f"Waiting {crawl_delay}s before next fetch...")
                    time.sleep(crawl_delay)

            self._quit_driver() 

            ASCIIColors.success(f"Website crawl finished. Visited {len(visited)} pages ({len(successfully_visited)} scraped successfully).")

            if download_images_output_dir and aggregated_image_urls:
                 self.download_images(list(aggregated_image_urls), download_images_output_dir)

            return {
                'markdown': "\n".join(aggregated_markdown).strip() if convert_to_markdown else None,
                'texts': aggregated_texts,
                'image_urls': sorted(list(aggregated_image_urls)), 
                'visited_urls': successfully_visited,
                'failed_urls': failed_urls
            }
    
    # --- Multi-Media Extraction Methods ---

    def scrape_video(self, url_or_id: str, extract_type: str = 'auto') -> dict | None:
        """
        Unified video scraping interface inspired by YouTube transcript API.
        
        Args:
            url_or_id: YouTube URL/ID, Vimeo URL, or Twitch clip URL
            extract_type: 'auto', 'transcript', 'metadata', or 'comments'
            
        Returns:
            dict with keys: source, video_id, transcript (if available), metadata, comments
        """
        result = {"source": "unknown", "video_id": None, "transcript": None, "metadata": {}, "comments": []}
        
        # Detect platform
        if self._is_youtube_url(url_or_id):
            result["source"] = "youtube"
            video_id = self._extract_youtube_id(url_or_id)
            result["video_id"] = video_id
            
            if extract_type in ('auto', 'transcript'):
                result["transcript"] = self.scrape_youtube_transcript(video_id)
            
            if extract_type in ('auto', 'metadata') and self.initial_url:
                result["metadata"] = self._extract_youtube_metadata(video_id)
                
        elif "vimeo.com" in url_or_id:
            result["source"] = "vimeo"
            match = re.search(r'vimeo\.com/(\d+)', url_or_id)
            if match:
                result["video_id"] = match.group(1)
                result["metadata"] = self._extract_vimeo_metadata(result["video_id"])
                
        elif "clips.twitch.tv" in url_or_id or "twitch.tv" in url_or_id:
            result["source"] = "twitch"
            if extract_type in ('auto', 'comments'):
                result["comments"] = self._extract_twitch_chat(url_or_id)
        
        return result if result["source"] != "unknown" else None

    def _is_youtube_url(self, url: str) -> bool:
        """Check if URL is YouTube."""
        return "youtube.com" in url or "youtu.be" in url or (len(url) == 11 and '/' not in url)

    def _extract_youtube_metadata(self, video_id: str) -> dict:
        """Extract metadata from YouTube page."""
        metadata = {"id": video_id, "title": None, "author": None, "duration": None, "views": None}
        
        # Try to fetch page for metadata
        try:
            temp_url = f"https://www.youtube.com/watch?v={video_id}"
            original_url = self.current_url
            self.set_url(temp_url)
            
            if self._fetch_content(['requests']):
                soup = self.current_soup
                if soup:
                    # Title
                    if soup.find('h1', class_='ytd-watch-metadata'):
                        metadata["title"] = soup.find('h1', class_='ytd-watch-metadata').get_text().strip()
                    
                    # Views
                    view_count = soup.find('span', class_='view-count')
                    if view_count:
                        metadata["views"] = view_count.get_text().strip()
            
            # Restore original URL
            if original_url != temp_url:
                self.set_url(original_url)
                
        except Exception as e:
            ASCIIColors.warning(f"Could not extract YouTube metadata: {e}")
            
        return metadata

    def _extract_vimeo_metadata(self, video_id: str) -> dict:
        """Extract metadata from Vimeo."""
        try:
            url = f"https://vimeo.com/{video_id}"
            original = self.current_url
            self.set_url(url)
            
            if self._fetch_content(['requests']):
                structured = self.scrape_structured_data()
                if structured and structured.get("json_ld"):
                    for item in structured["json_ld"]:
                        if item.get("@type") == "VideoObject":
                            return {
                                "id": video_id,
                                "title": item.get("name"),
                                "description": item.get("description"),
                                "upload_date": item.get("uploadDate"),
                                "duration": item.get("duration")
                            }
            
            if original:
                self.set_url(original)
                
        except Exception as e:
            ASCIIColors.warning(f"Vimeo metadata error: {e}")
            
        return {"id": video_id}

    def _extract_twitch_chat(self, url: str) -> list[dict]:
        """Extract chat replay from Twitch (requires additional API calls)."""
        # Placeholder for Twitch chat extraction
        # Real implementation would use Twitch API with client credentials
        return [{"platform": "twitch", "note": "Chat extraction requires Twitch API credentials"}]

    def scrape_media_links(self, media_types: list[str] | None = None) -> dict:
        """
        Extract media URLs from current page (video, audio, images).
        
        Args:
            media_types: Filter list ['video', 'audio', 'image']
            
        Returns:
            dict with keys: videos, audios, images, embeds
        """
        if not self.current_soup:
            if not self._fetch_content(self.strategy):
                return {"videos": [], "audios": [], "images": [], "embeds": []}

        if media_types is None:
            media_types = ['video', 'audio', 'image']

        results = {"videos": [], "audios": [], "images": [], "embeds": []}
        base_url = self.current_url or ""

        # Videos
        if 'video' in media_types:
            # <video> tags
            for video in self.current_soup.find_all('video'):
                src = video.get('src') or video.find('source')
                if src:
                    src_url = src.get('src') if hasattr(src, 'get') else src
                    results["videos"].append(urljoin(base_url, src_url))
            # YouTube embeds
            for iframe in self.current_soup.find_all('iframe', src=True):
                if 'youtube.com' in iframe['src'] or 'youtu.be' in iframe['src']:
                    results["embeds"].append({"type": "youtube", "url": iframe['src']})

        # Audio
        if 'audio' in media_types:
            for audio in self.current_soup.find_all('audio'):
                src = audio.get('src') or audio.find('source')
                if src:
                    src_url = src.get('src') if hasattr(src, 'get') else src
                    results["audios"].append(urljoin(base_url, src_url))

        # Images (enhanced from scrape_images)
        if 'image' in media_types:
            results["images"] = self.scrape_images()

        return results

    # --- Podcast & RSS Methods ---

    def scrape_podcast_feed(self, feed_url: str | None = None) -> dict | None:
        """
        Parse podcast RSS feed for episodes and metadata.
        Inspired by YouTube transcript pattern - simple, focused extraction.
        """
        if not feed_url:
            # Try to find feed in current page
            if self.current_soup:
                for link in self.current_soup.find_all('link', type='application/rss+xml'):
                    if link.get('href'):
                        feed_url = urljoin(self.current_url, link['href'])
                        break
            
            if not feed_url:
                self.last_error = "No RSS feed found on current page"
                return None

        try:
            self.set_url(feed_url)
            response = self.session.get(feed_url, timeout=30)
            response.raise_for_status()
            
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            
            # Itunes namespace
            ns = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}
            
            feed_info = {
                "title": root.find('.//channel/title').text if root.find('.//channel/title') is not None else "Unknown",
                "author": root.find('.//itunes:author', ns).text if root.find('.//itunes:author', ns) is not None else None,
                "episodes": []
            }
            
            for item in root.findall('.//item'):
                episode = {
                    "title": item.find('title').text if item.find('title') is not None else "Untitled",
                    "date": item.find('pubDate').text if item.find('pubDate') is not None else None,
                    "description": item.find('description').text if item.find('description') is not None else None,
                    "audio_url": None,
                    "duration": None
                }
                
                # Find enclosure
                enclosure = item.find('enclosure')
                if enclosure is not None:
                    episode["audio_url"] = enclosure.get('url')
                    
                # iTunes duration
                dur = item.find('itunes:duration', ns)
                if dur is not None:
                    episode["duration"] = dur.text
                    
                feed_info["episodes"].append(episode)
            
            return feed_info
            
        except Exception as e:
            self.last_error = f"Podcast feed error: {e}"
            return None

    # --- Social Media Extraction ---

    def scrape_social_post(self) -> dict | None:
        """
        Extract structured social media content (Twitter/X, LinkedIn patterns).
        Returns dict with author, text, quoted_content, thread_context.
        """
        if not self.current_soup:
            if not self._fetch_content(self.strategy):
                return None

        post = {
            "platform": "unknown",
            "author": None,
            "timestamp": None,
            "text": "",
            "quoted_content": None,
            "thread_context": [],
            "metrics": {"likes": None, "reposts": None, "replies": None}
        }

        current_url = self.current_url or ""
        
        # Twitter/X detection
        if "twitter.com" in current_url or "x.com" in current_url:
            post["platform"] = "twitter"
            return self._extract_twitter_post(post, current_url)
        
        # LinkedIn detection  
        elif "linkedin.com" in current_url:
            post["platform"] = "linkedin"
            return self._extract_linkedin_post(post)
            
        return None

    def _extract_twitter_post(self, post: dict, url: str) -> dict:
        """Twitter/X specific extraction."""
        # Article body
        article = self.current_soup.find('article', {'data-testid': 'tweet'})
        if not article:
            return None
            
        # Text content
        text_div = article.find('div', {'data-testid': 'tweetText'})
        if text_div:
            post["text"] = text_div.get_text()
            
        # Quoted tweet
        quote = article.find('div', {'class': 'thread-tweet'})
        if quote:
            quote_text = quote.find('div', {'data-testid': 'tweetText'})
            if quote_text:
                post["quoted_content"] = {
                    "text": quote_text.get_text(),
                    "author": quote.find('span', {'class': 'username'})
                }
                
        # Metrics
        metrics = article.find_all('div', {'class': 'metric'})
        for m in metrics:
            label = m.get('aria-label', '').lower()
            if 'reply' in label:
                post["metrics"]["replies"] = m.get_text()
            elif 'like' in label:
                post["metrics"]["likes"] = m.get_text()
                
        return post

    def _extract_linkedin_post(self, post: dict) -> dict:
        """LinkedIn specific extraction."""
        text_area = self.current_soup.find('div', class_='feed-shared-text')
        if text_area:
            post["text"] = text_area.get_text().strip()
            
        return post

    # --- News Article Extraction ---

    def scrape_article(self, extract_comments: bool = False) -> dict | None:
        """
        Smart article extraction: author, date, section, body, reading time.
        Inspired by transcript simplicity - returns structured dict.
        """
        if not self.current_soup:
            if not self._fetch_content(self.strategy):
                return None

        article = {
            "title": None,
            "author": None,
            "published_date": None,
            "section": None,
            "content_md": None,
            "reading_time_min": None,
            "word_count": 0,
            "comments": [] if extract_comments else None
        }

        # Title from meta or h1
        title_tag = self.current_soup.find('meta', property='og:title')
        if title_tag and title_tag.get('content'):
            article["title"] = title_tag['content']
        elif self.current_soup.find('h1'):
            article["title"] = self.current_soup.find('h1').get_text().strip()

        # Author detection
        author_meta = self.current_soup.find('meta', attrs={'name': 'author'})
        if author_meta:
            article["author"] = author_meta.get('content')
        else:
            # Look for byline patterns
            byline = self.current_soup.find(['span', 'div', 'p'], class_=re.compile(r'byline|author|writer', re.I))
            if byline:
                article["author"] = byline.get_text().strip()

        # Date
        time_tag = self.current_soup.find('time')
        if time_tag:
            article["published_date"] = time_tag.get('datetime') or time_tag.get_text()
        else:
            # Meta date
            date_meta = self.current_soup.find('meta', property='article:published_time')
            if date_meta:
                article["published_date"] = date_meta.get('content')

        # Section from breadcrumb or tags
        section_tag = self.current_soup.find('meta', property='article:section')
        if section_tag:
            article["section"] = section_tag.get('content')

        # Content
        article["content_md"] = self.scrape_markdown()
        if article["content_md"]:
            words = len(article["content_md"].split())
            article["word_count"] = words
            article["reading_time_min"] = round(words / 200, 1)

        # Comments if requested
        if extract_comments:
            article["comments"] = self._extract_comments()

        return article

    def _extract_comments(self) -> list[dict]:
        """Disqus/Native comment extraction."""
        comments = []
        
        # Disqus
        disqus = self.current_soup.find_all('div', class_=re.compile(r'disqus'))
        for d in disqus:
            comments.append({
                "platform": "disqus",
                "text": d.get_text().strip(),
                "author": None
            })
            
        # Native comments area
        comment_area = self.current_soup.find('div', id='comments') or self.current_soup.find('section', class_=re.compile(r'comment', re.I))
        if comment_area:
            comments.append({
                "platform": "native",
                "text": comment_area.get_text().strip(),
                "author": None
            })
            
        return comments

    # --- Original YouTube Methods (Keep for compatibility) ---

    def _extract_youtube_id(self, url_or_id: str) -> str:
        """Helper to extract YouTube video ID from a URL or return the ID if it looks like one."""
        if len(url_or_id) == 11 and ' ' not in url_or_id and '/' not in url_or_id:
             return url_or_id
        
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        
        raise ValueError(f"Could not extract YouTube video ID from: {url_or_id}")

    def get_youtube_languages(self, url_or_id: str) -> list[dict] | None:
        """Retrieves a list of available transcript languages for a YouTube video."""
        if not YOUTUBE_AVAILABLE:
            ASCIIColors.warning("YouTube transcript scraping requires 'youtube-transcript-api'. Please install it.")
            return None
        
        try:
            video_id = self._extract_youtube_id(url_or_id)
            ASCIIColors.info(f"Fetching available transcript languages for video: {video_id}")
            vtapi = YouTubeTranscriptApi()
            transcript_list = vtapi.list(video_id)
            languages = []
            
            def get_info(t):
                return {
                    "code": t.language_code,
                    "name": t.language,
                    "is_generated": t.is_generated,
                    "is_translatable": t.is_translatable
                }

            for t in transcript_list._manually_created_transcripts.values():
                languages.append(get_info(t))
                
            for t in transcript_list._generated_transcripts.values():
                languages.append(get_info(t))
                
            return languages

        except Exception as e:
            self.last_error = f"Error fetching YouTube languages: {e}"
            ASCIIColors.error(self.last_error)
            return None

    def scrape_youtube_transcript(self, url_or_id: str, language_code: str | None = None) -> str | None:
        """Scrapes the transcript text from a YouTube video with GDPR bypass."""
        if not YOUTUBE_AVAILABLE:
            ASCIIColors.warning("YouTube transcript scraping requires 'youtube-transcript-api'. Please install it.")
            return None

        # Set session cookies before transcript fetch to bypass GDPR consent
        # The library uses the session's cookies when making requests
        if hasattr(self, 'session') and self.session:
            self.session.cookies.set("SOCS", "CAE", domain=".youtube.com", path="/")
            self.session.cookies.set("SOCS", "CAE", domain="youtube.com", path="/")
            self.session.cookies.set("SOCS", "CAE", domain=".google.com", path="/")

        vtapi = YouTubeTranscriptApi()
        try:
            video_id = self._extract_youtube_id(url_or_id)
            ASCIIColors.info(f"Fetching transcript for video: {video_id}")

            if language_code:
                ASCIIColors.info(f"Attempting to fetch transcript for language: {language_code}")
                transcript_data = vtapi.fetch(video_id, languages=[language_code])
            else:
                # Auto-detect available languages to handle non-English videos
                ASCIIColors.info("No language specified. Detecting available languages...")
                transcript_list = vtapi.list(video_id)
                available_langs = []

                for transcript in transcript_list:
                    available_langs.append(transcript.language_code)

                if not available_langs:
                    raise ValueError("No transcripts available for this video")

                # Prefer manually created over auto-generated
                preferred_lang = None
                for transcript in transcript_list:
                    if not transcript.is_generated:
                        preferred_lang = transcript.language_code
                        break

                if not preferred_lang:
                    preferred_lang = available_langs[0]  # Use first available

                ASCIIColors.info(f"Auto-detected language: {preferred_lang}")
                transcript_data = vtapi.fetch(video_id, languages=[preferred_lang])

            full_text = " ".join([entry.text for entry in transcript_data.snippets])
            full_text = re.sub(r'\s+', ' ', full_text).strip()

            ASCIIColors.success("YouTube transcript fetched successfully.")
            return full_text

        except Exception as e:
            self.last_error = f"Error fetching YouTube transcript: {e}"
            ASCIIColors.error(self.last_error)
            return None

    # --- Utility and Session Management Methods ---

    def set_random_user_agent(self):
        """Sets a random User-Agent header from the internal list for the requests session."""
        ua = random.choice(self.user_agents)
        self.session.headers['User-Agent'] = ua
        ASCIIColors.debug(f"Set User-Agent: {ua}")

    def use_proxy(self, proxy: str):
        """Sets a proxy for the requests session."""
        self.session.proxies = {'http': proxy, 'https': proxy}
        ASCIIColors.info(f"Using proxy: {proxy}")

    def save_cookies(self, filename: str = 'cookies.pkl'):
        """Saves the requests session cookies to a file using pickle."""
        try:
            with open(filename, 'wb') as f:
                pickle.dump(self.session.cookies, f)
            ASCIIColors.info(f"Requests session cookies saved to {filename}")
        except Exception as e:
            ASCIIColors.error(f"Failed to save requests cookies: {e}")

    def load_cookies(self, filename: str = 'cookies.pkl'):
        """Loads requests session cookies from a file using pickle."""
        try:
            with open(filename, 'rb') as f:
                self.session.cookies.update(pickle.load(f))
            ASCIIColors.info(f"Requests session cookies loaded from {filename}")
        except FileNotFoundError:
            ASCIIColors.warning(f"Cookie file not found: {filename}")
        except Exception as e:
            ASCIIColors.error(f"Failed to load requests cookies: {e}")

    def save_selenium_cookies(self, filename: str = 'selenium_cookies.json'):
        """Saves Selenium cookies to a JSON file."""
        if not self.driver:
            ASCIIColors.warning("Cannot save Selenium cookies: Driver not active.")
            return
        try:
            cookies = self.driver.get_cookies()
            with open(filename, 'w') as f:
                json.dump(cookies, f, indent=4)
            ASCIIColors.info(f"Selenium cookies saved to {filename}")
        except Exception as e:
            ASCIIColors.error(f"Failed to save Selenium cookies: {e}")

    def load_selenium_cookies(self, filename: str = 'selenium_cookies.json'):
        """Loads Selenium cookies from a JSON file. Requires driver to be active."""
        if not self.driver:
            ASCIIColors.warning("Cannot load Selenium cookies: Driver not active. Fetch page first.")
            return
        try:
            with open(filename, 'r') as f:
                cookies = json.load(f)
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e_add:
                    ASCIIColors.warning(f"Could not add cookie {cookie.get('name', 'N/A')}: {e_add}")
            ASCIIColors.info(f"Selenium cookies loaded from {filename}")
            self.driver.refresh() 
        except FileNotFoundError:
            ASCIIColors.warning(f"Selenium cookie file not found: {filename}")
        except Exception as e:
            ASCIIColors.error(f"Failed to load Selenium cookies: {e}")


    def download_images(self, image_urls: list[str], output_dir: str):
        """Downloads images from the provided URLs to the specified directory."""
        if not image_urls:
            return

        images_dir = Path(output_dir) / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        ASCIIColors.info(f"Downloading {len(image_urls)} images to {images_dir}...")
        downloaded_count = 0

        for i, url in enumerate(image_urls):
            try:
                parsed_path = Path(urlparse(url).path)
                filename_base = parsed_path.stem
                filename_ext = parsed_path.suffix or '.jpg' 
                safe_filename_base = re.sub(r'[^\w\-]+', '_', filename_base)
                filename = f"{safe_filename_base[:50]}_{i}{filename_ext}" 
                filepath = images_dir / filename

                response = self.session.get(url, stream=True, timeout=20)
                response.raise_for_status()

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded_count += 1
                ASCIIColors.debug(f"Downloaded {url} to {filepath}")

            except requests.exceptions.RequestException as ex:
                ASCIIColors.warning(f"Failed to download image {url}: {ex}")
            except IOError as ex:
                ASCIIColors.warning(f"Failed to save image {url} to {filepath}: {ex}")
            except Exception as ex:
                ASCIIColors.warning(f"Unexpected error downloading image {url}: {ex}")


    # --- Deprecated Methods ---

    def fetch_page(self):
        """DEPRECATED (use scrape_... methods with strategy=['requests'])."""
        ASCIIColors.warning("fetch_page() is deprecated. Use scrape_... methods with fetch_strategy=['requests'].")
        try:
            html, soup, error = self._try_requests()
            if soup:
                self.current_soup = soup
                self.html_content = html
                self.last_strategy_used = 'requests'
                self.last_error = None
            else:
                self.last_error = error or "Requests fetch failed"
                raise PageFetchError(self.last_error)
        except Exception as e:
             self.last_error = f"Error in fetch_page: {e}"
             raise PageFetchError(self.last_error) from e


    def fetch_page_with_js(self):
        """DEPRECATED (use scrape_... methods with strategy=['selenium'])."""
        ASCIIColors.warning("fetch_page_with_js() is deprecated. Use scrape_... methods with fetch_strategy=['selenium'].")
        try:
            html, soup, error = self._try_selenium(use_undetected=False)
            if soup:
                self.current_soup = soup
                self.html_content = html
                self.last_strategy_used = 'selenium'
                self.last_error = None
            else:
                 self.last_error = error or "Selenium fetch failed"
                 raise StrategyError(self.last_error)
        except Exception as e:
             self.last_error = f"Error in fetch_page_with_js: {e}"
             raise StrategyError(self.last_error) from e

    # --- Login methods remain similar ---

    def login(self, login_url, username, password, username_field='username', password_field='password'):
        """Logs into a website using the requests session. Best for simple form logins."""
        ASCIIColors.info(f"Attempting requests-based login to {login_url}")
        data = {username_field: username, password_field: password}
        try:
            response = self.session.post(login_url, data=data)
            response.raise_for_status()
            ASCIIColors.success("Requests-based login likely successful (check cookies/subsequent requests).")
        except requests.exceptions.RequestException as e:
            raise PageFetchError(f"Requests login failed: {e}") from e

    def login_with_selenium(self, login_url, username, password, username_selector, password_selector, submit_selector, wait_after_login=5):
        """Logs into a website using Selenium. Better for JS-heavy login forms."""
        ASCIIColors.info(f"Attempting Selenium-based login to {login_url}")
        if not self.driver:
            ASCIIColors.warning("Initializing standard Selenium driver for login.")
            options = self._setup_selenium_options(for_undetected=False)
            driver_path = self._get_driver_path()
            if not driver_path: raise DriverInitializationError("Cannot login with Selenium: driver path not found.")
            service = ChromeService(executable_path=driver_path)
            self.driver = webdriver.Chrome(service=service, options=options)

        try:
            self.driver.get(login_url)
            wait = WebDriverWait(self.driver, 15) 

            user_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, username_selector)))
            pass_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, password_selector)))
            submit_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_selector)))

            user_field.clear(); user_field.send_keys(username)
            pass_field.clear(); pass_field.send_keys(password)
            submit_button.click()

            ASCIIColors.info(f"Login submitted. Waiting {wait_after_login}s for redirection/page load...")
            time.sleep(wait_after_login)

        except (WebDriverException, TimeoutException) as e:
            raise StrategyError(f"Selenium login failed: {e}") from e
        except Exception as e:
             raise ScrapeMasterError(f"Unexpected error during Selenium login: {e}") from e


    def scrape_website(self,
                       start_url: str | None = None,
                       max_depth: int = 1,
                       output_dir: str = 'scraped_website_output',
                       file_prefix: str = 'page_',
                       crawl_delay: float = 0.5,
                       allowed_domains: list[str] | None = None,
                       fetch_strategy: list[str] | str | None = None,
                       convert_to_markdown: bool = True,
                       save_images: bool = False):
        """Recursively scrapes a website starting from a URL, following links up to a max depth."""
        start_url = start_url or self.initial_url
        if not start_url or not is_valid_url(start_url):
            raise ValueError("Invalid start URL for website scraping.")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        visited = set()
        queue = [(start_url, 0)] 

        if allowed_domains is None:
            allowed_domains = [urlparse(start_url).netloc]

        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        page_count = 0

        ASCIIColors.info(f"Starting website crawl from {start_url}, max_depth={max_depth}, allowed_domains={allowed_domains}")

        while queue:
            current_url, current_depth = queue.pop(0)

            if current_url in visited or current_depth > max_depth:
                continue

            current_domain = urlparse(current_url).netloc
            if current_domain not in allowed_domains:
                ASCIIColors.debug(f"Skipping external domain: {current_url}")
                continue

            visited.add(current_url)
            page_count += 1
            ASCIIColors.info(f"Crawling [Depth:{current_depth}, Page:{page_count}]: {current_url}")

            self.set_url(current_url) 

            results = self.scrape_all(
                fetch_strategy=strategy_to_use,
                convert_to_markdown=convert_to_markdown,
                download_images_output_dir=output_path if save_images else None
            )

            if results:
                page_filename_base = f"{file_prefix}{page_count}_{current_domain}_{Path(urlparse(current_url).path).name or 'index'}"
                page_filename_base = re.sub(r'[^\w\-]+', '_', page_filename_base)[:100] 

                if convert_to_markdown and results.get('markdown'):
                    filepath = output_path / f"{page_filename_base}.md"
                    try:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(f"# Scraped Content from: {current_url}\n\n")
                            f.write(results['markdown'])
                        ASCIIColors.debug(f"Saved Markdown to {filepath}")
                    except IOError as e:
                        ASCIIColors.error(f"Failed to save Markdown for {current_url}: {e}")
                elif results.get('texts'): 
                    filepath = output_path / f"{page_filename_base}.txt"
                    try:
                         with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(f"Scraped Text Fragments from: {current_url}\n\n")
                            f.write('\n---\n'.join(results['texts']))
                         ASCIIColors.debug(f"Saved Text to {filepath}")
                    except IOError as e:
                        ASCIIColors.error(f"Failed to save text for {current_url}: {e}")

                if current_depth < max_depth and self.current_soup:
                    links = self.current_soup.select('a[href]')
                    for link in links:
                        href = link.get('href')
                        if isinstance(href, str) and href.strip():
                            next_url = urljoin(current_url, href)
                            if is_valid_url(next_url) and urlparse(next_url).fragment == '':
                                if next_url not in visited:
                                    queue.append((next_url, current_depth + 1))
            else:
                 ASCIIColors.error(f"Failed to scrape page {current_url}. Error: {self.get_last_error()}")

            if queue: 
                ASCIIColors.debug(f"Waiting {crawl_delay}s before next fetch...")
                time.sleep(crawl_delay)

        ASCIIColors.success(f"Website crawl finished. Visited {len(visited)} pages.")
        self._quit_driver() 
