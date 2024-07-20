import unittest
from scrapemaster.core import ScrapeMaster
from unittest.mock import patch, MagicMock

class TestScrapeMaster(unittest.TestCase):

    @patch('ScrapeMaster.core.requests.Session')
    def setUp(self, MockSession):
        self.mock_session = MockSession.return_value
        self.scraper = ScrapeMaster('https://example.com')

    @patch('ScrapeMaster.core.BeautifulSoup')
    def test_fetch_page(self, MockBeautifulSoup):
        self.mock_session.get.return_value.content = b'<html></html>'
        self.scraper.fetch_page()
        self.mock_session.get.assert_called_once_with('https://example.com')
        MockBeautifulSoup.assert_called_once()

    @patch('ScrapeMaster.core.webdriver.Chrome')
    def test_fetch_page_with_js(self, MockWebDriver):
        mock_driver = MockWebDriver.return_value
        mock_driver.page_source = '<html><body></body></html>'  # Set a valid HTML string
        self.scraper.fetch_page_with_js()
        mock_driver.get.assert_called_once_with('https://example.com')

    def test_scrape_text(self):
        self.scraper.soup = MagicMock()
        self.scraper.soup.select.return_value = [MagicMock(get_text=lambda: 'Test Text')]
        result = self.scraper.scrape_text('p')
        self.assertEqual(result, ['Test Text'])


if __name__ == '__main__':
    unittest.main()
