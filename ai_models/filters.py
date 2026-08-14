import re

TARGET_ASSETS = {
    "BITCOIN", "BTC",
    "ETHEREUM", "ETH",
    "TETHER", "USDT",
    "BNB",
    "XRP",
    "USD COIN", "USDC",
    "SOLANA", "SOL",
    "TRON", "TRX",
    "DOGECOIN", "DOGE",
    "HYPERLIQUID", "HYPE"
}

NAMES_PATTERN = re.compile(
    r'\b(bitcoin|ethereum|tether|bnb|xrp|usd coin|solana|tron|dogecoin|hyperliquid)\b', 
    re.IGNORECASE
)
TICKERS_PATTERN = re.compile(
    r'\b(BTC|ETH|USDT|USDC|SOL|TRX|DOGE|HYPE)\b'
)

def is_top_10_news(news_item):
    """
    Filter using Regex to check for Top 10 assets.
    """
    title = news_item.get("title", "")
    # Fallback order: full_body -> rss_summary -> description
    body = news_item.get("full_body") or news_item.get("rss_summary") or news_item.get("description") or ""
    full_text = f"{title}. {body}"
    
     # Check if any full name is mentioned (case-insensitive)
    if NAMES_PATTERN.search(full_text):
        return True
        
    # Check if any exact ticker is mentioned (case-sensitive)
    if TICKERS_PATTERN.search(full_text):
        return True
        
    return False