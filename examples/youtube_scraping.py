"""
YouTube Scraping Example - Demonstrates video metadata and transcript extraction
Inspired by the clean transcript pattern in the original library.
"""
import sys
import os

# Add parent directory to path for local development
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scrapemaster import ScrapeMaster

def main():
    # Initialize
    scraper = ScrapeMaster()
    
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Never Gonna Give You Up (test video)
    
    print(f"--- ScrapeMaster Video Extraction Demo ---")
    print(f"Target: {video_url}\n")
    
    # 1. Unified Video Interface (Auto-detects YouTube)
    print("[1] Extracting video data (transcript + metadata)...")
    video_data = scraper.scrape_video(video_url, extract_type='auto')
    
    if not video_data:
        print("Failed to detect video platform.")
        return
        
    print(f"✓ Platform: {video_data['source']}")
    print(f"✓ Video ID: {video_data['video_id']}")
    
    if video_data.get('transcript'):
        print(f"✓ Transcript: {len(video_data['transcript'])} characters")
        print(f"  Preview: {video_data['transcript'][:150]}...")
    else:
        print("✗ No transcript available")
        
    if video_data.get('metadata'):
        meta = video_data['metadata']
        print(f"✓ Title: {meta.get('title', 'Unknown')}")
        if meta.get('views'):
            print(f"✓ Views: {meta['views']}")

    # 2. Media Links Extraction (Thumbnail, etc.)
    print("\n[2] Extracting media links from page...")
    media = scraper.scrape_media_links(['image'])
    if media['images']:
        print(f"✓ Found {len(media['images'])} images (including thumbnails)")

    # 3. Podcast Feed Example
    print("\n[3] Podcast Feed Detection...")
    # Example with a test podcast feed
    podcast_url = "https://api.substack.com/feed/podcast/10845.rss"  # Example RSS
    feed = scraper.scrape_podcast_feed(podcast_url)
    if feed and feed['episodes']:
        print(f"✓ Podcast: {feed['title']}")
        print(f"✓ Latest episode: {feed['episodes'][0]['title']}")
    else:
        print("✗ Could not fetch podcast feed (this is normal if feed is private)")

    # 4. News Article Extraction (Author, Date, Reading Time)
    print("\n[4] News Article Extraction...")
    article_url = "https://www.theverge.com/2024/1/1/sample-article"  # Replace with real URL
    try:
        article = scraper.scrape_article()
        if article:
            print(f"✓ Title: {article['title']}")
            print(f"✓ Author: {article.get('author', 'Unknown')}")
            print(f"✓ Reading Time: {article.get('reading_time_min')} min")
    except:
        print("✗ Article extraction test skipped (needs valid news URL)")

    print("\n--- Demo Complete ---")

if __name__ == "__main__":
    main()