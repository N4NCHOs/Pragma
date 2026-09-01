import json
from rss_scrape_scheduler import run_scheduler
from database import SessionLocal
from ai_models.filters import is_top_10_news
from ai_models.novelty_detection import process_incoming_news
from ai_models.crypto_ner import extract_and_link_entities
from ai_models.flan_t5 import flan_service
from ai_models.deberta_classifier import deberta_service

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
            print(f"[{i}/{total}] {article.get('title')}")
            
            # If the scraper failed (e.g. Rate Limit), it will naturally fall back 
            # to the RSS summary below.
            
            # 4. Use the imported filter function
            if not is_top_10_news(article):
                print(" -> [DROPPED] Not a Top 10 asset\n")
                continue
                
            # 5. AI Novelty Detection
            uncommitted_article = process_incoming_news(article, db)
            
            # 6. AI Inference (Only for Unique Articles)
            if uncommitted_article.is_redundant == False:
                title = article.get("title", "")
                body = article.get("full_body") or article.get("rss_summary") or article.get("description") or ""
                full_text = f"{title}. {body}"
                
                # Run NLP Models
                extracted_entities = extract_and_link_entities(full_text)
                summary_result = flan_service.summarize_with_metrics(full_text)
                classification_result = deberta_service.classify(full_text)

                # Aggregate all AI results into memory
                uncommitted_article.extracted_assets = extracted_entities
                uncommitted_article.summary = summary_result.summary
                uncommitted_article.category = classification_result.category
                uncommitted_article.impact = classification_result.impact
                uncommitted_article.sentiment = classification_result.sentiment
                uncommitted_article.target_investor = classification_result.target_investor

                if extracted_entities:
                    found_texts = [e['matched_text'] for e in extracted_entities]
                    print(f" -> Found Entities: {found_texts}\n")
                else:
                    print(f" -> Found Entities: None")

                print(f" -> FLAN-T5 Summary: {summary_result.summary}")
                print(
                    " -> FLAN-T5 Metrics: "
                    f"{summary_result.inference_seconds:.3f}s, "
                    f"{summary_result.input_token_count} input tokens, "
                    f"{summary_result.output_token_count} output tokens, "
                    f"truncated={summary_result.input_was_truncated}\n"
                )

                print(
                    " -> DeBERTa Classification: "
                    f"category={classification_result.category} "
                    f"({classification_result.category_confidence}), "
                    f"impact={classification_result.impact} "
                    f"({classification_result.impact_confidence}), "
                    f"sentiment={classification_result.sentiment} "
                    f"({classification_result.sentiment_confidence})"
                )
                print(f" -> DeBERTa Target Investor: {classification_result.target_investor}")
                print(
                    " -> DeBERTa Metrics: "
                    f"{classification_result.inference_seconds:.3f}s\n"
                )

            # 7. Final Save to Database
            db.add(uncommitted_article)
            db.commit()
            db.refresh(uncommitted_article) 
            
            if uncommitted_article.is_redundant == True:
                print(f" -> [PROCESSED] Saved to DB with ID: {uncommitted_article.id} (Redundant)\n")
            else:
                print(f" -> [PROCESSED] Saved to DB with ID: {uncommitted_article.id} (Unique)\n")
    finally:
        db.close()

if __name__ == "__main__":
    run_pipeline()
