# ScrapeMaster

ScrapeMaster is a comprehensive Python library for web scraping that handles both simple and complex websites, offering features like text and image extraction, session management, and anti-bot circumvention techniques.

## Features

- Scrape text and images from websites
- Handle JavaScript-rendered content using Selenium
- Manage cookies and sessions for authenticated scraping
- Rotate user agents and use proxies to avoid detection
- Clean and format extracted data

## Installation

You can install ScrapeMaster using pip:

```
pip install ScrapeMaster
```

## Quick Start

Here's a simple example of how to use ScrapeMaster:

```python
from scrapemaster import ScrapeMaster

scraper = ScrapeMaster('https://example.com')
results = scraper.scrape_all('p', 'img', 'output_images')
print(results['texts'])
print(results['image_urls'])
```

## Advanced Usage

For more advanced usage, including handling of JavaScript-rendered content and authenticated scraping, please refer to the documentation.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.