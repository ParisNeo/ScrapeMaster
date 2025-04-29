import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import pytest  # Using pytest markers if desired

from scrapemaster import ScrapeMaster
from scrapemaster.exceptions import PageFetchError, StrategyError, BlockerDetectedError

# NOTE: These tests are illustrative and need significant expansion
#       to cover the new strategies, error handling, and edge cases.
#       Mocking Selenium and UC effectively is complex.

# Mock the pipmaster call if needed during testing
@patch('scrapemaster.core.pm.ensure_packages', return_value=None)
class TestScrapeMasterCore(unittest.TestCase):

    def test_initialization_defaults(self, mock_ensure_packages):
        scraper = ScrapeMaster("http://example.com")
        self.assertEqual(scraper.current_url, "http://example.com")
        self.assertEqual(scraper.strategy, ['requests', 'selenium', 'undetected'])
        self.assertTrue(scraper.headless)
        self.assertIsNone(scraper.last_error)

    def test_initialization_custom_strategy(self, mock_ensure_packages):
        scraper = ScrapeMaster("http://example.com", strategy=['requests', 'undetected'], headless=False)
        self.assertEqual(scraper.strategy, ['requests', 'undetected'])
        self.assertFalse(scraper.headless)

    def test_initialization_invalid_strategy(self, mock_ensure_packages):
        with self.assertRaises(ValueError):
            ScrapeMaster("http://example.com", strategy='invalid')
        with self.assertRaises(ValueError):
            ScrapeMaster("http://example.com", strategy=['requests', 'bad_strategy'])

    def test_set_url(self, mock_ensure_packages):
        scraper = ScrapeMaster()
        scraper.set_url("https://new-example.com")
        self.assertEqual(scraper.current_url, "https://new-example.com")
        with self.assertRaises(ValueError):
             scraper.set_url("invalid-url")

    # --- Testing Fetching Strategies (Requires extensive mocking) ---

    @patch('scrapemaster.core.requests.Session.get')
    def test_try_requests_success(self, mock_get, mock_ensure_packages):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'text/html'}
        mock_response.encoding = 'utf-8'
        mock_response.content = b"<html><body><p>Success</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        scraper = ScrapeMaster("http://example.com")
        html, soup, error = scraper._try_requests()

        self.assertIsNotNone(html)
        self.assertIsNotNone(soup)
        self.assertIsNone(error)
        self.assertIn("Success", soup.body.p.text)
        mock_get.assert_called_once()

    @patch('scrapemaster.core.requests.Session.get')
    def test_try_requests_403(self, mock_get, mock_ensure_packages):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {'Content-Type': 'text/html'}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        scraper = ScrapeMaster("http://example.com")
        html, soup, error = scraper._try_requests()

        self.assertIsNone(html)
        self.assertIsNone(soup)
        self.assertEqual(error, "Requests: 403 Forbidden")

    @patch('scrapemaster.core.requests.Session.get')
    @patch('scrapemaster.utils.check_for_blocker', return_value=True) # Mock blocker detection
    def test_try_requests_blocker(self, mock_check_blocker, mock_get, mock_ensure_packages):
        # Similar setup as success case, but check_for_blocker returns True
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
        self.assertEqual(error, "Blocker page detected")
        mock_check_blocker.assert_called_once()

    # Need similar complex tests for _try_selenium (standard and UC)
    # Mocking webdriver.Chrome, uc.Chrome, WebDriverWait, element interactions etc.
    # Example (very simplified structure):
    @patch('scrapemaster.core.webdriver.Chrome')
    @patch('scrapemaster.core.ChromeDriverManager')
    @patch('scrapemaster.core.WebDriverWait')
    def test_try_selenium_success_mocked(self, MockWait, MockDriverManager, MockChrome, mock_ensure_packages):
         # Setup mocks for driver, wait, elements, page_source...
         mock_driver_instance = MockChrome.return_value
         mock_driver_instance.page_source = "<html><body><p>Selenium Content</p></body></html>"
         MockDriverManager.return_value.install.return_value = "/fake/path/chromedriver"
         # ... setup MockWait to return elements ...

         scraper = ScrapeMaster("http://example.com", strategy=['selenium'])
         success = scraper._fetch_content(scraper.strategy)

         self.assertTrue(success)
         self.assertIsNotNone(scraper.current_soup)
         self.assertIn("Selenium Content", scraper.current_soup.text)
         self.assertEqual(scraper.last_strategy_used, 'selenium')
         # Assert driver.get, wait.until etc. were called
         mock_driver_instance.quit.assert_called_once() # Check cleanup

    # --- Testing Scraping Methods ---

    def test_scrape_text_no_fetch(self, mock_ensure_packages):
        scraper = ScrapeMaster("http://example.com")
        # Mock _fetch_content to return False
        with patch.object(scraper, '_fetch_content', return_value=False) as mock_fetch:
            texts = scraper.scrape_text()
            self.assertEqual(texts, [])
            mock_fetch.assert_called_once()

    def test_scrape_markdown_simple(self, mock_ensure_packages):
         scraper = ScrapeMaster("http://example.com")
         # Mock the fetch to provide simple soup directly
         mock_soup = BeautifulSoup("<html><body><main><h1>Title</h1><p>Paragraph.</p></main><footer>Footer</footer></body></html>", "lxml")
         with patch.object(scraper, '_fetch_content', return_value=True):
              scraper.current_soup = mock_soup # Inject soup after mocked fetch
              markdown = scraper.scrape_markdown()
              self.assertIsNotNone(markdown)
              self.assertIn("# Title", markdown)
              self.assertIn("Paragraph.", markdown)
              self.assertNotIn("Footer", markdown) # Check noise removal


# Add more tests for scrape_images, scrape_all, download_images, login, cookies, scrape_website etc.

if __name__ == '__main__':
    unittest.main()