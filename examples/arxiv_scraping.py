"""
Example: Scraping an ArXiv PDF (even without .pdf extension) using Docling integration.
"""
import sys
import os

# Add parent directory to path to import scrapemaster
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scrapemaster import ScrapeMaster

def scrape_arxiv_paper():
    # URL provided by user: contains /pdf/ but no .pdf extension
    url = "https://arxiv.org/pdf/2109.09572"
    
    print(f"Initializing ScrapeMaster for: {url}")
    # Initialize with auto strategy
    # The updated logic in core.py will detect 'arxiv.org' and '/pdf/' and enforce 'docling'
    scraper = ScrapeMaster(url, strategy='auto')

    print("Attempting to scrape and convert PDF to Markdown...")
    markdown_content = scraper.scrape_markdown()

    if markdown_content:
        print("\n" + "="*50)
        print("SUCCESSFULLY SCRAPED ARXIV PAPER")
        print("="*50)
        
        # Print the first 2000 characters as a preview
        print(markdown_content[:2000])
        print("\n" + "="*50)
        print("... (Content truncated for preview) ...")
        
        # Save to file
        output_filename = "arxiv_paper.md"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print(f"\nFull content saved to: {output_filename}")
        
    else:
        print("\nScraping failed.")
        print(f"Error: {scraper.get_last_error()}")

if __name__ == "__main__":
    scrape_arxiv_paper()
