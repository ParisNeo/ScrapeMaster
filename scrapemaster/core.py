"""
ScrapeMaster Core Module: Provides the main ScrapeMaster class for web scraping.
"""
import time
import random
import pickle
import json
import re
from pathlib import Path
from urllib.parse import urljoin

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
        "ascii_colors",

    ]) # Added verbose=True for clarity on startup
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
    uc = None # Define uc as None if not available
    UNDETECTED_AVAILABLE = False

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
SUPPORTED_STRATEGIES = ["requests", "selenium", "undetected"]
DEFAULT_STRATEGY_ORDER = ["requests", "selenium", "undetected"]

def _clean_markdown_code_blocks(markdown_text: str) -> str:
    """Uses regex to remove lines containing only numbers within Markdown code blocks."""
    if not markdown_text or "```" not in markdown_text:
        return markdown_text # No code blocks found or empty text

    cleaned_lines = []
    in_code_block = False
    # Pattern to match a line containing optional whitespace, one or more digits, optional dot, and optional whitespace
    line_number_pattern = re.compile(r"^\s*\d+\.?\s*$")

    for line in markdown_text.splitlines():
        # Toggle code block state
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            cleaned_lines.append(line) # Keep the fence itself
            continue

        # If inside a code block, check if the line is just a line number
        if in_code_block:
            if line_number_pattern.match(line):
                # Skip this line (it's likely a line number)
                ASCIIColors.debug(f"Skipping likely line number in code block: '{line.strip()}'")
                continue
            else:
                # Keep the actual code line
                cleaned_lines.append(line)
        else:
            # Outside a code block, keep the line as is
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

        # --- Attempt Code Block Line Number Cleaning (Optional - Keep or Remove based on testing) ---
        # Keeping the previous HTML-based cleaning might still be useful for some sites,
        # but the Markdown post-processing is likely more reliable for this specific case.
        # You can comment out this block if the post-processing works well.
        code_blocks_cleaned_count = 0
        pre_tags = main_content_element.find_all('pre')
        if pre_tags:
            ASCIIColors.debug(f"Found {len(pre_tags)} <pre> tags. Attempting HTML line number removal...")
            # ... (Keep the HTML cleaning code from the previous attempt if desired) ...
            # Example: Remove common classes
            line_number_classes = ['.lineno', '.line-number', '.line-numbers', '.gutter', '.line-numbers-rows']
            for pre_tag in pre_tags:
                for ln_class in line_number_classes:
                    try:
                        elements_to_remove = pre_tag.select(ln_class)
                        for el in elements_to_remove: el.decompose(); code_blocks_cleaned_count += 1
                    except Exception: pass
            if code_blocks_cleaned_count > 0:
                ASCIIColors.debug(f"Removed {code_blocks_cleaned_count} potential HTML line number elements.")
        # --- End Optional HTML Code Block Cleaning ---

        # Check for blocker message
        cleaned_text_sample = main_content_element.get_text(strip=True)[:500].lower()
        if check_for_blocker(cleaned_text_sample):
             ASCIIColors.warning("Content container holds blocker message after cleaning.")
             return None, f"Blocker identified within '{used_selector}' after cleaning."

        # --- Markdown Conversion ---
        ASCIIColors.info("Converting cleaned HTML to Markdown...")
        html_string = str(main_content_element)
        markdown_text = md(html_string, heading_style="ATX", escape_underscores=False, default_title=True)

        # --- Post-processing ---
        # 1. Basic whitespace cleanup
        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text).strip()
        # 2. NEW: Clean line numbers from code blocks
        markdown_text = _clean_markdown_code_blocks(markdown_text)
        # --- End Post-processing ---

        ASCIIColors.success("Markdown conversion and cleaning complete.")
        return markdown_text, None # Success

    except Exception as e:
        import traceback
        error_msg = f"Error during parsing/markdownify: {e}"
        ASCIIColors.error(error_msg)
        ASCIIColors.error(traceback.format_exc())
        raise ParsingError(error_msg) from e

