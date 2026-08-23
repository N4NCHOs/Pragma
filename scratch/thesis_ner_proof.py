from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification
import re
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ai_models.filters import NAMES_PATTERN, TICKERS_PATTERN

print("Loading AI Model for Thesis Proof...")
tokenizer = AutoTokenizer.from_pretrained("covalenthq/cryptoNER")
model = AutoModelForTokenClassification.from_pretrained("covalenthq/cryptoNER")
eval_pipeline = pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple")

journalistic_data = [
    {"text": "Bitcoin nears key technical breakout that could propel prices to $76,000", "true_entities": ["BITCOIN"]},
    {"text": "BTC is surging today as the Federal Reserve cuts rates.", "true_entities": ["BTC"]},
    {"text": "Ethereum's vitalik buterin proposed a new EIP.", "true_entities": ["ETHEREUM"]},
    {"text": "Solana validators successfully deployed the new patch today.", "true_entities": ["SOLANA"]},
    {"text": "Ripple backs an RLUSD credit fund amid XRP's best week in months.", "true_entities": ["RIPPLE", "XRP"]},
    {"text": "Tether and USDC are the leading stablecoins.", "true_entities": ["TETHER", "USDC"]},
    {"text": "Binance Coin has seen a lot of volatility.", "true_entities": ["BINANCE COIN"]},
    {"text": "Dogecoin jumped after a tweet from Elon Musk.", "true_entities": ["DOGECOIN"]},
    {"text": "TRON network activity reached an all-time high.", "true_entities": ["TRON"]},
    {"text": "The price of ETH dropped below $3000.", "true_entities": ["ETH"]}
]

social_media_data = [
    {"text": "just bought some #bitcoin gonna go to the moon ngl 🚀", "true_entities": ["BITCOIN"]},
    {"text": "I love $ETH so much fr fr", "true_entities": ["ETH"]},
    {"text": "solana is pumping rn tbh", "true_entities": ["SOLANA"]},
    {"text": "buy btc now or stay poor", "true_entities": ["BTC"]},
    {"text": "my whole portfolio is in XRP and $DOGE lmao", "true_entities": ["XRP", "DOGE"]}
]

def calculate_f1(tp, fp, fn):
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1

def evaluate_ai(dataset, title):
    print(f"\n{'='*50}\n{title}\n{'='*50}")
    tp, fp, fn = 0, 0, 0
    
    for i, item in enumerate(dataset, 1):
        text = item["text"]
        true_entities = set([e.upper() for e in item["true_entities"]])
        
        raw_preds = eval_pipeline(text)
        pred_entities = set()
        if raw_preds:
            for p in raw_preds:
                if p['score'] > 0.00:
                    word = p['word'].replace('\u2581', '').replace(' ', '').strip().upper()
                    if word:
                        pred_entities.add(word)
                        
        for p_ent in pred_entities:
            if p_ent in true_entities: tp += 1
            else: fp += 1
                
        for t_ent in true_entities:
            if t_ent not in pred_entities: fn += 1
            
    p, r, f1 = calculate_f1(tp, fp, fn)
    print(f"Precision: {p:.4f} | Recall: {r:.4f} | F1-Score: {f1:.4f}")
    return f1

def evaluate_dictionary(dataset, title):
    print(f"\n{'='*50}\n{title}\n{'='*50}")
    tp, fp, fn = 0, 0, 0
    
    for i, item in enumerate(dataset, 1):
        text = item["text"]
        true_entities = set([e.upper() for e in item["true_entities"]])
        
        pred_entities = set()
        for pattern in [NAMES_PATTERN, TICKERS_PATTERN]:
            for match in pattern.finditer(text):
                pred_entities.add(match.group().upper())
                
        for p_ent in pred_entities:
            if p_ent in true_entities: tp += 1
            else: fp += 1
                
        for t_ent in true_entities:
            if t_ent not in pred_entities: fn += 1
            
    p, r, f1 = calculate_f1(tp, fp, fn)
    print(f"Precision: {p:.4f} | Recall: {r:.4f} | F1-Score: {f1:.4f}")
    return f1

if __name__ == "__main__":
    evaluate_ai(journalistic_data, "[TEST 1] AI cryptoNER on Journalistic Text")
    evaluate_ai(social_media_data, "[TEST 2] AI cryptoNER on Social Media Text")
    evaluate_dictionary(journalistic_data, "[TEST 3] Pure Regex Dictionary on Journalistic Text")
