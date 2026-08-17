from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline

print("Loading AutoTokenizer and AutoModelForTokenClassification...")
tokenizer = AutoTokenizer.from_pretrained("covalenthq/cryptoNER")
model = AutoModelForTokenClassification.from_pretrained("covalenthq/cryptoNER")

ner_pipeline = pipeline(
    "token-classification", 
    model=model, 
    tokenizer=tokenizer, 
    aggregation_strategy="simple"
)

# ==========================================
# Complete Dictionary-based Entity Linking
# ==========================================
# Based on Top 10 Market Cap as of May 17, 2026
ASSET_DICTIONARY = {
    # 1. Bitcoin
    "BITCOIN": "asset_btc",
    "BTC": "asset_btc",
    
    # 2. Ethereum
    "ETHEREUM": "asset_eth",
    "ETH": "asset_eth",
    
    # 3. Tether
    "TETHER": "asset_usdt",
    "USDT": "asset_usdt",
    
    # 4. BNB
    "BNB": "asset_bnb",
    "BINANCE COIN": "asset_bnb",
    
    # 5. XRP
    "XRP": "asset_xrp",
    "RIPPLE": "asset_xrp",
    
    # 6. USDC
    "USD COIN": "asset_usdc",
    "USDC": "asset_usdc",
    
    # 7. Solana
    "SOLANA": "asset_sol",
    "SOL": "asset_sol",
    
    # 8. TRON
    "TRON": "asset_trx",
    "TRX": "asset_trx",
    
    # 9. Dogecoin
    "DOGECOIN": "asset_doge",
    "DOGE": "asset_doge",
    
    # 10. Hyperliquid
    "HYPERLIQUID": "asset_hype",
    "HYPE": "asset_hype"
}

# ==========================================
# 3. The Extraction & Linking Function
# ==========================================
def extract_and_link_entities(news_text: str):
    """
    Extracts entities using XLM-RoBERTa and maps them to unique IDs.
    """
    raw_entities = ner_pipeline(news_text)
    
    linked_entities = {}
    
    for entity in raw_entities:
        # Clean the extracted word and uppercase it for dictionary matching
        # \u2581 is the special block character used by XLM-RoBERTa for spaces
        word = entity['word'].replace('\u2581', '').replace(' ', '').strip().upper()
        confidence = round(float(entity['score']), 4)
        
        # Only process high-confidence extractions
        if confidence > 0.80:
            # Match the extracted word against our internal dictionary
            unique_id = ASSET_DICTIONARY.get(word)
            
            # If it exists in our system, link it!
            if unique_id and unique_id not in linked_entities:
                linked_entities[unique_id] = {
                    "asset_id": unique_id,
                    "matched_text": word,
                    "ner_confidence": confidence
                }
                
    return list(linked_entities.values())

if __name__ == "__main__":
    sample_news_text = """
    Solana validators successfully deployed the new patch today. 
    Meanwhile, BTC dominance continues to hover around 52%, leaving 
    Ethereum and altcoins like HYPE struggling.
    """
    
    print("\n--- Processing News ---")
    print(sample_news_text.strip())
    
    print("\n--- Linked Entities for Frontend/Database ---")
    final_output = extract_and_link_entities(sample_news_text)
    
    for item in final_output:
        print(f"ID: {item['asset_id']} | Matched: {item['matched_text']} | Confidence: {item['ner_confidence']}")
