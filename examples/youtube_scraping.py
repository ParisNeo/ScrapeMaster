import sys
import os

# --- Import the ScrapeMaster Library (Local import for development) ---
# This ensures we use the local version of the library instead of an installed one
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scrapemaster import ScrapeMaster

def main():
    # Initialize ScrapeMaster
    # Note: YouTube scraping relies on the API wrapper, so browser strategies are not used here,
    # but the class is still the entry point.
    scraper = ScrapeMaster()

    # YouTube Video URL (Example: "Me at the zoo" - the first ever YouTube video)
    video_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    
    print(f"--- ScrapeMaster YouTube Example ---")
    print(f"Target Video: {video_url}\n")

    # ---------------------------------------------------------
    # 1. Check Available Languages
    # ---------------------------------------------------------
    print("[1] Fetching available transcript languages...")
    languages = scraper.get_youtube_languages(video_url)
    
    if languages:
        print(f"Found {len(languages)} available transcript(s):")
        for lang in languages:
            type_str = "Generated" if lang['is_generated'] else "Manual"
            print(f" - Code: {lang['code']:<5} | Name: {lang['name']:<15} | Type: {type_str}")
    else:
        print("No transcripts found or error occurred.")
        return

    # ---------------------------------------------------------
    # 2. Fetch Transcript (Auto-Detect)
    # ---------------------------------------------------------
    print("\n[2] Fetching transcript (Auto-detect mode)...")
    # This automatically prefers manually created transcripts over auto-generated ones
    transcript_text = scraper.scrape_youtube_transcript(video_url)
    
    if transcript_text:
        print(f"Success! Retrieved {len(transcript_text)} characters.")
        print("-" * 40)
        print(f"Preview:\n{transcript_text[:300]}...")
        print("-" * 40)
    else:
        print("Failed to retrieve transcript.")

    # ---------------------------------------------------------
    # 3. Fetch Transcript (Specific Language)
    # ---------------------------------------------------------
    # Example: If the video has 'es' (Spanish), try to fetch that specifically.
    # For this demo, we'll just pick the last one from the list we found earlier.
    if languages:
        target_lang = languages[-1]['code'] 
        print(f"\n[3] Attempting to fetch specific language: '{target_lang}'...")
        
        specific_transcript = scraper.scrape_youtube_transcript(video_url, language_code=target_lang)
        
        if specific_transcript:
            print(f"Success! Retrieved {len(specific_transcript)} characters for '{target_lang}'.")
        else:
            print(f"Could not retrieve transcript for '{target_lang}'.")

if __name__ == "__main__":
    main()
