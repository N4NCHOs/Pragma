from ai_models.crypto_ner import extract_and_link_entities, ner_pipeline

text = "bitcoin nears key technical breakout that could propel prices to $76,000. BTC Ethereum ETH Solana USDT TRON HYPE"
print("Lowercased:")
print(ner_pipeline(text.lower()))

print("\nUppercased:")
print(ner_pipeline(text.upper()))

print("\nOriginal:")
print(ner_pipeline(text))
