import unittest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
import requests

from scrapemaster.core import ScrapeMaster, _clean_markdown_code_blocks, SUPPORTED_STRATEGIES, DEFAULT_STRATEGY_ORDER
from scrapemaster.exceptions import ScrapeMasterError, PageFetchError, StrategyError

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

if __name__ == '__main__':
    unittest.main()