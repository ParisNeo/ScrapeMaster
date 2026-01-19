"""
ScrapeMaster Core Module: Provides the main ScrapeMaster class for web scraping.
"""
import time
import random
import pickle
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

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
        "markdown",              # Added for MD -> HTML conversion (Docling support)
        "ascii_colors",
        "youtube_transcript_api",
        "wikipedia",
        "docling"
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

# Docling Import
try:
    from docling.document_converter import DocumentConverter
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False


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
SUPPORTED_STRATEGIES = ["requests", "selenium", "undetected", "wikipedia", "docling"]
DEFAULT_STRATEGY_ORDER = ["wikipedia", "requests", "selenium", "undetected"] 

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
                ASCIIColors.debug(f"Skipping likely line number in code block: '{line.strip()}'")
                continue
            else:
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)

def _parse_and_markdownify(html_content: str,
                           content_selectors: list = DEFAULT_CONTENT_SELECTORS,
                           noisy_selectors: list = DEFAULT_NOISY_SELECTORS
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

        # --- Standard Noise Removal ---
        removed_noise_count = remove_noisy_elements(main_content_element, noisy_selectors)
        ASCIIColors.debug(f"Removed {removed_noise_count} general noisy elements.")

        # Check for blocker message (Double check after cleaning)
        cleaned_text_sample = main_content_element.get_text(strip=True)[:500].lower()
        if check_for_blocker(cleaned_text_sample):
             ASCIIColors.warning("Content container holds blocker message after cleaning.")
             return None, f"Blocker identified within '{used_selector}' after cleaning."

        # --- Markdown Conversion ---
        ASCIIColors.info("Converting cleaned HTML to Markdown...")
        html_string = str(main_content_element)
        markdown_text = md(html_string, heading_style="ATX", escape_underscores=False, default_title=True)

        # --- Post-processing ---
        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text).strip()
        markdown_text = _clean_markdown_code_blocks(markdown_text)

        ASCIIColors.success("Markdown conversion and cleaning complete.")
        return markdown_text, None 

    except Exception as e:
        import traceback
        error_msg = f"Error during parsing/markdownify: {e}"
        ASCIIColors.error(error_msg)
        raise ParsingError(error_msg) from e

