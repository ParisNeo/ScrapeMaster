<div align="center">
  <br>
  <h1>ScrapeMaster</h1>
  <p>
    <strong>A powerful and versatile Python library for web scraping, designed to handle everything from simple static pages to complex, JavaScript-heavy websites with advanced anti-bot measures.</strong>
  </p>
  <br>
</div>

<div align="center">
  <!-- PyPI Version -->
  <a href="https://pypi.org/project/scrapemaster/">
    <img src="https://img.shields.io/pypi/v/scrapemaster.svg" alt="PyPI Version">
  </a>
  <!-- Python Versions -->
  <a href="https://pypi.org/project/scrapemaster/">
    <img src="https://img.shields.io/pypi/pyversions/scrapemaster.svg" alt="Python Versions">
  </a>
  <!-- License -->
  <a href="https://github.com/ParisNeo/ScrapeMaster/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/ParisNeo/ScrapeMaster" alt="License">
  </a>
  <!-- Build Status -->
  <a href="https://github.com/ParisNeo/ScrapeMaster/actions/workflows/python-package.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/ParisNeo/ScrapeMaster/python-package.yml?branch=main" alt="Build Status">
  </a>
  <!-- Downloads -->
  <a href="https://pypi.org/project/scrapemaster/">
    <img src="https://img.shields.io/pypi/dm/scrapemaster.svg" alt="Downloads">
  </a>
</div>

---

## 🚀 Overview

**ScrapeMaster** is a comprehensive Python library that simplifies the complexities of web scraping. It intelligently switches between multiple scraping strategies—from simple `requests` to browser automation with `Selenium`, `Playwright`, and `undetected-chromedriver`—to ensure you get the data you need, when you need it.

Whether you're extracting text, downloading images, converting articles to clean Markdown, crawling entire websites, fetching YouTube transcripts, or parsing structured data from JSON-LD, ScrapeMaster provides a unified and powerful API to handle it all.

## ✨ Key Features

-   **Multi-Strategy Scraping**: Automatically tries `requests`, `Playwright`, `Selenium`, or `undetected-chromedriver` to bypass anti-bot measures. Now supports `curl_cffi` for TLS fingerprint spoofing.
-   **Async Bulk Operations**: Use `scrape_many()` for high-performance concurrent scraping with `aiohttp`, complete with auto-rate limiting and content deduplication.
-   **Sitemap-Based Discovery**: Automatically discover and crawl URLs from `sitemap.xml` (including sitemap indexes) for faster, more focused harvesting.
-   **Structured Data Extraction**: Native support for JSON-LD, Microdata, and OpenGraph metadata extraction.
-   **Smart Content Pipeline**: Post-processors allow custom transformations on Markdown output. Content deduplication prevents re-processing identical pages.
-   **Advanced Evasion**: Undetected Chromedriver, Playwright stealth, and TLS fingerprint impersonation via `curl_cffi`.
-   **Rate Limiting with Jitter**: Exponential backoff prevents IP bans; per-domain tracking ensures polite scraping.
-   **Export Pipelines**: Direct export to JSON, Notion databases, and Obsidian vaults. Screenshot capture for visual debugging.
-   **Content Intelligence**: MD5 hashing for deduplication, incremental scraping with SQLite caching, and infinite scroll handling for SPAs.
-   **Network Interception**: Capture XHR/API calls using Playwright's network events.
-   **Plugin System**: Register custom scraping strategies via `register_strategy()`.

## 📦 Installation

```bash
pip install ScrapeMaster
```

For full functionality (Playwright, async, TLS spoofing), install optional dependencies:

```bash
pip install Playwright aiohttp curl_cffi xmltodict
playwright install chromium  # Required for Playwright strategy
```

The library uses `pipmaster` to automatically manage core dependencies upon first use.

## Usage Examples

### 1. Simple Scraping with Auto-Strategy

```python
from scrapemaster import ScrapeMaster

scraper = ScrapeMaster('https://example.com')
markdown = scraper.scrape_markdown()
print(markdown)
```

### 2. Async Bulk Scraping (10x Faster)

```python
import asyncio
from scrapemaster import ScrapeMaster

urls = [
    "https://blog.example.com/post1",
    "https://blog.example.com/post2",
    "https://blog.example.com/post3",
]

scraper = ScrapeMaster()

# Async batch scraping with auto rate limiting
results = await scraper.scrape_many_async(
    urls, 
    max_concurrent=5, 
    extract_markdown=True
)

for result in results:
    if "markdown" in result:
        print(f"Scraped {result['url']}: {len(result['markdown'])} chars")
    else:
        print(f"Failed {result['url']}: {result.get('error')}")
```

