import unittest
from ScrapeMaster.utils import clean_text

class TestUtils(unittest.TestCase):

    def test_clean_text(self):
        self.assertEqual(clean_text('  Hello   World  '), 'Hello World')
        self.assertEqual(clean_text('\nNew Line\n'), 'New Line')

if __name__ == '__main__':
    unittest.main()
