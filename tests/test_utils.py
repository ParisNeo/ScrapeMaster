import unittest
from bs4 import BeautifulSoup
from scrapemaster.utils import (
    clean_text, is_valid_url, check_for_blocker,
    extract_main_content_html, remove_noisy_elements,
    DEFAULT_CONTENT_SELECTORS, DEFAULT_NOISY_SELECTORS
)

class TestUtils(unittest.TestCase):

    def test_clean_text(self):
        self.assertEqual(clean_text('  Hello \n\t World  '), 'Hello World')
        self.assertEqual(clean_text('\nNew Line\n'), 'New Line')
        self.assertEqual(clean_text('No Change'), 'No Change')
        self.assertEqual(clean_text(''), '')
        self.assertEqual(clean_text(None), '') # Handle None input

    def test_is_valid_url(self):
        self.assertTrue(is_valid_url('http://example.com'))
        self.assertTrue(is_valid_url('https://example.com/path?query=1'))
        self.assertFalse(is_valid_url('ftp://example.com'))
        self.assertFalse(is_valid_url('example.com'))
        self.assertFalse(is_valid_url(''))
        self.assertFalse(is_valid_url(None))
        self.assertFalse(is_valid_url('http//example.com'))

    def test_check_for_blocker(self):
        self.assertTrue(check_for_blocker('<html>Checking your browser before accessing...</html>'))
        self.assertTrue(check_for_blocker('<html><body>Please enable JavaScript and cookies</body></html>'))
        self.assertTrue(check_for_blocker('<title>Cloudflare</title>'))
        self.assertFalse(check_for_blocker('<html><body>Regular content here</body></html>'))
        self.assertFalse(check_for_blocker(''))
        self.assertFalse(check_for_blocker(None))

    def test_extract_main_content_html(self):
        html_main = "<html><body><header>H</header><main id='main'>Main content<p>P</p></main><footer>F</footer></body></html>"
        soup_main = BeautifulSoup(html_main, 'lxml')
        content, selector = extract_main_content_html(soup_main)
        self.assertIsNotNone(content)
        self.assertEqual(content.name, 'main')
        self.assertEqual(selector, 'main')
        self.assertIn('Main content', content.text)

        html_article = "<html><body><article class='post'>Article content</article></body></html>"
        soup_article = BeautifulSoup(html_article, 'lxml')
        content, selector = extract_main_content_html(soup_article)
        self.assertIsNotNone(content)
        self.assertEqual(content.name, 'article')
        self.assertEqual(selector, 'article')

        html_body_fallback = "<html><body><div>Just a div</div></body></html>"
        soup_body = BeautifulSoup(html_body_fallback, 'lxml')
        content, selector = extract_main_content_html(soup_body)
        self.assertIsNotNone(content)
        self.assertEqual(content.name, 'body')
        self.assertEqual(selector, 'body (fallback)')

        self.assertIsNone(extract_main_content_html(None)[0])

    def test_remove_noisy_elements(self):
        html = """
        <main>
            <h1>Title</h1>
            <p>Real text.</p>
            <nav>Navigation</nav>
            <script>alert('hi');</script>
            <div class="sidebar">Sidebar</div>
            <footer>Footer</footer>
        </main>
        """
        soup = BeautifulSoup(html, 'lxml')
        main_content = soup.main
        removed_count = remove_noisy_elements(main_content)

        self.assertGreater(removed_count, 3) # nav, script, sidebar, footer
        self.assertIsNone(main_content.find('nav'))
        self.assertIsNone(main_content.find('script'))
        self.assertIsNone(main_content.find(class_='sidebar'))
        self.assertIsNone(main_content.find('footer'))
        self.assertIsNotNone(main_content.find('p'))

        self.assertEqual(remove_noisy_elements(None), 0)


if __name__ == '__main__':
    unittest.main()