class ScrapeMaster:
    """
    A versatile web scraping class using multiple strategies (requests, Selenium, undetected-chromedriver)
    for fetching and extracting web content, including Markdown conversion.
    """
    def __init__(self, url: str | None = None, strategy: list[str] | str = 'auto', headless: bool = True):
        """
        Initializes the ScrapeMaster.

        Args:
            url (str, optional): The initial URL to target. Can be set later via `set_url`. Defaults to None.
            strategy (list[str] | str): The scraping strategy or list of strategies to use.
                - 'auto': Use the default order ['requests', 'selenium', 'undetected'].
                - list[str]: A list containing 'requests', 'selenium', and/or 'undetected' in the desired order.
                Defaults to 'auto'.
            headless (bool): Whether to run Selenium/undetected-chromedriver in headless mode. Defaults to True.
                                Note: Setting to False might be required for some sites but will show browser windows.
        """
        self._validate_url(url)
        self.initial_url = url
        self.current_url = url
        self.strategy = self._resolve_strategy(strategy)
        self.headless = headless

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.driver = None # Stores the active Selenium/UC driver instance
        self.current_soup = None # Stores the BeautifulSoup object from the last successful fetch
        self.html_content = "" # Stores the raw HTML from the last successful fetch
        self.last_error = None # Stores the last significant error message
        self.last_strategy_used = None # Stores the strategy that succeeded

        self.user_agents = list(DEFAULT_HEADERS.values()) # Simplified user agent list for now

        print(f"ScrapeMaster initialized. Strategy: {self.strategy}, Headless: {self.headless}")
        if 'undetected' in self.strategy and not UNDETECTED_AVAILABLE:
            ASCIIColors.warning("Specified 'undetected' strategy, but undetected-chromedriver library is not available.")

    def _validate_url(self, url: str | None):
        """Validates the provided URL."""
        if url is not None and not is_valid_url(url):
            raise ValueError(f"Invalid initial URL provided: {url}")

    def _resolve_strategy(self, strategy: list[str] | str) -> list[str]:
        """Resolves the strategy argument into a validated list."""
        if strategy == 'auto':
            return DEFAULT_STRATEGY_ORDER
        if isinstance(strategy, str):
            strategy = [strategy] # Allow single string strategy
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
        """Sets or updates the target URL."""
        self._validate_url(url)
        self.current_url = url
        self.current_soup = None # Reset soup when URL changes
        self.html_content = ""
        self.last_error = None
        ASCIIColors.info(f"Target URL set to: {url}")

    def get_last_error(self) -> str | None:
        """Returns the last recorded error message."""
        return self.last_error

    def _get_driver_path(self) -> str | None:
        """Gets the ChromeDriver path using webdriver-manager."""
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
        """Configures Chrome options for Selenium/UC."""
        options = webdriver.ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        else:
            ASCIIColors.info("*** RUNNING IN NON-HEADLESS (VISIBLE BROWSER) MODE ***")

        options.add_argument("--disable-gpu"); options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage"); options.add_argument(f"user-agent={self.session.headers['User-Agent']}")
        options.add_argument("window-size=1920,1080"); options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--log-level=3") # Suppress console logs

        if not for_undetected:
            # Apply options potentially conflicting with UC only for standard Selenium
            options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
            options.add_experimental_option('useAutomationExtension', False)
            prefs = {"profile.default_content_setting_values.cookies": 1, "profile.default_content_setting_values.javascript": 1}
            options.add_experimental_option("prefs", prefs)
        return options

    def _quit_driver(self):
        """Safely quits the Selenium driver if it exists."""
        if self.driver:
            try:
                self.driver.quit()
                ASCIIColors.debug("WebDriver instance quit.")
            except Exception as e:
                ASCIIColors.warning(f"Error quitting WebDriver: {e}")
            finally:
                self.driver = None

    def __del__(self):
        """Ensures the driver is quit when the object is garbage collected."""
        self._quit_driver()

    # --- Strategy Implementations ---

    def _try_requests(self) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts fetching with the requests library."""
        ASCIIColors.info("-- Strategy: Trying simple HTTP request (requests) --")
        if not self.current_url: return None, None, "No URL set"
        try:
            self.set_random_user_agent() # Rotate user agent
            response = self.session.get(self.current_url, timeout=25)
            ASCIIColors.debug(f"Requests Status Code: {response.status_code}")

            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                return None, None, f"Non-HTML content type received: {content_type}"

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            html_content = response.content.decode(response.encoding or 'utf-8', errors='ignore')

            if check_for_blocker(html_content):
                ASCIIColors.warning("Requests: Blocker page detected.")
                return None, None, "Blocker page detected" # Signal blocker

            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Requests: Fetch and parse successful.")
            return html_content, soup, None # Success

        except requests.exceptions.RequestException as e:
            error_msg = f"Requests Error: {e}"
            ASCIIColors.error(error_msg)
            # Return specific error types for better handling later
            if hasattr(e, 'response') and e.response is not None:
                 if e.response.status_code == 403:
                     return None, None, "Requests: 403 Forbidden" # Signal blocker/permission issue
                 else:
                     return None, None, f"Requests: HTTP Error {e.response.status_code}"
            else: # Network error, timeout etc.
                raise PageFetchError(error_msg) from e # Raise definitive fetch error
        except Exception as e:
            error_msg = f"Requests: Unexpected error: {e}"
            ASCIIColors.error(error_msg)
            raise ScrapeMasterError(error_msg) from e # Raise general error

    def _run_selenium_attempt(self, driver: webdriver.Chrome | uc.Chrome) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Core logic shared by Selenium and UC strategies."""
        if not self.current_url: return None, None, "No URL set"
        try:
            driver.set_page_load_timeout(45)
            # Use small implicit wait mainly for initial element presence checks
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

            # Optional: Add specific element wait if needed, but often waiting for body
            #           and then checking for blockers is sufficient for UC.
            # Example: wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, DEFAULT_CONTENT_SELECTORS[0])))

            time.sleep(2) # Short pause for JS rendering after load signal

            ASCIIColors.info("Retrieving page source...")
            html_content = driver.page_source
            if not html_content:
                raise StrategyError("Selenium retrieved empty page source.")

            if check_for_blocker(html_content):
                ASCIIColors.warning("Selenium/UC: Blocker page detected after wait.")
                return None, None, "Blocker page detected" # Signal blocker

            ASCIIColors.info("Parsing HTML with BeautifulSoup...")
            soup = BeautifulSoup(html_content, 'lxml')
            ASCIIColors.success("Selenium/UC: Fetch and parse successful.")
            return html_content, soup, None # Success

        except TimeoutException:
            error_msg = f"Selenium/UC: Timed out waiting for page elements ({wait_time}s)."
            ASCIIColors.error(error_msg)
            # Check if we got a blocker page even on timeout
            try:
                html_on_timeout = driver.page_source
                if check_for_blocker(html_on_timeout):
                    return None, None, "Blocker page detected (on timeout)"
            except Exception: pass # Ignore errors checking source on timeout
            return None, None, error_msg # Return timeout error
        except WebDriverException as e:
            error_msg = f"Selenium/UC: WebDriver Error: {e.msg[:500]}" # Limit error message length
            ASCIIColors.error(error_msg)
            # Don't raise here, return error message to allow main loop to handle/retry
            return None, None, error_msg
        except Exception as e:
            error_msg = f"Selenium/UC: Unexpected error during run: {e}"
            ASCIIColors.error(error_msg)
            raise StrategyError(error_msg) from e # Raise strategy error

    def _try_selenium(self, use_undetected: bool) -> tuple[str | None, BeautifulSoup | None, str | None]:
        """Attempts fetching with Selenium or undetected-chromedriver."""
        driver_type = "undetected-chromedriver" if use_undetected else "standard Selenium"
        ASCIIColors.info(f"-- Strategy: Trying {driver_type} --")

        if use_undetected and not UNDETECTED_AVAILABLE:
            return None, None, "undetected-chromedriver library not available"

        driver_path = self._get_driver_path()
        if not driver_path and not use_undetected: # Standard selenium needs the path found by manager
             raise DriverInitializationError(self.last_error or "Could not get driver path.")
        elif not driver_path and use_undetected:
             ASCIIColors.warning("Could not get driver path via manager, UC will try auto-detection.")
             # UC might still work if chromedriver is in PATH or its cache

        options = self._setup_selenium_options(for_undetected=use_undetected)
        self._quit_driver() # Ensure no previous driver is running

        try:
            ASCIIColors.info(f"Initializing {driver_type}...")
            start_time = time.time()
            if use_undetected:
                self.driver = uc.Chrome(
                    driver_executable_path=driver_path if driver_path else None, # Allow UC to auto-detect if manager failed
                    options=options,
                    version_main=119, # Optional: Specify major Chrome version if needed
                    headless=self.headless,
                    use_subprocess=True # Often helps with stability/evasion
                )
            else:
                service = ChromeService(executable_path=driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)

            init_time = time.time() - start_time
            ASCIIColors.debug(f"{driver_type} initialized in {init_time:.2f}s.")

            # Run the core fetching logic
            return self._run_selenium_attempt(self.driver)

        except WebDriverException as e:
            error_msg = f"{driver_type} Initialization/Run Error: {e.msg[:500]}"
            ASCIIColors.error(error_msg)
            self._quit_driver() # Clean up failed driver
            # Raise specific error if init failed, return message if run failed
            if "initialized" not in locals(): # Check if error happened during init
                 raise DriverInitializationError(error_msg) from e
            else:
                 return None, None, error_msg
        except Exception as e:
            error_msg = f"{driver_type}: Unexpected error: {e}"
            ASCIIColors.error(error_msg)
            self._quit_driver() # Clean up
            raise StrategyError(error_msg) from e # Raise strategy error

    # --- Core Fetching Orchestration ---

    def _fetch_content(self, strategy_list: list[str]) -> bool:
        """
        Orchestrates fetching content using the specified strategies.
        Updates self.html_content and self.current_soup on success.
        Returns True on success, False on failure after trying all strategies.
        """
        if not self.current_url:
            self.last_error = "Cannot fetch: URL not set."
            ASCIIColors.error(self.last_error)
            return False

        ASCIIColors.info(f"--- Starting fetch for: {self.current_url} ---")
        ASCIIColors.info(f"Using strategies: {strategy_list}")

        self.current_soup = None
        self.html_content = ""
        self.last_error = "No strategies succeeded." # Default error
        self.last_strategy_used = None

        for strategy_name in strategy_list:
            html = None
            soup = None
            error_msg = None # Specific outcome message for this strategy attempt

            try:
                if strategy_name == "requests":
                    html, soup, error_msg = self._try_requests()
                elif strategy_name == "selenium":
                    html, soup, error_msg = self._try_selenium(use_undetected=False)
                elif strategy_name == "undetected":
                    if UNDETECTED_AVAILABLE:
                        html, soup, error_msg = self._try_selenium(use_undetected=True)
                    else:
                        error_msg = "skipped (library unavailable)"
                        ASCIIColors.warning("-- Strategy: Skipping undetected-chromedriver (unavailable) --")
                        continue # Skip to next strategy
                else:
                    # Should not happen if _resolve_strategy worked
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
                    self._quit_driver() # Quit driver after successful fetch
                    return True
                elif error_msg:
                    # Strategy attempted but failed or was blocked
                    self.last_error = f"{strategy_name.capitalize()}: {error_msg}"
                    ASCIIColors.warning(f"Strategy '{strategy_name}' failed: {error_msg}")
                    if "Blocker page detected" in error_msg or "403 Forbidden" in error_msg:
                        # Blocker detected, continue to next strategy
                        continue
                    else:
                        # Other potentially definitive error from this strategy
                        # Decide whether to stop or continue (for now, continue)
                         pass
                else:
                     # Should not happen - indicates logic error in strategy function
                     self.last_error = f"{strategy_name.capitalize()}: Strategy returned unexpected empty result."
                     ASCIIColors.error(self.last_error)


            except (DriverInitializationError, PageFetchError, StrategyError, ScrapeMasterError) as e:
                # Catch definitive errors raised by strategies
                self.last_error = f"{strategy_name.capitalize()} Error: {e}"
                ASCIIColors.critical(f"--- Definitive error during '{strategy_name}' strategy: {e} ---")
                # Stop processing further strategies if a critical error occurred (like driver init failure)
                if isinstance(e, DriverInitializationError):
                    return False
                # For other errors, we might choose to continue or stop. Let's continue for now.
            except Exception as e:
                # Catch any other unexpected exceptions
                self.last_error = f"{strategy_name.capitalize()} Unexpected Error: {e}"
                ASCIIColors.critical(f"--- Unexpected critical error during '{strategy_name}' strategy: {e} ---")
                import traceback
                ASCIIColors.error(traceback.format_exc())
                return False # Stop on truly unexpected errors

        # If loop finishes without success
        ASCIIColors.error(f"--- Fetch failed after trying all strategies. Last status: {self.last_error} ---")
        self._quit_driver() # Ensure driver is quit even if all strategies failed
        return False

    # --- Public Scraping Methods ---

    def scrape_text(self, selectors: list[str] | None = None, fetch_strategy: list[str] | str | None = None) -> list[str]:
        """
        Scrapes text fragments from the page using specified selectors after fetching content.

        Args:
            selectors (list[str] | None): List of CSS selectors for text elements.
                                          Defaults to DEFAULT_TEXT_SELECTORS.
            fetch_strategy (list[str] | str | None): Override the instance's strategy for this call.
                                                    Defaults to None (use instance strategy).

        Returns:
            list[str]: A list of cleaned text fragments found. Returns empty list on fetch failure.
        """
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        if not self.current_soup: # Fetch only if needed
             if not self._fetch_content(strategy_to_use):
                 return [] # Fetch failed

        if not self.current_soup: # Check again after fetch attempt
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
        """
        Scrapes image URLs from the page using specified selectors after fetching content.

        Args:
            selectors (list[str] | None): List of CSS selectors for image elements.
                                          Defaults to DEFAULT_IMAGE_SELECTORS.
            fetch_strategy (list[str] | str | None): Override the instance's strategy for this call.
                                                    Defaults to None (use instance strategy).

        Returns:
            list[str]: A list of absolute image URLs found. Returns empty list on fetch failure.
        """
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
                             if is_valid_url(abs_url): # Basic check if it looks like a valid image URL
                                 image_urls.append(abs_url)
            ASCIIColors.debug(f"Scraped {len(image_urls)} image URLs using selectors: {selectors}")
        except Exception as e:
            raise ParsingError(f"Error during image scraping with selectors {selectors}: {e}") from e

        return image_urls

    def scrape_markdown(self,
                        content_selectors: list[str] | None = None,
                        noisy_selectors: list[str] | None = None,
                        fetch_strategy: list[str] | str | None = None) -> str | None:
        """
        Fetches content, identifies the main content area, cleans it (incl. line numbers),
        and converts to Markdown.
        """
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
            self.html_content, # Pass the fetched html
            content_selectors=content_selectors,
            noisy_selectors=noisy_selectors
            # Note: _parse_and_markdownify now uses the soup generated from html_content
        )

        if error:
            self.last_error = f"Markdown Conversion Failed: {error}"
            # Don't raise here, return None as per function signature
            return None

        return markdown_text


    def scrape_all(self,
                   max_depth: int = 0, # NEW: Maximum crawl depth
                   crawl_delay: float = 0.5, # NEW: Delay between pages when crawling
                   allowed_domains: list[str] | None = None, # NEW: Domains to restrict crawl
                   text_selectors: list[str] | None = None,
                   image_selectors: list[str] | None = None,
                   content_selectors: list[str] | None = None, # For markdown
                   noisy_selectors: list[str] | None = None,   # For markdown
                   convert_to_markdown: bool = False,         # Control markdown generation
                   download_images_output_dir: str | None = None,
                   fetch_strategy: list[str] | str | None = None
                   ) -> dict | None:
        """
        Performs a comprehensive scrape, potentially crawling linked pages up to max_depth.
        Fetches content, extracts text fragments, extracts image URLs,
        optionally converts main content to Markdown, and optionally downloads images.
        When crawling (max_depth > 0), results are aggregated.

        Args:
            max_depth (int): Max depth to follow links (0 = only initial URL). Defaults to 0.
            crawl_delay (float): Seconds to wait between page fetches when crawling. Defaults to 0.5.
            allowed_domains (list[str] | None): Restrict crawling to these domains. If None,
                                               stays on the initial URL's domain. Defaults to None.
            text_selectors (list[str] | None): Selectors for text fragments. Defaults to library defaults.
            image_selectors (list[str] | None): Selectors for image elements. Defaults to library defaults.
            content_selectors (list[str] | None): Selectors for main content (for Markdown). Defaults to library defaults.
            noisy_selectors (list[str] | None): Selectors for noise removal (for Markdown). Defaults to library defaults.
            convert_to_markdown (bool): If True, attempt to convert main content area to Markdown. Defaults to False.
            download_images_output_dir (str | None): Directory to save downloaded images. If None, images are not downloaded.
                                                    Note: When crawling, images from all pages are saved here.
            fetch_strategy (list[str] | str | None): Override the instance's strategy for this call. Defaults to None.

        Returns:
            dict | None: A dictionary containing aggregated results:
                         'markdown': Combined Markdown string (or None).
                         'texts': List of all text fragments from all pages.
                         'image_urls': List of all unique image URLs from all pages.
                         'visited_urls': List of successfully scraped URLs.
                         'failed_urls': List of URLs that failed to scrape during crawl.
                         Returns None if the initial fetch operation fails.
        """
        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        start_url = self.current_url or self.initial_url # Use current if set, else initial

        if not start_url:
            self.last_error = "Cannot scrape: No initial URL provided."
            ASCIIColors.error(self.last_error)
            return None

        if max_depth == 0:
            # --- Single Page Scraping Logic ---
            ASCIIColors.info(f"Performing single-page scrape for: {start_url}")
            if not self._fetch_content(strategy_to_use):
                 ASCIIColors.error("scrape_all failed: Could not fetch content for the single page.")
                 return None # Fetch failed

            results = {
                'markdown': None, 'texts': [], 'image_urls': [],
                'visited_urls': [start_url], 'failed_urls': []
            }
            try:
                results['texts'] = self.scrape_text(selectors=text_selectors, fetch_strategy=None) # Use already fetched
            except ParsingError as e: ASCIIColors.warning(f"Error scraping text: {e}")
            try:
                results['image_urls'] = self.scrape_images(selectors=image_selectors, fetch_strategy=None) # Use already fetched
            except ParsingError as e: ASCIIColors.warning(f"Error scraping images: {e}")
            if convert_to_markdown:
                try:
                    results['markdown'] = self.scrape_markdown(content_selectors, noisy_selectors, fetch_strategy=None) # Use already fetched
                except ParsingError as e: ASCIIColors.warning(f"Error converting to markdown: {e}")

            if download_images_output_dir and results['image_urls']:
                self.download_images(results['image_urls'], download_images_output_dir)
            return results

        else:
            # --- Multi-Page Crawling Logic ---
            output_path = Path(download_images_output_dir) if download_images_output_dir else None
            if output_path: # Create output dir if specified for images
                 output_path.mkdir(parents=True, exist_ok=True)

            visited = set()
            queue = [(start_url, 0)] # Queue of (url, depth)
            aggregated_markdown = []
            aggregated_texts = []
            aggregated_image_urls = set() # Use set for uniqueness
            successfully_visited = []
            failed_urls = []

            # Determine allowed domains
            if allowed_domains is None:
                try:
                    initial_domain = urlparse(start_url).netloc
                    allowed_domains = [initial_domain] if initial_domain else []
                except Exception:
                     allowed_domains = [] # Cannot determine domain, don't crawl widely
            if not allowed_domains:
                 ASCIIColors.warning("Could not determine allowed domain. Restricting crawl to max_depth=0.")
                 return self.scrape_all(max_depth=0, # Call single-page logic
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

                # Check domain permission
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

                # --- Scrape individual page ---
                self.set_url(current_url) # Update scraper's current URL
                page_markdown = None
                page_texts = []
                page_image_urls = []
                fetch_success = self._fetch_content(strategy_to_use) # Fetch the content for this page

                if fetch_success and self.current_soup:
                    successfully_visited.append(current_url)
                    # Extract content from this page
                    try:
                         page_texts = self.scrape_text(selectors=text_selectors, fetch_strategy=None)
                         aggregated_texts.extend(page_texts)
                    except ParsingError as e: ASCIIColors.warning(f"Error scraping text on {current_url}: {e}")
                    try:
                         page_image_urls = self.scrape_images(selectors=image_selectors, fetch_strategy=None)
                         aggregated_image_urls.update(page_image_urls) # Add unique urls
                    except ParsingError as e: ASCIIColors.warning(f"Error scraping images on {current_url}: {e}")
                    if convert_to_markdown:
                        try:
                            page_markdown = self.scrape_markdown(content_selectors, noisy_selectors, fetch_strategy=None)
                            if page_markdown:
                                 # Add URL separator/header for combined markdown
                                 aggregated_markdown.append(f"\n\n## Scraped Content from: {current_url}\n\n---\n\n{page_markdown}")
                        except ParsingError as e: ASCIIColors.warning(f"Error converting to markdown on {current_url}: {e}")

                    # Find and queue new links if depth allows
                    if current_depth < max_depth:
                        links = self.current_soup.select('a[href]')
                        for link in links:
                            href = link.get('href')
                            if isinstance(href, str) and href.strip():
                                try:
                                    next_url = urljoin(current_url, href.strip())
                                    # Basic check to avoid mailto, javascript, etc. and fragments
                                    parsed_next = urlparse(next_url)
                                    if parsed_next.scheme in ['http', 'https'] and parsed_next.fragment == '':
                                        if next_url not in visited:
                                            queue.append((next_url, current_depth + 1))
                                except Exception:
                                     pass # Ignore invalid URLs formed by urljoin
                else:
                     # Fetch failed for this page
                     ASCIIColors.error(f"Failed to scrape page {current_url}. Error: {self.get_last_error()}")
                     failed_urls.append(current_url)

                # Respect crawl delay
                if queue: # Only delay if there are more pages to crawl
                    ASCIIColors.debug(f"Waiting {crawl_delay}s before next fetch...")
                    time.sleep(crawl_delay)
            # --- End Crawl Loop ---

            self._quit_driver() # Ensure driver is closed after crawl

            ASCIIColors.success(f"Website crawl finished. Visited {len(visited)} pages ({len(successfully_visited)} scraped successfully).")

            # Download all collected images if requested
            if download_images_output_dir and aggregated_image_urls:
                 self.download_images(list(aggregated_image_urls), download_images_output_dir)

            return {
                'markdown': "\n".join(aggregated_markdown).strip() if convert_to_markdown else None,
                'texts': aggregated_texts,
                'image_urls': sorted(list(aggregated_image_urls)), # Return sorted list
                'visited_urls': successfully_visited,
                'failed_urls': failed_urls
            }

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
            # Need to decide: should this initialize the driver? For now, no.
            ASCIIColors.warning("Cannot load Selenium cookies: Driver not active. Fetch page first.")
            return
        try:
            with open(filename, 'r') as f:
                cookies = json.load(f)
            for cookie in cookies:
                # Handle potential cookie compatibility issues if necessary
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e_add:
                    ASCIIColors.warning(f"Could not add cookie {cookie.get('name', 'N/A')}: {e_add}")
            ASCIIColors.info(f"Selenium cookies loaded from {filename}")
            self.driver.refresh() # Refresh page to apply cookies
        except FileNotFoundError:
            ASCIIColors.warning(f"Selenium cookie file not found: {filename}")
        except Exception as e:
            ASCIIColors.error(f"Failed to load Selenium cookies: {e}")


    def download_images(self, image_urls: list[str], output_dir: str):
        """
        Downloads images from the provided URLs to the specified directory.

        Args:
            image_urls (list[str]): A list of absolute image URLs to download.
            output_dir (str): The directory to save downloaded images. Images will be saved in `output_dir/images`.
        """
        if not image_urls:
            return

        images_dir = Path(output_dir) / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        ASCIIColors.info(f"Downloading {len(image_urls)} images to {images_dir}...")
        downloaded_count = 0

        for i, url in enumerate(image_urls):
            try:
                # Generate filename from URL path, sanitize it
                parsed_path = Path(urlparse(url).path)
                filename_base = parsed_path.stem
                filename_ext = parsed_path.suffix or '.jpg' # Default extension if none
                # Basic sanitization
                safe_filename_base = re.sub(r'[^\w\-]+', '_', filename_base)
                filename = f"{safe_filename_base[:50]}_{i}{filename_ext}" # Add index for uniqueness, limit length
                filepath = images_dir / filename

                # Use the existing session for downloading
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

        ASCIIColors.info(f"Finished downloading. {downloaded_count}/{len(image_urls)} images saved.")


    # --- Kept original methods for potential compatibility/specific use ---
    # Note: These now have potential redundancy with scrape_all/scrape_text/etc.
    # Consider deprecating or clearly documenting their limited scope (requests only).

    def fetch_page(self):
        """
        DEPRECATED (use scrape_... methods with strategy=['requests']).
        Fetches the page using only the requests library.
        """
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
        """
        DEPRECATED (use scrape_... methods with strategy=['selenium']).
        Fetches the page using only standard Selenium.
        """
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

    # --- Login methods remain similar, maybe add strategy hints ---

    def login(self, login_url, username, password, username_field='username', password_field='password'):
        """Logs into a website using the requests session. Best for simple form logins."""
        ASCIIColors.info(f"Attempting requests-based login to {login_url}")
        data = {username_field: username, password_field: password}
        try:
            response = self.session.post(login_url, data=data)
            response.raise_for_status()
            ASCIIColors.success("Requests-based login likely successful (check cookies/subsequent requests).")
            # self.save_cookies() # Optionally save cookies after login
        except requests.exceptions.RequestException as e:
            raise PageFetchError(f"Requests login failed: {e}") from e

    def login_with_selenium(self, login_url, username, password, username_selector, password_selector, submit_selector, wait_after_login=5):
        """Logs into a website using Selenium. Better for JS-heavy login forms."""
        ASCIIColors.info(f"Attempting Selenium-based login to {login_url}")
        if not self.driver:
            # Initialize standard driver if not already active
            ASCIIColors.warning("Initializing standard Selenium driver for login.")
            options = self._setup_selenium_options(for_undetected=False)
            driver_path = self._get_driver_path()
            if not driver_path: raise DriverInitializationError("Cannot login with Selenium: driver path not found.")
            service = ChromeService(executable_path=driver_path)
            self.driver = webdriver.Chrome(service=service, options=options)

        try:
            self.driver.get(login_url)
            wait = WebDriverWait(self.driver, 15) # Increased wait time

            user_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, username_selector)))
            pass_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, password_selector)))
            submit_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_selector)))

            user_field.clear(); user_field.send_keys(username)
            pass_field.clear(); pass_field.send_keys(password)
            submit_button.click()

            ASCIIColors.info(f"Login submitted. Waiting {wait_after_login}s for redirection/page load...")
            # Instead of url_changes, wait for a known element on the logged-in page or just pause
            time.sleep(wait_after_login)
            # Example: Wait for a logout button or user profile element
            # try:
            #     wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '#logout-button')))
            #     ASCIIColors.success("Selenium login likely successful (found logout button).")
            # except TimeoutException:
            #     ASCIIColors.warning("Selenium login submitted, but confirmation element not found.")

            # self.save_selenium_cookies() # Optionally save cookies

        except (WebDriverException, TimeoutException) as e:
            raise StrategyError(f"Selenium login failed: {e}") from e
        except Exception as e:
             raise ScrapeMasterError(f"Unexpected error during Selenium login: {e}") from e


    # --- Recursive Scraping ---
    # Updated to use the new fetch mechanism

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
        """
        Recursively scrapes a website starting from a URL, following links up to a max depth.

        Args:
            start_url (str | None): The URL to start scraping from. Defaults to instance URL.
            max_depth (int): Maximum depth of links to follow (0 = start_url only). Defaults to 1.
            output_dir (str): Directory to save scraped content.
            file_prefix (str): Prefix for saved files (e.g., 'page_').
            crawl_delay (float): Seconds to wait between page fetches. Defaults to 0.5.
            allowed_domains (list[str] | None): Optional list of domains to restrict crawling to.
                                               If None, only stays on the start_url's domain.
            fetch_strategy (list[str] | str | None): Strategy for fetching pages. Defaults to instance default.
            convert_to_markdown (bool): Save main content as Markdown. Defaults to True.
            save_images (bool): Download images for each page. Defaults to False.
        """
        start_url = start_url or self.initial_url
        if not start_url or not is_valid_url(start_url):
            raise ValueError("Invalid start URL for website scraping.")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        visited = set()
        queue = [(start_url, 0)] # Queue of (url, depth)

        if allowed_domains is None:
            allowed_domains = [urlparse(start_url).netloc]

        strategy_to_use = self._resolve_strategy(fetch_strategy) if fetch_strategy else self.strategy
        page_count = 0

        ASCIIColors.info(f"Starting website crawl from {start_url}, max_depth={max_depth}, allowed_domains={allowed_domains}")

        while queue:
            current_url, current_depth = queue.pop(0)

            if current_url in visited or current_depth > max_depth:
                continue

            # Check domain permission
            current_domain = urlparse(current_url).netloc
            if current_domain not in allowed_domains:
                ASCIIColors.debug(f"Skipping external domain: {current_url}")
                continue

            visited.add(current_url)
            page_count += 1
            ASCIIColors.info(f"Crawling [Depth:{current_depth}, Page:{page_count}]: {current_url}")

            self.set_url(current_url) # Update scraper's current URL

            results = self.scrape_all(
                fetch_strategy=strategy_to_use,
                convert_to_markdown=convert_to_markdown,
                download_images_output_dir=output_path if save_images else None
            )

            if results:
                # Save content
                page_filename_base = f"{file_prefix}{page_count}_{current_domain}_{Path(urlparse(current_url).path).name or 'index'}"
                page_filename_base = re.sub(r'[^\w\-]+', '_', page_filename_base)[:100] # Sanitize

                if convert_to_markdown and results.get('markdown'):
                    filepath = output_path / f"{page_filename_base}.md"
                    try:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(f"# Scraped Content from: {current_url}\n\n")
                            f.write(results['markdown'])
                        ASCIIColors.debug(f"Saved Markdown to {filepath}")
                    except IOError as e:
                        ASCIIColors.error(f"Failed to save Markdown for {current_url}: {e}")
                elif results.get('texts'): # Fallback to saving raw texts if no markdown
                    filepath = output_path / f"{page_filename_base}.txt"
                    try:
                         with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(f"Scraped Text Fragments from: {current_url}\n\n")
                            f.write('\n---\n'.join(results['texts']))
                         ASCIIColors.debug(f"Saved Text to {filepath}")
                    except IOError as e:
                        ASCIIColors.error(f"Failed to save text for {current_url}: {e}")

                # Find and queue new links if depth allows
                if current_depth < max_depth and self.current_soup:
                    links = self.current_soup.select('a[href]')
                    for link in links:
                        href = link['href']
                        if isinstance(href, str) and href.strip():
                            next_url = urljoin(current_url, href)
                            # Basic check to avoid mailto, javascript, etc. and fragments
                            if is_valid_url(next_url) and urlparse(next_url).fragment == '':
                                if next_url not in visited:
                                    queue.append((next_url, current_depth + 1))
            else:
                 ASCIIColors.error(f"Failed to scrape page {current_url}. Error: {self.get_last_error()}")

            # Respect crawl delay
            if queue: # Only delay if there are more pages to crawl
                ASCIIColors.debug(f"Waiting {crawl_delay}s before next fetch...")
                time.sleep(crawl_delay)

        ASCIIColors.success(f"Website crawl finished. Visited {len(visited)} pages.")
        self._quit_driver() # Ensure driver is closed after crawl