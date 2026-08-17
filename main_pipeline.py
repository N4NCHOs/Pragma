import json
from rss_scrape_scheduler import run_scheduler
from database import SessionLocal
from ai_models.filters import is_top_10_news
from ai_models.novelty_detection import process_incoming_news

def run_pipeline():
    print("\n==========================================")
    print("Step 1: Running Scraper...")
    print("==========================================\n")
    scrape_stats = run_scheduler()
    
    print("\n[Scraper Summary]")
    print(f" -> RSS Items Fetched:  {scrape_stats.get('rss_items')}")
    print(f" -> New Items Found:    {scrape_stats.get('new_items')}")
    print(f" -> Successfully Scraped: {scrape_stats.get('scrape_success')}")
    print(f" -> Failed to Scrape:   {scrape_stats.get('scrape_failed')}\n")
    
    # 2. Open the JSON created by the RSS scraper
    try:
        with open("output/scraped_news.json", "r", encoding="utf-8") as f:
            news_batch = json.load(f)
    except FileNotFoundError:
        print("scraped_news.json not found! Scraper may have failed.")
        return
        
    db = SessionLocal()
    
    try:
        print("\n==========================================")
        print("Step 2: Processing Pipeline...")
        print("==========================================")
        
        total = len(news_batch)
        print(f"Found {total} articles to process.\n")
        
        # 3. Process each article
        for i, article in enumerate(news_batch, 1):
            # Skip failed scrapes from the scraper script
            if article.get("scrape_status") != "success":
                continue
                
            print(f"[{i}/{total}] {article.get('title')}")
            
            # 4. Use the imported filter function
            if not is_top_10_news(article):
                print(" -> [DROPPED] Not a Top 10 asset\n")
                continue
                
            # 5. Use the imported novelty function
            saved_article = process_incoming_news(article, db)
            print(f" -> [PROCESSED] Saved to DB with ID: {saved_article.id}\n")
    finally:
        db.close()

if __name__ == "__main__":
    run_pipeline()