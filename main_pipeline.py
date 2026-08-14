import json
from rss_scrape_scheduler import run_scheduler
from database import SessionLocal
from ai_models.filters import is_top_10_news
from ai_models.novelty_detection import process_incoming_news

def run_pipeline():
    # 1. Run the RSS Scraper to get the latest batch of news
    print("==========================================")
    print("Step 1: Running Scraper...")
    print("==========================================")
    scrape_stats = run_scheduler()
    print(f"Scrape Complete: {scrape_stats}\n")
    
    # 2. Open the JSON created by the RSS scraper
    try:
        with open("scraped_news.json", "r", encoding="utf-8") as f:
            news_batch = json.load(f)
    except FileNotFoundError:
        print("scraped_news.json not found! Scraper may have failed.")
        return
        
    db = SessionLocal()
    
    try:
        print("==========================================")
        print("Step 2: Processing Pipeline...")
        print("==========================================")
        # 3. Process each article
        for article in news_batch:
            # Skip failed scrapes from the scraper script
            if article.get("scrape_status") != "success":
                continue
                
            # 4. Use the imported filter function
            if not is_top_10_news(article):
                print(f"[DROPPED] Not a Top 10 asset: {article.get('title')}")
                continue
                
            # 5. Use the imported novelty function
            saved_article = process_incoming_news(article, db)
            print(f"[PROCESSED] Saved ID {saved_article.id}: {saved_article.title}")
            
    finally:
        db.close()

if __name__ == "__main__":
    run_pipeline()