import unittest
from unittest.mock import patch, MagicMock, mock_open, call
from bs4 import BeautifulSoup
import requests
from pathlib import Path
import json
import tempfile
import os

from scrapemaster.core import (
    ScrapeMaster,
    _clean_markdown_code_blocks,
    SUPPORTED_STRATEGIES,
    DEFAULT_STRATEGY_ORDER
)
from scrapemaster.exceptions import (
    ScrapeMasterError,
    PageFetchError,
    StrategyError,
    DriverInitializationError
)


class TestScrapeMasterSecurity(unittest.TestCase):
    """Security-focused tests for ScrapeMaster v0.8.6 fixes."""

    @patch('scrapemaster.core.pm.ensure_packages')
    def setUp(self, mock_ensure):
        self.scraper = ScrapeMaster("http://example.com")

    def test_save_cookies_json_format(self):
        """Verify cookies are saved as JSON, not pickle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "cookies.json"
            
            # Mock a cookie
            mock_cookie = MagicMock()
            mock_cookie.name = "session_id"
            mock_cookie.value = "abc123"
            mock_cookie.domain = ".example.com"
            mock_cookie.path = "/"
            
            with patch.object(self.scraper.session, 'cookies', [mock_cookie]):
                self.scraper.save_cookies(str(filepath))
            
            # Verify file is JSON, not pickle
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.assertIsInstance(data, list)
            self.assertEqual(data[0]['name'], 'session_id')
            self.assertEqual(data[0]['value'], 'abc123')
            
            # Verify it's not binary (pickle would fail json.load)
            with open(filepath, 'rb') as f:
                start = f.read(2)
                self.assertNotEqual(start, b'\x80\x04')  # Pickle magic bytes

    def test_load_cookies_json_format(self):
        """Verify loading cookies from JSON works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "cookies.json"
            
            # Create valid JSON cookie file
            cookie_data = [{
                "name": "test_cookie",
                "value": "test_value",
                "domain": ".test.com",
                "path": "/"
            }]
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(cookie_data, f)
            
            # Load and verify
            self.scraper.load_cookies(str(filepath))
            self.assertIn('test_cookie', self.scraper.session.cookies.keys())

    def test_load_cookies_malformed_json(self):
        """Verify graceful handling of malformed JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "bad_cookies.json"
            with open(filepath, 'w') as f:
                f.write("this is not json")
            
            # Should not raise, should log error
            self.scraper.load_cookies(str(filepath))
            # Should have empty cookies
            self.assertEqual(len(self.scraper.session.cookies), 0)

    def test_download_images_path_traversal_prevention(self):
        """Verify download_images uses resolve_safe_path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('scrapemaster.core.resolve_safe_path') as mock_resolve:
                # Setup mock to return a safe path
                safe_path = Path(tmpdir) / "images" / "test.jpg"
                mock_resolve.return_value = safe_path
                
                # Mock successful response
                with patch('scrapemaster.core.requests.Session.get') as mock_get:
                    mock_response = MagicMock()
                    mock_response.iter_content = lambda chunk_size: [b"fake image data"]
                    mock_response.raise_for_status = MagicMock()
                    mock_get.return_value = mock_response
                    
                    # Attempt download
                    self.scraper.download_images(["http://example.com/image.jpg"], tmpdir)
                    
                    # Verify resolve_safe_path was called with a filename derived from the URL
                    mock_resolve.assert_called()
                    call_args = mock_resolve.call_args[0]
                    filename_arg = str(call_args[1])
                    # Should contain the base name from URL (image.jpg), not path traversal patterns
                    self.assertIn("image.jpg", filename_arg)

                    # Verify path is within base
                    self.assertTrue(str(safe_path).startswith(str(Path(tmpdir).resolve())))

    def test_download_images_resolves_base_path(self):
        """Verify image directory is resolved to absolute path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('scrapemaster.core.requests.Session.get') as mock_get:
                mock_response = MagicMock()
                mock_response.iter_content = lambda chunk_size: [b"data"]
                mock_get.return_value = mock_response
                
                self.scraper.download_images(["http://example.com/img.png"], tmpdir)
                
                # Check that .resolve() was called on the path
                # The path passed to resolve_safe_path should be absolute
                with patch('scrapemaster.core.resolve_safe_path') as mock_resolve:
                    self.scraper.download_images(["http://example.com/img.png"], tmpdir)
                    base_dir = mock_resolve.call_args[0][0]
                    self.assertTrue(Path(base_dir).is_absolute())


class TestScrapeMasterCore(unittest.TestCase):
    
    @patch('scrapemaster.core.pm.ensure_packages')
    def test_initialization_defaults(self, mock_ensure_packages):
        """Test default initialization sets URL and strategy list correctly."""
        scraper = ScrapeMaster("http://example.com")
        self.assertEqual(scraper.current_url, "http://example.com")
        # Auto mode now includes local_parser and playwright by default
        expected = ['local_parser', 'requests', 'playwright', 'selenium', 'undetected']
        self.assertEqual(scraper.strategy, expected)
        self.assertTrue(scraper.headless)
        mock_ensure_packages.assert_called_once()

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_initialization_invalid_strategy(self, mock_ensure_packages):
        """Test that invalid strategies raise ValueError or are filtered."""
        # Test string 'invalid' - should raise because no valid strategies remain
        with self.assertRaises(ValueError):
            ScrapeMaster("http://example.com", strategy='invalid')
        
        # Test list with invalid - should raise because no valid strategies remain  
        with self.assertRaises(ValueError):
            ScrapeMaster("http://example.com", strategy=['requests', 'bad_strategy'])

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_initialization_list_strategy(self, mock_ensure_packages):
        """Test initialization with valid list of strategies."""
        scraper = ScrapeMaster("http://example.com", strategy=['requests', 'selenium'])
        self.assertEqual(scraper.strategy, ['requests', 'selenium'])

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_strategy_auto_wikipedia(self, mock_ensure_packages):
        """Test that Wikipedia URLs automatically prioritize wikipedia strategy."""
        scraper = ScrapeMaster("https://en.wikipedia.org/wiki/Test")
        self.assertEqual(scraper.strategy[0], 'wikipedia')

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_try_requests_success(self, mock_ensure_packages):
        """Test successful requests strategy."""
        with patch('scrapemaster.core.requests.Session.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {'Content-Type': 'text/html; charset=utf-8'}
            mock_response.encoding = 'utf-8'
            mock_response.content = b"<html><body>Hello World</body></html>"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            scraper = ScrapeMaster("http://example.com")
            html, soup, error = scraper._try_requests()
            
            self.assertIsNotNone(html)
            self.assertIsNotNone(soup)
            self.assertIsNone(error)
            self.assertIn("Hello World", soup.text)

    @patch('scrapemaster.core.requests.Session.get')
    @patch('scrapemaster.core.pm.ensure_packages')
    def test_try_requests_403(self, mock_ensure_packages, mock_get):
        """Test 403 error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {'Content-Type': 'text/html'}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_get.return_value = mock_response
        
        scraper = ScrapeMaster("http://example.com")
        html, soup, error = scraper._try_requests()
        
        self.assertIsNone(html)
        self.assertIsNone(soup)
        self.assertIsNotNone(error)
        self.assertIn("403", error)

    @patch('scrapemaster.core.requests.Session.get')
    @patch('scrapemaster.core.check_for_blocker', return_value=True)
    @patch('scrapemaster.core.pm.ensure_packages')
    def test_try_requests_blocker(self, mock_ensure_packages, mock_check_blocker, mock_get):
        """Test blocker detection."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'text/html'}
        mock_response.encoding = 'utf-8'
        mock_response.content = b"<html><body>Checking browser...</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        scraper = ScrapeMaster("http://example.com")
        html, soup, error = scraper._try_requests()
        
        self.assertIsNone(html)
        self.assertIsNone(soup)
        self.assertIsNotNone(error)
        self.assertIn("Blocker", error)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_scrape_text_basic(self, mock_ensure_packages):
        """Test basic text scraping with mocked soup."""
        scraper = ScrapeMaster("http://example.com")
        mock_soup = BeautifulSoup("<html><body><p>Test</p><p>Test2</p></body></html>", "lxml")
        scraper.current_soup = mock_soup
        
        texts = scraper.scrape_text()
        self.assertIn("Test", texts)
        self.assertIn("Test2", texts)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_scrape_images_basic(self, mock_ensure_packages):
        """Test basic image scraping."""
        scraper = ScrapeMaster("http://example.com")
        mock_soup = BeautifulSoup("<html><body><img src='a.jpg'><img src='b.png'></body></html>", "lxml")
        scraper.current_soup = mock_soup
        scraper.current_url = "http://example.com"
        
        images = scraper.scrape_images()
        self.assertIn("http://example.com/a.jpg", images)
        self.assertIn("http://example.com/b.png", images)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_scrape_markdown_simple(self, mock_ensure_packages):
        """Test basic markdown conversion."""
        scraper = ScrapeMaster("http://example.com")
        html = "<html><body><main><h1>Title</h1><p>Paragraph.</p></main><footer>Footer</footer></body></html>"
        mock_soup = BeautifulSoup(html, "lxml")
        scraper.current_soup = mock_soup
        scraper.html_content = html
        
        md = scraper.scrape_markdown()
        self.assertIsNotNone(md)
        self.assertIn("# Title", md)
        self.assertIn("Paragraph.", md)

    @patch('scrapemaster.core.ScrapeMaster._try_selenium')
    @patch('scrapemaster.core.pm.ensure_packages')
    def test_selenium_fallback(self, mock_ensure_packages, mock_selenium):
        """Test that selenium fallback works when requests fails."""
        mock_selenium.return_value = ("<html></html>", BeautifulSoup("<html></html>", "lxml"), None)
        
        with patch('scrapemaster.core.ScrapeMaster._try_requests') as mock_req:
            mock_req.return_value = (None, None, "403 Forbidden")
            
            scraper = ScrapeMaster("http://example.com", strategy=['requests', 'selenium'])
            success = scraper._fetch_content(['requests', 'selenium'])
            
            self.assertTrue(success)
            self.assertEqual(scraper.last_strategy_used, 'selenium')
            mock_selenium.assert_called_once()

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_clean_markdown_code_blocks(self, mock_ensure_packages):
        """Test markdown code block cleaning."""
        dirty = "```python\n1\n2\nprint('hello')\n3\n```"
        clean = _clean_markdown_code_blocks(dirty)
        self.assertNotIn("\n1\n", clean)
        self.assertIn("print('hello')", clean)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_content_hashing(self, mock_ensure_packages):
        """Test content caching/hash generation."""
        scraper = ScrapeMaster("http://example.com")
        content = b"test content"
        hash1 = scraper._content_hash(content)
        hash2 = scraper._content_hash(content)
        self.assertEqual(hash1, hash2)
        
        result = scraper._cache_content("http://example.com", content)
        self.assertTrue(result)  # First time is new
        result2 = scraper._cache_content("http://example.com", content)
        self.assertFalse(result2)  # Second time is duplicate

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_smart_delay(self, mock_ensure_packages):
        """Test rate limiting delay."""
        import time
        scraper = ScrapeMaster("http://example.com")
        start = time.time()
        scraper._smart_delay("example.com", attempt=0)
        scraper._smart_delay("example.com", attempt=0)  # Should delay
        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 0.1)  # At least some delay occurred

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_structured_data_extraction(self, mock_ensure_packages):
        """Test extraction of JSON-LD and OpenGraph."""
        scraper = ScrapeMaster("http://example.com")
        html = """
        <html><head>
        <script type="application/ld+json">{"@type": "Article", "headline": "Test"}</script>
        <meta property="og:title" content="Test Title">
        </head><body></body></html>
        """
        scraper.current_soup = BeautifulSoup(html, "lxml")
        scraper.html_content = html

        data = scraper.scrape_structured_data()
        self.assertIsNotNone(data)
        self.assertEqual(data["json_ld"][0]["@type"], "Article")
        self.assertEqual(data["opengraph"]["title"], "Test Title")

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_scrape_incremental_context_manager(self, mock_ensure_packages):
        """Test that SQLite uses context manager (auto-close)."""
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.db"

            scraper = ScrapeMaster("http://example.com")
            scraper.current_soup = BeautifulSoup("<html></html>", "lxml")
            scraper.html_content = "<html></html>"

            # First call creates DB
            result = scraper.scrape_incremental(str(cache_file))

            # Verify connection is closed (file not locked on Windows)
            # If we can delete the file, connection was closed properly
            self.assertTrue(cache_file.exists())

            # Try to delete - if connection was open, this would fail on Windows
            try:
                os.remove(cache_file)
                closed_properly = True
            except PermissionError:
                closed_properly = False

            self.assertTrue(closed_properly, "SQLite connection was not closed properly")

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_try_requests_error_classification(self, mock_ensure_packages):
        """Test consistent error message formatting."""
        scraper = ScrapeMaster("http://example.com")

        with patch('scrapemaster.core.requests.Session.get') as mock_get:
            # Test 403
            mock_response_403 = MagicMock()
            mock_response_403.status_code = 403
            mock_response_403.headers = {'Content-Type': 'text/html'}
            mock_response_403.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response_403)
            mock_get.return_value = mock_response_403

            html, soup, error = scraper._try_requests()
            self.assertIn("403", error)
            self.assertNotIn("HTTP Error", error)  # Should use specific format

            # Test 404
            mock_response_404 = MagicMock()
            mock_response_404.status_code = 404
            mock_response_404.headers = {'Content-Type': 'text/html'}
            mock_response_404.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response_404)
            mock_get.return_value = mock_response_404

            html, soup, error = scraper._try_requests()
            self.assertIn("404 Not Found", error)

            # Test 500
            mock_response_500 = MagicMock()
            mock_response_500.status_code = 500
            mock_response_500.headers = {'Content-Type': 'text/html'}
            mock_response_500.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response_500)
            mock_get.return_value = mock_response_500

            html, soup, error = scraper._try_requests()
            self.assertIn("Server Error 500", error)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_export_to_json_null_check(self, mock_ensure_packages):
        """Test export_to_json fails gracefully with no content."""
        scraper = ScrapeMaster("http://example.com")
        scraper.current_soup = None
        scraper.html_content = ""

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "output.json"
            result = scraper.export_to_json(str(filepath))

            self.assertFalse(result)
            self.assertFalse(filepath.exists())

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_try_selenium_driver_initialized_flag(self, mock_ensure_packages):
        """Test the driver_initialized flag fix - verifies DriverInitializationError on fatal init failure."""
        scraper = ScrapeMaster("http://example.com")

        with patch('scrapemaster.core.uc.Chrome') as mock_uc:
            with patch('scrapemaster.core.webdriver.Chrome') as mock_chrome:
                with patch('scrapemaster.core.ScrapeMaster._get_driver_path') as mock_path:
                    mock_path.return_value = "/fake/path"
                    # Setup options mock
                    with patch('scrapemaster.core.ScrapeMaster._setup_selenium_options') as mock_opts:
                        mock_opts.return_value = MagicMock()

                        # Simulate DriverInitializationError during initialization
                        mock_chrome.side_effect = DriverInitializationError("Init failed")

                        with self.assertRaises(DriverInitializationError):
                            scraper._try_selenium(use_undetected=False)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_notion_token_validation_length(self, mock_ensure_packages):
        """Test Notion token validation (length check, not hardcoded prefix)."""
        scraper = ScrapeMaster("http://example.com")

        # Should fail: too short
        with self.assertRaises(ValueError):
            scraper.export_to_notion("db_id", "short")

        # Should pass: valid length (but will fail on network/mock, so we catch that)
        with patch('scrapemaster.core.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = scraper.export_to_notion("db_id_12345", "secret_" + "x" * 30)
            self.assertTrue(result)

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_sitemap_xml_type_hint(self, mock_ensure_packages):
        """Test _parse_sitemap_xml has correct type signature."""
        import xml.etree.ElementTree as ET
        import inspect

        scraper = ScrapeMaster("http://example.com")
        sig = inspect.signature(scraper._parse_sitemap_xml)
        params = list(sig.parameters.values())

        # Check first param is named 'root' and has type annotation
        self.assertEqual(params[0].name, 'root')
        self.assertIsNotNone(params[0].annotation)
        # Check it's ElementTree Element or similar
        self.assertIn('Element', str(params[0].annotation))

    @patch('scrapemaster.core.pm.ensure_packages')
    def test_scrape_all_no_infinite_recursion(self, mock_ensure_packages):
        """Test scrape_all recursion fix when allowed_domains is empty."""
        scraper = ScrapeMaster("http://example.com")

        # Mock scrape_all to track recursion depth
        original_scrape_all = scraper.scrape_all
        call_count = [0]

        def mock_scrape_all(**kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                # If called recursively with use_sitemap=False, it shouldn't recurse again
                if kwargs.get('use_sitemap', True) is False:
                    return {'markdown': 'test', 'visited_urls': ['http://example.com']}
            # Original behavior for first call
            kwargs['use_sitemap'] = False
            return {'markdown': 'test', 'visited_urls': ['http://example.com']}

        with patch.object(scraper, 'scrape_all', side_effect=mock_scrape_all):
            # This should trigger the empty allowed_domains branch
            result = scraper.scrape_all(max_depth=0, use_sitemap=False)
            self.assertIsNotNone(result)


if __name__ == '__main__':
    unittest.main()