### 3. Sitemap-Based Discovery

```python
scraper = ScrapeMaster("https://example.com")

# Automatically discover all URLs from sitemap.xml
results = scraper.scrape_all(
    use_sitemap=True,
    url_pattern=r"/blog/\d{4}/",  # Only blog posts
    sitemap_limit=50,
    convert_to_markdown=True
)

print(f"Scraped {len(results['urls'])} pages from sitemap")
```

### 4. Structured Data Extraction (JSON-LD, Microdata)

```python
scraper = ScrapeMaster("https://shopping.example.com/product/123")
structured = scraper.scrape_structured_data()

if structured and structured["json_ld"]:
    product = structured["json_ld"][0]
    print(f"Product: {product.get('name')}, Price: {product.get('offers', {}).get('price')}")
```

### 5. Incremental Scraping (Skip Unchanged Pages)

```python
scraper = ScrapeMaster()

# First run: scrapes everything
results = scraper.scrape_incremental(cache_file="crawl_cache.db")
print(f"Updated: {len(results['updated'])}, Skipped: {len(results['skipped'])}")

# Second run: skips pages with same content hash
```

### 6. Export to External Tools

```python
# Obsidian vault export
scraper = ScrapeMaster("https://docs.python.org/3/")
scraper.export_to_obsidian(vault_path="./docs_vault", filename="python_docs.md")

# Notion database export (requires integration token)
scraper.export_to_notion(
    database_id="abc123", 
    token="secret_xxxxx"
)

# JSON export with metadata
scraper.export_to_json("output.json", include_metadata=True)
```

### 7. Plugin System (Custom Strategies)

```python
from scrapemaster import ScrapeMaster
from bs4 import BeautifulSoup

def custom_api_strategy(scraper_instance, url):
    """Custom strategy for JSON APIs"""
    import requests
    r = requests.get(url + "/api/data")
    soup = BeautifulSoup(f"<pre>{r.text}</pre>", "lxml")
    return r.text, soup, None

# Register and use
ScrapeMaster.register_strategy("api_endpoint", custom_api_strategy)

scraper = ScrapeMaster("https://api.example.com", strategy=["api_endpoint"])
results = scraper.scrape_markdown()
```

### 8. Advanced Anti-Bot Evasion

```python
# Force Playwright for maximum stealth (modern alternative to Selenium)
scraper = ScrapeMaster(
    "https://protected-site.com", 
    strategy=["playwright"], 
    headless=True
)
markdown = scraper.scrape_markdown()

# Or use curl_cffi for TLS fingerprint spoofing (bypasses basic fingerprinting)
scraper = ScrapeMaster(
    "https://protected-site.com", 
    strategy=["curl_cffi"]
)
```

### 9. Screenshot Capture

```python
scraper = ScrapeMaster("https://example.com", strategy=["selenium"])
scraper.scrape_markdown()  # Initializes driver
scraper.save_screenshot("debug.png", full_page=True)
```

### 10. Infinite Scroll / Infinite Pagination

```python
scraper = ScrapeMaster("https://twitter.com/some_thread", strategy=["playwright"])
# Automatically scrolls and captures dynamic content
content = scraper.scrape_infinite_scroll(scroll_pause=2, max_scrolls=20)
```

## Core Concepts

ScrapeMaster's power comes from its layered, fallback-driven approach. When you request data, it follows a strategy order:

1.  **Wikipedia**: Native API for Wikipedia URLs (fastest, most reliable).
2.  **Local Parser**: PDF/DOCX direct download and extraction.
3.  **Requests**: Fast HTTP for static pages.
4.  **Playwright**: Modern browser automation (recommended for SPAs).
5.  **Selenium**: Legacy browser automation.
6.  **Undetected**: Patched Chrome for Cloudflare/WAF bypass.
7.  **Custom**: Your registered plugins.

This "auto" mode ensures the highest chance of success with optimal performance. You can also force a specific strategy if you know what the target site requires.

## Security Best Practices

- **URL Validation**: All inputs are validated; `javascript:` and `data:` URLs are rejected.
- **Path Sanitization**: `export_to_obsidian` and `save_screenshot` sanitize filenames to prevent directory traversal.
- **No Hardcoded Credentials**: Notion integration requires explicit token passing.
- **Rate Limiting**: Built-in exponential backoff prevents aggressive scraping of single domains.

## 🤝 Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests with clear descriptions.

## 📜 License

Apache-2.0. See [LICENSE](LICENSE) for details.

## 👤 Author

**ParisNeo** - [GitHub](https://github.com/ParisNeo)