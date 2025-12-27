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

**ScrapeMaster** is a comprehensive Python library that simplifies the complexities of web scraping. It intelligently switches between multiple scraping strategies—from simple `requests` to browser automation with `Selenium` and `undetected-chromedriver`—to ensure you get the data you need, when you need it.

Whether you're extracting text, downloading images, converting articles to clean Markdown, crawling entire websites, or even fetching YouTube transcripts, ScrapeMaster provides a unified and powerful API to handle it all.

## ✨ Key Features

-   **Multi-Strategy Scraping**: Automatically tries different methods (`requests`, `Selenium`, `undetected-chromedriver`) to bypass anti-bot measures and handle JavaScript-rendered content.
-   **Content-to-Markdown**: Intelligently extracts the main content from a webpage, removes noise (like headers, footers, ads), and converts it into clean, readable Markdown.
-   **YouTube Transcripts**: Built-in support for fetching video transcripts (manual or auto-generated) via the `youtube-transcript-api`.
-   **Comprehensive Data Extraction**: Easily scrape text, images, and other structured data using CSS selectors.
-   **Website Crawler**: Recursively scrape an entire website by following links up to a specified depth, with domain restrictions to keep the crawl focused.
-   **Anti-Bot Circumvention**: Utilizes `undetected-chromedriver` and rotates user agents to appear more like a human user and avoid common blockers.
-   **Session & Cookie Management**: Persist sessions across requests by saving and loading cookies for both `requests` and `Selenium`.
-   **Image Downloader**: A built-in utility to download all scraped images to a local directory.
-   **Robust Error Handling**: Gracefully manages failures, providing clear feedback on which strategies failed and why.

## 📦 Installation

You can install ScrapeMaster directly from PyPI:

```bash
pip install ScrapeMaster
```

The library uses `pipmaster` to automatically manage and install its dependencies (like `requests`, `selenium`, `youtube-transcript-api`, etc.) upon first use, ensuring a smooth setup process.

## Usage Examples

### 1. Simple Text and Image Scraping

Fetch a static page and extract all paragraph texts and image URLs.

```python
from scrapemaster import ScrapeMaster

# Initialize with the target URL
scraper = ScrapeMaster('https://example.com')

# Scrape text from <p> tags and image URLs from <img> tags
results = scraper.scrape_all(
    text_selectors=['p'],
    image_selectors=['img']
)

if results:
    print("--- Texts ---")
    for text in results['texts']:
        print(f"- {text}")
        
    print("\n--- Image URLs ---")
    for url in results['image_urls']:
        print(f"- {url}")
```

### 2. Scraping a JavaScript-Rendered Page

ScrapeMaster will automatically switch to a browser-based strategy if `requests` fails or is blocked.

```python
from scrapemaster import ScrapeMaster

# This URL likely requires JavaScript to load its content
url = "https://quotes.toscrape.com/js/"
scraper = ScrapeMaster(url)

# The 'auto' strategy will try requests, then selenium, then undetected
# to ensure content is loaded.
results = scraper.scrape_all(text_selectors=['.text', '.author'])

if results:
    for text in results['texts']:
        print(text)

print(f"\nSuccessfully used strategy: {scraper.last_strategy_used}")
```

### 3. Converting an Article to Clean Markdown

Extract the main content of a blog post or documentation page and save it as Markdown.

```python
from scrapemaster import ScrapeMaster

url = "https://www.scrapethissite.com/pages/simple/"
scraper = ScrapeMaster(url)

# This method focuses on finding the main content and cleaning it
markdown_content = scraper.scrape_markdown()

if markdown_content:
    print(markdown_content)
    # You can save this to a file
    # with open('article.md', 'w', encoding='utf-8') as f:
    #     f.write(markdown_content)
```

### 4. Crawling a Website and Downloading Images

Crawl the first two levels of a website, aggregate all text, and download all found images.

```python
from scrapemaster import ScrapeMaster

url = "https://blog.scrapinghub.com/"
scraper = ScrapeMaster(url)

# Crawl up to 1 level deep (start page + links on it)
# and download all images to 'scraped_images' directory.
results = scraper.scrape_all(
    max_depth=1,
    crawl_delay=1,  # 1-second delay between page requests
    download_images_output_dir='scraped_images'
)

if results:
    print(f"Successfully visited {len(results['visited_urls'])} pages.")
    print(f"Found {len(results['texts'])} text fragments.")
    print(f"Found and downloaded {len(results['image_urls'])} unique images.")
```

### 5. Scraping YouTube Transcripts

Retrieve transcripts from YouTube videos. You can list available languages and fetch the transcript text (preferring manually created ones over auto-generated).

```python
from scrapemaster import ScrapeMaster

scraper = ScrapeMaster()
video_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

# 1. List available languages
languages = scraper.get_youtube_languages(video_url)
if languages:
    print("Available Languages:")
    for lang in languages:
        print(f"- {lang['code']}: {lang['name']} ({'Generated' if lang['is_generated'] else 'Manual'})")

# 2. Fetch the transcript (Auto-detects best available, or pass language_code='en')
transcript = scraper.scrape_youtube_transcript(video_url)

if transcript:
    print("\n--- Transcript Preview ---")
    print(transcript[:500] + "...") 
```

## Core Concepts

ScrapeMaster's power comes from its layered, fallback-driven approach. When you request data, it follows a strategy order (default is `['requests', 'selenium', 'undetected']`):

1.  **Requests**: The fastest method. It makes a simple HTTP GET request. If it receives a successful HTML response and doesn't detect a blocker, it succeeds.
2.  **Selenium**: If `requests` fails (e.g., due to a 403 error or a blocker page), ScrapeMaster launches a standard Selenium-controlled Chrome browser to render the page, executing JavaScript.
3.  **Undetected-Chromedriver**: If standard Selenium is also blocked, it escalates to `undetected-chromedriver`, which is patched to be much harder for services like Cloudflare to detect.

This "auto" mode ensures the highest chance of success with optimal performance. You can also force a specific strategy if you know what the target site requires.

## 🤝 Contributing

Contributions are welcome! If you have ideas for new features, bug fixes, or improvements, please feel free to:

1.  Open an issue to discuss the change.
2.  Fork the repository and create a new branch.
3.  Submit a pull request with a clear description of your changes.

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 👤 Author

**ScrapeMaster** is developed and maintained by **ParisNeo**.

-   **GitHub**: [@ParisNeo](https://github.com/ParisNeo)