class ScrapeMaster:
    """
    A versatile web scraping class using multiple strategies (requests, Selenium, undetected, wikipedia, docling)
    for fetching and extracting web content, including Markdown conversion.
    """
    def __init__(self, url: str | None = None, strategy: list[str] | str = 'auto', headless: bool = True):
        self._validate_url(url)
        self.initial_url = url
        self.current_url = url
        self.headless = headless
        self.strategy = self._resolve_strategy(strategy) # Resolve after setting URL to auto-detect wiki

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.driver = None 
        self.current_soup = None 
        self.html_content = "" 
        self.last_error = None 
        self.last_strategy_used = None

        self.user_agents = list(DEFAULT_HEADERS.values()) 

        print(f"ScrapeMaster initialized. Strategy: {self.strategy}, Headless: {self.headless}")
        if 'undetected' in self.strategy and not UNDETECTED_AVAILABLE:
            ASCIIColors.warning("Specified 'undetected' strategy, but library is not available.")

    def _validate_url(self, url: str | None):
        if url is not None and not is_valid_url(url):
            raise ValueError(f"Invalid initial URL provided: {url}")

    def _resolve_strategy(self, strategy: list[str] | str) -> list[str]:
        """Resolves the strategy argument into a validated list, handling 'auto' logic."""
        if strategy == 'auto':
            # Dynamic strategy ordering based on URL
            strat_order = list(DEFAULT_STRATEGY_ORDER)
            
            # If explicit Wikipedia URL, ensure wikipedia strategy is first
            if self.current_url and "wikipedia.org" in self.current_url:
                if "wikipedia" in strat_order:
                    strat_order.remove("wikipedia")
                strat_order.insert(0, "wikipedia")
                ASCIIColors.info("Wikipedia URL detected: Prioritizing 'wikipedia' library strategy.")
            elif "wikipedia" in strat_order:
                # If not a wiki url, move wikipedia to end or remove it to save time
                strat_order.remove("wikipedia")
            
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
        # Re-evaluate auto strategy order if using auto, but simple init usually enough
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

        if not for_undetected:
            options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
            options.add_experimental_option('useAutomationExtension', False)
            prefs = {"profile.default_content_setting_values.cookies": 1, "profile.default_content_setting_values.javascript": 1}
            options.add_experimental_option("prefs", prefs)
        return options

    def _quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
                ASCIIColors.debug("WebDriver instance quit.")
            except Exception as e:
                ASCIIColors.warning(f"Error quitting WebDriver: {e}")
            finally:
                self.driver = None

    def __del__(self):
        self._quit_driver()

    # --- Strategy Implementations ---

    def _try_wikipedia(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts to fetch content using the official Wikipedia library."""
        if not WIKIPEDIA_AVAILABLE:
            return None, None, "wikipedia library not installed"
        
        ASCIIColors.info("-- Strategy: Trying 'wikipedia' library --")
        try:
            parsed = urlparse(self.current_url)
            if "wikipedia.org" not in parsed.netloc:
                return None, None, "Not a Wikipedia URL"

            # Extract language (e.g., 'fr.wikipedia.org' -> 'fr')
            parts = parsed.netloc.split('.')
            if len(parts) >= 3:
                lang = parts[0]
                wikipedia.set_lang(lang)
            
            # Extract title (e.g., /wiki/Python_(programming_language))
            path_parts = parsed.path.split('/')
            if len(path_parts) > 2 and path_parts[1] == 'wiki':
                title = unquote(path_parts[2])
            else:
                return None, None, "Could not parse Wikipedia title from URL"

            ASCIIColors.info(f"Fetching Wikipedia page: {title} ({lang if 'lang' in locals() else 'default'})")
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

    def _try_docling(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts to fetch and parse using Docling."""
        if not DOCLING_AVAILABLE:
            return None, None, "docling library not installed"
            
        ASCIIColors.info("-- Strategy: Trying 'docling' --")
        try:
            converter = DocumentConverter()
            ASCIIColors.info(f"Docling converting: {self.current_url}")
            # Docling handles fetching internally
            result = converter.convert(self.current_url)
            
            markdown_content = result.document.export_to_markdown()
            
            # Wrap in HTML for compatibility
            try:
                import markdown
                html_content = markdown.markdown(markdown_content)
                html_content = f"<html><body>{html_content}</body></html>"
            except ImportError:
                # Fallback if markdown library is not installed
                html_content = f"<html><body><pre>{markdown_content}</pre></body></html>"

            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Docling: Conversion successful.")
            return html_content, soup, None

        except Exception as e:
            return None, None, f"Docling Error: {e}"

    def _try_requests(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts fetching with the requests library."""
        ASCIIColors.info("-- Strategy: Trying simple HTTP request (requests) --")
        if not self.current_url: return None, None, "No URL set"
        try:
            self.set_random_user_agent() 
            response = self.session.get(self.current_url, timeout=25)
            ASCIIColors.debug(f"Requests Status Code: {response.status_code}")

            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                return None, None, f"Non-HTML content type received: {content_type}"

            response.raise_for_status() 
            html_content = response.content.decode(response.encoding or 'utf-8', errors='ignore')

            if check_for_blocker(html_content):
                ASCIIColors.warning("Requests: Blocker page detected.")
                return None, None, "Blocker page detected" 

            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Requests: Fetch and parse successful.")
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

            # --- Explicit Wait for Content Containers ---
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
                # Undetected Chromedriver often manages its own binary better than WDM
                # Try letting it auto-detect first if WDM path isn't strictly enforced
                try:
                    self.driver = uc.Chrome(
                        options=options,
                        version_main=None, # Auto-detect version
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
                ASCIIColors.warning("Tip: This often indicates a Chrome version mismatch or a zombie Chrome process. Try killing old chrome processes.")
            
            if "initialized" not in locals(): 
                 raise DriverInitializationError(error_msg) from e
            else:
                 return None, None, error_msg
        except Exception as e:
            error_msg = f"{driver_type}: Unexpected error: {e}"
            ASCIIColors.error(error_msg)
            self._quit_driver() 
            raise StrategyError(error_msg) from e 

    # --- Core Fetching Orchestration ---

    def _fetch_content(self, strategy_list: list[str]) -> bool:
        """
        Orchestrates fetching content using the specified strategies.
        """
        if not self.current_url:
            self.last_error = "Cannot fetch: URL not set."
            ASCIIColors.error(self.last_error)
            return False

        # ----------------------------------------------------------------
        # 1️⃣  Auto-Detect File Types (PDF, DOCX, etc.) & Enforce Docling
        # ----------------------------------------------------------------
        # Check if the URL points to a document type that Docling handles best.
        # This overrides the passed strategy list to ensure the right tool is used.
        doc_extensions = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', '.asciidoc'}
        try:
            parsed_url = urlparse(self.current_url)
            path_ext = Path(parsed_url.path).suffix.lower()
            
            # Check 1: Extension match
            is_doc = path_ext in doc_extensions
            
            # Check 2: ArXiv PDF pattern (often missing extension in URL)
            # Example: https://arxiv.org/pdf/2109.09572
            if not is_doc and "arxiv.org" in parsed_url.netloc and "/pdf/" in parsed_url.path:
                is_doc = True
            
            if is_doc:
                ASCIIColors.info(f"Document file detected (ext: '{path_ext}'): Enforcing 'docling' strategy.")
                strategy_list = ['docling']
        except Exception:
            pass # Fallback to standard flow if parsing fails

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
                if strategy_name == "wikipedia":
                    html, soup, error_msg = self._try_wikipedia()
                elif strategy_name == "docling":
                    html, soup, error_msg = self._try_docling()
                elif strategy_name == "requests":
                    html, soup, error_msg = self._try_requests()
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

                # --- Process Strategy Outcome ---
                if html is not None and soup is not None:
                    # SUCCESS!
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
                    # Should we abort completely if driver init fails? 
                    # Usually better to try other strategies (like docling or requests if they come later)
                    pass 
            except Exception as e:
                self.last_error = f"{strategy_name.capitalize()} Unexpected Error: {e}"
                ASCIIColors.critical(f"--- Unexpected critical error during '{strategy_name}' strategy: {e} ---")
                import traceback
                ASCIIColors.error(traceback.format_exc())
                # Continue to next strategy

        ASCIIColors.error(f"--- Fetch failed after trying all strategies. Last status: {self.last_error} ---")
        self._quit_driver() 
        return False

    # --- Public Scraping Methods ---

    def scrape_text(self, selectors: list[str] | None = None, fetch_strategy: list[str] | str | None = None) -> list[str]:
        """Scrapes text fragments from the page using specified selectors after fetching content."""
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
        """Scrapes image URLs from the page using specified selectors after fetching content."""
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
                        allowed_domains: list[str] | None = None
                        ) -> str | None:
        """Fetches content, cleans it, and converts to Markdown."""
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

        # --- Single Page Logic ---
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        if not self.current_soup:
            if not self._fetch_content(strategy_to_use):
                return None

        if not self.current_soup:
            self.last_error = "Cannot convert to Markdown: No valid page content fetched."
            ASCIIColors.error(self.last_error)
            return None

        # Use library defaults if None are passed
        content_selectors = content_selectors or DEFAULT_CONTENT_SELECTORS
        noisy_selectors = noisy_selectors or DEFAULT_NOISY_SELECTORS

        # Call the enhanced parsing function
        markdown_text, error = _parse_and_markdownify(
            self.html_content, 
            content_selectors=content_selectors,
            noisy_selectors=noisy_selectors
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
                   fetch_strategy: list[str] | str | None = None
                   ) -> dict | None:
        """Performs a comprehensive scrape, potentially crawling linked pages up to max_depth."""
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        start_url = self.current_url or self.initial_url 

        if not start_url:
            self.last_error = "Cannot scrape: No initial URL provided."
            ASCIIColors.error(self.last_error)
            return None

        if max_depth == 0:
            # --- Single Page Scraping Logic ---
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
    
    # --- YouTube Transcript Methods ---

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
        """Scrapes the transcript text from a YouTube video."""
        if not YOUTUBE_AVAILABLE:
            ASCIIColors.warning("YouTube transcript scraping requires 'youtube-transcript-api'. Please install it.")
            return None
        vtapi = YouTubeTranscriptApi()
        try:
            video_id = self._extract_youtube_id(url_or_id)
            ASCIIColors.info(f"Fetching transcript for video: {video_id}")

            if language_code:
                ASCIIColors.info(f"Attempting to fetch transcript for language: {language_code}")
                

                transcript_data = vtapi.fetch(video_id, languages=[language_code])
            else:
                ASCIIColors.info("No language specified. Searching for available transcripts (Manual > Generated)...")
                transcript_data =  vtapi.fetch(video_id)
                
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
